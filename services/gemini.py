import asyncio
import base64
import json
import wave
import audioop
from google import genai
from google.genai import types
import websockets
import numpy as np
from dotenv import load_dotenv

import utils

load_dotenv()

owner_string = f"{utils.args.assistant_owner}'s " if utils.args.assistant_owner else ""

GEMINI_PROMPTS = {
    "assistant_instruction": f"You are a helpful and friendly {owner_string}personal voice assistant. Your task is to conduct a conversation, which will then be transferred to the assistant's owner. Use language: {utils.args.assistant_language}.",
    "inbound_init": "Hello! Please introduce yourself.",
    "outbound_init": "You are being redirected to interlocutor so please start the conversation from now. Your task as an assistant: ",
    "end_call": "Ends the voice call. Call this at the end of the conversation.",
    "admin_message": "Message from admin: "
}

class GeminiConversationManager:
    """Manages the conversation state and interaction with the Gemini Live API."""

    def __init__(self, websocket, call_state, initial_prompt="Hello! How can I help you today?"):
        self.websocket = websocket
        self.call_state = call_state
        self.input_queue = asyncio.Queue()
        self.initial_prompt_sent = asyncio.Event()
        self.initial_prompt = initial_prompt
        self.recorder = None
        self.observers = set()
        self.transcription_history = []
        self.call_ended_event = asyncio.Event()
        self.assistant_audio_buffer = bytearray()

    async def broadcast_event(self, event: dict):
        for ws in list(self.observers):
            try: await ws.send_text(json.dumps(event))
            except Exception: self.observers.discard(ws)

    async def send_audio_to_twilio(self, pcm_24k_audio):
        pcm_8k, _ = audioop.ratecv(pcm_24k_audio, 2, 1, 24000, 8000, None)
        if not pcm_8k:
            return
            
        await self.broadcast_event({"type": "audio", "source": "assistant", "data": base64.b64encode(pcm_8k).decode()})
        self.assistant_audio_buffer.extend(pcm_8k)
        
        await self.websocket.send_text(json.dumps({
            "event": "media",
            "media": {"payload": base64.b64encode(audioop.lin2ulaw(pcm_8k, 2)).decode()},
            "streamSid": self.call_state['stream_sid']
        }))

    def start_recording(self, filename):
        self.recorder = wave.open(filename, 'wb')
        self.recorder.setnchannels(1)
        self.recorder.setsampwidth(2)
        self.recorder.setframerate(8000)

    async def process_user_audio(self, pcm_8k):
        # Broadcast user audio to live observers
        await self.broadcast_event({"type": "audio", "source": "user", "data": base64.b64encode(pcm_8k).decode()})
        
        # Mix with assistant audio for the recorder
        if self.recorder:
            chunk_len = len(pcm_8k)
            ast_chunk = self.assistant_audio_buffer[:chunk_len]
            self.assistant_audio_buffer = self.assistant_audio_buffer[chunk_len:]
            
            if len(ast_chunk) < chunk_len:
                ast_chunk.extend(b'\x00' * (chunk_len - len(ast_chunk)))
                
            mixed_pcm = audioop.add(pcm_8k, bytes(ast_chunk), 2)
            self.recorder.writeframes(mixed_pcm)

    def _append_to_transcript(self, role, text):
        if self.transcription_history and self.transcription_history[-1]["role"] == role:
            self.transcription_history[-1]["text"] += text
        else:
            self.transcription_history.append({"role": role, "text": text})

    async def send_text_prompt(self, text: str):
         self._append_to_transcript("admin", text)
         await self.input_queue.put(('text', GEMINI_PROMPTS["admin_message"] + text))
         await self.broadcast_event({"type": "log", "role": "admin", "text": text})

    async def run(self):
        client = genai.Client()
        end_call_tool = types.Tool(function_declarations=[
            types.FunctionDeclaration(name="end_call", description=GEMINI_PROMPTS["end_call"])
        ])
        
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": GEMINI_PROMPTS["assistant_instruction"],
            "tools": [end_call_tool],
            "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": utils.args.gemini_assistant_voice}}},
            "input_audio_transcription": {},
            "output_audio_transcription": {}
        }

        async with client.aio.live.connect(model=utils.args.gemini_assistant_model, config=config) as session:
            async def sender():
                try:
                    await self.initial_prompt_sent.wait()
                    print("DEBUG [Gemini Sender]: Sending initial prompt.")
                    await session.send_realtime_input(text=self.initial_prompt)
                    while True:
                        item = await self.input_queue.get()
                        if item is None:
                            print("DEBUG [Gemini Sender]: Received None, breaking.")
                            break
                        type_, data = item
                        if type_ == 'audio': await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=8000"))
                        elif type_ == 'text': await session.send_realtime_input(text=data)
                except Exception as e:
                    print(f"DEBUG [Gemini Sender]: Error: {e}")
                print("DEBUG [Gemini Sender]: Completed.")

            async def receiver():
                try:
                    while True:
                        async for response in session.receive():
                            if getattr(response, 'tool_call', None) and any(tc.name == "end_call" for tc in response.tool_call.function_calls):
                                print("DEBUG [Gemini Receiver]: Model called end_call!!!")
                                return
                            
                            if getattr(response, 'server_content', None):
                                out_t = getattr(response.server_content, 'output_transcription', None)
                                if out_t and getattr(out_t, 'text', None):
                                    self._append_to_transcript("assistant", out_t.text)
                                    await self.broadcast_event({"type": "log", "role": "assistant", "text": out_t.text})
                                    
                                in_t = getattr(response.server_content, 'input_transcription', None)
                                if in_t and getattr(in_t, 'text', None):
                                    self._append_to_transcript("user", in_t.text)
                                    await self.broadcast_event({"type": "log", "role": "user", "text": in_t.text})

                            data = None
                            try:
                                if hasattr(response, 'data'):
                                    data = response.data
                            except Exception:
                                pass

                            if data and self.call_state.get('stream_sid'):
                                await self.send_audio_to_twilio(data)
                except Exception as e:
                    print(f"DEBUG [Gemini Receiver]: Error: {e}")
                print("DEBUG [Gemini Receiver]: session.receive() stream ended or broke.")

            done, pending = await asyncio.wait([asyncio.create_task(sender()), asyncio.create_task(receiver())], 
                                             return_when=asyncio.FIRST_COMPLETED)
            self.call_ended_event.set()
            for task in pending: task.cancel()
