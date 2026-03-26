import os
from twilio.rest import Client
from dotenv import load_dotenv
import utils

load_dotenv()

twilio_client = Client(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

def get_twilio_call_data(call_sid: str) -> dict:
    """Fetches a Twilio call by its SID and returns a dict."""
    call = twilio_client.calls(call_sid).fetch()
    return {k: v for k, v in call.__dict__.items() if not k.startswith('_')}

def update_twilio_webhook(phone_number: str, public_url: str):
    """Updates the Twilio voice webhook URL."""
    if not phone_number:
        return
    try:
        numbers = twilio_client.incoming_phone_numbers.list(phone_number=phone_number)
        if numbers:
            twilio_client.incoming_phone_numbers(numbers[0].sid).update(
                voice_url=f"{public_url}/twilio/voice"
            )
            print(f"Updated Twilio webhook for {phone_number}")
    except Exception as e:
        print(f"Error updating Twilio webhook: {e}")

def make_outbound_call(public_url: str, to_number: str) -> str | None:
    """Initiates an outbound call using Twilio."""
    if not utils.args.phone_number:
        print("phone_number argument not set.")
        return None
    try:
        call = twilio_client.calls.create(
            to=to_number,
            from_=utils.args.phone_number,
            url=f"{public_url}/twilio/voice",
            status_callback=f"{public_url}/twilio/status_callback",
            status_callback_method='POST',
            machine_detection='Enable'
        )
        return call.sid
    except Exception as e:
        print(f"Error making outbound call: {e}")
        return None
