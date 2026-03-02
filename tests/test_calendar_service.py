"""
Unit tests for calendar_service.py.

Strategy
--------
- _load_credentials: tested with valid JSON, missing var, and malformed JSON.
- create_event: the Google API client is mocked so no real HTTP calls are made.
  We verify the event body sent to the API is correctly constructed.
"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import calendar_service
from calendar_service import (
    DEFAULT_TIMEZONE,
    EVENT_DURATION_MINUTES,
    _load_credentials,
    create_event,
)

# ---------------------------------------------------------------------------
# Minimal valid service-account dict (structure only, keys are fake)
# ---------------------------------------------------------------------------

FAKE_SA_INFO = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "key-id-123",
    "private_key": (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "-----END RSA PRIVATE KEY-----\n"
    ),
    "client_email": "test@test-project.iam.gserviceaccount.com",
    "client_id": "000000000000000000000",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test",
}

FAKE_SA_JSON = json.dumps(FAKE_SA_INFO)


# ---------------------------------------------------------------------------
# _load_credentials
# ---------------------------------------------------------------------------


class TestLoadCredentials:
    def test_raises_when_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
        with pytest.raises(EnvironmentError, match="GOOGLE_CREDENTIALS_JSON"):
            _load_credentials()

    def test_raises_on_invalid_json(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "not-valid-json{{{")
        with pytest.raises(EnvironmentError, match="not valid JSON"):
            _load_credentials()

    def test_returns_credentials_on_valid_json(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", FAKE_SA_JSON)
        with patch("calendar_service.service_account.Credentials.from_service_account_info") as mock_creds:
            mock_creds.return_value = MagicMock()
            result = _load_credentials()
        mock_creds.assert_called_once_with(FAKE_SA_INFO, scopes=calendar_service.SCOPES)
        assert result is mock_creds.return_value

    def test_passes_correct_scopes(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", FAKE_SA_JSON)
        with patch("calendar_service.service_account.Credentials.from_service_account_info") as mock_creds:
            mock_creds.return_value = MagicMock()
            _load_credentials()
        _, kwargs = mock_creds.call_args
        assert "https://www.googleapis.com/auth/calendar" in kwargs["scopes"]


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_google_service(monkeypatch):
    """
    Patches get_calendar_service() to return a fully mocked API client.
    Returns the mock insert().execute() return value so tests can customise it.
    """
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", FAKE_SA_JSON)
    monkeypatch.setenv("CALENDAR_ID", "primary")  # isolate from local .env

    fake_event = {"id": "evt-001", "htmlLink": "https://calendar.google.com/event?eid=evt-001"}

    mock_service = MagicMock()
    mock_service.events().insert().execute.return_value = fake_event

    with patch("calendar_service.get_calendar_service", return_value=mock_service):
        yield mock_service, fake_event


class TestCreateEvent:
    TZ = ZoneInfo(DEFAULT_TIMEZONE)
    START = datetime(2026, 3, 15, 14, 0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))

    def test_returns_event_dict(self, mock_google_service):
        _, fake_event = mock_google_service
        result = create_event("Team Sync", self.START, "John")
        assert result == fake_event

    def test_inserts_into_primary_calendar(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Team Sync", self.START, "John")
        call_kwargs = mock_service.events().insert.call_args.kwargs
        assert call_kwargs["calendarId"] == "primary"

    def test_event_summary_matches(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Board Meeting", self.START, "Alice")
        body = mock_service.events().insert.call_args.kwargs["body"]
        assert body["summary"] == "Board Meeting"

    def test_event_description_contains_attendee_name(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Team Sync", self.START, "John")
        body = mock_service.events().insert.call_args.kwargs["body"]
        assert "John" in body["description"]

    def test_event_start_datetime_is_correct(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Team Sync", self.START, "John")
        body = mock_service.events().insert.call_args.kwargs["body"]
        assert "2026-03-15T14:00:00" in body["start"]["dateTime"]

    def test_event_duration_is_45_minutes(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Team Sync", self.START, "John")
        body = mock_service.events().insert.call_args.kwargs["body"]

        start_str = body["start"]["dateTime"]
        end_str = body["end"]["dateTime"]

        # Parse back and compute delta
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        delta_minutes = (end_dt - start_dt).seconds // 60
        assert delta_minutes == EVENT_DURATION_MINUTES

    def test_event_timezone_is_set(self, mock_google_service):
        mock_service, _ = mock_google_service
        create_event("Team Sync", self.START, "John")
        body = mock_service.events().insert.call_args.kwargs["body"]
        assert body["start"]["timeZone"] == DEFAULT_TIMEZONE
        assert body["end"]["timeZone"] == DEFAULT_TIMEZONE
