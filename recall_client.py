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
    Output: "Brandon: Let's start\\nMaher: Sounds good"
    """
    lines = []
    for u in utterances:
        speaker = u.get("speaker") or u.get("participant", {}).get("name") or "Unknown"
        words = u.get("words", [])
        text = " ".join(w.get("text", "") for w in words).strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)
