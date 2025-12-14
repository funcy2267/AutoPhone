import asyncio
import base64
import json
import wave
import audioop
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GEMINI_LANGUAGE = os.environ.get("ASSISTANT_LANGUAGE")
GEMINI_ASSISTANT_OWNER_NAME = os.environ.get("ASSISTANT_OWNER_NAME")

GEMINI_PROMPTS = {
    "assistant_instruction": f"You are a helpful and friendly {GEMINI_ASSISTANT_OWNER_NAME}'s personal voice assistant. Your task is to conduct a conversation, which will then be transferred to the assistant's owner. At the end of the conversation, you can end the call using the available tool. Use language: {GEMINI_LANGUAGE}.",
    "inbound_init": "Hello! Please introduce yourself.",
    "outbound_init": "You are being redirected to interlocutor so please start the conversation from now. Your task as an assistant: "
}

class GeminiConversationManager:
    """Manages the conversation state and interaction with the Gemini Live API."""

    def __init__(self, websocket, call_state, initial_prompt="Hello! How can I help you today?"):
        self.websocket = websocket
        self.call_state = call_state
        self.audio_queue = asyncio.Queue()
        self.initial_prompt_sent = asyncio.Event()
        self.initial_prompt = initial_prompt
        self.recorder = None
        self.is_speaking = False

    async def send_audio_to_twilio(self, pcm_24k_audio):
        """Transcodes and sends audio data to Twilio."""
        # 1. Resample from 24kHz to 8kHz
        pcm_8k_audio, _ = audioop.ratecv(pcm_24k_audio, 2, 1, 24000, 8000, None)
        # 2. Convert 16-bit linear PCM to 8-bit mulaw

        if self.recorder:
            self.recorder.writeframes(pcm_8k_audio)

        mulaw_audio = audioop.lin2ulaw(pcm_8k_audio, 2)
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

    async def run(self):
        """Main loop to run the conversation, sending and receiving audio."""
        gemini_client = genai.Client()

        # Tool definition for ending the call
        end_call_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="end_call",
                    description="Ends the voice call. Call this when the user says goodbye or wants to end the conversation.",
                )
            ]
        )

        gemini_config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": GEMINI_PROMPTS["assistant_instruction"],
            "tools": [end_call_tool]
        }


        async with gemini_client.aio.live.connect(model=os.environ.get("GEMINI_ASSISTANT_MODEL"), config=gemini_config) as gemini_session:
            print("Gemini Live session started for continuous conversation.")

            async def sender():
                # Wait for the initial prompt to be sent before processing audio queue
                await self.initial_prompt_sent.wait()
                await gemini_session.send_realtime_input(
                    text=self.initial_prompt
                )

                """Sends audio from the internal queue to Gemini."""
                while True:
                    audio_chunk = await self.audio_queue.get()
                    if audio_chunk is None:
                        break
                    await gemini_session.send_realtime_input(
                        audio=types.Blob(data=audio_chunk, mime_type="audio/pcm;rate=8000")
                    )

            async def receiver():
                """Receives audio from Gemini and sends it to Twilio."""
                # This loop runs for the entire duration of the call
                while True:
                    async for response in gemini_session.receive():
                        # Check for tool calls
                        if response.tool_calls:
                            for tool_call in response.tool_calls:
                                if tool_call.name == "end_call":
                                    print("Gemini requested to end the call.")
                                    await self.websocket.close()
                                    return

                        if response.data and self.call_state['stream_sid']:
                            await self.send_audio_to_twilio(response.data)

            # Start sender and receiver tasks that run for the duration of the session
            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())

            # We wait for either task to complete.
            # If sender_task completes (Twilio stopped), we are done.
            # If receiver_task completes (Gemini tool call), we are also done.
            done, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()

            # If receiver task finished first (Gemini ended call), we might want to ensure everything is clean.

def gemini_summarize_audio(audio_file_path):
    with open(audio_file_path, 'rb') as f:
        audio_bytes = f.read()

    client = genai.Client()
    response = client.models.generate_content(
    model=os.environ.get("GEMINI_SUMMARIZATION_MODEL"),
    contents=[
        f'Summarize this voice call between AI and user. Use language: {GEMINI_LANGUAGE}.',
        types.Part.from_bytes(
        data=audio_bytes,
        mime_type='audio/wav',
        )
    ]
    )

    return response.text
