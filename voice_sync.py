"""Shams Voice Sync — real-time conversation in Google Meet.

Sections:
- Session state (in-memory, keyed by Recall bot_id)
- Turn detection (pause-based)
- Live context builder (calendar + commitments + mentions)
- Conversation turn (Claude Haiku)
- Speak (ElevenLabs TTS → Recall output_audio)
- Webhook entrypoint (called by app.py)
- Smart ping evaluator + bot dispatch (called by scheduler)
- Post-call routing (called by app.py)
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import config
import db
import memory

logger = logging.getLogger(__name__)

# ── Session state ───────────────────────────────────────────────────────────
#
# Threading model: _SESSION_LOCK only guards inserts/removes from the registry
# map. Per-session field mutation (history.append, mode assignment, speaking
# flag, etc.) is not locked — it relies on CPython's GIL atomicity for the
# single-writer case (one MJ → one bot → one webhook thread driving turns).
# Callers must ensure end_session(bot_id) is not invoked while another thread
# holds a reference returned by get_session(bot_id) and is still mutating it.

_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = threading.Lock()


def create_session(bot_id: str) -> dict:
    with _SESSION_LOCK:
        s = {
            "bot_id": bot_id,
            "history": [],            # [{role, content}]
            "pending_words": [],      # buffered FINAL utterance segments waiting to drain
            "pending_partial": "",    # latest CUMULATIVE partial text (Deepgram rolls this)
            "last_word_at": 0.0,      # monotonic seconds — for pause detection
            "mode": "active",         # "active" | "passive" (just listen)
            "context_cache": {},      # {calendar, commitments, mentions, ...} — populated by build_live_context (Task 7)
            "started_at": time.time(),
            "speaking": False,        # true while Shams is mid-TTS to avoid overlap
            "pause_timer": None,      # threading.Timer that fires _on_pause_complete after silence
        }
        _SESSIONS[bot_id] = s
        return s


def get_session(bot_id: str) -> dict | None:
    """Return the live session dict (mutable). Callers must respect the threading model."""
    return _SESSIONS.get(bot_id)


def end_session(bot_id: str) -> None:
    with _SESSION_LOCK:
        s = _SESSIONS.pop(bot_id, None)
        if s and s.get("pause_timer"):
            try:
                s["pause_timer"].cancel()
            except Exception:
                pass


def append_user_turn(bot_id: str, text: str) -> None:
    s = _SESSIONS.get(bot_id)
    if s is not None:
        s["history"].append({"role": "user", "content": text})


def append_assistant_turn(bot_id: str, text: str) -> None:
    s = _SESSIONS.get(bot_id)
    if s is not None:
        s["history"].append({"role": "assistant", "content": text})


def set_mode(bot_id: str, mode: str) -> None:
    s = _SESSIONS.get(bot_id)
    if s is not None and mode in ("active", "passive"):
        s["mode"] = mode


# ── Turn detection ──────────────────────────────────────────────────────────


def buffer_words(bot_id: str, text: str, is_final: bool) -> None:
    """Buffer transcript chunks during MJ's utterance.

    Recall's `transcript.partial_data` events deliver CUMULATIVE rolling text
    (each partial contains all prior text), so we cannot just append every
    chunk — we'd duplicate. Strategy:
    - Always update `last_word_at` so pause detection sees activity.
    - Track the latest cumulative partial in s["pending_partial"].
    - Only commit to `pending_words` on a final event; the committed text is
      the final's `text` (which Recall guarantees contains the complete
      utterance segment).
    """
    s = _SESSIONS.get(bot_id)
    if s is None:
        return
    text = text.strip()
    if not text:
        return

    s["last_word_at"] = time.monotonic()

    if is_final:
        # Commit the final text and clear the partial buffer.
        s["pending_words"].append(text)
        s["pending_partial"] = ""
    else:
        # Replace the rolling partial — DO NOT append.
        s["pending_partial"] = text

    # Arm a background timer so the pause-completion check fires even if no
    # more events arrive (which is exactly what happens when MJ stops talking).
    _arm_pause_timer(bot_id)


def _arm_pause_timer(bot_id: str) -> None:
    """Schedule (or reschedule) the pause-completion check for a session.

    Each new word resets the timer to fire SYNC_PAUSE_SECONDS later. Once the
    user falls silent that long, _on_pause_complete runs and drains the turn.
    """
    s = _SESSIONS.get(bot_id)
    if s is None:
        return
    existing = s.get("pause_timer")
    if existing is not None:
        try:
            existing.cancel()
        except Exception:
            pass
    delay = max(config.SYNC_PAUSE_SECONDS + 0.05, 0.1)
    t = threading.Timer(delay, _on_pause_complete, args=[bot_id])
    t.daemon = True
    s["pause_timer"] = t
    t.start()


def _on_pause_complete(bot_id: str) -> None:
    """Timer callback — runs ~SYNC_PAUSE_SECONDS after the last buffered chunk.

    Re-checks turn completion (a fresh chunk could have arrived and bumped
    last_word_at, in which case is_turn_complete is False and we bail — the
    later buffer call already armed a new timer).
    """
    try:
        s = _SESSIONS.get(bot_id)
        if s is None:
            return
        if s.get("speaking"):
            # Echo guard: while Shams is mid-TTS, don't process incoming audio
            return
        if not is_turn_complete(bot_id):
            return
        utterance = drain_pending(bot_id)
        if not utterance:
            return
        logger.info(f"voice_sync turn drained bot={bot_id} utterance={utterance!r}")
        reply = process_user_turn(bot_id, utterance)
        if reply:
            logger.info(f"voice_sync reply bot={bot_id} reply={reply!r}")
            speak(bot_id, reply)
    except Exception:
        logger.exception(f"_on_pause_complete error for bot {bot_id}")


def is_turn_complete(bot_id: str) -> bool:
    """True if MJ has paused long enough to count as end-of-turn."""
    s = _SESSIONS.get(bot_id)
    if s is None:
        return False
    if not s["pending_words"] and not s.get("pending_partial"):
        return False
    silence = time.monotonic() - s["last_word_at"]
    return silence >= config.SYNC_PAUSE_SECONDS


def drain_pending(bot_id: str) -> str:
    """Pop pending words + any unfinalized partial; clear the buffer."""
    s = _SESSIONS.get(bot_id)
    if s is None:
        return ""
    parts = list(s["pending_words"])
    partial = s.get("pending_partial", "")
    if partial:
        parts.append(partial)
    text = " ".join(parts).strip()
    s["pending_words"] = []
    s["pending_partial"] = ""
    return text


# ── Live context ────────────────────────────────────────────────────────────

# Common words that look like names but aren't
_NAME_STOPWORDS = {
    # pronouns + articles + conjunctions
    "i", "i'll", "i've", "i'm", "you", "your", "yours", "we", "us", "our",
    "they", "them", "their", "he", "she", "him", "her", "his", "hers",
    "it", "its", "the", "and", "but", "or", "if", "to", "for", "with",
    "from", "of", "on", "in", "at", "as", "by", "about",
    # be/have/do/will family
    "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did", "doing", "done",
    "will", "would", "should", "could", "can", "may", "might", "must",
    # wh/question + common verbs
    "what", "when", "where", "who", "why", "how", "which",
    "tell", "let", "send", "see", "saw", "look", "looking", "make",
    "made", "take", "took", "come", "came", "going", "gone", "go",
    "get", "got", "say", "said", "saying", "talk", "talked", "talking",
    "think", "thinking", "know", "knew", "want", "wanted", "need",
    "needed", "ask", "asked", "asking", "meet", "meeting", "give",
    "gave", "given", "put", "use", "used", "using", "try", "tried",
    "trying", "feel", "felt", "show", "showed", "find", "found",
    "work", "working",
    # time/day words
    "today", "tomorrow", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
    "morning", "afternoon", "evening", "night", "now", "then", "soon",
    "later", "earlier", "week", "weeks", "month", "months", "year",
    "years", "day", "days", "hour", "hours", "minute", "minutes",
    "time", "times",
    # affirmation/negation/social
    "yeah", "yes", "no", "ok", "okay", "sure", "fine", "nope", "yep",
    "thanks", "thank", "please", "hi", "hello", "hey", "bye", "goodbye",
    "right", "wrong", "good", "great", "bad", "really", "very",
    "much", "many", "more", "most", "less", "least",
    # filler/discourse
    "uh", "um", "like", "just", "kind", "kinda", "sort", "sorta",
    "actually", "basically", "literally", "honestly", "anyway", "well",
    "still", "even", "also", "only", "maybe", "probably", "always",
    "never", "ever", "again", "back", "here", "there",
    # demonstratives + generic nouns
    "this", "that", "these", "those", "thing", "things", "stuff",
    "deal", "deals", "way", "ways", "part", "parts", "side",
    # bot itself
    "shams",
}

_NAME_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def extract_mentioned_names(utterance: str) -> list[str]:
    """Heuristic: words capitalized in the source OR in a known-people list.

    Voice transcripts are often lowercase, so we accept any token that's not in
    the stopword list and is at least 3 chars. The downstream lookup filters
    junk by checking against the email archive's known senders.
    """
    if not utterance:
        return []
    out = []
    seen = set()
    for tok in _NAME_RE.findall(utterance):
        low = tok.lower()
        if low in _NAME_STOPWORDS or len(low) < 3:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def _get_remaining_today() -> list[dict]:
    """Calendar events from now until end of day."""
    try:
        import google_client
        events = google_client.get_todays_events()
    except Exception:
        logger.exception("Live context calendar error")
        return []

    now = datetime.now(timezone.utc)
    out = []
    for ev in events:
        start_raw = ev.get("start", "")
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if start_dt >= now:
            out.append({"summary": ev.get("summary", ""), "start": start_raw})
    return out[:5]


def _get_overdue_commitments() -> list[dict]:
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT recipient_email, commitment_text,
                          EXTRACT(DAY FROM (NOW() - promised_at))::INT AS days_old
                   FROM shams_open_commitments
                   WHERE status = 'open'
                   ORDER BY promised_at ASC LIMIT 5"""
            )
            return [
                {"to": r[0], "text": r[1], "days_old": r[2] or 0}
                for r in cur.fetchall()
            ]
    except Exception:
        logger.exception("Live context commitments error")
        return []


def _get_recent_emails_for_names(names: list[str]) -> dict[str, list[dict]]:
    """For each mentioned name, return up to 3 recent emails (last 30d).

    Best-effort: a per-name SQL error is logged and skipped; the rest of the
    names are still attempted.
    """
    if not names:
        return {}
    out: dict[str, list[dict]] = {}
    try:
        conn = db.get_conn()
    except Exception:
        logger.exception("Live context emails: db.get_conn failed")
        return out
    try:
        with conn:
            for name in names[:5]:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT from_addr, subject, date FROM shams_email_archive
                               WHERE (from_addr ILIKE %s OR subject ~* %s)
                                 AND date > NOW() - INTERVAL '30 days'
                               ORDER BY date DESC LIMIT 3""",
                            (f"%{name}%", rf"\m{name}\M"),
                        )
                        rows = cur.fetchall()
                        if rows:
                            out[name.lower()] = [
                                {"from": r[0], "subject": r[1], "date": str(r[2])[:10]}
                                for r in rows
                            ]
                except Exception:
                    logger.exception(f"Live context emails: lookup failed for name={name!r}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def build_live_context(utterance: str) -> dict:
    """Assemble the live context bundle for one Claude turn."""
    names = extract_mentioned_names(utterance)
    return {
        "calendar_today": _get_remaining_today(),
        "overdue_commitments": _get_overdue_commitments(),
        "mentioned_emails": _get_recent_emails_for_names(names),
    }


def format_context_for_prompt(ctx: dict) -> str:
    """Compact text block injected into Claude's system message for the turn."""
    lines = []
    cal = ctx.get("calendar_today", [])
    if cal:
        lines.append("CALENDAR (remaining today):")
        for ev in cal:
            lines.append(f"- {ev.get('summary', '')} @ {ev.get('start', '')[:16]}")
    coms = ctx.get("overdue_commitments", [])
    if coms:
        lines.append("\nOVERDUE COMMITMENTS:")
        for c in coms:
            lines.append(f"- to {c.get('to', '?')}: \"{c.get('text', '')[:80]}\" ({c.get('days_old', 0)}d old)")
    mentions = ctx.get("mentioned_emails", {})
    if mentions:
        lines.append("\nRECENT EMAILS FOR PEOPLE MENTIONED:")
        for name, emails in mentions.items():
            for e in emails[:2]:
                lines.append(f"- {name}: {e.get('subject', '')} ({e.get('date', '')})")
    return "\n".join(lines)


# ── Claude turn ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are Shams, MJ's chief of staff. You're in a live voice conversation.

RULES:
- Be concise. Speak in 1-3 sentences per turn. Never monologue.
- Surface relevant context proactively when useful.
- Push back gently when something looks off.
- Ask ONE clarifying question at a time, never multiple.
- When MJ mentions a person, reference their recent email/commitments if you have them.
- When MJ commits to something ("I'll do X"), confirm: "Got it, tracking that."
- Don't say "as an AI" — you're his chief of staff.
- Match his energy: casual when he's casual, sharp when he's focused.
- If he says "just listen" — go quiet.
"""

_SYNC_MODEL = os.environ.get("SYNC_CLAUDE_MODEL", "claude-haiku-4-5")
_MAX_SENTENCES = 3


@functools.lru_cache(maxsize=1)
def _anthropic_client():
    """Module-level cached Anthropic client.

    Keeping one client across turns lets the underlying httpx client reuse the
    TLS connection to api.anthropic.com — saves ~100-200ms per turn vs a fresh
    handshake. Tests monkeypatch this function, which bypasses the cache.
    """
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _truncate_to_sentences(text: str, max_sentences: int = _MAX_SENTENCES) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:max_sentences]).strip()


def _is_addressed_to_shams(utterance: str) -> bool:
    """Wake-word check: did MJ explicitly call out Shams?

    Used to gate replies in passive mode. Intentionally strict — a bare
    question mark would otherwise make Shams interject when MJ is asking a
    human teammate something. Active mode does not call this.
    """
    return "shams" in utterance.lower()


def process_user_turn(bot_id: str, utterance: str) -> str | None:
    """Append the utterance to history, call Claude, return the reply (or None).

    Returns None when in passive mode and MJ didn't address Shams directly.
    """
    s = _SESSIONS.get(bot_id)
    if s is None:
        return None

    append_user_turn(bot_id, utterance)

    if s["mode"] == "passive" and not _is_addressed_to_shams(utterance):
        return None

    ctx = build_live_context(utterance)
    ctx_text = format_context_for_prompt(ctx)
    system = _SYSTEM_PROMPT
    if ctx_text:
        system = system + "\n\nLIVE CONTEXT:\n" + ctx_text

    # TODO: prompt caching — split system into a static persona block (cached)
    # and a per-turn LIVE CONTEXT block (uncached) using
    # `system=[{"type":"text","text":_SYSTEM_PROMPT,"cache_control":{"type":"ephemeral"}},
    #          {"type":"text","text":"LIVE CONTEXT:\n"+ctx_text}]`.
    # Saves ~50-100ms TTFT and ~90% of the persona token cost on Haiku.
    # Defer until after Task 10 (webhook handler) ships.
    try:
        api = _anthropic_client()
        resp = api.messages.create(
            model=_SYNC_MODEL,
            max_tokens=300,
            system=system,
            messages=list(s["history"]),
        )
        text = resp.content[0].text.strip()
    except Exception:
        logger.exception("Voice sync Claude turn error")
        return None

    text = _truncate_to_sentences(text)
    append_assistant_turn(bot_id, text)
    return text


# ── Speak ───────────────────────────────────────────────────────────────────


def _tts(text: str, voice_id: str | None = None) -> bytes | None:
    """Wrapper for elevenlabs_client.tts so it's monkeypatchable in tests."""
    import elevenlabs_client
    return elevenlabs_client.tts(text, voice_id=voice_id)


def _output_audio(bot_id: str, mp3_bytes: bytes) -> bool:
    """Wrapper for recall_client.output_audio so it's monkeypatchable in tests."""
    import recall_client
    return recall_client.output_audio(bot_id, mp3_bytes)


def speak(bot_id: str, text: str) -> bool:
    """TTS the text and play it through the bot. Returns True on success."""
    s = _SESSIONS.get(bot_id)
    if s is None:
        return False

    s["speaking"] = True
    try:
        mp3 = _tts(text)
        if not mp3:
            logger.warning(f"TTS returned no audio for bot {bot_id}; skipping output")
            return False
        if not _output_audio(bot_id, mp3):
            return False
        return True
    finally:
        s["speaking"] = False


# ── Realtime event handler ──────────────────────────────────────────────────

# Speakers we treat as MJ. Recall's `participant.name` comes from the meeting
# attendee display name. Tolerant matching since Google Meet may show "Maher",
# "Maher Janajri", "MJ", etc.
_MJ_SPEAKER_TOKENS = ("maher", "mj", "janajri")


def _is_mj_speaker(name: str | None) -> bool:
    """True iff the participant name matches one of the known MJ tokens.

    Default-False when speaker info is missing — once MJ adds a teammate to
    the call, treating unidentified events as MJ would let other voices drive
    Shams's turns. Recall almost always populates participant.name once
    diarization warms up.
    """
    if not name:
        return False
    low = name.lower()
    return any(tok in low for tok in _MJ_SPEAKER_TOKENS)


def handle_realtime_event(payload: dict) -> None:
    """Process one Recall.ai realtime transcript event.

    Webhook delivers `transcript.data` (final) and `transcript.partial_data`
    (in-progress) events. We append every chunk's words and check pause-based
    completion after each one.
    """
    # TEMP DEBUG: log compact payload shape so we can see what's arriving
    try:
        evt = payload.get("event")
        d = payload.get("data", {}) or {}
        bid = (d.get("bot", {}) or {}).get("id")
        inner = d.get("data", {}) or {}
        words = inner.get("words", []) or []
        text_preview = " ".join(w.get("text", "") for w in words)[:80]
        is_final = inner.get("is_final")
        speaker = (inner.get("participant") or {}).get("name")
        logger.info(
            f"realtime evt={evt!r} bot={bid} speaker={speaker!r} is_final={is_final} "
            f"words={len(words)} text={text_preview!r} session_exists={bid in _SESSIONS}"
        )
    except Exception:
        logger.exception("realtime debug log failed")

    data_outer = payload.get("data", {}) or {}
    bot = data_outer.get("bot", {}) or {}
    bot_id = bot.get("id") or data_outer.get("bot_id", "")
    if not bot_id:
        return

    s = _SESSIONS.get(bot_id)
    if s is None:
        return
    # Echo guard: while Shams's TTS is playing into the meeting, ignore
    # transcripts — Recall will pick up our own audio and we don't want to
    # respond to ourselves.
    if s.get("speaking"):
        return

    inner = data_outer.get("data", {}) or {}
    words = inner.get("words", []) or []
    text = " ".join(w.get("text", "") for w in words).strip()
    is_final = bool(inner.get("is_final", payload.get("event") == "transcript.data"))
    speaker = (inner.get("participant") or {}).get("name", "")

    if not _is_mj_speaker(speaker):
        return

    if text:
        buffer_words(bot_id, text, is_final=is_final)

    if not is_turn_complete(bot_id):
        return

    utterance = drain_pending(bot_id)
    if not utterance:
        return

    reply = process_user_turn(bot_id, utterance)
    if reply:
        speak(bot_id, reply)


# ── Smart ping ──────────────────────────────────────────────────────────────


def _recall(key: str) -> str | None:
    """Indirection for monkeypatching memory.recall in tests."""
    return memory.recall(key)


def _in_window(now) -> bool:
    return config.SYNC_WINDOW_START_UTC <= now.hour < config.SYNC_WINDOW_END_UTC


def _is_weekend(now) -> bool:
    return now.weekday() >= 5  # Sat=5, Sun=6


def _already_pinged_today(date_str: str) -> bool:
    return bool(_recall(f"sync_pinged_{date_str}"))


def _next_30min_free(now) -> bool:
    for ev in _get_remaining_today():
        try:
            start_dt = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
        except Exception:
            continue
        delta = (start_dt - now).total_seconds() / 60
        if 0 <= delta <= 30:
            return False
    return True


def should_ping(now=None) -> bool:
    """Evaluate all conditions for sending a sync ping."""
    if config.SYNC_DISABLED:
        return False
    if not config.SYNC_MEET_URL:
        return False
    now = now or datetime.now(timezone.utc)
    if not _in_window(now):
        return False
    if config.SYNC_SKIP_WEEKENDS and _is_weekend(now):
        return False
    if _already_pinged_today(now.strftime("%Y-%m-%d")):
        return False
    if not _next_30min_free(now):
        return False
    return True


# ── Bot dispatch ────────────────────────────────────────────────────────────


def _create_bot(**kwargs):
    """Indirection for monkeypatching."""
    import recall_client
    return recall_client.create_bot(**kwargs)


def _remember(key: str, value: str) -> None:
    """Indirection for monkeypatching."""
    memory.remember(key, value)


def _realtime_webhook_url() -> str:
    """The public URL Recall posts realtime events to."""
    base = os.environ.get("APP_URL", "https://app.myshams.ai").rstrip("/")
    return f"{base}/api/recall/realtime"


def dispatch_sync_bot() -> str | None:
    """Send the bot to the persistent sync Meet. Creates session state.

    Returns the bot_id on success.
    """
    if not config.SYNC_MEET_URL:
        logger.error("SYNC_MEET_URL not set")
        return None

    bot = _create_bot(
        meeting_url=config.SYNC_MEET_URL,
        bot_name=config.SYNC_BOT_NAME,
        realtime_webhook_url=_realtime_webhook_url(),
        transcript_provider=config.SYNC_REALTIME_TRANSCRIPT_PROVIDER,
    )
    if not bot or not bot.get("id"):
        return None

    bot_id = bot["id"]
    create_session(bot_id)

    # Mark as a sync bot so post-call routing knows the persona/type
    _remember(f"sync_bot_{bot_id}", "1")
    # Reuse the meeting_bot key so the existing transcript-fetcher path works
    _remember(
        f"recall_bot_{bot_id}",
        json.dumps({
            "event_id": f"sync_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            "title": "Shams Sync",
            "start": datetime.now(timezone.utc).isoformat(),
            "end": "",
            "attendees": [],
            "platform": "google_meet",
            "meeting_type": "daily_sync",
            "persona": "shams",
        }),
    )
    return bot_id


# ── Telegram ping ───────────────────────────────────────────────────────────


def _send_telegram_with_buttons(chat_id: str, text: str, buttons: list) -> None:
    """Indirection — Telegram's helper expects a list of dicts on one row.

    For sync we want two distinct rows so the deeplink (URL) and callback_data
    button render cleanly.
    """
    import requests
    from telegram import TG_BASE
    if not TG_BASE:
        return
    keyboard = {"inline_keyboard": [[b] for b in buttons]}
    try:
        requests.post(
            f"{TG_BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text, "reply_markup": keyboard},
            timeout=15,
        )
    except Exception as e:
        logger.error(f"Sync ping send failed: {e}")


def send_sync_ping() -> None:
    """Send the inline-button Telegram ping."""
    if not config.SYNC_MEET_URL:
        return
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    text = "☀️ Got a clear window — want to sync?"
    buttons = [
        {"text": "Join Sync ☕", "url": config.SYNC_MEET_URL},
        {"text": "Not today", "callback_data": f"sync_skip:{today}"},
    ]
    _send_telegram_with_buttons(chat_id, text, buttons)
    # Mark pinged so we don't re-ping today even before MJ acts
    _remember(f"sync_pinged_{today}", "sent")


def handle_sync_callback(cb_data: str) -> None:
    """Handle Telegram callback for sync_* buttons."""
    if not cb_data:
        return
    parts = cb_data.split(":", 1)
    action = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if action == "sync_skip":
        date_str = arg or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _remember(f"sync_pinged_{date_str}", "skipped")
        # Mark "Not today" so we don't ping again
        return

    if action == "sync_join":
        # Manual dispatch path (in case we ever wire a callback button to it)
        dispatch_sync_bot()
        return


def smart_sync_ping_check() -> None:
    """Scheduler entrypoint — every 15 min during the window."""
    try:
        if should_ping():
            send_sync_ping()
    except Exception as e:
        logger.error(f"smart_sync_ping_check error: {e}")
