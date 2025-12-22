import os
import uvicorn
from pyngrok import ngrok
import services
from app import app, SERVER_PUBLIC_URL

# Configuration
SERVICE_PORT = 8080

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
    
    # We also need to update this validity in app.py if it uses it directly.
    # But app.py imports SERVER_PUBLIC_URL? No, variables are not shared like that.
    # We should set it on app module.
    import app as app_module
    app_module.SERVER_PUBLIC_URL = public_url
    
    print(f"Ngrok tunnel is active at: {public_url}")

    # Update the webhook for incoming calls
    services.twilio.update_twilio_webhook(public_url)

    try:
        # Run the FastAPI app
        uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)

    finally:
        print("Shutting down ngrok tunnel.")
        ngrok.disconnect(public_url)
        ngrok.kill()

if __name__ == "__main__":
    run_app()
