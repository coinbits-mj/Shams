"""Gmail + Google Calendar integration."""

import logging
from datetime import datetime, timedelta
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

logger = logging.getLogger(__name__)

_GOOGLE_AVAILABLE = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

if _GOOGLE_AVAILABLE:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
else:
    logger.warning("Google credentials not set — Gmail/Calendar disabled")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


def _get_creds():
    import pathlib

    token_path = pathlib.Path(TOKEN_PATH)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


# ── Gmail ────────────────────────────────────────────────────────────────────

def get_unread_emails(max_results: int = 10) -> list[dict]:
    """Fetch unread emails — returns list of {subject, from, snippet, date}."""
    if not _GOOGLE_AVAILABLE:
        return []
    try:
        service = build("gmail", "v1", credentials=_get_creds())
        results = service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        messages = results.get("messages", [])

        emails = []
        for msg in messages:
            detail = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            emails.append({
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "snippet": detail.get("snippet", ""),
                "date": headers.get("Date", ""),
            })
        return emails
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        return []


# ── Google Calendar ──────────────────────────────────────────────────────────

def get_todays_events() -> list[dict]:
    """Fetch today's calendar events — returns list of {summary, start, end, location}."""
    if not _GOOGLE_AVAILABLE:
        return []
    try:
        service = build("calendar", "v3", credentials=_get_creds())
        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
        end_of_day = now.replace(hour=23, minute=59, second=59).isoformat() + "Z"

        results = service.events().list(
            calendarId="primary",
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for event in results.get("items", []):
            start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
            end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
            events.append({
                "summary": event.get("summary", ""),
                "start": start,
                "end": end,
                "location": event.get("location", ""),
            })
        return events
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return []


def get_upcoming_events(days: int = 7) -> list[dict]:
    """Fetch events for the next N days."""
    if not _GOOGLE_AVAILABLE:
        return []
    try:
        service = build("calendar", "v3", credentials=_get_creds())
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days)).isoformat() + "Z"

        results = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return [
            {
                "summary": e.get("summary", ""),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
                "location": e.get("location", ""),
            }
            for e in results.get("items", [])
        ]
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return []
