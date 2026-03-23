import argparse
import uvicorn
import utils

parser = argparse.ArgumentParser(description="AutoPhone")
parser.add_argument("phone_number", type=str, help="Twilio phone number used for voice assistant")
parser.add_argument("server_public_url", type=str, help="Publicly accessible server URL")
parser.add_argument("server_port", type=int, help="Run server on specified port")
parser.add_argument("--assistant-language", type=str, default="English", help="Assistant language")
parser.add_argument("--assistant-owner", type=str, help="Assistant owner name")
parser.add_argument("--keep-calls", type=int, default=5, help="Number of calls to keep")
parser.add_argument("--enable-auth", action="store_true", help="Require authentication when connecting to the server")
parser.add_argument("--notify", type=str, help="Send webhook notification to specified URL when assistant is starting a call")
parser.add_argument("--gemini-assistant-model", type=str, default="gemini-2.5-flash-native-audio-preview-09-2025", help="Gemini Live assistant model")
parser.add_argument("--gemini-assistant-voice", type=str, default="Sulafat", help="Gemini Live assistant voice")
parser.add_argument("--no-recording", action="store_true", help="Disable call recording")
args = parser.parse_args()

utils.args = args

import services
import app

def run_app():
    """Starts the FastAPI app to handle incoming calls."""

    public_url = utils.args.server_public_url

    if public_url:
        print(f"Using public URL: {public_url}")
        # Update the webhook for incoming calls
        services.twilio.update_twilio_webhook(public_url)
    else:
        print("Warning: SERVER_PUBLIC_URL not set.")

    try:
        # Run the FastAPI app
        uvicorn.run(app.app, host="0.0.0.0", port=utils.args.server_port)

    except Exception as e:
        print(f"Error starting app: {e}")

if __name__ == "__main__":
    run_app()
