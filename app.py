import asyncio
import base64
import json
import os
import audioop
import shutil
import secrets
import requests
from contextlib import asynccontextmanager
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, Request, status
from fastapi.responses import Response, HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv

import utils
import services

load_dotenv()

CALLS_DIR = "user_data/calls"
RECORDING_FILE, TRANSCRIPT_FILE, TWILIO_DATA_FILE = "recording.wav", "transcript.json", "twilio_call.json"
EP = type("EP", (), {"calls": "calls", "make": "make", "twilio": "twilio", "live": "live", "verify": "verify"})

class State:
    call_prompts: Dict[str, str] = {}
    live_sid: Optional[str] = None
    active_cm: Optional[services.gemini.GeminiConversationManager] = None

async def verify_public_url(url: str):
    try:
        headers = {}
        if utils.args.enable_auth:
            cred = base64.b64encode(f"{os.environ.get('HTTP_USERNAME', '')}:{os.environ.get('HTTP_PASSWORD', '')}".encode()).decode()
            headers["Authorization"] = f"Basic {cred}"
        res = await asyncio.to_thread(requests.get, f"{url.rstrip('/')}/{EP.verify}", headers=headers, timeout=10)
        if res.status_code == 200 and res.json().get("status") == "success":
            print("Public URL verified successfully.")
    except Exception as e:
        print(f"Public URL verification failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if utils.args.public_url:
        asyncio.create_task(verify_public_url(utils.args.public_url))
    yield

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def verify_password(request: Request, call_next):
    if utils.args.enable_auth and any(request.url.path.startswith(f"/{p}") for p in [EP.calls, EP.live, EP.verify]):
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "): 
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"}, content={"detail": "Unauthorized"})
        try:
            u, p = base64.b64decode(auth[6:]).decode().split(":", 1)
            if not (secrets.compare_digest(u, os.environ.get("HTTP_USERNAME", "")) and secrets.compare_digest(p, os.environ.get("HTTP_PASSWORD", ""))):
                raise ValueError
        except Exception:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"}, content={"detail": "Unauthorized"})
    return await call_next(request)

@app.get("/")
async def root_endpoint():
    return Response(content="AutoPhone", media_type="text/plain")

@app.get(f"/{EP.verify}")
async def verify_endpoint():
    return {"status": "success"}

# outbound calls

class CallRequest(BaseModel):
    to_number: str
    prompt: str

@app.post(f"/{EP.make}")
async def make_call(req: CallRequest):
    if not utils.args.public_url:
        return JSONResponse({"status": "error", "message": "Server public URL not set."}, status_code=500)
    sid = services.twilio.make_outbound_call(utils.args.public_url, req.to_number)
    if sid:
        State.call_prompts[sid] = services.gemini.GEMINI_PROMPTS["outbound_init"] + req.prompt
        return {"status": "success", "call_sid": sid}
    return JSONResponse({"status": "error", "message": "Failed to initiate call."}, status_code=500)

# live call

@app.get(f"/{EP.live}")
async def get_live_info():
    return {"active": State.active_cm is not None, "call_sid": State.live_sid}

@app.get(f"/{EP.live}/audio")
async def live_audio_html(req: Request):
    if not State.live_sid: return HTMLResponse("<h1>No active call to preview</h1>")
    ws_url = f"{'wss' if req.url.scheme == 'https' else 'ws'}://{req.headers.get('host')}/{EP.live}/ws"
    with open("audio.html", "r") as f:
        return HTMLResponse(f.read().replace("{{AUDIO_URL}}", ws_url))

@app.websocket(f"/{EP.live}/ws")
async def live_ws(ws: WebSocket):
    await ws.accept()
    if not State.active_cm: return await ws.close(code=1000, reason="No active call")
    cm = State.active_cm
    cm.observers.add(ws)
    try:
        while not cm.call_ended_event.is_set():
            recv = asyncio.create_task(ws.receive_text())
            end = asyncio.create_task(cm.call_ended_event.wait())
            done, _ = await asyncio.wait([recv, end], return_when=asyncio.FIRST_COMPLETED)
            if end in done: break
            await cm.send_text_prompt(recv.result())
    except Exception: pass
    finally:
        cm.observers.discard(ws)
        try:
            if ws.client_state.value == 1 and ws.application_state.value == 1:
                await ws.close()
        except Exception:
            pass

# twilio

@app.post(f"/{EP.twilio}/status_callback")
async def twilio_status(req: Request):
    form = await req.form()
    sid, stat, ans = form.get("CallSid"), form.get("CallStatus"), form.get("AnsweredBy")
    if stat in ["busy", "no-answer", "failed", "canceled"] or (ans and ans.startswith("machine")):
        State.call_prompts.pop(sid, None)
        if sid == State.live_sid: State.live_sid, State.active_cm = None, None
        asyncio.create_task(asyncio.to_thread(post_process_call, sid, []))
    return Response(content="OK")

@app.post(f"/{EP.twilio}/voice")
async def twilio_voice(req: Request):
    form = await req.form()
    ans, fwd = form.get("AnsweredBy"), form.get("ForwardedFrom")
    resp = VoiceResponse()
    if (ans and ans.startswith("machine")) or fwd:
        resp.hangup()
    else:
        conn = Connect()
        conn.stream(url=f"wss://{req.headers['host']}/{EP.twilio}/ws")
        resp.append(conn)
    return Response(content=str(resp), media_type="application/xml")

@app.websocket(f"/{EP.twilio}/ws")
async def twilio_ws(ws: WebSocket):
    await ws.accept()
    cm, sid, gemini_task = None, None, None
    try:
        while True:
            recv_task = asyncio.create_task(ws.receive_text())
            tasks = [recv_task] + ([gemini_task] if gemini_task else [])
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            if gemini_task and gemini_task in done:
                print(f"DEBUG [{sid}]: Gemini task triggered completion.")
                if gemini_task.exception():
                    print(f"DEBUG [{sid}]: Gemini task threw exception: {gemini_task.exception()}")
                recv_task.cancel()
                break
                
            try:
                msg = recv_task.result()
            except Exception as e:
                print(f"DEBUG [{sid}]: Twilio websocket disconnected or failed. Error: {e}")
                break
                
            data = json.loads(msg)
            if data['event'] == 'start':
                stream_sid, sid = data['start']['streamSid'], data['start']['callSid']
                os.makedirs(os.path.join(CALLS_DIR, sid), exist_ok=True)
                
                State.live_sid = sid
                cm = services.gemini.GeminiConversationManager(ws, {'stream_sid': stream_sid}, State.call_prompts.pop(sid, services.gemini.GEMINI_PROMPTS["inbound_init"]))
                State.active_cm = cm
                
                if not utils.args.no_recording: cm.start_recording(os.path.join(CALLS_DIR, sid, RECORDING_FILE))
                cm.initial_prompt_sent.set()
                gemini_task = asyncio.create_task(cm.run())
                print(f"DEBUG [{sid}]: Stream started, Gemini task launched.")

            elif data['event'] == 'media' and cm:
                try:
                    pcm = audioop.ulaw2lin(base64.b64decode(data['media']['payload']), 2)
                    await cm.input_queue.put(('audio', pcm))
                    await cm.process_user_audio(pcm)
                except Exception as e:
                    print(f"DEBUG [{sid}]: Media processing error: {e}")
            
            elif data['event'] == 'stop':
                print(f"DEBUG [{sid}]: Twilio requested stop.")
                if cm: await cm.input_queue.put(None)
                break
    except Exception as e:
        print(f"DEBUG [{sid}]: Unexpected twilio_ws error: {e}")
    finally:
        print(f"DEBUG [{sid}]: WebSocket closing cleanup.")
        if sid and sid == State.live_sid: State.live_sid, State.active_cm = None, None
        if gemini_task and not gemini_task.done(): gemini_task.cancel()
        if cm and cm.recorder: cm.recorder.close()
        try:
            if ws.client_state.value == 1 and ws.application_state.value == 1:
                await ws.close()
        except Exception:
            pass
        if sid: asyncio.create_task(asyncio.to_thread(post_process_call, sid, cm.transcription_history if cm else []))

# call management

def post_process_call(sid: str, transcript: list):
    try:
        data = services.twilio.get_twilio_call_data(sid)
        cdir = os.path.join(CALLS_DIR, sid)
        os.makedirs(cdir, exist_ok=True)
        with open(os.path.join(cdir, TWILIO_DATA_FILE), 'w') as f: json.dump(data, f, default=utils.json_datetime_serializer)
        with open(os.path.join(cdir, TRANSCRIPT_FILE), 'w') as f: json.dump(transcript, f, default=utils.json_datetime_serializer)
        utils.cleanup_calls(CALLS_DIR, utils.args.keep_calls)
    except Exception as e:
        print(f"Error processing {sid}: {e}")

    if utils.args.notify:
        asyncio.create_task(asyncio.to_thread(requests.post, utils.args.notify, json=data, timeout=30))
        print(f"Webhook notification sent to {utils.args.notify}")

@app.get(f"/{EP.calls}")
async def list_calls():
    return [d for d in os.listdir(CALLS_DIR) if os.path.isdir(os.path.join(CALLS_DIR, d))] if os.path.exists(CALLS_DIR) else []

@app.get(f"/{EP.calls}/{{sid}}")
async def call_files(sid: str):
    d = os.path.join(CALLS_DIR, sid)
    return os.listdir(d) if os.path.exists(d) and os.path.isdir(d) else JSONResponse({"error": "Not found"}, 404)

@app.get(f"/{EP.calls}/{{sid}}/{{file}}")
async def call_file(sid: str, file: str, raw: bool = False):
    p = os.path.join(CALLS_DIR, sid, file)
    if not os.path.exists(p): return Response("Not found", 404)
    if file == RECORDING_FILE and not raw:
        try:
            with open("audio.html", "r") as f: return HTMLResponse(f.read().replace("{{AUDIO_URL}}", f"{file}?raw=true"))
        except FileNotFoundError: return HTMLResponse("audio.html missing")
    return FileResponse(p)

@app.delete(f"/{EP.calls}/{{sid}}")
async def del_call(sid: str):
    p = os.path.join(CALLS_DIR, sid)
    if os.path.exists(p):
        shutil.rmtree(p, ignore_errors=True)
        return {"status": "deleted"}
    return JSONResponse({"error": "Not found"}, 404)
