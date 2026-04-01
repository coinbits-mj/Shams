"""Gmail + Google Calendar — multi-account support for all three inboxes."""

from __future__ import annotations

import logging
import requests
from datetime import datetime, timedelta
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_ACCOUNTS
import memory

logger = logging.getLogger(__name__)


def _get_access_token(account_key: str) -> str | None:
    """Get a valid access token for an account, refreshing if needed."""
    token = memory.recall(f"google_{account_key}_access_token")
    if not token:
        return None

    # Try to use it — if it fails, refresh
    r = requests.get("https://www.googleapis.com/oauth2/v1/tokeninfo",
                      params={"access_token": token}, timeout=10)
    if r.ok:
        return token

    # Refresh
    refresh_token = memory.recall(f"google_{account_key}_refresh_token")
    if not refresh_token:
        return None

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)

    if r.ok:
        new_token = r.json().get("access_token")
        memory.remember(f"google_{account_key}_access_token", new_token)
        return new_token

    logger.error(f"Google token refresh failed for {account_key}: {r.text}")
    return None


def _gmail_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Gmail — Multi-account ────────────────────────────────────────────────────

def get_unread_emails(max_results: int = 10) -> list[dict]:
    """Fetch unread emails from ALL connected accounts."""
    all_emails = []
    for account_key, email_addr in GOOGLE_ACCOUNTS.items():
        token = _get_access_token(account_key)
        if not token:
            continue
        try:
            emails = _fetch_emails_for_account(token, email_addr, account_key, max_results)
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Gmail error for {account_key}: {e}")

    # Sort by date (newest first) and cap total
    all_emails.sort(key=lambda e: e.get("date", ""), reverse=True)
    return all_emails[:max_results]


def get_unread_emails_for_account(account_key: str, max_results: int = 10) -> list[dict]:
    """Fetch unread emails from a specific account."""
    token = _get_access_token(account_key)
    if not token:
        return []
    email_addr = GOOGLE_ACCOUNTS.get(account_key, account_key)
    return _fetch_emails_for_account(token, email_addr, account_key, max_results)


def _fetch_emails_for_account(token: str, email_addr: str, account_key: str,
                               max_results: int) -> list[dict]:
    """Fetch unread emails for one account."""
    headers = _gmail_headers(token)

    r = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                      headers=headers, params={"q": "is:unread", "maxResults": max_results},
                      timeout=15)
    if not r.ok:
        logger.error(f"Gmail list error for {account_key}: {r.status_code}")
        return []

    messages = r.json().get("messages", [])
    emails = []

    for msg in messages:
        detail = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers, params={"format": "metadata"}, timeout=15
        )
        if not detail.ok:
            continue
        data = detail.json()
        hdrs = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        emails.append({
            "account": account_key,
            "account_email": email_addr,
            "subject": hdrs.get("Subject", ""),
            "from": hdrs.get("From", ""),
            "snippet": data.get("snippet", ""),
            "date": hdrs.get("Date", ""),
            "message_id": msg["id"],
        })

    return emails


def search_emails(query: str, max_results: int = 10) -> list[dict]:
    """Search emails across ALL connected accounts using Gmail search syntax."""
    all_emails = []
    for account_key, email_addr in GOOGLE_ACCOUNTS.items():
        token = _get_access_token(account_key)
        if not token:
            continue
        try:
            headers = _gmail_headers(token)
            r = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                             headers=headers, params={"q": query, "maxResults": max_results},
                             timeout=15)
            if not r.ok:
                continue
            messages = r.json().get("messages", [])
            for msg in messages:
                detail = requests.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                    headers=headers, params={"format": "metadata"}, timeout=15
                )
                if not detail.ok:
                    continue
                data = detail.json()
                hdrs = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
                all_emails.append({
                    "account": account_key,
                    "account_email": email_addr,
                    "subject": hdrs.get("Subject", ""),
                    "from": hdrs.get("From", ""),
                    "snippet": data.get("snippet", ""),
                    "date": hdrs.get("Date", ""),
                    "message_id": msg["id"],
                })
        except Exception as e:
            logger.error(f"Gmail search error for {account_key}: {e}")

    all_emails.sort(key=lambda e: e.get("date", ""), reverse=True)
    return all_emails[:max_results]


def get_email_body(account_key: str, message_id: str) -> str:
    """Get the full body text of a specific email."""
    import base64
    token = _get_access_token(account_key)
    if not token:
        return "Account not connected."
    headers = _gmail_headers(token)
    r = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        headers=headers, params={"format": "full"}, timeout=15
    )
    if not r.ok:
        return f"Failed to fetch email: {r.status_code}"

    data = r.json()
    payload = data.get("payload", {})

    def _extract_text(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            text = _extract_text(sub)
            if text:
                return text
        return ""

    body = _extract_text(payload)
    return body[:5000] if body else data.get("snippet", "No body text found.")


# ── Google Calendar ──────────────────────────────────────────────────────────

def get_todays_events() -> list[dict]:
    """Fetch today's events from the QCC account (primary calendar)."""
    token = _get_access_token("qcc")
    if not token:
        # Fall back to personal
        token = _get_access_token("personal")
    if not token:
        return []

    try:
        headers = _gmail_headers(token)
        now = datetime.utcnow()
        start = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
        end = now.replace(hour=23, minute=59, second=59).isoformat() + "Z"

        r = requests.get("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                          headers=headers, params={
                              "timeMin": start, "timeMax": end,
                              "singleEvents": True, "orderBy": "startTime",
                          }, timeout=15)
        if not r.ok:
            return []

        events = []
        for event in r.json().get("items", []):
            s = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
            e = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
            events.append({
                "summary": event.get("summary", ""),
                "start": s, "end": e,
                "location": event.get("location", ""),
            })
        return events
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return []


def get_upcoming_events(days: int = 7) -> list[dict]:
    """Fetch events for the next N days."""
    token = _get_access_token("qcc") or _get_access_token("personal")
    if not token:
        return []

    try:
        headers = _gmail_headers(token)
        now = datetime.utcnow()
        r = requests.get("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                          headers=headers, params={
                              "timeMin": now.isoformat() + "Z",
                              "timeMax": (now + timedelta(days=days)).isoformat() + "Z",
                              "singleEvents": True, "orderBy": "startTime",
                          }, timeout=15)
        if not r.ok:
            return []

        return [
            {
                "summary": e.get("summary", ""),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
                "location": e.get("location", ""),
            }
            for e in r.json().get("items", [])
        ]
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return []
