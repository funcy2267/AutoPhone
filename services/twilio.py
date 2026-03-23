import os
from twilio.rest import Client
from dotenv import load_dotenv
import utils

load_dotenv()

TWILIO_ENDPOINT = "twilio"

twilio_client = Client(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

def get_twilio_call_data(call_sid: str) -> dict:
    """Fetches a Twilio call by its SID and formats it into a dictionary."""
    call = twilio_client.calls(call_sid).fetch()
    return {k: v for k, v in call.__dict__.items() if not k.startswith('_')}

def update_twilio_webhook(public_url):
    """Finds the Twilio phone number and updates its voice webhook URL."""
    if not utils.args.phone_number:
        print("phone_number argument not set. Skipping webhook update.")
        return

    try:
        print(f"Attempting to update webhook for {utils.args.phone_number}...")
        incoming_phone_numbers = twilio_client.incoming_phone_numbers.list(phone_number=utils.args.phone_number)
        if not incoming_phone_numbers:
            print(f"Error: Phone number {utils.args.phone_number} not found in your Twilio account.")
            return

        number_sid = incoming_phone_numbers[0].sid
        twilio_client.incoming_phone_numbers(number_sid).update(voice_url=f"{public_url}/{TWILIO_ENDPOINT}/voice")
        print(f"Successfully updated webhook for {utils.args.phone_number}.")
    except Exception as e:
        print(f"Error updating Twilio webhook: {e}")

def make_outbound_call(public_url, to_number) -> str | None:
    """Initiates an outbound call using Twilio."""
    if not utils.args.phone_number:
        print("phone_number argument not set. Cannot make outbound call.")
        return None

    try:
        print(f"Initiating call to {to_number}...")
        call = twilio_client.calls.create(
            to=to_number,
            from_=utils.args.phone_number,
            url=f"{public_url}/{TWILIO_ENDPOINT}/voice",
            status_callback=f"{public_url}/{TWILIO_ENDPOINT}/status_callback",
            status_callback_method='POST',
            machine_detection='Enable'
        )
        print(f"Call initiated successfully. SID: {call.sid}")
        return call.sid
    except Exception as e:
        print(f"Error making outbound call: {e}")
        return None
