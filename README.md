# AutoPhone
A voice assistant application powered by Gemini and Twilio, capable of handling phone calls with real-time AI interaction.

## Features

- **Real-time Voice AI**: Uses Gemini Live API for voice conversations.
- **Handling calls with Twilio**: Handles phone calls via Twilio Voice.
- **Live call preview**: Preview the call in real-time.
- **GUI App**: Graphical user interface for managing assistant.

## Prerequisites

- Python 3
- Twilio account (with dedicated phone number used for voice assistant)
- Google account (used for Gemini API)

# Configuration

### Get all required API keys

- [Gemini API key](https://aistudio.google.com/api-keys)
- [Twilio Account SID and API key](https://console.twilio.com)

### Provide API keys and settings

```bash
cp .env.example .env
```

Edit `.env` to provide credentials.
Your instance must be publicly available, so use your own configuration or tunnelling service like [ngrok](https://ngrok.com).

### Install requirements
```bash
pip install -r requirements.txt
```

# Usage

## Running the Server

```bash
python3 main.py --help
```

## API Endpoints

Go to `/docs` on server to view API documentation.

## GUI

App is available [here](https://gallery.appinventor.mit.edu/?galleryid=468a172f-b469-43d4-b359-93a40cb70d4a).
