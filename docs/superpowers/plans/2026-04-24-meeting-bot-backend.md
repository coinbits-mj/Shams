# Meeting Bot Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shams auto-joins MJ's Google Meet and Zoom meetings via Recall.ai, records + transcribes, generates persona-aware summaries cross-referenced against email archive + commitments + missions, and delivers via Telegram + email + queryable DB.

**Architecture:** Calendar poller (existing 10-min job) detects upcoming meetings, applies smart filter, dispatches a Recall.ai bot. Recall.ai webhook fires when recording completes. Shams pulls transcript, detects meeting type, selects persona, cross-references existing data, synthesizes summary via Haiku, stores in `shams_meeting_notes`, delivers via Telegram + Resend email.

**Tech Stack:** Python 3, Flask, Recall.ai REST API, anthropic SDK (Haiku), Resend email, Postgres (Railway), APScheduler.

**Spec:** `docs/superpowers/specs/2026-04-24-meeting-bot-design.md`

**Scope:** Calendar-triggered meetings only. Slack huddle listener + Telegram "join" command are follow-up.

---

## File Structure

### New files
- `recall_client.py` — thin wrapper around Recall.ai REST API
- `meeting_bot.py` — smart filter, bot dispatch, transcript processing, summarization, delivery
- `migrations/2026-04-24-meeting-notes.sql` — shams_meeting_notes table
- `tools/meeting_tools.py` — Claude tool for querying past meeting notes
- `tests/test_meeting_bot.py` — unit tests

### Modified files
- `config.py` — add RECALL_API_KEY, RECALL_REGION, meeting config vars
- `scheduler.py` — add `_check_meeting_bots` polling job for dispatch + completion
- `app.py` — add `/api/recall/webhook` endpoint for Recall.ai status change callbacks
- `schema.sql` — append shams_meeting_notes table
- `memory.py` — add `insert_meeting_notes`, `get_meeting_notes`, `search_meeting_notes` helpers

---

## Task 1: Schema migration + config

**Files:**
- Create: `migrations/2026-04-24-meeting-notes.sql`
- Modify: `config.py`

- [ ] **Step 1: Create migration SQL**

```sql
-- migrations/2026-04-24-meeting-notes.sql

CREATE TABLE IF NOT EXISTS shams_meeting_notes (
    id                    BIGSERIAL PRIMARY KEY,
    event_id              TEXT,
    recall_bot_id         TEXT UNIQUE,
    title                 TEXT,
    started_at            TIMESTAMPTZ,
    ended_at              TIMESTAMPTZ,
    duration_min          INT,
    attendees             JSONB NOT NULL DEFAULT '[]'::jsonb,
    platform              TEXT,
    transcript            TEXT,
    summary               TEXT,
    action_items          JSONB NOT NULL DEFAULT '[]'::jsonb,
    decisions             JSONB NOT NULL DEFAULT '[]'::jsonb,
    commitments_created   INT[] DEFAULT '{}',
    commitments_resolved  INT[] DEFAULT '{}',
    persona_used          TEXT,
    meeting_type          TEXT,
    telegram_sent         BOOLEAN NOT NULL DEFAULT FALSE,
    email_sent            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meeting_notes_event
    ON shams_meeting_notes(event_id);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_started
    ON shams_meeting_notes(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_attendees_gin
    ON shams_meeting_notes USING GIN (attendees);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_action_items_gin
    ON shams_meeting_notes USING GIN (action_items);
```

- [ ] **Step 2: Apply migration to shams-db**

```bash
cd /Users/mj/code/Shams
set -a && source .env && set +a
python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
sql = open('migrations/2026-04-24-meeting-notes.sql').read()
with conn.cursor() as cur: cur.execute(sql)
conn.commit()
print('applied')
"
```

- [ ] **Step 3: Append to schema.sql**

Append the full contents of `migrations/2026-04-24-meeting-notes.sql` to the end of `schema.sql`.

- [ ] **Step 4: Add config vars to config.py**

Append to `config.py`:

```python
# ── Recall.ai (Meeting Bot) ─────────────────────────────────────────────────
RECALL_API_KEY = os.environ.get("RECALL_API_KEY", "")
RECALL_REGION = os.environ.get("RECALL_REGION", "us-east-1")
RECALL_WEBHOOK_SECRET = os.environ.get("RECALL_WEBHOOK_SECRET", "")
RECALL_BASE_URL = f"https://{RECALL_REGION}.recall.ai/api/v1"

MEETING_BOT_NAME = os.environ.get("MEETING_BOT_NAME", "Shams Notetaker")
MEETING_BOT_MAX_DAILY = int(os.environ.get("MEETING_BOT_MAX_DAILY", "10"))
MEETING_MAX_DURATION_HOURS = int(os.environ.get("MEETING_MAX_DURATION_HOURS", "3"))
MEETING_EXCLUDE_PATTERNS = os.environ.get(
    "MEETING_EXCLUDE_PATTERNS",
    "lunch,dentist,personal,block,focus time,gym,doctor,dinner"
).lower().split(",")
MEETING_BOT_DISABLED = os.environ.get("MEETING_BOT_DISABLED", "").lower() in ("1", "true", "yes")
```

- [ ] **Step 5: Commit**

```bash
git add migrations/2026-04-24-meeting-notes.sql schema.sql config.py
git commit -m "Meeting bot: schema + config for Recall.ai integration"
```

---

## Task 2: Recall.ai API client

**Files:**
- Create: `recall_client.py`
- Create: `tests/test_meeting_bot.py`

- [ ] **Step 1: Write failing tests for the client**

```python
# tests/test_meeting_bot.py
from __future__ import annotations

import json
import pytest


class TestRecallClient:
    def test_create_bot_returns_bot_id(self, monkeypatch):
        import recall_client

        def fake_post(url, **kwargs):
            class R:
                ok = True
                status_code = 201
                def json(self):
                    return {"id": "bot-uuid-123", "status_code": "ready"}
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        result = recall_client.create_bot("https://meet.google.com/abc-def-ghi")
        assert result["id"] == "bot-uuid-123"

    def test_create_bot_with_join_at(self, monkeypatch):
        import recall_client

        captured = {}
        def fake_post(url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            class R:
                ok = True
                status_code = 201
                def json(self):
                    return {"id": "bot-456"}
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        recall_client.create_bot("https://meet.google.com/abc", join_at="2026-04-24T14:00:00Z")
        assert captured["json"]["join_at"] == "2026-04-24T14:00:00Z"

    def test_create_bot_failure_returns_none(self, monkeypatch):
        import recall_client

        def fake_post(url, **kwargs):
            class R:
                ok = False
                status_code = 400
                text = "bad request"
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        result = recall_client.create_bot("https://bad-url")
        assert result is None

    def test_get_bot_returns_status(self, monkeypatch):
        import recall_client

        def fake_get(url, **kwargs):
            class R:
                ok = True
                def json(self):
                    return {"id": "bot-123", "status_code": "done", "media_shortcuts": {"transcript": {"data": []}}}
            return R()

        monkeypatch.setattr("requests.get", fake_get)
        result = recall_client.get_bot("bot-123")
        assert result["status_code"] == "done"

    def test_get_transcript_returns_utterances(self, monkeypatch):
        import recall_client

        def fake_get(url, **kwargs):
            class R:
                ok = True
                def json(self):
                    return {"results": [
                        {"speaker": "Brandon", "words": [{"text": "Let's"}, {"text": "start"}]},
                        {"speaker": "Maher", "words": [{"text": "Sounds"}, {"text": "good"}]},
                    ]}
            return R()

        monkeypatch.setattr("requests.get", fake_get)
        result = recall_client.get_transcript("bot-123")
        assert len(result) == 2
        assert result[0]["speaker"] == "Brandon"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_meeting_bot.py::TestRecallClient -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'recall_client'`.

- [ ] **Step 3: Implement recall_client.py**

```python
"""Recall.ai API client — create bots, check status, retrieve transcripts."""
from __future__ import annotations

import logging

import requests

import config

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "Authorization": f"Token {config.RECALL_API_KEY}",
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{config.RECALL_BASE_URL}{path}"


def create_bot(
    meeting_url: str,
    bot_name: str | None = None,
    join_at: str | None = None,
) -> dict | None:
    """Create a Recall.ai bot to join a meeting.

    Returns the bot dict (with 'id' key) on success, None on failure.
    """
    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name or config.MEETING_BOT_NAME,
        "recording_config": {
            "transcript": {
                "provider": {"meeting_captions": {}},
            },
        },
    }
    if join_at:
        body["join_at"] = join_at

    try:
        r = requests.post(_url("/bot/"), json=body, headers=_headers(), timeout=30)
    except Exception as e:
        logger.error(f"Recall create_bot error: {e}")
        return None

    if not r.ok:
        logger.error(f"Recall create_bot failed {r.status_code}: {r.text[:300]}")
        return None

    return r.json()


def get_bot(bot_id: str) -> dict | None:
    """Get bot status + metadata."""
    try:
        r = requests.get(_url(f"/bot/{bot_id}/"), headers=_headers(), timeout=15)
    except Exception as e:
        logger.error(f"Recall get_bot error: {e}")
        return None
    if not r.ok:
        return None
    return r.json()


def get_transcript(bot_id: str) -> list[dict]:
    """Get the transcript for a completed bot.

    Returns list of utterance dicts: [{speaker, words: [{text}]}].
    Falls back to media_shortcuts if transcript endpoint fails.
    """
    try:
        r = requests.get(_url(f"/bot/{bot_id}/transcript/"), headers=_headers(), timeout=30)
        if r.ok:
            data = r.json()
            # Normalize: Recall returns either {results: [...]} or bare [...]
            if isinstance(data, dict):
                return data.get("results", [])
            return data
    except Exception as e:
        logger.error(f"Recall get_transcript error: {e}")

    # Fallback: try to get from bot's media_shortcuts
    try:
        bot = get_bot(bot_id)
        if bot:
            shortcuts = bot.get("media_shortcuts", {})
            transcript_data = shortcuts.get("transcript", {}).get("data", [])
            if transcript_data:
                return transcript_data
    except Exception as e:
        logger.error(f"Recall transcript fallback error: {e}")

    return []


def format_transcript(utterances: list[dict]) -> str:
    """Convert raw utterances to readable text.

    Input: [{speaker: "Brandon", words: [{text: "Let's"}, {text: "start"}]}]
    Output: "Brandon: Let's start\nMaher: Sounds good"
    """
    lines = []
    for u in utterances:
        speaker = u.get("speaker") or u.get("participant", {}).get("name") or "Unknown"
        words = u.get("words", [])
        text = " ".join(w.get("text", "") for w in words).strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_meeting_bot.py::TestRecallClient -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add recall_client.py tests/test_meeting_bot.py
git commit -m "Meeting bot: Recall.ai API client with create/get/transcript"
```

---

## Task 3: Smart filter + bot dispatcher

**Files:**
- Create: `meeting_bot.py`
- Modify: `tests/test_meeting_bot.py`

- [ ] **Step 1: Write failing tests for smart filter**

Append to `tests/test_meeting_bot.py`:

```python
class TestSmartFilter:
    def test_passes_normal_meeting(self):
        import meeting_bot
        event = {
            "summary": "Weekly Standup",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True, "response": "accepted"},
                {"email": "brandon@qcitycoffee.com", "self": False, "response": "accepted"},
            ],
            "hangout_link": "https://meet.google.com/abc-def-ghi",
        }
        assert meeting_bot.should_join(event) is True

    def test_rejects_no_meeting_link(self):
        import meeting_bot
        event = {
            "summary": "Coffee chat",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "friend@gmail.com", "self": False},
            ],
            "hangout_link": "",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_solo_event(self):
        import meeting_bot
        event = {
            "summary": "Focus time",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T16:00:00-04:00",
            "attendees": [{"email": "maher@qcitycoffee.com", "self": True}],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_excluded_title(self):
        import meeting_bot
        event = {
            "summary": "Lunch with friends",
            "start": "2026-04-24T12:00:00-04:00",
            "end": "2026-04-24T13:00:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "friend@gmail.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_declined_event(self):
        import meeting_bot
        event = {
            "summary": "Meeting",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True, "response": "declined"},
                {"email": "someone@x.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_long_event(self):
        import meeting_bot
        event = {
            "summary": "All-day conference",
            "start": "2026-04-24T09:00:00-04:00",
            "end": "2026-04-24T17:00:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "speaker@conf.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_all_day_event(self):
        import meeting_bot
        event = {
            "summary": "Company offsite",
            "start": "2026-04-24",
            "end": "2026-04-25",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "team@x.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_extracts_meeting_url_from_hangout_link(self):
        import meeting_bot
        event = {
            "hangout_link": "https://meet.google.com/abc-def-ghi",
            "location": "",
            "description": "",
        }
        assert meeting_bot.extract_meeting_url(event) == "https://meet.google.com/abc-def-ghi"

    def test_extracts_zoom_url_from_description(self):
        import meeting_bot
        event = {
            "hangout_link": "",
            "location": "",
            "description": "Join Zoom: https://us06web.zoom.us/j/123456789?pwd=abc123 some other text",
        }
        url = meeting_bot.extract_meeting_url(event)
        assert url and "zoom.us" in url
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_meeting_bot.py::TestSmartFilter -v
```

Expected: FAIL.

- [ ] **Step 3: Implement meeting_bot.py (smart filter + URL extraction + dispatch)**

```python
"""Meeting bot — smart filter, bot dispatch, transcript processing, summarization.

Spec: docs/superpowers/specs/2026-04-24-meeting-bot-design.md
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import anthropic

import config
import db
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

    # Priority 2: location field
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
                f"🤖 Joining *{title}* in ~{int(mins_until)}min — I'll send notes after.",
                parse_mode="Markdown",
            )

    return dispatched
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_meeting_bot.py::TestSmartFilter -v
```

Expected: 9 PASSED.

- [ ] **Step 5: Commit**

```bash
git add meeting_bot.py tests/test_meeting_bot.py
git commit -m "Meeting bot: smart filter + bot dispatch + calendar poller"
```

---

## Task 4: Transcript processing + persona-aware summarization

**Files:**
- Modify: `meeting_bot.py`
- Modify: `tests/test_meeting_bot.py`

- [ ] **Step 1: Write failing tests for meeting type detection and summarization**

Append to `tests/test_meeting_bot.py`:

```python
class TestMeetingTypeDetection:
    def test_detects_legal_meeting(self):
        import meeting_bot
        attendees = [{"email": "counsel@sewkis.com", "name": "Miller"}]
        assert meeting_bot.detect_meeting_type("FRE 408 Discussion", attendees) == "legal"

    def test_detects_standup(self):
        import meeting_bot
        attendees = [{"email": "brandon@qcitycoffee.com"}]
        assert meeting_bot.detect_meeting_type("Daily Stand-Up", attendees) == "operations"

    def test_detects_deal_meeting(self):
        import meeting_bot
        attendees = [{"email": "richard@rhrcoffee.com"}]
        assert meeting_bot.detect_meeting_type("NDA Review + LOI", attendees) == "deal"

    def test_detects_interview(self):
        import meeting_bot
        attendees = [{"email": "annie@gmail.com"}]
        assert meeting_bot.detect_meeting_type("Annie — Barista Interview", attendees) == "interview"

    def test_defaults_to_general(self):
        import meeting_bot
        attendees = [{"email": "someone@company.com"}]
        assert meeting_bot.detect_meeting_type("Quick sync", attendees) == "general"


class TestProcessTranscript:
    def test_process_builds_summary_and_stores(self, monkeypatch):
        import meeting_bot

        # Mock the LLM call
        def fake_create(**kwargs):
            class Content:
                text = json.dumps({
                    "summary": "Discussed Q2 targets. Brandon will follow up on vendor pricing.",
                    "action_items": [{"assignee": "Brandon", "task": "Follow up on vendor pricing", "deadline": None}],
                    "decisions": [{"decision": "Push Q2 launch to May", "context": "Waiting on vendor"}],
                    "commitments_made": [{"to": "Brandon", "text": "send the pricing sheet", "deadline": "Friday"}],
                    "commitments_resolved": [],
                })
            class Resp:
                content = [Content()]
            return Resp()

        monkeypatch.setattr("anthropic.Anthropic", lambda **kw: type("C", (), {"messages": type("M", (), {"create": staticmethod(fake_create)})()})())

        # Mock DB + delivery
        stored = {}
        monkeypatch.setattr("memory.insert_meeting_notes", lambda data: stored.update(data) or 1)
        monkeypatch.setattr("telegram.send_message", lambda text, **kw: None)

        result = meeting_bot.process_completed_meeting(
            bot_id="bot-123",
            transcript_text="Brandon: Let's push to May.\nMaher: Agreed. I'll send the pricing sheet by Friday.",
            event_meta={
                "event_id": "evt-1",
                "title": "Weekly Ops",
                "start": "2026-04-24T14:00:00Z",
                "end": "2026-04-24T14:30:00Z",
                "attendees": [{"email": "brandon@qcitycoffee.com", "name": "Brandon"}],
                "platform": "google_meet",
            },
        )
        assert result is not None
        assert stored.get("summary")
        assert len(stored.get("action_items", [])) == 1
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_meeting_bot.py::TestMeetingTypeDetection tests/test_meeting_bot.py::TestProcessTranscript -v
```

Expected: FAIL.

- [ ] **Step 3: Implement meeting type detection + process_completed_meeting**

Append to `meeting_bot.py`:

```python
# ── Meeting type detection ───────────────────────────────────────────────────

LEGAL_DOMAINS = {"sewkis.com", "amslawgrp.com", "cooley.com", "rajehsaadeh.com", "meyersroman.com", "schmendel.com"}
DEAL_KEYWORDS = {"deal", "nda", "loi", "partnership", "acquisition", "alignment", "investment", "term sheet"}
OPS_KEYWORDS = {"standup", "stand-up", "sync", "check-in", "check in", "weekly", "ops", "huddle", "daily"}
INTERVIEW_KEYWORDS = {"interview", "barista", "candidate", "hire", "hiring"}

PERSONA_MAP = {
    "legal": "wakil",
    "operations": "rumi",
    "deal": "scout",
    "interview": "shams",
    "general": "shams",
}


def detect_meeting_type(title: str, attendees: list[dict]) -> str:
    """Detect meeting type from title keywords + attendee domains."""
    title_lower = title.lower()

    # Check attendee domains for legal firms
    for a in attendees:
        email = a.get("email", "")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in LEGAL_DOMAINS:
            return "legal"

    # Check title keywords
    for kw in INTERVIEW_KEYWORDS:
        if kw in title_lower:
            return "interview"
    for kw in DEAL_KEYWORDS:
        if kw in title_lower:
            return "deal"
    for kw in OPS_KEYWORDS:
        if kw in title_lower:
            return "operations"

    # Check if any attendee is in the deals table
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                emails = [a.get("email", "") for a in attendees if a.get("email")]
                if emails:
                    cur.execute(
                        "SELECT 1 FROM shams_deals WHERE contact = ANY(%s) AND stage NOT IN ('closed','dead') LIMIT 1",
                        (emails,),
                    )
                    if cur.fetchone():
                        return "deal"
    except Exception:
        pass

    return "general"


# ── Cross-referencing ────────────────────────────────────────────────────────

def _gather_cross_references(attendee_emails: list[str]) -> dict:
    """Pull email history + commitments + missions for attendees."""
    refs = {"emails": {}, "commitments": [], "missions": []}

    if not attendee_emails:
        return refs

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Recent emails (last 30d)
            for email in attendee_emails[:10]:
                cur.execute(
                    """SELECT from_addr, subject, date FROM shams_email_archive
                       WHERE (from_addr = %s OR %s = ANY(to_addrs))
                         AND date > NOW() - INTERVAL '30 days'
                       ORDER BY date DESC LIMIT 3""",
                    (email, email),
                )
                rows = cur.fetchall()
                if rows:
                    refs["emails"][email] = [
                        {"from": r[0], "subject": r[1], "date": str(r[2])[:10]}
                        for r in rows
                    ]

            # Open commitments
            cur.execute(
                """SELECT id, recipient_email, commitment_text, commitment_type,
                          EXTRACT(DAY FROM (NOW() - promised_at))::INT AS days_old
                   FROM shams_open_commitments
                   WHERE status = 'open' AND recipient_email = ANY(%s)""",
                (attendee_emails,),
            )
            refs["commitments"] = [
                {"id": r[0], "to": r[1], "text": r[2], "type": r[3], "days_old": r[4]}
                for r in cur.fetchall()
            ]

            # Active missions
            for email in attendee_emails[:5]:
                name_part = email.split("@")[0]
                cur.execute(
                    "SELECT id, title FROM shams_missions WHERE status='active' AND (title ILIKE %s OR description ILIKE %s) LIMIT 3",
                    (f"%{name_part}%", f"%{name_part}%"),
                )
                for r in cur.fetchall():
                    refs["missions"].append({"id": r[0], "title": r[1]})

    return refs


# ── Summarization ────────────────────────────────────────────────────────────

SUMMARY_MODEL = os.environ.get("MEETING_SUMMARY_MODEL", "claude-haiku-4-5")

_SUMMARY_SYSTEM = """You are Shams, MJ's chief of staff. Summarize this meeting transcript.

OUTPUT strict JSON:
{
  "summary": "2-4 sentence summary of what was discussed and decided",
  "action_items": [{"assignee": "Name", "task": "what they need to do", "deadline": "date or null"}],
  "decisions": [{"decision": "what was decided", "context": "why/context"}],
  "commitments_made": [{"to": "recipient name or email", "text": "what MJ promised", "deadline": "date or null"}],
  "commitments_resolved": [{"commitment_text": "the original promise", "how": "how it was resolved in this meeting"}]
}

RULES:
- action_items: ONLY concrete tasks with a clear owner. Not vague "discuss later."
- commitments_made: ONLY promises MJ explicitly made (not others)
- commitments_resolved: match against OPEN COMMITMENTS provided in context. If someone confirms something MJ promised was done, include it.
- Keep summary SHORT. MJ reads on Telegram.
- If transcript is garbled/empty, return {"summary":"Transcript unavailable","action_items":[],"decisions":[],"commitments_made":[],"commitments_resolved":[]}"""


def process_completed_meeting(
    bot_id: str,
    transcript_text: str,
    event_meta: dict,
) -> dict | None:
    """Process a completed meeting: summarize, cross-ref, store, deliver.

    event_meta: {event_id, title, start, end, attendees, platform}
    Returns the stored meeting notes dict, or None on failure.
    """
    title = event_meta.get("title", "Untitled")
    attendees = event_meta.get("attendees", [])
    attendee_emails = [a.get("email", "") for a in attendees if a.get("email") and a.get("email") not in MJ_ADDRESSES]
    platform = event_meta.get("platform", "google_meet")

    # Detect type + persona
    meeting_type = detect_meeting_type(title, attendees)
    persona = PERSONA_MAP.get(meeting_type, "shams")

    # Cross-references
    refs = _gather_cross_references(attendee_emails)

    # Build context for LLM
    ctx_lines = []
    if refs["commitments"]:
        ctx_lines.append("OPEN COMMITMENTS TO ATTENDEES:")
        for c in refs["commitments"]:
            ctx_lines.append(f'  To {c["to"]}: "{c["text"]}" ({c["days_old"]}d ago)')
    if refs["emails"]:
        ctx_lines.append("RECENT EMAIL THREADS:")
        for email, threads in refs["emails"].items():
            for t in threads:
                ctx_lines.append(f"  {t['date']} — {t['from']}: {t['subject']}")
    if refs["missions"]:
        ctx_lines.append("RELATED MISSIONS:")
        for m in refs["missions"]:
            ctx_lines.append(f"  [{m['id']}] {m['title']}")

    persona_note = ""
    if persona == "wakil":
        persona_note = "\nThis is a LEGAL meeting. Focus on legal implications, deadlines, litigation risks."
    elif persona == "rumi":
        persona_note = "\nThis is an OPS meeting. Focus on task status, blockers, accountability."
    elif persona == "scout":
        persona_note = "\nThis is a DEAL meeting. Focus on deal terms, next steps, relationship signals."

    user_msg = (
        f"Meeting: {title}\n"
        f"Attendees: {', '.join(a.get('name') or a.get('email','?') for a in attendees)}\n"
        f"{persona_note}\n\n"
        f"{'chr(10)'.join(ctx_lines) if ctx_lines else '(no prior context with these attendees)'}\n\n"
        f"TRANSCRIPT:\n{transcript_text[:30000]}"
    )

    # Call LLM
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=2000,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"Meeting summary LLM error: {e}")
        parsed = {
            "summary": f"Meeting '{title}' completed but summary generation failed.",
            "action_items": [],
            "decisions": [],
            "commitments_made": [],
            "commitments_resolved": [],
        }

    # Auto-create commitments
    created_ids = []
    import commitments as commitments_mod
    for c in parsed.get("commitments_made", []):
        inserted = commitments_mod.persist_commitments(
            archive_id=0,  # no email source
            account="qcc",
            recipient_email=c.get("to"),
            recipient_name=c.get("to"),
            promised_at=event_meta.get("start"),
            commitments=[{"type": "other", "text": c.get("text", ""), "deadline_raw": c.get("deadline")}],
        )
        if inserted:
            created_ids.append(inserted)

    # Auto-resolve commitments
    resolved_ids = []
    for c in parsed.get("commitments_resolved", []):
        for open_c in refs["commitments"]:
            if c.get("commitment_text", "").lower() in open_c.get("text", "").lower():
                commitments_mod.mark_fulfilled(open_c["id"])
                resolved_ids.append(open_c["id"])

    # Calculate duration
    duration_min = None
    try:
        s = datetime.fromisoformat(event_meta["start"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(event_meta["end"].replace("Z", "+00:00"))
        duration_min = int((e - s).total_seconds() / 60)
    except Exception:
        pass

    # Store in DB
    notes_data = {
        "event_id": event_meta.get("event_id"),
        "recall_bot_id": bot_id,
        "title": title,
        "started_at": event_meta.get("start"),
        "ended_at": event_meta.get("end"),
        "duration_min": duration_min,
        "attendees": attendees,
        "platform": platform,
        "transcript": transcript_text[:100000],
        "summary": parsed.get("summary", ""),
        "action_items": parsed.get("action_items", []),
        "decisions": parsed.get("decisions", []),
        "commitments_created": created_ids,
        "commitments_resolved": resolved_ids,
        "persona_used": persona,
        "meeting_type": meeting_type,
    }

    notes_id = memory.insert_meeting_notes(notes_data)
    notes_data["id"] = notes_id

    # Deliver via Telegram
    _send_telegram_summary(notes_data)

    # Deliver via email
    _send_email_summary(notes_data)

    return notes_data


# ── Delivery ─────────────────────────────────────────────────────────────────

def _send_telegram_summary(notes: dict):
    """Send terse meeting summary via Telegram."""
    title = notes.get("title", "Untitled")
    duration = notes.get("duration_min") or "?"
    attendees = notes.get("attendees", [])
    names = [a.get("name") or a.get("email", "?").split("@")[0] for a in attendees if not a.get("self")]

    lines = [f"📋 *{title}* just ended ({duration} min)"]
    if names:
        lines.append(f"👥 {', '.join(names[:8])}")

    decisions = notes.get("decisions", [])
    if decisions:
        lines.append("\n📌 Decisions:")
        for d in decisions[:5]:
            lines.append(f"- {d.get('decision', '')}")

    actions = notes.get("action_items", [])
    if actions:
        lines.append("\n⚡ Action items:")
        for a in actions[:8]:
            assignee = a.get("assignee", "?")
            task = a.get("task", "")
            lines.append(f"- {assignee}: {task}")

    if notes.get("commitments_created"):
        lines.append(f"\n⚠️ {len(notes['commitments_created'])} new commitment(s) auto-tracked")
    if notes.get("commitments_resolved"):
        lines.append(f"✅ {len(notes['commitments_resolved'])} commitment(s) resolved")

    text = "\n".join(lines)
    try:
        telegram.send_message(text, parse_mode="Markdown")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shams_meeting_notes SET telegram_sent=TRUE WHERE id=%s", (notes.get("id"),))
    except Exception as e:
        logger.error(f"Telegram meeting summary failed: {e}")


def _send_email_summary(notes: dict):
    """Send meeting summary email via Resend."""
    if not config.RESEND_API_KEY:
        return

    try:
        import resend
        resend.api_key = config.RESEND_API_KEY

        title = notes.get("title", "Untitled")
        summary = notes.get("summary", "")
        actions = notes.get("action_items", [])
        decisions = notes.get("decisions", [])

        action_html = "".join(f"<li><b>{a.get('assignee','?')}</b>: {a.get('task','')}</li>" for a in actions)
        decision_html = "".join(f"<li>{d.get('decision','')}</li>" for d in decisions)

        html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a1a2e;">📋 {title}</h2>
            <p style="color: #64748b;">{notes.get('duration_min', '?')} min · {notes.get('meeting_type', 'general')} · {notes.get('persona_used', 'shams')} lens</p>
            <h3>Summary</h3>
            <p>{summary}</p>
            {'<h3>Decisions</h3><ul>' + decision_html + '</ul>' if decisions else ''}
            {'<h3>Action Items</h3><ul>' + action_html + '</ul>' if actions else ''}
            <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
            <p style="color: #94a3b8; font-size: 12px;">Generated by Shams · Reply to query this meeting</p>
        </div>
        """

        resend.Emails.send({
            "from": config.RESEND_FROM_EMAIL,
            "to": ["maher@qcitycoffee.com"],
            "subject": f"📋 Meeting Notes: {title}",
            "html": html,
        })

        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shams_meeting_notes SET email_sent=TRUE WHERE id=%s", (notes.get("id"),))
    except Exception as e:
        logger.error(f"Email meeting summary failed: {e}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_meeting_bot.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add meeting_bot.py tests/test_meeting_bot.py
git commit -m "Meeting bot: type detection + summarization + cross-referencing + delivery"
```

---

## Task 5: Memory helpers for meeting notes

**Files:**
- Modify: `memory.py`

- [ ] **Step 1: Add helpers to memory.py**

Append to `memory.py`:

```python
# ── Meeting notes helpers ────────────────────────────────────────────────────

def insert_meeting_notes(data: dict) -> int | None:
    """Insert a meeting notes row. Returns the row id."""
    import json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shams_meeting_notes
                    (event_id, recall_bot_id, title, started_at, ended_at,
                     duration_min, attendees, platform, transcript, summary,
                     action_items, decisions, commitments_created, commitments_resolved,
                     persona_used, meeting_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (recall_bot_id) DO NOTHING
                RETURNING id
                """,
                (
                    data.get("event_id"),
                    data.get("recall_bot_id"),
                    data.get("title"),
                    data.get("started_at"),
                    data.get("ended_at"),
                    data.get("duration_min"),
                    json.dumps(data.get("attendees") or []),
                    data.get("platform"),
                    data.get("transcript"),
                    data.get("summary"),
                    json.dumps(data.get("action_items") or []),
                    json.dumps(data.get("decisions") or []),
                    data.get("commitments_created") or [],
                    data.get("commitments_resolved") or [],
                    data.get("persona_used"),
                    data.get("meeting_type"),
                ),
            )
            row = cur.fetchone()
            return row[0] if row else None


def search_meeting_notes(query: str = "", attendee: str = "", meeting_type: str = "",
                         since: str = "", limit: int = 10) -> list[dict]:
    """Search meeting notes. Returns list of dicts."""
    sql = ["SELECT id, title, started_at, duration_min, meeting_type, summary, action_items FROM shams_meeting_notes WHERE 1=1"]
    params = []
    if query:
        sql.append("AND (summary ILIKE %s OR transcript ILIKE %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    if attendee:
        sql.append("AND attendees::text ILIKE %s")
        params.append(f"%{attendee}%")
    if meeting_type:
        sql.append("AND meeting_type = %s")
        params.append(meeting_type)
    if since:
        sql.append("AND started_at >= %s")
        params.append(since)
    sql.append("ORDER BY started_at DESC LIMIT %s")
    params.append(limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
```

- [ ] **Step 2: Commit**

```bash
git add memory.py
git commit -m "Meeting bot: memory helpers for meeting notes CRUD + search"
```

---

## Task 6: Webhook endpoint + completion poller

**Files:**
- Modify: `app.py`
- Modify: `scheduler.py`

- [ ] **Step 1: Add webhook endpoint to app.py**

Find the Flask app's blueprint/route registration area and add:

```python
@app.route("/api/recall/webhook", methods=["POST"])
def recall_webhook():
    """Handle Recall.ai bot status change webhooks."""
    import meeting_bot
    import recall_client as rc

    data = request.get_json(silent=True) or {}
    event_type = data.get("event") or data.get("type", "")
    bot_data = data.get("data", {}).get("bot") or data.get("data", {})
    bot_id = bot_data.get("id") or data.get("bot_id", "")
    status = bot_data.get("status_code") or data.get("status", "")

    logger.info(f"Recall webhook: event={event_type} bot={bot_id} status={status}")

    if status == "done" and bot_id:
        # Async: process in background to respond to webhook quickly
        import threading
        threading.Thread(
            target=_process_recall_bot,
            args=(bot_id,),
            daemon=True,
        ).start()

    return jsonify({"ok": True}), 200


def _process_recall_bot(bot_id: str):
    """Background handler: pull transcript, process, deliver."""
    import meeting_bot
    import recall_client as rc
    import json

    try:
        # Get event metadata from memory
        meta_raw = memory.recall(f"recall_bot_{bot_id}")
        if not meta_raw:
            logger.error(f"No event meta found for bot {bot_id}")
            return
        event_meta = json.loads(meta_raw)

        # Get transcript
        utterances = rc.get_transcript(bot_id)
        transcript_text = rc.format_transcript(utterances)

        if not transcript_text or len(transcript_text) < 50:
            logger.warning(f"Transcript too short for bot {bot_id}, skipping")
            return

        # Process
        meeting_bot.process_completed_meeting(
            bot_id=bot_id,
            transcript_text=transcript_text,
            event_meta=event_meta,
        )
    except Exception as e:
        logger.error(f"process_recall_bot error: {e}", exc_info=True)
```

- [ ] **Step 2: Add completion poller to scheduler.py**

Add a new function and register it:

```python
def _check_meeting_bots():
    """Poll for both: (1) upcoming meetings to dispatch bots, (2) completed bots to process."""
    try:
        from meeting_bot import check_and_dispatch_bots
        dispatched = check_and_dispatch_bots()
        if dispatched:
            logger.info(f"Meeting bot: dispatched {dispatched} bot(s)")
    except Exception as e:
        logger.error(f"Meeting bot dispatch error: {e}")

    # Fallback poller: check for any bots that finished but webhook was missed
    try:
        import recall_client as rc
        import meeting_bot
        import json

        # Get all active bot IDs from memory (recall_bot_* keys)
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM shams_memory WHERE key LIKE 'recall_bot_%'")
                active_bots = cur.fetchall()

        for key, meta_raw in active_bots:
            bot_id = key.replace("recall_bot_", "")
            # Skip if already processed
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM shams_meeting_notes WHERE recall_bot_id = %s", (bot_id,))
                    if cur.fetchone():
                        continue

            bot = rc.get_bot(bot_id)
            if bot and bot.get("status_code") == "done":
                logger.info(f"Fallback poller: processing completed bot {bot_id}")
                utterances = rc.get_transcript(bot_id)
                transcript_text = rc.format_transcript(utterances)
                if transcript_text and len(transcript_text) >= 50:
                    event_meta = json.loads(meta_raw)
                    meeting_bot.process_completed_meeting(
                        bot_id=bot_id,
                        transcript_text=transcript_text,
                        event_meta=event_meta,
                    )
    except Exception as e:
        logger.error(f"Meeting bot fallback poller error: {e}")
```

Update `init_scheduler` to register the job (replace the existing `_check_meeting_preps` with `_check_meeting_bots` since the meeting bot subsumes the prep feature):

```python
scheduler.add_job(_check_meeting_bots, "interval", minutes=10, id="meeting_bot_check")
```

- [ ] **Step 3: Commit**

```bash
git add app.py scheduler.py
git commit -m "Meeting bot: webhook endpoint + completion poller + scheduler integration"
```

---

## Task 7: Claude tool for querying past meetings

**Files:**
- Create: `tools/meeting_tools.py`

- [ ] **Step 1: Create the tool**

```python
# tools/meeting_tools.py
"""Claude tool for querying Shams's meeting notes archive."""
from __future__ import annotations

import json
import memory
from tools.registry import tool


@tool(
    name="search_meeting_notes",
    description="Search past meeting recordings and summaries. Find what was discussed, decided, or assigned in any meeting Shams attended.",
    agent=None,
    schema={
        "properties": {
            "query": {"type": "string", "description": "Free-text search (matches transcript + summary)"},
            "attendee": {"type": "string", "description": "Filter by attendee name or email"},
            "meeting_type": {"type": "string", "enum": ["legal", "operations", "deal", "interview", "general"]},
            "since": {"type": "string", "description": "ISO date — only meetings on/after this date"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": [],
    },
)
def search_meeting_notes_tool(query: str = "", attendee: str = "", meeting_type: str = "",
                              since: str = "", limit: int = 5) -> str:
    limit = max(1, min(int(limit or 5), 20))
    results = memory.search_meeting_notes(
        query=query, attendee=attendee, meeting_type=meeting_type,
        since=since, limit=limit,
    )
    if not results:
        return "No meeting notes match that search."
    lines = [f"Found {len(results)} meeting(s):"]
    for r in results:
        started = str(r.get("started_at", ""))[:16]
        title = r.get("title", "?")
        mtype = r.get("meeting_type", "?")
        dur = r.get("duration_min") or "?"
        summary = (r.get("summary") or "")[:200]
        actions = r.get("action_items") or []
        if isinstance(actions, str):
            actions = json.loads(actions)
        lines.append(f"\n📋 {title} ({started}, {dur}min, {mtype})")
        lines.append(f"  {summary}")
        if actions:
            lines.append(f"  Action items: {len(actions)}")
            for a in actions[:3]:
                if isinstance(a, dict):
                    lines.append(f"    - {a.get('assignee','?')}: {a.get('task','')}")
    return "\n".join(lines)
```

- [ ] **Step 2: Verify auto-registration**

```bash
cd /Users/mj/code/Shams
set -a && source .env && set +a
python3 -c "
import tools.meeting_tools
from tools import registry
names = {d['name'] for d in registry.get_tool_definitions()}
assert 'search_meeting_notes' in names
print('OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add tools/meeting_tools.py
git commit -m "Meeting bot: Claude tool for querying past meeting notes"
```

---

## Task 8: Deploy + test

**Files:**
- (operational)

- [ ] **Step 1: Set the Recall.ai webhook URL**

Configure the webhook in Recall.ai dashboard to point to: `https://app.myshams.ai/api/recall/webhook`

Or via API:
```bash
curl -X POST https://us-east-1.recall.ai/api/v1/webhook/ \
  -H "Authorization: Token b58ae3de68d77288b31e3f187d523070d6674f9d" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://app.myshams.ai/api/recall/webhook", "events": ["bot.status_change"]}'
```

- [ ] **Step 2: Push to Railway**

```bash
cd /Users/mj/code/Shams
git push origin main
```

- [ ] **Step 3: Manual test**

Tell Shams via Telegram: "join my next meeting" (or wait for a meeting to start within 15 min).

Verify:
1. Telegram: "🤖 Joining *Meeting Name* in ~Xmin — I'll send notes after."
2. Bot appears in the meeting
3. After meeting ends: Telegram summary with decisions + action items
4. Email digest arrives
5. Query via Shams: "what was discussed in the last meeting?"

- [ ] **Step 4: Commit verification**

```bash
git commit --allow-empty -m "Meeting bot: deployed + tested"
```

---

## Known Deferrals

1. **Slack huddle auto-join** — needs Slack Events API listener for `huddle_started`. Follow-up plan.
2. **Telegram "join" command** — manual trigger via chat. Follow-up.
3. **Meeting prep integration** — currently separate from meeting bot. Could merge: prep fires 15 min before, bot dispatches 5 min before. Low priority.
4. **Transcript quality detection** — detect garbled/low-quality transcripts and fall back to async Recall.ai transcription instead of meeting captions.
5. **Cost tracking dashboard** — track Recall.ai spend per day/month. Currently just a daily bot count limit.

---

## Summary of Commits

| # | Task | Commit |
|---|---|---|
| 1 | Schema + config | `Meeting bot: schema + config for Recall.ai integration` |
| 2 | Recall.ai client | `Meeting bot: Recall.ai API client with create/get/transcript` |
| 3 | Smart filter + dispatch | `Meeting bot: smart filter + bot dispatch + calendar poller` |
| 4 | Summarization + delivery | `Meeting bot: type detection + summarization + cross-referencing + delivery` |
| 5 | Memory helpers | `Meeting bot: memory helpers for meeting notes CRUD + search` |
| 6 | Webhook + scheduler | `Meeting bot: webhook endpoint + completion poller + scheduler integration` |
| 7 | Claude tool | `Meeting bot: Claude tool for querying past meeting notes` |
| 8 | Deploy + test | `Meeting bot: deployed + tested` |
