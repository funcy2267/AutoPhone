import asyncio
import base64
import json
import requests
import audioop
import os
import uvicorn
from typing import Dict, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response, HTMLResponse, FileResponse
from pydantic import BaseModel
from pyngrok import ngrok
from twilio.twiml.voice_response import VoiceResponse, Connect

# Import from new modules
from services.gemini import GEMINI_PROMPTS
from utils import json_datetime_serializer, cleanup_calls
from services.twilio import twilio_client, update_twilio_webhook, make_outbound_call
from services.gemini import GeminiConversationManager, gemini_summarize_audio
import call_queue

# Configuration
CALLS_DIR = "calls"
CALLS_URL_ENDPOINT = "calls"
SERVICE_PORT = 8080
KEEP_CALLS = int(os.environ.get("KEEP_CALLS"))
RECORDING_FILENAME = "recording.wav"
METADATA_FILENAME = "call.json"

# In-memory store for call-specific data like custom prompts
call_data_store: Dict[str, Dict] = {}

# Global variable to store the public URL
SERVER_PUBLIC_URL: Optional[str] = None

# --- FastAPI App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(call_queue.process_queue_loop(lambda: SERVER_PUBLIC_URL, call_data_store))
    yield

app = FastAPI(lifespan=lifespan)

def process_and_save_call(call_sid: str, call_dict: dict, summarized_text: Optional[str] = None):
    """Saves call metadata and sends a webhook if configured."""
    try:
        call_dir = os.path.join(CALLS_DIR, call_sid)
        os.makedirs(call_dir, exist_ok=True)
        
        webhook_payload = {
            "call": call_dict,
            "summarized_text": summarized_text
        }
        
        metadata_path = os.path.join(call_dir, METADATA_FILENAME)
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(webhook_payload, f, default=json_datetime_serializer)

        cleanup_calls(CALLS_DIR, KEEP_CALLS)

        # Send webhook
        webhook_url = os.environ.get("WEBHOOK_TARGET_URL")
        if webhook_url:
            with open(metadata_path, 'r') as f:
                payload = json.load(f)
            try:
                requests.post(webhook_url, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=10)
                print(f"Processed call {call_sid} and sent webhook.")
            except Exception as e:
                print(f"Error sending webhook for call {call_sid}: {e}")

    except Exception as e:
        print(f"Error in process_and_save_call for {call_sid}: {e}")


# --- Queue Endpoints ---

@app.get("/calls/queue")
async def get_queue_ids():
    """List queued calls ids."""
    return list(call_queue.get_queue().keys())

@app.get("/calls/queue/{queue_id}")
async def get_queue_item(queue_id: int):
    """Get the metadata for a specific queued call."""
    item = call_queue.get_queued_call(queue_id)
    if item:
        return item
    return Response(content=json.dumps({"error": "Item not found"}), status_code=404, media_type="application/json")

@app.delete("/calls/queue/{queue_id}")
async def delete_queue_item(queue_id: int):
    """Remove a queued call."""
    if call_queue.delete_from_queue(queue_id):
        return {"status": "deleted", "id": queue_id}
    return Response(content=json.dumps({"error": "Item not found"}), status_code=404, media_type="application/json")


@app.get(f"/{CALLS_URL_ENDPOINT}/{{call_sid}}/{{filename}}")
async def get_call_data(call_sid: str, filename: str, raw: bool = False):
    """Serves the call data for a specific call."""
    file_path = os.path.join(CALLS_DIR, call_sid, filename)
    if os.path.exists(file_path):
        # Handle audio preview
        if filename == RECORDING_FILENAME and not raw:
            html_content = f"""
            <html>
                <head>
                    <title>Audio Preview</title>
                    <style>
                        body {{ display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a1a; color: white; font-family: system-ui, sans-serif; }}
                        audio {{ width: 80%; max-width: 800px; }}
                    </style>
                </head>
                <body>
                    <audio controls autoplay>
                        <source src="{filename}?raw=true" type="audio/wav">
                        Your browser does not support the audio element.
                    </audio>
                </body>
            </html>
            """
            return HTMLResponse(content=html_content)

        return FileResponse(file_path)
    return Response(content="File not found", status_code=404)

@app.get(f"/{CALLS_URL_ENDPOINT}")
async def get_calls_list():
    """Returns a list of saved call SIDs."""
    if not os.path.exists(CALLS_DIR):
        return []
    calls = [d for d in os.listdir(CALLS_DIR) if os.path.isdir(os.path.join(CALLS_DIR, d))]
    return calls

@app.post("/voice")
async def voice_handler(request: Request):
    """Handles incoming call from Twilio and establishes a WebSocket stream."""
    response = VoiceResponse()
    
    form_data = await request.form()
    answered_by = form_data.get("AnsweredBy")
    forwarded_from = form_data.get("ForwardedFrom")
    print(f"Incoming call answered by: {answered_by}, ForwardedFrom: {forwarded_from}")

    if answered_by and answered_by.startswith("machine"):
        print("Answering machine detected. Hanging up.")
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

    if forwarded_from:
        print(f"Call forwarded from {forwarded_from}. Rejecting potential voicemail loop.")
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

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
            receive_task = asyncio.create_task(websocket.receive_text())
            wait_tasks = [receive_task]
            if gemini_task:
                wait_tasks.append(gemini_task)

            done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            if gemini_task and gemini_task in done:
                print("Gemini assistant ended the conversation.")
                if not receive_task.done():
                    receive_task.cancel()
                break

            try:
                message = receive_task.result()
            except WebSocketDisconnect:
                print("WebSocket disconnected.")
                break
            data = json.loads(message)

            if data['event'] == 'start':
                print(data)
                call_state['stream_sid'] = data['start']['streamSid']
                call_sid = data['start']['callSid']
                os.makedirs(os.path.join(CALLS_DIR, call_sid), exist_ok=True)
                recording_path = os.path.join(CALLS_DIR, call_sid, RECORDING_FILENAME)
                print(f"Twilio stream started: {call_state['stream_sid']}")

                # Determine prompt (inbound or outbound)
                if call_sid in call_data_store:
                   prompt = call_data_store[call_sid]["prompt"]
                   print(f"Using custom prompt for call {call_sid}")
                   del call_data_store[call_sid]
                else:
                   prompt = GEMINI_PROMPTS["inbound_init"]
                   print(f"Using default inbound prompt for call {call_sid}")

                conversation_manager = GeminiConversationManager(websocket, call_state, prompt)
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
        # If call_sid was extracted from 'start' event, we can proceed with post-call processing.
        # We don't rely on 'stop' event because the socket might be closed by the assistant.
        if call_sid:
            try:
                call = twilio_client.calls(call_sid).fetch()
                call_dict = {k: v for k, v in call.__dict__.items() if not k.startswith('_')}
                
                call_dir = os.path.join(CALLS_DIR, call_sid)
                os.makedirs(call_dir, exist_ok=True)
                
                if call.answered_by and call.answered_by.startswith("machine"):
                    print(f"Call answered by {call.answered_by}. Skipping success webhook and deleting recording.")
                    if os.path.exists(call_dir):
                        import shutil
                        shutil.rmtree(call_dir)
                        print(f"Deleted call directory: {call_dir}")
                else:
                    recording_path = os.path.join(call_dir, RECORDING_FILENAME)
                    summarized_text = None
                    
                    if conversation_manager and conversation_manager.recorder:
                         try:
                             summarized_text = gemini_summarize_audio(recording_path)
                         except:
                             summarized_text = None

                    process_and_save_call(call_sid, call_dict, summarized_text)
            except Exception as e:
                print(f"Error in post-call processing: {e}")

class CallRequest(BaseModel):
    to_number: str
    prompt: str
    datetime: Optional[str] = None

@app.post("/call")
async def make_outbound_call_handler(request: Request, call_request: CallRequest):
    """Handles a webhook request to initiate an outbound call with a custom prompt."""
    global SERVER_PUBLIC_URL, call_data_store

    if call_request.datetime:
        call_data = {
            "to_number": call_request.to_number,
            "prompt": call_request.prompt,
            "datetime": call_request.datetime
        }
        q_id = call_queue.add_to_queue(call_data)
        return {"status": "queued", "queue_id": q_id}

    public_url = SERVER_PUBLIC_URL

    print("Using Public URL for callback: ", public_url)
    call_sid = make_outbound_call(public_url, call_request.to_number)
    
    if call_sid:
        # Store the custom prompt with the call SID
        call_data_store[call_sid] = {"prompt": GEMINI_PROMPTS["outbound_init"] + call_request.prompt}
        return {"status": "success", "call_sid": call_sid}
    else:
        return Response(content=json.dumps({"status": "error", "message": "Failed to initiate call."}), status_code=500, media_type="application/json")

@app.post("/status_callback")
async def status_callback_handler(request: Request):
    """Handles Twilio status callbacks."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    answered_by = form_data.get("AnsweredBy")

    print(f"Call {call_sid} status: {call_status}, AnsweredBy: {answered_by}")

    if call_status in ["busy", "no-answer", "failed", "canceled"] or (answered_by and answered_by.startswith("machine")):
        # If the call failed, clean up the custom prompt if it exists
        if call_sid in call_data_store:
            del call_data_store[call_sid]

        try:
            # We construct a partial call dict from the form data, or fetch it if needed.
            # Fetching is safer to get full details.
            call = twilio_client.calls(call_sid).fetch()
            call_dict = {k: v for k, v in call.__dict__.items() if not k.startswith('_')}

            process_and_save_call(call_sid, call_dict, "None")

        except Exception as e:
            print(f"Error in status callback processing: {e}")
    else:
        print(f"Call {call_sid} status '{call_status}' is not considered a failure. Webhook not sent.")

    return Response(content="OK", status_code=200)





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
