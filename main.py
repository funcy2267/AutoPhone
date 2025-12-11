import asyncio
import base64
import json
import requests
import audioop
import os
import uvicorn
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response, HTMLResponse, FileResponse
from pydantic import BaseModel
from pyngrok import ngrok
from twilio.twiml.voice_response import VoiceResponse, Connect

# Import from new modules
from services.gemini import GEMINI_PROMPTS
from utils import json_datetime_serializer, cleanup_files
from services.twilio import twilio_client, update_twilio_webhook, make_outbound_call
from services.gemini import GeminiConversationManager, gemini_summarize_audio

# Configuration
CALLS_DIR = "call_recordings"
SERVICE_PORT = 8080
KEEP_CALL_RECORDINGS = int(os.environ.get("KEEP_CALL_RECORDINGS", 10))

# In-memory store for call-specific data like custom prompts
call_data_store: Dict[str, Dict] = {}

# Global variable to store the public URL
SERVER_PUBLIC_URL: Optional[str] = None

# --- FastAPI App ---
app = FastAPI()

@app.get("/call_recordings")
async def list_call_recordings(request: Request):
    """Lists available call recordings."""
    if not os.path.exists(CALLS_DIR):
        return HTMLResponse(content="<h1>No recordings found</h1>")

    files = os.listdir(CALLS_DIR)
    # Filter for wav files
    files = [f for f in files if f.endswith(".wav")]
    files.sort(reverse=True)

    html_content = "<h1>Call Recordings</h1><ul>"
    for f in files:
        html_content += f'<li><a href="/call_recordings/{f}">{f}</a></li>'
    html_content += "</ul>"

    return HTMLResponse(content=html_content)

@app.get("/call_recordings/{filename}")
async def get_call_recording(filename: str):
    """Serves a specific call recording file."""
    file_path = os.path.join(CALLS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return Response(content="File not found", status_code=404)

@app.post("/voice")
async def voice_handler(request: Request):
    """Handles incoming call from Twilio and establishes a WebSocket stream."""
    response = VoiceResponse()
    connect = Connect()
    websocket_url = f"wss://{request.headers['host']}/ws"
    connect.stream(url=websocket_url)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")

@app.websocket("/ws")
async def websocket_handler(websocket: WebSocket):
    """Handles the WebSocket audio stream with Twilio."""
    await websocket.accept()
    print("WebSocket connection established.")

    call_state = {"stream_sid": None}
    # We will create the conversation manager after we get the 'start' event and have the callSid to look up a custom prompt.
    conversation_manager = None
    gemini_task = None
    data = None # Initialize data to avoid UnboundLocalError in finally block if loop doesn't run

    try:
        # Main loop to receive messages from Twilio
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)

            if data['event'] == 'start':
                print(data)
                call_state['stream_sid'] = data['start']['streamSid']
                call_sid = data['start']['callSid']
                os.makedirs(CALLS_DIR, exist_ok=True)
                recording_path = f"{CALLS_DIR}/{call_sid}.wav"
                print(f"Twilio stream started: {call_state['stream_sid']}")

                conversation_manager = GeminiConversationManager(websocket, call_state, GEMINI_PROMPTS["inbound_init"])
                gemini_task = asyncio.create_task(conversation_manager.run())
                conversation_manager.start_recording(recording_path)
                conversation_manager.initial_prompt_sent.set()

            elif data['event'] == 'media':
                if not conversation_manager:
                    continue
                    
                # Audio from Twilio is base64 encoded mulaw
                mulaw_audio = base64.b64decode(data['media']['payload'])
                # Convert mulaw to 16-bit PCM for Gemini
                pcm_audio = audioop.ulaw2lin(mulaw_audio, 2)
                if conversation_manager and conversation_manager.recorder:
                    conversation_manager.recorder.writeframes(pcm_audio)
                if conversation_manager:
                    await conversation_manager.audio_queue.put(pcm_audio)

            elif data['event'] == 'stop':
                print("Twilio stream stopped.")
                if conversation_manager:
                    await conversation_manager.audio_queue.put(None) # Signal end of stream
                break

        # Wait for the Gemini task to finish
        if gemini_task:
            await gemini_task

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Ensure the gemini task is cancelled if it's still running
        if gemini_task and not gemini_task.done():
            gemini_task.cancel()

        print("Closing WebSocket connection.")
        if conversation_manager and conversation_manager.recorder:
            conversation_manager.recorder.close()
            print("Recording saved.")
        if websocket.client_state != 3: # 3 is DISCONNECTED state
             await websocket.close()
        
        # Handle the end of call
        if data and 'stop' in data and 'callSid' in data['stop']:
            cleanup_files(CALLS_DIR, "*.wav", KEEP_CALL_RECORDINGS)
            call_sid = data['stop']['callSid']
            try:
                call = twilio_client.calls(call_sid).fetch()
                call_dict = {k: v for k, v in call.__dict__.items() if not k.startswith('_')}
                if conversation_manager and conversation_manager.recorder:
                     recording_path = f"{CALLS_DIR}/{call_sid}.wav"

                     audio_url = f"{SERVER_PUBLIC_URL}/call_recordings/{call_sid}.wav"

                     webhook_payload = {
                         "call": call_dict,
                         "summarized_text": gemini_summarize_audio(recording_path),
                         "audio": audio_url
                     }

                     requests.post(os.environ.get("WEBHOOK_TARGET_URL"), data=json.dumps(webhook_payload, default=json_datetime_serializer), headers={"Content-Type": "application/json"}, timeout=10)
            except Exception as e:
                print(f"Error in post-call processing: {e}")

class CallRequest(BaseModel):
    to_number: str
    prompt: str

@app.post("/call")
async def make_outbound_call_handler(request: Request, call_request: CallRequest):
    """Handles a webhook request to initiate an outbound call with a custom prompt."""
    global SERVER_PUBLIC_URL, call_data_store

    public_url = SERVER_PUBLIC_URL

    print("Using Public URL for callback: ", public_url)
    call_sid = make_outbound_call(public_url, call_request.to_number)
    
    if call_sid:
        # Store the custom prompt with the call SID
        call_data_store[call_sid] = {"prompt": GEMINI_PROMPTS["outbound_init"] + call_request.prompt}
        return {"status": "success", "call_sid": call_sid}
    else:
        return Response(content=json.dumps({"status": "error", "message": "Failed to initiate call."}), status_code=500, media_type="application/json")

def run_app():
    """Starts the ngrok tunnel and the FastAPI app to handle incoming calls."""
    global SERVER_PUBLIC_URL
    
    ngrok_authtoken = os.environ.get("NGROK_AUTHTOKEN")
    if ngrok_authtoken:
        ngrok.set_auth_token(ngrok_authtoken)

    # Start ngrok tunnel
    tunnel = ngrok.connect(SERVICE_PORT)
    public_url = tunnel.public_url
    SERVER_PUBLIC_URL = public_url
    print(f"Ngrok tunnel is active at: {public_url}")

    # Update the webhook for incoming calls
    update_twilio_webhook(public_url)

    try:
        # Run the FastAPI app
        uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)

    finally:
        print("Shutting down ngrok tunnel.")
        ngrok.disconnect(public_url)
        ngrok.kill()

run_app()
