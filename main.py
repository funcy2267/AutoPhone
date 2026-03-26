import argparse
import uvicorn
from pyngrok import ngrok
from dotenv import load_dotenv
import os

load_dotenv()

import utils
import services
import app

def parse_args():
    parser = argparse.ArgumentParser(description="AutoPhone")
    parser.add_argument("phone_number", type=str, help="Twilio phone number for voice assistant")
    parser.add_argument("--public-url", type=str, help="Publicly accessible server URL")
    parser.add_argument("--port", type=int, default=8080, help="Run server on specified port")
    parser.add_argument("--assistant-language", type=str, default="English", help="Assistant language")
    parser.add_argument("--assistant-owner", type=str, help="Assistant owner name")
    parser.add_argument("--keep-calls", type=int, default=5, help="Number of calls to keep")
    parser.add_argument("--enable-auth", action="store_true", help="Require basic authentication")
    parser.add_argument("--notify", type=str, help="Webhook URL for call start notification")
    parser.add_argument("--gemini-assistant-model", type=str, default="gemini-2.5-flash-native-audio-preview-09-2025", help="Gemini Live model")
    parser.add_argument("--gemini-assistant-voice", type=str, default="Sulafat", help="Gemini Live voice")
    parser.add_argument("--no-recording", action="store_true", help="Disable call recording")
    return parser.parse_args()

def main():
    utils.args = parse_args()

    public_url = utils.args.public_url

    if not public_url:
        try:
            ngrok_auth_token = os.environ.get("NGROK_AUTHTOKEN")
            if ngrok_auth_token:
                ngrok.set_ngrok_auth_token(ngrok_auth_token)
            tunnel = ngrok.connect(utils.args.port)
            public_url = tunnel.public_url
            utils.args.public_url = public_url
        except Exception as e:
            print(f"Error starting ngrok tunnel: {e}")

    if public_url:
        print(f"Using public URL: {public_url}")
        services.twilio.update_twilio_webhook(public_url)
    else:
        print("Warning: public_url not set.")

    try:
        uvicorn.run(app.app, host="0.0.0.0", port=utils.args.port)
    except Exception as e:
        print(f"Error starting app: {e}")

if __name__ == "__main__":
    main()
