# AutoPhone
A voice assistant application powered by Gemini and Twilio, capable of handling phone calls with real-time AI interaction.

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

Public URL will be available with Ngrok tunnel.

## API Endpoints

Go to `/docs` to view API documentation.

## GUI

App is available [here](https://gallery.appinventor.mit.edu/?galleryid=468a172f-b469-43d4-b359-93a40cb70d4a).
