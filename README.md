# Voice Scheduling Agent

A real-time AI voice assistant that books Google Calendar meetings through natural conversation — powered by [Vapi](https://vapi.ai), FastAPI, and the Google Calendar API.

---

## Live Demo

> **Deployed at:** `https://voice-agent-kjjt.onrender.com/demo`
> *(replace with your Render URL after deploying — see [Deploy to Render](#deploy-to-render) below)*

Open the URL in any browser and click **Talk to Agent**. No account, no setup, no install required.

**To test locally instead** — run `python run_agent.py` (5-minute setup below), then open `http://localhost:10000/demo`.

---

## How to Test the Agent

### Option 1 — Browser (recommended, zero friction)

1. Open the demo URL above
2. Click **Talk to Agent** and allow microphone access
3. Speak naturally — the agent will guide you:
   - *"What's your name?"*
   - *"What date works for you?"*
   - *"What time?"*
   - *"What should I call this meeting?"*
   - *"Just to confirm — I'll book [title] for [name] on [date] at [time] Eastern Time, for 45 minutes. Does that sound right?"*
4. Say **"yes"** to confirm — the event is created live on Google Calendar

### Option 2 — REST API directly

```bash
curl -X POST https://voice-agent-kjjt.onrender.com/schedule \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "date": "2026-03-20", "time": "14:00", "title": "Demo Call"}'
```

Response:

```json
{
  "status": "success",
  "message": "Done! I have booked 'Demo Call' for Alice on Friday, March 20 at 2:00 PM Eastern Time. The meeting is 45 minutes long.",
  "event_id": "abc123xyz",
  "event_link": "https://www.google.com/calendar/event?eid=..."
}
```

### Option 3 — Phone call

Vapi Dashboard → Phone Numbers → Buy a number → link it to the **Voice Scheduling Assistant**. Call it and speak naturally.

---

## Calendar Integration

### How it works

The agent authenticates with Google Calendar using a **Service Account** — a server-side credential that requires no user login or OAuth flow.

```
Voice call
  → Vapi (STT → GPT-4o-mini decides to book → TTS)
    → POST /vapi/tool-call  (this FastAPI backend)
      → calendar_service.py  (Service Account auth)
        → Google Calendar API  (event inserted)
          → confirmation spoken back to caller
```

### Authentication

1. A Google Cloud Service Account key (JSON) is stored as a single-line string in the `GOOGLE_CREDENTIALS_JSON` environment variable — no JSON file on disk, never committed to git
2. On each booking request, `calendar_service.py` loads the credentials:
   ```python
   info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
   creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
   service = build("calendar", "v3", credentials=creds)
   ```
3. The service account email (`voice-agent@voice-agent-488721.iam.gserviceaccount.com`) is shared on the target calendar with **"Make changes to events"** permission in Google Calendar settings

### Event creation

```python
service.events().insert(
    calendarId=os.environ.get("CALENDAR_ID", "primary"),
    body={
        "summary": title,
        "start": {"dateTime": start_time.isoformat(), "timeZone": "America/New_York"},
        "end":   {"dateTime": end_time.isoformat(),   "timeZone": "America/New_York"},
    }
).execute()
```

- All events are 45 minutes, in **Eastern Time**
- `CALENDAR_ID` in `.env` controls which calendar receives events (defaults to `"primary"`)
- The API returns the event's `htmlLink` — logged to the terminal and returned in the JSON response so every booking is immediately verifiable

### Why Service Account (not OAuth)?

OAuth requires a user to click "Allow" in a browser each time. A Service Account is pre-authorized for server-to-server access — exactly right for an automated voice agent that books meetings without any human interaction on the backend.

---

## Proof of Event Creation

Every booking prints two lines to the server terminal:

```
[calendar_service] Creating event in calendarId='omarshehab061@gmail.com'
[calendar_service] Event created: https://www.google.com/calendar/event?eid=dW91cDdl...
```

Live test output (March 3, 2026):

```
--- Booking test event ---
[calendar_service] Creating event in calendarId='omarshehab061@gmail.com'
[calendar_service] Event created: https://www.google.com/calendar/event?eid=dW91cDdldmw2MjhjaWFvam12ZmtnbHJyc2cgb21hcnNoZWhhYjA2MUBt
Returned event_id:   uoup7evl628ciaojmvfkglrrsg
Returned event_link: https://www.google.com/calendar/event?eid=dW91cDdldmw2MjhjaWFvam12ZmtnbHJyc2cgb21hcnNoZWhhYjA2MUBt
--- Done ---
```

The `event_link` is a direct Google Calendar URL — click it to see the event live on the calendar.

---

## Run Locally (5 minutes)

### Prerequisites

| Tool | Install |
|---|---|
| Python 3.11+ | [python.org](https://www.python.org/downloads/) |
| ngrok (free account) | `brew install ngrok` then [dashboard.ngrok.com](https://dashboard.ngrok.com) → Auth |
| Vapi account | [vapi.ai](https://vapi.ai) (free tier) |
| Google Cloud Service Account | [console.cloud.google.com](https://console.cloud.google.com) |

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in three values:

**`GOOGLE_CREDENTIALS_JSON`** — your Service Account JSON key, compacted to a single line:
```bash
python -c "import json; print(json.dumps(json.load(open('your-key.json'))))"
# paste the output as the value
```
> Also share your Google Calendar with the service account's `client_email` and grant **"Make changes to events"** permission.

**`VAPI_API_KEY`** — Vapi Dashboard → Account → API Keys → **Secret Key**

**`VAPI_PUBLIC_KEY`** — same page → **Public Key** (separate field, safe for browsers)

### 3. Authenticate ngrok

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

### 4. Run

```bash
python run_agent.py
```

The script handles everything automatically:

```
[1/5] Checking environment...
      .env loaded ✓

[2/5] Starting FastAPI backend on port 10000...
      Waiting for backend....... ready ✓

[3/5] Starting ngrok tunnel...
      Waiting for ngrok tunnel.. ready ✓
      Tunnel URL: https://abc123.ngrok-free.app

[4/5] Registering Vapi assistant...
      'Voice Scheduling Assistant' created (ID: asst_xxx) ✓

[5/5] Agent is live!

──────────────────────────────────────────────────────────────
  🎤  TALK NOW  →  http://localhost:10000/demo

  Backend     →  http://localhost:10000
  Public URL  →  https://abc123.ngrok-free.app
  API docs    →  http://localhost:10000/docs
  ngrok UI    →  http://localhost:4040

  Vapi assistant : Voice Scheduling Assistant
  Assistant ID   : asst_xxx
──────────────────────────────────────────────────────────────

Press Ctrl+C to stop all services.
```

Open `http://localhost:10000/demo`, click **Talk to Agent**, and speak. Press **Ctrl+C** to stop everything cleanly.

---

## Running Tests

```bash
pytest tests/ -v
# 35 tests — all run offline with mocked Google and Vapi calls
```

---

## Project Structure

```
voice-agent/
├── main.py                   # FastAPI app (4 endpoints)
│                             #   GET  /demo           → browser voice client
│                             #   POST /schedule       → direct REST booking
│                             #   POST /vapi/tool-call → Vapi webhook
│                             #   POST /internal/set-agent → injects assistant ID post-startup
├── calendar_service.py       # Google Calendar Service Account auth + event creation
├── demo.html                 # Vapi Web SDK browser client (served by /demo)
├── vapi_config.json          # Vapi assistant definition (system prompt, voice, tool schema)
├── create_vapi_assistant.py  # Registers the assistant via Vapi REST API
├── run_agent.py              # One-command launcher (uvicorn + ngrok + Vapi setup)
├── requirements.txt
├── Procfile                  # Render deployment: uvicorn main:app --host 0.0.0.0 --port 10000
├── .env.example              # Environment variable template
└── tests/
    ├── test_main.py          # 23 API endpoint tests
    └── test_calendar_service.py  # 12 unit tests for auth + event creation
```

---

## Architecture

```
┌──────────────────────┐
│   Browser / Caller   │
└────────┬─────────────┘
         │  voice (Vapi Web SDK or phone)
         ▼
┌──────────────────────┐
│   Vapi Platform      │  STT → GPT-4o-mini → TTS
│  (manages dialogue)  │  collects: name, date, time, title
└────────┬─────────────┘
         │  POST /vapi/tool-call  (after user confirms)
         ▼
┌──────────────────────┐
│   FastAPI Backend    │  parses args, calls calendar_service
└────────┬─────────────┘
         │  Service Account credentials (from env var)
         ▼
┌──────────────────────┐
│  Google Calendar API │  inserts 45-min event, returns htmlLink
└──────────────────────┘
```

---

## Deploy to Render

1. Push to GitHub (`.env` is in `.gitignore` — credentials are safe)
2. Render → **New Web Service** → connect your repo
3. Add environment variables in Render's dashboard:
   - `GOOGLE_CREDENTIALS_JSON`
   - `VAPI_API_KEY`
   - `VAPI_PUBLIC_KEY`
   - `VAPI_ASSISTANT_ID` ← get this by running:
     ```bash
     python create_vapi_assistant.py --url https://voice-agent-kjjt.onrender.com/
     ```
4. The `Procfile` is auto-detected; your app goes live at `https://voice-agent-kjjt.onrender.com/demo`
5. Update the **Live Demo** URL at the top of this README
