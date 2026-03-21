import uvicorn
import utils
import services
import app

settings = utils.load_settings()

# Configuration
SERVICE_PORT = settings.get("SERVICE_PORT")
SERVER_PUBLIC_URL = settings.get("SERVER_PUBLIC_URL")

def run_app():
    """Starts the FastAPI app to handle incoming calls."""

    public_url = SERVER_PUBLIC_URL

    if public_url:
        print(f"Using public URL: {public_url}")
        # Update the webhook for incoming calls
        services.twilio.update_twilio_webhook(public_url)
    else:
        print("Warning: SERVER_PUBLIC_URL not set.")

    try:
        # Run the FastAPI app
        uvicorn.run(app.app, host="0.0.0.0", port=SERVICE_PORT)

    except Exception as e:
        print(f"Error starting app: {e}")

if __name__ == "__main__":
    run_app()
