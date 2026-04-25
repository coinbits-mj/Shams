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
import threading
import time
from typing import Any

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
