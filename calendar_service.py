import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()  # ensure .env is loaded even when calendar_service is the entry point

SCOPES = ["https://www.googleapis.com/auth/calendar"]
DEFAULT_TIMEZONE = "America/New_York"
EVENT_DURATION_MINUTES = 45


def _load_credentials() -> service_account.Credentials:
    """
    Loads Google Service Account credentials strictly from the
    GOOGLE_CREDENTIALS_JSON environment variable.

    Raises:
        EnvironmentError: If the variable is missing or not valid JSON.
    """
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise EnvironmentError(
            "GOOGLE_CREDENTIALS_JSON environment variable is not set. "
            "Set it to the contents of your Service Account JSON key file."
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EnvironmentError(
            f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {exc}"
        ) from exc

    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def get_calendar_service():
    """Builds and returns an authenticated Google Calendar API service client."""
    credentials = _load_credentials()
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def create_event(summary: str, start_time: datetime, attendee_name: str) -> dict:
    """
    Creates a 45-minute Google Calendar event on the primary calendar.

    Args:
        summary:       The event title / subject.
        start_time:    A timezone-aware datetime for the start of the event.
        attendee_name: Name of the person the meeting is with (stored in description).

    Returns:
        The full event resource dict returned by the Google Calendar API.

    Raises:
        HttpError: On any Google API error.
        EnvironmentError: If credentials are misconfigured.
    """
    service = get_calendar_service()
    end_time = start_time + timedelta(minutes=EVENT_DURATION_MINUTES)

    event_body = {
        "summary": summary,
        "description": f"Meeting scheduled with {attendee_name} via Voice Scheduling Agent.",
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": DEFAULT_TIMEZONE,
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": DEFAULT_TIMEZONE,
        },
    }

    calendar_id = os.environ.get("CALENDAR_ID", "primary")
    print(f"[calendar_service] Creating event in calendarId={calendar_id!r}", flush=True)

    try:
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
    except HttpError as exc:
        raise HttpError(
            resp=exc.resp,
            content=exc.content,
        ) from exc

    print(f"[calendar_service] Event created: {created.get('htmlLink')}", flush=True)
    return created
