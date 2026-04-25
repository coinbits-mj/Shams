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

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import config
import db

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
            "pending_words": [],      # buffered partial words during current MJ utterance
            "last_word_at": 0.0,      # monotonic seconds — for pause detection
            "mode": "active",         # "active" | "passive" (just listen)
            "context_cache": {},      # {calendar, commitments, mentions, ...} — populated by build_live_context (Task 7)
            "started_at": time.time(),
            "speaking": False,        # true while Shams is mid-TTS to avoid overlap
        }
        _SESSIONS[bot_id] = s
        return s


def get_session(bot_id: str) -> dict | None:
    """Return the live session dict (mutable). Callers must respect the threading model."""
    return _SESSIONS.get(bot_id)


def end_session(bot_id: str) -> None:
    with _SESSION_LOCK:
        _SESSIONS.pop(bot_id, None)


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
    """Buffer transcript words/phrases during MJ's utterance.

    Recall's transcript.data events deliver chunks (final or partial). We append
    every chunk's text and update last_word_at so pause detection works.
    """
    s = _SESSIONS.get(bot_id)
    if s is None:
        return
    text = text.strip()
    if not text:
        return
    s["pending_words"].append(text)
    s["last_word_at"] = time.monotonic()


def is_turn_complete(bot_id: str) -> bool:
    """True if MJ has paused long enough to count as end-of-turn."""
    s = _SESSIONS.get(bot_id)
    if s is None or not s["pending_words"]:
        return False
    silence = time.monotonic() - s["last_word_at"]
    return silence >= config.SYNC_PAUSE_SECONDS


def drain_pending(bot_id: str) -> str:
    """Pop pending words as a single utterance string and clear the buffer."""
    s = _SESSIONS.get(bot_id)
    if s is None:
        return ""
    text = " ".join(s["pending_words"]).strip()
    s["pending_words"] = []
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


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _truncate_to_sentences(text: str, max_sentences: int = _MAX_SENTENCES) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:max_sentences]).strip()


def _is_addressed_to_shams(utterance: str) -> bool:
    """Cheap heuristic: does MJ name Shams or ask a direct question?"""
    low = utterance.lower()
    if "shams" in low:
        return True
    if "?" in utterance:
        return True
    return False


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
