# AutoPhone
A voice assistant application powered by Gemini and Twilio, capable of handling phone calls with real-time AI interaction.

## Features

- **Real-time Voice AI**: Uses Gemini Live API for voice conversations.
- **Twilio Integration**: Handles phone calls via Twilio Voice.
- **Call Summarization**: Automatically summarizes calls after they end.
- **Live call preview**: Preview the call in real-time.
- **GUI App**: Graphical user interface for managing assistant.

## Prerequisites

- Python 3
- Twilio Account (with dedicated phone number used for voice assistant)
- Gemini API Key

# Configuration

### Get all required API keys

- [Gemini API key](https://aistudio.google.com/api-keys)
- [Twilio Account SID and API key](https://console.twilio.com)

### Provide API keys and settings

```bash
cp .env.example .env
cp settings.json.example settings.json
```

Edit `.env` and `settings.json` to provide API keys and settings.
Your instance must be publicly available, so use your own configuration or tunnelling service like [ngrok](https://ngrok.com).

### Install requirements
```bash
pip install -r requirements.txt
```

# Usage

## Running the Server

```bash
python3 main.py
```

## API Endpoints

Go to `/docs` on server to view API documentation.

## GUI

App is available [here](https://gallery.appinventor.mit.edu/?galleryid=468a172f-b469-43d4-b359-93a40cb70d4a).
