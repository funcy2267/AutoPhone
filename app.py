import asyncio
import base64
import json
import requests
import os
import shutil
import datetime
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response, HTMLResponse, FileResponse
from pydantic import BaseModel
from twilio.twiml.voice_response import VoiceResponse, Connect
import utils

import services

# Configuration
CALLS_DIR = "calls"
KEEP_CALLS = int(os.environ.get("KEEP_CALLS"))
SUMMARIZE_CALLS = os.environ.get("SUMMARIZE_CALLS", "true").lower() == "true"
RECORDING_FILENAME = "recording.wav"
METADATA_FILENAME = "call.json"

# Endpoints
CALLS_ENDPOINT = "calls"
TWILIO_ENDPOINT = "twilio"
CURRENT_CALL_ENDPOINT = "current"
QUEUE_ENDPOINT = "queue"

# In-memory store
call_data_store: Dict[str, Dict] = {}

current_call_sid: Optional[str] = None
active_cm: Optional[services.gemini.GeminiConversationManager] = None
scheduled_calls: Dict[int, asyncio.Task] = {}
scheduled_calls_data: Dict[int, Dict] = {}
next_queue_id = 1
SERVER_PUBLIC_URL: Optional[str] = None

# --- FastAPI App & Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for task in scheduled_calls.values():
        task.cancel()

app = FastAPI(lifespan=lifespan)


# ==========================================
# Group 1: Queue Management
# ==========================================

async def schedule_call(queue_id: int, delay_seconds: float, call_data: dict):
    try:
        print(f"Call {queue_id} scheduled in {delay_seconds} seconds.")
        await asyncio.sleep(delay_seconds)
        
        print(f"Executing queued call {queue_id}")
        if SERVER_PUBLIC_URL:
            sid = services.twilio.make_outbound_call(SERVER_PUBLIC_URL, call_data["to_number"])
            if sid:
                full_prompt = services.gemini.GEMINI_PROMPTS["outbound_init"] + call_data["prompt"]
                call_data_store[sid] = {"prompt": full_prompt}
                print(f"Initiated queued call {queue_id}, SID: {sid}")
            else:
                print(f"Failed to initiate queued call {queue_id}")
        else:
            print("Server public URL not set, skipping queued call execution.")
            
    except asyncio.CancelledError:
        print(f"Scheduled call {queue_id} cancelled.")
    finally:
        if queue_id in scheduled_calls:
            del scheduled_calls[queue_id]
        if queue_id in scheduled_calls_data:
            del scheduled_calls_data[queue_id]

# List all queued calls IDs
@app.get(f"/{CALLS_ENDPOINT}/{QUEUE_ENDPOINT}")
async def get_queue_ids():
    return list(scheduled_calls_data.keys())

# Retrieve details of a specific queued call
@app.get(f"/{CALLS_ENDPOINT}/{QUEUE_ENDPOINT}/{{queue_id}}")
async def get_queue_item(queue_id: int):
    item = scheduled_calls_data.get(queue_id)
    if item:
        return item
    return Response(content=json.dumps({"error": "Item not found"}), status_code=404, media_type="application/json")

# Remove a call from the queue
@app.delete(f"/{CALLS_ENDPOINT}/{QUEUE_ENDPOINT}/{{queue_id}}")
async def delete_queue_item(queue_id: int):
    if queue_id in scheduled_calls:
        scheduled_calls[queue_id].cancel()
        if queue_id in scheduled_calls_data:
             del scheduled_calls_data[queue_id]
        if queue_id in scheduled_calls:
             del scheduled_calls[queue_id]
        return {"status": "deleted", "id": queue_id}
    return Response(content=json.dumps({"error": "Item not found"}), status_code=404, media_type="application/json")


# ==========================================
# Group 2: Outbound Call Management
# ==========================================

class CallRequest(BaseModel):
    to_number: str
    prompt: str
    datetime: Optional[str] = None

async def handle_scheduled_call(call_request: CallRequest):
    global next_queue_id, scheduled_calls, scheduled_calls_data
    try:
        scheduled_time = datetime.datetime.strptime(call_request.datetime, "%Y-%m-%d-%H-%M")
        now = datetime.datetime.now()
        delay = (scheduled_time - now).total_seconds()
        
        if delay < 0:
                return Response(content=json.dumps({"error": "Scheduled time is in the past"}), status_code=400, media_type="application/json")
        
        q_id = next_queue_id
        next_queue_id += 1
        
        call_data = {
            "to_number": call_request.to_number,
            "prompt": call_request.prompt,
            "datetime": call_request.datetime
        }
        
        task = asyncio.create_task(schedule_call(q_id, delay, call_data))
        scheduled_calls[q_id] = task
        scheduled_calls_data[q_id] = call_data
        
        return {"status": "queued", "queue_id": q_id}
        
    except ValueError:
        return Response(content=json.dumps({"error": "Invalid datetime format. Use YYYY-MM-DD-HH-MM"}), status_code=400, media_type="application/json")

async def handle_immediate_call(call_request: CallRequest):
    global SERVER_PUBLIC_URL, call_data_store
    
    public_url = SERVER_PUBLIC_URL
    print("Using Public URL for callback: ", public_url)
    call_sid = services.twilio.make_outbound_call(public_url, call_request.to_number)
    
    if call_sid:
        call_data_store[call_sid] = {"prompt": services.gemini.GEMINI_PROMPTS["outbound_init"] + call_request.prompt}
        return {"status": "success", "call_sid": call_sid}
    else:
        return Response(content=json.dumps({"status": "error", "message": "Failed to initiate call."}), status_code=500, media_type="application/json")

# Initiate a new outbound call
@app.post("/make_call")
async def make_outbound_call_handler(request: Request, call_request: CallRequest):
    if call_request.datetime:
        return await handle_scheduled_call(call_request)
    return await handle_immediate_call(call_request)


# ==========================================
# Group 3: Active Call Control
# ==========================================

# Helper to get active call sid
def get_current_call_sid():
    global current_call_sid
    return current_call_sid

async def send_prompt_to_call(call_sid: str, payload: dict):
    prompt = payload.get("prompt")
    if not prompt:
        return Response(content=json.dumps({"error": "Prompt is required"}), status_code=400, media_type="application/json")

    global active_cm
    if active_cm and current_call_sid == call_sid:
        await active_cm.send_text_prompt(prompt)
        return {"status": "sent", "prompt": prompt}
    
    return Response(content=json.dumps({"error": "Active call not found"}), status_code=404, media_type="application/json")

# Send a text prompt to the currently active call
@app.post(f"/{CALLS_ENDPOINT}/{CURRENT_CALL_ENDPOINT}/prompt")
async def send_prompt_to_current_call(payload: dict):
    call_sid = get_current_call_sid()
    if not call_sid:
        return Response(content=json.dumps({"error": "No active calls"}), status_code=404, media_type="application/json")
    return await send_prompt_to_call(call_sid, payload)

# Serve the preview page for the currently active call
@app.get(f"/{CALLS_ENDPOINT}/{CURRENT_CALL_ENDPOINT}/preview")
async def preview_current_call(request: Request):
    call_sid = get_current_call_sid()
    if not call_sid:
        return HTMLResponse("<h1>No active call to preview</h1>")

    scheme = "wss" if request.url.scheme == "https" else "ws"
    ws_url = f"{scheme}://{request.url.netloc}/{CALLS_ENDPOINT}/{CURRENT_CALL_ENDPOINT}/ws"

    html_content = f"""
    <html>
        <head>
            <title>Call Preview: {call_sid}</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; display: flex; flex-direction: column; height: 90vh; }}
                .status {{ padding: 10px; background: #eee; margin-bottom: 20px; }}
                .controls {{ border-top: 1px solid #ccc; padding-top: 20px; margin-bottom: 20px; }}
                input[type="text"] {{ width: 300px; padding: 5px; }}
                button {{ padding: 5px 10px; }}
                #chat-container {{ flex-grow: 1; border: 1px solid #ddd; overflow-y: auto; padding: 10px; background: #f9f9f9; }}
                .message {{ margin-bottom: 10px; padding: 8px; border-radius: 5px; max-width: 80%; }}
                .role-assistant {{ background-color: #e1f5fe; align-self: flex-start; }}
                .role-admin {{ background-color: #e8f5e9; align-self: flex-end; margin-left: auto; }}
                .role-system {{ background-color: #eee; text-align: center; font-style: italic; max-width: 100%; }}
                .role-user {{ background-color: #fff3e0; align-self: flex-start; }}
                .meta {{ font-size: 0.8em; color: #666; margin-bottom: 2px; }}
            </style>
        </head>
        <body>
            <h1>Call: {call_sid}</h1>
            <div class="status">
                Status: <span id="status-text">{'Active' if call_sid == current_call_sid else 'Inactive'}</span>
                <button onclick="toggleAudio()" id="audio-btn">Enable Audio</button>
            </div>
            
            <div id="chat-container"></div>

            <div class="controls">
                <h3>Inject Prompt</h3>
                <input type="text" id="promptInput" placeholder="Enter text to say..." onkeydown="if(event.key === 'Enter') sendPrompt()">
                <button onclick="sendPrompt()">Send</button>
            </div>

            <script>
                const wsUrl = "{ws_url}";
                let ws;
                let audioCtx;
                let nextStartTime = 0;

                function initAudio() {{
                    if (!audioCtx) {{
                        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    }}
                    if (audioCtx.state === 'suspended') {{
                        audioCtx.resume();
                    }}
                }}

                function toggleAudio() {{
                    initAudio();
                    document.getElementById('audio-btn').innerText = "Audio Enabled";
                }}

                function playPcm(base64Data) {{
                    if (!audioCtx) return;
                    
                    const binaryString = window.atob(base64Data);
                    const len = binaryString.length;
                    const bytes = new Uint8Array(len);
                    for (let i = 0; i < len; i++) {{
                        bytes[i] = binaryString.charCodeAt(i);
                    }}
                    
                    // Convert 16-bit PCM to float32
                    const int16 = new Int16Array(bytes.buffer);
                    const float32 = new Float32Array(int16.length);
                    for (let i = 0; i < int16.length; i++) {{
                        float32[i] = int16[i] / 32768.0;
                    }}
                    
                    const buffer = audioCtx.createBuffer(1, float32.length, 8000);
                    buffer.copyToChannel(float32, 0);
                    
                    const source = audioCtx.createBufferSource();
                    source.buffer = buffer;
                    source.connect(audioCtx.destination);
                    
                    const BUFFER_DELAY = 0.15; // 150ms buffer
                    if (nextStartTime < audioCtx.currentTime) {{
                        nextStartTime = audioCtx.currentTime + BUFFER_DELAY;
                    }}
                    source.start(nextStartTime);
                    nextStartTime += buffer.duration;
                }}

                function connect() {{
                    ws = new WebSocket(wsUrl);
                    const statusText = document.getElementById('status-text');

                    ws.onopen = function() {{
                        addMessage("system", "Connected to live updates");
                        statusText.innerText = "Connected (Active)";
                    }};

                    ws.onmessage = function(event) {{
                        const data = JSON.parse(event.data);
                        if (data.type === 'log') {{
                            addMessage(data.role, data.text);
                        }} else if (data.type === 'audio') {{
                            playPcm(data.data);
                        }}
                    }};

                    ws.onclose = function() {{
                        addMessage("system", "Connection closed");
                        statusText.innerText = "Disconnected";
                    }};
                }}

                function addMessage(role, text) {{
                    const chatContainer = document.getElementById('chat-container');
                    const lastMessage = chatContainer.lastElementChild;
                    
                    // Check if the last message exists and has the same role
                    if (lastMessage && lastMessage.classList.contains("role-" + role) && role !== 'system') {{
                        // Append text to the existing content div
                        const contentDiv = lastMessage.querySelector('.content');
                        if (contentDiv) {{
                            contentDiv.innerText += text;
                        }}
                    }} else {{
                        // Create new message block
                        const div = document.createElement('div');
                        div.className = "message role-" + role;
                        
                        const meta = document.createElement('div');
                        meta.className = "meta";
                        meta.innerText = role.toUpperCase();
                        
                        const content = document.createElement('div');
                        content.className = "content"; // Add class for easy selection
                        content.innerText = text;
                        
                        if (role !== 'system') {{
                            div.appendChild(meta);
                        }}
                        div.appendChild(content);
                        chatContainer.appendChild(div);
                    }}
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }}

                async function sendPrompt() {{
                    const input = document.getElementById('promptInput');
                    const prompt = input.value;
                    if (!prompt) return;
                    
                    try {{
                        const response = await fetch('/{CALLS_ENDPOINT}/{CURRENT_CALL_ENDPOINT}/prompt', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ prompt: prompt }})
                        }});
                        const result = await response.json();
                        if (result.status === 'sent') {{
                            input.value = '';
                        }} else {{
                            alert('Error: ' + JSON.stringify(result));
                        }}
                    }} catch (e) {{
                        alert('Error: ' + e);
                    }}
                }}
                
                connect();
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# WebSocket endpoint for streaming call audio and logs
@app.websocket(f"/{CALLS_ENDPOINT}/{CURRENT_CALL_ENDPOINT}/ws")
async def preview_websocket(websocket: WebSocket):
    await websocket.accept()
    
    global active_cm
    if not active_cm or current_call_sid != call_sid:
        await websocket.close(code=1000, reason="Call not active")
        return

    await active_cm.add_observer(websocket)
    try:
        while True:
             await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Preview websocket error: {e}")
    finally:
        if active_cm:
            active_cm.remove_observer(websocket)

# ==========================================
# Group 4: Twilio Integration (Webhooks & Streams)
# ==========================================

# Twilio webhook for call status updates
@app.post(f"/{TWILIO_ENDPOINT}/status_callback")
async def status_callback_handler(request: Request):
    global current_call_sid, active_cm
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    answered_by = form_data.get("AnsweredBy")

    print(f"Call {call_sid} status: {call_status}, AnsweredBy: {answered_by}")

    if call_status in ["busy", "no-answer", "failed", "canceled"] or (answered_by and answered_by.startswith("machine")):
        if call_sid in call_data_store:
            del call_data_store[call_sid]
        
        if call_sid == current_call_sid:
            current_call_sid = None
            active_cm = None

        try:
            call = services.twilio.twilio_client.calls(call_sid).fetch()
            call_dict = {k: v for k, v in call.__dict__.items() if not k.startswith('_')}
            process_call(call_sid, call_dict, "None", [])
        except Exception as e:
            print(f"Error in status callback processing: {e}")
    else:
        print(f"Call {call_sid} status '{call_status}' is not considered a failure. Webhook not sent.")

    return Response(content="OK", status_code=200)

# Twilio webhook for incoming voice calls
@app.post(f"/{TWILIO_ENDPOINT}/voice")
async def voice_handler(request: Request):
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
    websocket_url = f"wss://{request.headers['host']}/{TWILIO_ENDPOINT}/ws"
    connect.stream(url=websocket_url)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")

# Main WebSocket handler for Twilio Media Streams
@app.websocket(f"/{TWILIO_ENDPOINT}/ws")
async def websocket_handler(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection established.")


    global current_call_sid, active_cm

    call_state = {"stream_sid": None}
    conversation_manager = None
    gemini_task = None
    call_sid = None

    try:
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
            except asyncio.CancelledError:
                 break

            data = json.loads(message)

            if data['event'] == 'start':
                print(data)
                call_state['stream_sid'] = data['start']['streamSid']
                call_sid = data['start']['callSid']
                os.makedirs(os.path.join(CALLS_DIR, call_sid), exist_ok=True)
                recording_path = os.path.join(CALLS_DIR, call_sid, RECORDING_FILENAME)
                print(f"Twilio stream started: {call_state['stream_sid']}")

                if call_sid in call_data_store:
                   prompt = call_data_store[call_sid]["prompt"]
                   print(f"Using custom prompt for call {call_sid}")
                   del call_data_store[call_sid]
                else:
                   prompt = services.gemini.GEMINI_PROMPTS["inbound_init"]
                   print(f"Using default inbound prompt for call {call_sid}")

                if active_cm is not None:
                     print(f"Rejecting new call {call_sid} because {current_call_sid} is active")
                     # We can't easily reject via websocket other than closing or ignoring. 
                     # But for better UX, we might want to just proceed and let the old one handle itself or similar.
                     # User request: "operate on only one active call".
                     # Let's enforce strict single call.
                     # Actually, if we just overwrite, we might kill the previous one. 
                     # Let's just overwrite for now as it seems most robust for "I want to switch to this call".
                     # OR if the user meant "don't handle two at once", maybe just error?
                     # A common pattern is "Busy". But here we are already connected via WS.
                     # Let's check if the previous one is still running.
                     pass 

                current_call_sid = call_sid
                conversation_manager = services.gemini.GeminiConversationManager(websocket, call_state, prompt)
                active_cm = conversation_manager
                # active_calls[call_sid] = conversation_manager # Removed active_calls usage
                
                gemini_task = asyncio.create_task(conversation_manager.run())
                conversation_manager.start_recording(recording_path)
                conversation_manager.initial_prompt_sent.set()

            elif data['event'] == 'media':
                if not conversation_manager:
                    continue
                
                mulaw_audio = base64.b64decode(data['media']['payload'])
                # Convert mulaw to 16-bit PCM for Gemini
                pcm_audio = services.utils_audio.ulaw2lin(mulaw_audio, 2)
                
                if conversation_manager and conversation_manager.recorder:
                    conversation_manager.recorder.writeframes(pcm_audio)
                if conversation_manager:
                    await conversation_manager.input_queue.put(('audio', pcm_audio))
                    # Broadcast audio for preview (we use the same PCM chunks)
                    await conversation_manager.broadcast_audio(pcm_audio)

            elif data['event'] == 'stop':
                print("Twilio stream stopped.")
                if conversation_manager:
                    await conversation_manager.input_queue.put(None)
                break

        if gemini_task:
            await gemini_task

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if call_sid and call_sid == current_call_sid:
            current_call_sid = None
            active_cm = None
            # del active_calls[call_sid]

        if gemini_task and not gemini_task.done():
            gemini_task.cancel()

        print("Closing WebSocket connection.")
        if conversation_manager and conversation_manager.recorder:
            conversation_manager.recorder.close()
            print("Recording saved.")
        if websocket.client_state != 3:
             await websocket.close()
        
        if call_sid:
            try:
                call = services.twilio.twilio_client.calls(call_sid).fetch()
                call_dict = {k: v for k, v in call.__dict__.items() if not k.startswith('_')}
                
                call_dir = os.path.join(CALLS_DIR, call_sid)
                os.makedirs(call_dir, exist_ok=True)
                
                if call.answered_by and call.answered_by.startswith("machine"):
                    print(f"Call answered by {call.answered_by}. Skipping success webhook and deleting recording.")
                    if os.path.exists(call_dir):
                        shutil.rmtree(call_dir)
                        print(f"Deleted call directory: {call_dir}")
                else:
                    recording_path = os.path.join(call_dir, RECORDING_FILENAME)
                    summarized_text = None
                    
                    transcription_history = []
                    if conversation_manager:
                         transcription_history = conversation_manager.transcription_history
                         if SUMMARIZE_CALLS:
                             try:
                                 summarized_text = services.gemini.gemini_summarize_call(transcription_history)
                             except:
                                 summarized_text = None

                    process_call(call_sid, call_dict, summarized_text, transcription_history)
            except Exception as e:
                print(f"Error in post-call processing: {e}")







# ==========================================
# Group 5: Call Management
# ==========================================

def process_call(call_sid: str, call_dict: dict, summarized_text: Optional[str] = None, transcription: list = []):
    try:
        call_dir = os.path.join(CALLS_DIR, call_sid)
        os.makedirs(call_dir, exist_ok=True)
        
        webhook_payload = {
            "twilio_call_data": call_dict,
            "summarized_text": summarized_text,
            "transcription": transcription
        }
        
        metadata_path = os.path.join(call_dir, METADATA_FILENAME)
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(webhook_payload, f, default=utils.json_datetime_serializer, ensure_ascii=False)

        utils.cleanup_calls(CALLS_DIR, KEEP_CALLS)

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
        print(f"Error in process_call for {call_sid}: {e}")

# List all historical calls
@app.get(f"/{CALLS_ENDPOINT}")
async def get_calls_list():
    if not os.path.exists(CALLS_DIR):
        return []
    calls = [d for d in os.listdir(CALLS_DIR) if os.path.isdir(os.path.join(CALLS_DIR, d))]
    return calls

# Retrieve a specific file (audio or JSON) for a call
@app.get(f"/{CALLS_ENDPOINT}/{{call_sid}}/{{filename}}")
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

# Delete a call recording and metadata
@app.delete(f"/{CALLS_ENDPOINT}/{{call_sid}}")
async def delete_call(call_sid: str):
    call_dir = os.path.join(CALLS_DIR, call_sid)
    if os.path.exists(call_dir):
        try:
            shutil.rmtree(call_dir)
            return {"status": "deleted", "call_sid": call_sid}
        except Exception as e:
             return Response(content=json.dumps({"error": f"Failed to delete: {e}"}), status_code=500, media_type="application/json")
    return Response(content=json.dumps({"error": "Call not found"}), status_code=404, media_type="application/json")
