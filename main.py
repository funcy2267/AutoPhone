import os
import uvicorn
from pyngrok import ngrok

import services
import app

# Configuration
SERVICE_PORT = 8080

def run_app():
    """Starts the ngrok tunnel and the FastAPI app to handle incoming calls."""

    public_url = None

    if os.environ.get("SERVER_PUBLIC_URL"):
        public_url = os.environ.get("SERVER_PUBLIC_URL")
        print(f"Using manual public URL: {public_url}")

    else:
        ngrok.set_auth_token(os.environ.get("NGROK_AUTHTOKEN"))
        tunnel = ngrok.connect(SERVICE_PORT)
        public_url = tunnel.public_url
        print(f"Ngrok tunnel is active at: {public_url}")

    app.SERVER_PUBLIC_URL = public_url

    # Update the webhook for incoming calls
    services.twilio.update_twilio_webhook(public_url)

    try:
        # Run the FastAPI app
        uvicorn.run(app.app, host="0.0.0.0", port=SERVICE_PORT)

    finally:
        print("Shutting down ngrok tunnel.")
        ngrok.disconnect(public_url)
        ngrok.kill()

if __name__ == "__main__":
    run_app()
