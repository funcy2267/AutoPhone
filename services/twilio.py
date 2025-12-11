import os
from twilio.rest import Client

twilio_client = Client(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

def update_twilio_webhook(public_url):
    """Finds the Twilio phone number and updates its voice webhook URL."""
    twilio_phone_number = os.environ.get("TWILIO_PHONE_NUMBER")
    if not twilio_phone_number:
        print("TWILIO_PHONE_NUMBER environment variable not set. Skipping webhook update.")
        return

    try:
        print(f"Attempting to update webhook for {twilio_phone_number}...")
        incoming_phone_numbers = twilio_client.incoming_phone_numbers.list(phone_number=twilio_phone_number)
        if not incoming_phone_numbers:
            print(f"Error: Phone number {twilio_phone_number} not found in your Twilio account.")
            return

        number_sid = incoming_phone_numbers[0].sid
        twilio_client.incoming_phone_numbers(number_sid).update(voice_url=f"{public_url}/voice")
        print(f"Successfully updated webhook for {twilio_phone_number}.")
    except Exception as e:
        print(f"Error updating Twilio webhook: {e}")

def make_outbound_call(public_url, to_number) -> str | None:
    """Initiates an outbound call using Twilio."""
    twilio_phone_number = os.environ.get("TWILIO_PHONE_NUMBER")
    if not twilio_phone_number:
        print("TWILIO_PHONE_NUMBER environment variable not set. Cannot make outbound call.")
        return None

    try:
        print(f"Initiating call to {to_number}...")
        call = twilio_client.calls.create(to=to_number, from_=twilio_phone_number, url=f"{public_url}/voice")
        print(f"Call initiated successfully. SID: {call.sid}")
        return call.sid
    except Exception as e:
        print(f"Error making outbound call: {e}")
        return None
