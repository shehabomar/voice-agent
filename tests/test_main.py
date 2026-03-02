"""
Unit tests for the Voice Scheduling Agent API.

Strategy
--------
- calendar_service.create_event is mocked in every test so no real
  Google API calls are made.  The actual credential / API integration
  is covered separately in test_calendar_service.py.
- The FastAPI TestClient is used so the full request/response cycle
  (routing, Pydantic validation, exception handlers) is exercised.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_EVENT = {
    "id": "abc123",
    "summary": "Team Sync",
    "htmlLink": "https://calendar.google.com/event?eid=abc123",
    "start": {"dateTime": "2026-03-15T14:00:00-04:00"},
    "end": {"dateTime": "2026-03-15T14:45:00-04:00"},
}


@pytest.fixture
def mock_create_event():
    """Patch calendar_service.create_event for the duration of a test."""
    with patch("main.create_event", return_value=FAKE_EVENT) as m:
        yield m


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_returns_ok_status(self):
        response = client.get("/health")
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /schedule — happy path
# ---------------------------------------------------------------------------


class TestScheduleHappyPath:
    VALID_PAYLOAD = {
        "name": "John",
        "date": "2026-03-15",
        "time": "14:00",
        "title": "Team Sync",
    }

    def test_returns_200(self, mock_create_event):
        response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.status_code == 200

    def test_status_is_success(self, mock_create_event):
        response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.json()["status"] == "success"

    def test_event_id_returned(self, mock_create_event):
        response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.json()["event_id"] == FAKE_EVENT["id"]

    def test_event_link_returned(self, mock_create_event):
        response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.json()["event_link"] == FAKE_EVENT["htmlLink"]

    def test_message_is_voice_friendly(self, mock_create_event):
        response = client.post("/schedule", json=self.VALID_PAYLOAD)
        msg = response.json()["message"]
        # Voice-friendly message should reference key booking details
        assert "Team Sync" in msg
        assert "John" in msg
        assert "45 minutes" in msg

    def test_create_event_called_with_correct_summary(self, mock_create_event):
        client.post("/schedule", json=self.VALID_PAYLOAD)
        _, kwargs = mock_create_event.call_args
        assert kwargs["summary"] == "Team Sync"

    def test_create_event_called_with_correct_attendee(self, mock_create_event):
        client.post("/schedule", json=self.VALID_PAYLOAD)
        _, kwargs = mock_create_event.call_args
        assert kwargs["attendee_name"] == "John"

    def test_create_event_called_with_correct_start_time(self, mock_create_event):
        client.post("/schedule", json=self.VALID_PAYLOAD)
        _, kwargs = mock_create_event.call_args
        dt: datetime = kwargs["start_time"]
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15
        assert dt.hour == 14
        assert dt.minute == 0

    def test_start_time_is_timezone_aware(self, mock_create_event):
        client.post("/schedule", json=self.VALID_PAYLOAD)
        _, kwargs = mock_create_event.call_args
        dt: datetime = kwargs["start_time"]
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# /schedule — input validation (no Google call needed)
# ---------------------------------------------------------------------------


class TestScheduleValidation:
    def test_bad_date_format_returns_422(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "15-03-2026", "time": "09:00", "title": "Sync"},
        )
        assert response.status_code == 422

    def test_bad_date_format_error_message(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "03/15/2026", "time": "09:00", "title": "Sync"},
        )
        detail = response.json()["detail"]
        assert any("YYYY-MM-DD" in str(d) for d in detail)

    def test_bad_time_format_returns_422(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "2026-03-15", "time": "2pm", "title": "Sync"},
        )
        assert response.status_code == 422

    def test_bad_time_format_error_message(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "2026-03-15", "time": "2:00pm", "title": "Sync"},
        )
        detail = response.json()["detail"]
        assert any("HH:MM" in str(d) for d in detail)

    def test_missing_name_returns_422(self):
        response = client.post(
            "/schedule",
            json={"date": "2026-03-15", "time": "09:00", "title": "Sync"},
        )
        assert response.status_code == 422

    def test_missing_date_returns_422(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "time": "09:00", "title": "Sync"},
        )
        assert response.status_code == 422

    def test_missing_time_returns_422(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "2026-03-15", "title": "Sync"},
        )
        assert response.status_code == 422

    def test_missing_title_returns_422(self):
        response = client.post(
            "/schedule",
            json={"name": "Jane", "date": "2026-03-15", "time": "09:00"},
        )
        assert response.status_code == 422

    def test_empty_body_returns_422(self):
        response = client.post("/schedule", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# /schedule — downstream error handling
# ---------------------------------------------------------------------------


class TestScheduleErrorHandling:
    VALID_PAYLOAD = {
        "name": "Alice",
        "date": "2026-03-20",
        "time": "10:00",
        "title": "Interview",
    }

    def test_credential_error_returns_500(self):
        with patch("main.create_event", side_effect=EnvironmentError("Credentials not set")):
            response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.status_code == 500

    def test_credential_error_detail(self):
        with patch("main.create_event", side_effect=EnvironmentError("Credentials not set")):
            response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert "Credentials not set" in response.json()["detail"]

    def test_google_api_error_returns_502(self):
        with patch("main.create_event", side_effect=Exception("API unavailable")):
            response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert response.status_code == 502

    def test_google_api_error_detail(self):
        with patch("main.create_event", side_effect=Exception("API unavailable")):
            response = client.post("/schedule", json=self.VALID_PAYLOAD)
        assert "API unavailable" in response.json()["detail"]
