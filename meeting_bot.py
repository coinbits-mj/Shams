"""Meeting bot — smart filter, bot dispatch, transcript processing, summarization.

Spec: docs/superpowers/specs/2026-04-24-meeting-bot-design.md
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import config
import memory
import recall_client
import telegram

logger = logging.getLogger(__name__)

MJ_ADDRESSES = {
    "maher@qcitycoffee.com",
    "maher@coinbits.app",
    "maher.janajri@gmail.com",
}

# ── Smart filter ─────────────────────────────────────────────────────────────

def extract_meeting_url(event: dict) -> str | None:
    """Extract a Google Meet or Zoom URL from a calendar event."""
    # Priority 1: hangout_link (Google Meet)
    hangout = (event.get("hangout_link") or "").strip()
    if hangout and "meet.google.com" in hangout:
        return hangout

    # Priority 2: location field, then description
    for field in ("location", "description"):
        text = event.get(field) or ""
        # Google Meet
        m = re.search(r"https://meet\.google\.com/[a-z\-]+", text)
        if m:
            return m.group(0)
        # Zoom
        m = re.search(r"https://[a-z0-9]+\.zoom\.us/j/\S+", text)
        if m:
            return m.group(0).rstrip(")")

    return None


def should_join(event: dict) -> bool:
    """Apply smart filter: should Shams dispatch a bot for this event?"""
    # Must have a meeting link
    if not extract_meeting_url(event):
        return False

    # Must have 2+ attendees (not just MJ)
    attendees = event.get("attendees", [])
    non_self = [a for a in attendees if not a.get("self")]
    if len(non_self) < 1:
        return False

    # All-day event check (start has no "T")
    start_raw = event.get("start", "")
    if "T" not in start_raw:
        return False

    # Duration check
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end_raw = event.get("end", "")
        end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        duration_hours = (end_dt - start_dt).total_seconds() / 3600
        if duration_hours > config.MEETING_MAX_DURATION_HOURS:
            return False
    except Exception:
        pass

    # Exclude patterns
    title = (event.get("summary") or "").lower()
    for pattern in config.MEETING_EXCLUDE_PATTERNS:
        if pattern.strip() and pattern.strip() in title:
            return False

    # MJ declined?
    for a in attendees:
        if a.get("self") and a.get("response") == "declined":
            return False

    return True


# ── Bot dispatch ─────────────────────────────────────────────────────────────

def _bots_today_count() -> int:
    """Count how many bots Shams has dispatched today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"meeting_bots_dispatched_{today}"
    val = memory.recall(key)
    return int(val) if val else 0


def _increment_bots_today():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"meeting_bots_dispatched_{today}"
    current = _bots_today_count()
    memory.remember(key, str(current + 1))


def dispatch_bot(event: dict) -> dict | None:
    """Dispatch a Recall.ai bot for a calendar event.

    Returns the bot dict or None on failure. Checks daily limit.
    """
    if config.MEETING_BOT_DISABLED:
        return None

    if _bots_today_count() >= config.MEETING_BOT_MAX_DAILY:
        logger.warning("Meeting bot daily limit reached")
        return None

    meeting_url = extract_meeting_url(event)
    if not meeting_url:
        return None

    # Schedule join 1 min before start (Recall.ai handles joining at the right time)
    start_raw = event.get("start", "")
    join_at = None
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        join_at = (start_dt - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    bot = recall_client.create_bot(
        meeting_url=meeting_url,
        bot_name=config.MEETING_BOT_NAME,
        join_at=join_at,
    )

    if bot:
        _increment_bots_today()
        event_id = event.get("event_id", "")
        title = event.get("summary", "Untitled")
        logger.info(f"Meeting bot dispatched: {title} (bot={bot.get('id')}, event={event_id})")

        # Store bot→event mapping in memory for webhook lookup
        memory.remember(
            f"recall_bot_{bot['id']}",
            json.dumps({
                "event_id": event_id,
                "title": title,
                "start": start_raw,
                "end": event.get("end", ""),
                "attendees": event.get("attendees", []),
                "platform": "google_meet" if "meet.google.com" in meeting_url else "zoom",
            }),
        )

    return bot


# ── Calendar poller integration ──────────────────────────────────────────────

def check_and_dispatch_bots() -> int:
    """Poll calendar for upcoming meetings, dispatch bots for ones passing smart filter.

    Called every 10 min by scheduler. Only dispatches for meetings starting in 5-15 min.
    Returns count of bots dispatched.
    """
    if config.MEETING_BOT_DISABLED:
        return 0

    import google_client

    events = google_client.get_todays_events()
    if not events:
        return 0

    now = datetime.now(timezone.utc)
    dispatched = 0

    for event in events:
        start_raw = event.get("start", "")
        if not start_raw or "T" not in start_raw:
            continue
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        mins_until = (start_dt - now).total_seconds() / 60

        # Only dispatch if meeting is 5-15 min away
        if mins_until < 5 or mins_until > 15:
            continue

        if not should_join(event):
            continue

        event_id = event.get("event_id", "")
        today_str = now.strftime("%Y-%m-%d")
        dispatch_key = f"meeting_bot_dispatched_{event_id}_{today_str}"

        if memory.recall(dispatch_key):
            continue

        bot = dispatch_bot(event)
        if bot:
            memory.remember(dispatch_key, bot.get("id", ""))
            dispatched += 1

            # Send a heads-up via Telegram
            title = event.get("summary", "Untitled")
            telegram.send_message(
                f"\U0001f916 Joining *{title}* in ~{int(mins_until)}min — I'll send notes after.",
                parse_mode="Markdown",
            )

    return dispatched
