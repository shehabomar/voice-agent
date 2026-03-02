import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator

from calendar_service import DEFAULT_TIMEZONE, EVENT_DURATION_MINUTES, create_event

load_dotenv()

app = FastAPI(
    title="Voice Scheduling Agent",
    description="Backend API for an AI voice agent that books Google Calendar meetings.",
    version="1.0.0",
)

# In-memory store populated by run_agent.py after the Vapi assistant is created.
# Falls back to environment variables so the /demo page also works on Render.
_agent_state: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ScheduleRequest(BaseModel):
    name: str
    date: str  # Expected format: YYYY-MM-DD
    time: str  # Expected format: HH:MM  (24-hour)
    title: str

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format (e.g. 2026-03-15)")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%H:%M")
        except ValueError:
            raise ValueError("time must be in HH:MM 24-hour format (e.g. 14:30)")
        return v


class ScheduleResponse(BaseModel):
    status: str
    message: str
    event_id: str | None = None
    event_link: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Lightweight liveness probe used by Render and load balancers."""
    return {"status": "ok"}


@app.post("/schedule", response_model=ScheduleResponse, tags=["Scheduling"])
async def schedule_meeting(request: ScheduleRequest):
    """
    Books a Google Calendar event.

    Accepts a JSON payload with `name`, `date` (YYYY-MM-DD), `time` (HH:MM),
    and `title`. Returns a voice-friendly confirmation message the AI can
    read directly to the caller.
    """
    tz = ZoneInfo(DEFAULT_TIMEZONE)

    # Combine date + time into a timezone-aware datetime
    try:
        start_dt = datetime.strptime(
            f"{request.date} {request.time}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = create_event(
            summary=request.title,
            start_time=start_dt,
            attendee_name=request.name,
        )
    except EnvironmentError as exc:
        # Misconfigured credentials — server-side issue
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Google Calendar API error: {exc}",
        )

    # Build a natural-language confirmation the voice agent can speak aloud
    friendly_date = start_dt.strftime("%A, %B %-d")   # e.g. "Monday, March 15"
    friendly_time = start_dt.strftime("%-I:%M %p")    # e.g. "2:00 PM"
    tz_label = "Eastern Time" if DEFAULT_TIMEZONE == "America/New_York" else DEFAULT_TIMEZONE

    message = (
        f"Done! I have booked '{request.title}' for {request.name} "
        f"on {friendly_date} at {friendly_time} {tz_label}. "
        f"The meeting is {EVENT_DURATION_MINUTES} minutes long."
    )

    return ScheduleResponse(
        status="success",
        message=message,
        event_id=event.get("id"),
        event_link=event.get("htmlLink"),
    )


# ---------------------------------------------------------------------------
# Demo web client — zero-friction "Talk Now" page
# ---------------------------------------------------------------------------


@app.post("/internal/set-agent", include_in_schema=False)
async def set_agent(request: Request):
    """
    Called by run_agent.py after the Vapi assistant is created.
    Stores the assistant ID and public key so /demo can serve them.
    Not exposed in the OpenAPI docs.
    """
    data = await request.json()
    _agent_state.update(data)
    return {"ok": True}


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo_page():
    """
    Serves a browser-based Vapi web client.
    Values come from run_agent.py (local) or env vars (Render deployment).
    """
    assistant_id = _agent_state.get("assistant_id") or os.environ.get("VAPI_ASSISTANT_ID", "")
    public_key   = _agent_state.get("public_key")   or os.environ.get("VAPI_PUBLIC_KEY", "")

    html = Path("demo.html").read_text()
    html = html.replace("__ASSISTANT_ID__", assistant_id).replace("__PUBLIC_KEY__", public_key)
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Vapi webhook — called by the voice assistant when it decides to book
# ---------------------------------------------------------------------------


def _build_confirmation(title: str, name: str, start_dt: datetime) -> str:
    friendly_date = start_dt.strftime("%A, %B %-d")
    friendly_time = start_dt.strftime("%-I:%M %p")
    tz_label = "Eastern Time" if DEFAULT_TIMEZONE == "America/New_York" else DEFAULT_TIMEZONE
    return (
        f"Perfect! I've booked '{title}' for {name} on {friendly_date} "
        f"at {friendly_time} {tz_label}. The meeting is {EVENT_DURATION_MINUTES} minutes long. "
        f"Is there anything else I can help you with?"
    )


@app.post("/vapi/tool-call", tags=["Vapi"])
async def vapi_tool_call(request: Request):
    """
    Webhook called by Vapi when the voice assistant invokes the book_meeting tool.

    Vapi sends:
        { "message": { "type": "tool-calls", "toolCallList": [ { "id": "...",
          "function": { "name": "book_meeting", "arguments": { ... } } } ] } }

    We must respond with:
        { "results": [ { "toolCallId": "...", "result": "<string Vapi reads aloud>" } ] }
    """
    payload = await request.json()
    message = payload.get("message", {})
    tool_calls = message.get("toolCallList", [])

    results = []
    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id")
        fn = tool_call.get("function", {})
        fn_name = fn.get("name")

        # Vapi may send arguments as a dict or as a JSON string
        raw_args = fn.get("arguments", {})
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

        if fn_name == "book_meeting":
            try:
                tz = ZoneInfo(DEFAULT_TIMEZONE)
                start_dt = datetime.strptime(
                    f"{args['date']} {args['time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=tz)

                create_event(
                    summary=args.get("title", "Meeting"),
                    start_time=start_dt,
                    attendee_name=args.get("name", ""),
                )

                result = _build_confirmation(
                    title=args.get("title", "Meeting"),
                    name=args.get("name", ""),
                    start_dt=start_dt,
                )
            except EnvironmentError:
                result = "I'm sorry, there was a configuration issue on my end. Please try again later."
            except Exception as exc:
                result = f"I'm sorry, I wasn't able to book that meeting. {exc}"
        else:
            result = f"Unknown tool: {fn_name}"

        results.append({"toolCallId": tool_call_id, "result": result})

    return {"results": results}
