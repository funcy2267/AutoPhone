# AutoPhone
A voice assistant application powered by Gemini and Twilio, capable of handling inbound and outbound calls with real-time AI interaction.

## Features

- **Real-time Voice AI**: Uses Gemini Live API for voice conversations.
- **Twilio Integration**: Handles phone calls via Twilio Voice.
- **Call Summarization**: Automatically summarizes calls after they end.
- **Live call preview**: Preview the call in real-time.
- **GUI App**: Graphical user interface for managing assistant.

## Prerequisites

- Docker (with Docker Compose)
- Twilio Account (with dedicated phone number used for AutoPhone)
- Ngrok Account
- Gemini API Key

# Configuration

### Get all required API keys.

- [Gemini API key](https://aistudio.google.com/api-keys)
- [Twilio Account SID and API key](https://console.twilio.com)
- [Ngrok API key](https://dashboard.ngrok.com/get-started/your-authtoken)

### Copy the example environment file:

```bash
cp .env.example .env
```
Edit `.env` to provide API keys and settings.

# Usage

## Running with Docker

```
sudo docker compose up --build
```

## API Endpoints

Public URL will be available with Ngrok tunnel.

- `GET /calls` List all saved call SIDs.
- `GET /calls/{call_sid}/call.json` Get the metadata for a specific call.
- `GET /calls/{call_sid}/recording.wav` Get the audio recording for a specific call.
- `DELETE /calls/{call_sid}` Delete a specific call.

After every call, a call metadata is saved and sent to the target webhook (if configured).

### Outbound calls

- `POST /make_call`: Initiate an outbound call.

#### Queue

- `GET /calls/queue`: List queued calls ids.
- `GET /calls/queue/{id}`: Get the metadata for a specific queued call.
- `DELETE /calls/queue/{id}`: Remove a queued call.

Queue is not persistent, so it won't be saved after server restart.

## GUI

App is available [here](https://gallery.appinventor.mit.edu/?galleryid=468a172f-b469-43d4-b359-93a40cb70d4a).
