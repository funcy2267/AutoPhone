import asyncio
import base64
import json
import wave
from services import utils_audio
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GEMINI_LANGUAGE = os.environ.get("ASSISTANT_LANGUAGE")
GEMINI_ASSISTANT_OWNER_NAME = os.environ.get("ASSISTANT_OWNER_NAME")

GEMINI_PROMPTS = {
    "assistant_instruction": f"You are a helpful and friendly {GEMINI_ASSISTANT_OWNER_NAME}'s personal voice assistant. Your task is to conduct a conversation, which will then be transferred to the assistant's owner. Use language: {GEMINI_LANGUAGE}.",
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
        self.is_speaking = False
        self.observers = []
        self.transcription_history = []
        self.call_ended_event = asyncio.Event()

    async def send_audio_to_twilio(self, pcm_24k_audio):
        """Transcodes and sends audio data to Twilio."""
        # 1. Resample from 24kHz to 8kHz
        pcm_8k_audio, _ = utils_audio.resample_24k_to_8k(pcm_24k_audio, 2)
        
        # Broadcast for preview
        await self.broadcast_audio(pcm_8k_audio)

        # 2. Convert 16-bit linear PCM to 8-bit mulaw

        if self.recorder:
            self.recorder.writeframes(pcm_8k_audio)

        mulaw_audio = utils_audio.lin2ulaw(pcm_8k_audio, 2)
        # 3. Base64 encode and send
        payload = base64.b64encode(mulaw_audio).decode("utf-8")

        await self.websocket.send_text(json.dumps({
            "event": "media",
            "media": {"payload": payload},
            "streamSid": self.call_state['stream_sid']
        }))

    def start_recording(self, filename):
        """Initializes the WAV file for recording."""
        self.recorder = wave.open(filename, 'wb')
        self.recorder.setnchannels(1)  # mono
        self.recorder.setsampwidth(2)  # 16-bit
        self.recorder.setframerate(8000) # 8kHz
        print(f"Recording call to {filename}")

    def _append_to_transcript(self, role, text):
        if self.transcription_history and self.transcription_history[-1]["role"] == role:
            self.transcription_history[-1]["text"] += text
        else:
            self.transcription_history.append({"role": role, "text": text})

    async def send_text_prompt(self, text: str):
         """Sends a text prompt to the assistant."""
         self._append_to_transcript("admin", text)
         prompt_text = GEMINI_PROMPTS.get("admin_message") + text
         await self.input_queue.put(('text', prompt_text))
         await self.broadcast_event({"type": "log", "role": "admin", "text": text})

    async def add_observer(self, websocket):
        self.observers.append(websocket)
        try:
             # Send initial log or status
             await websocket.send_text(json.dumps({"type": "status", "status": "connected"}))
        except:
             pass

    def remove_observer(self, websocket):
        if websocket in self.observers:
            self.observers.remove(websocket)

    async def broadcast_event(self, event: dict):
            current_observers = list(self.observers)
            for ws in current_observers:
                try:
                    await ws.send_text(json.dumps(event))
                except Exception as e:
                    print(f"Error broadcasting to observer: {e}")
                    self.remove_observer(ws)

    async def broadcast_audio(self, pcm_audio: bytes):
        """Broadcasts audio chunk to observers."""
        encoded_audio = base64.b64encode(pcm_audio).decode("utf-8")
        await self.broadcast_event({"type": "audio", "data": encoded_audio})

    async def run(self):
        """Main loop to run the conversation, sending and receiving audio."""
        gemini_client = genai.Client()

        # Tool definition for ending the call
        end_call_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="end_call",
                    description=GEMINI_PROMPTS["end_call"],
                )
            ]
        )

        gemini_config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": GEMINI_PROMPTS["assistant_instruction"],
            "tools": [end_call_tool],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": os.environ.get("GEMINI_ASSISTANT_VOICE")
                    }
                }
            }
        }

        # Enable input audio transcription
        gemini_config['input_audio_transcription'] = {}
        # Enable output audio transcription
        gemini_config['output_audio_transcription'] = {}


        async with gemini_client.aio.live.connect(model=os.environ.get("GEMINI_ASSISTANT_MODEL"), config=gemini_config) as gemini_session:
            print("Gemini Live session started for continuous conversation.")

            async def sender():
                # Wait for the initial prompt to be sent before processing input queue
                await self.initial_prompt_sent.wait()
                await gemini_session.send_realtime_input(
                    text=self.initial_prompt
                )

                """Sends inputs (audio or text) from the internal queue to Gemini."""
                while True:
                    item = await self.input_queue.get()
                    if item is None:
                        break
                    
                    type_, data = item
                    if type_ == 'audio':
                         await gemini_session.send_realtime_input(
                            audio=types.Blob(data=data, mime_type="audio/pcm;rate=8000")
                        )
                    elif type_ == 'text':
                         await gemini_session.send_realtime_input(text=data)

            async def receiver():
                """Receives audio from Gemini and sends it to Twilio."""
                # This loop runs for the entire duration of the call
                while True:
                    async for response in gemini_session.receive():
                        # Check for tool calls
                        if response.tool_call and response.tool_call.function_calls:
                            for tool_call in response.tool_call.function_calls:
                                if tool_call.name == "end_call":
                                    print("Gemini requested to end the call.")
                                    return
                        
                        # Check for text content (Assistant's response text) - deprecated for AUDIO mode
                        '''
                        if response.text:
                             print(f"Assistant said text: {response.text}")
                             await self.broadcast_event({"type": "log", "role": "assistant", "text": response.text})
                        '''
                        # Check for output transcription (Assistant's speech transcribed)
                        if response.server_content and response.server_content.output_transcription:
                            transcription = response.server_content.output_transcription
                            if transcription.text:
                                print(f"Assistant said: {transcription.text}")
                                self._append_to_transcript("assistant", transcription.text)
                                await self.broadcast_event({"type": "log", "role": "assistant", "text": transcription.text})

                        # Check for user input transcription
                        if response.server_content and response.server_content.input_transcription:
                            transcription = response.server_content.input_transcription
                            if transcription.text:
                                print(f"User said: {transcription.text}")
                                self._append_to_transcript("user", transcription.text)
                                await self.broadcast_event({"type": "log", "role": "user", "text": transcription.text})

                        if response.data and self.call_state['stream_sid']:
                            await self.send_audio_to_twilio(response.data)

            # Start sender and receiver tasks that run for the duration of the session
            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())

            # We wait for either task to complete.
            done, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            self.call_ended_event.set()

            # Cancel pending tasks
            for task in pending:
                task.cancel()

            # If receiver task finished first (Gemini ended call), we might want to ensure everything is clean.

def gemini_summarize_call(transcription_history):
    if not transcription_history:
        return "No transcription available."

    transcript_text = "\n".join([f"{entry['role'].upper()}: {entry['text']}" for entry in transcription_history])
    print(f"Transcript: {transcript_text}")

    client = genai.Client()
    response = client.models.generate_content(
    model=os.environ.get("GEMINI_SUMMARIZATION_MODEL"),
    contents=[
        f'Summarize this conversation between AI and user. Use language: {GEMINI_LANGUAGE}.\n\nTranscript:\n{transcript_text}'
    ]
    )

    return response.text
