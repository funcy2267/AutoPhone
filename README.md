# AutoPhone
A voice assistant application powered by Gemini and Twilio, capable of handling inbound and outbound calls with real-time AI interaction.

## Features

- **Real-time Voice AI**: Uses Gemini Live API for voice conversations.
- **Twilio Integration**: Handles phone calls via Twilio Voice.
- **Call Summarization**: automatically summarizes calls after they end.

## Prerequisites

- Docker (and Docker Compose)
- Twilio Account (with phone number used for voice assistant)
- Ngrok Account
- Gemini API Key

# Configuration

### Get all required API keys.

- [Gemini API key](https://aistudio.google.com/api-keys)
- [Twilio Account SID and API key](https://www.twilio.com/docs/usage/requests-to-twilio)
- [Ngrok API key](https://dashboard.ngrok.com/get-started/your-authtoken)

### Copy the example environment file:
   ```
   cp .env.example .env
   ```
Edit `.env` to provide API keys and settings.

# Usage

## Running with Docker

To start the application:

```
sudo docker compose up
```

## API Endpoints

- `POST /call`: Initiate an outbound call.
```bash
curl -X POST "http://0.0.0.0:8080/call" \
  -H "Content-Type: application/json" \
  -d '{
    "to_number": "+1234567890",
    "prompt": "Ask how life is going"
  }'
```

- `GET /calls`: List all saved call SIDs.
- `GET /calls/{call_sid}/call.json`: Get the metadata for a specific call.
- `GET /calls/{call_sid}/recording.wav`: Get the audio recording for a specific call.

- After every call, a call metadata is saved and sent to the target webhook (if configured).
```json
{
    "call": {
        "call metadata here"
    },
    "summarized_text": "AI summarization of call"
}
```

## GUI

App is available [here](https://gallery.appinventor.mit.edu/?galleryid=468a172f-b469-43d4-b359-93a40cb70d4a).
