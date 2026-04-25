"""Recall.ai API client — create bots, check status, retrieve transcripts."""
from __future__ import annotations

import base64
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
    realtime_webhook_url: str | None = None,
    transcript_provider: str | None = None,
) -> dict | None:
    """Create a Recall.ai bot to join a meeting.

    If realtime_webhook_url is set, configures a streaming transcript provider
    (defaults to deepgram_streaming) and a realtime_endpoints webhook for
    transcript.data events. Otherwise uses meeting_captions like the legacy
    meeting bot.

    Returns the bot dict (with 'id' key) on success, None on failure.
    """
    if realtime_webhook_url:
        provider = transcript_provider or "deepgram_streaming"
        recording_config = {
            "transcript": {"provider": {provider: {}}},
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": realtime_webhook_url,
                    "events": ["transcript.data", "transcript.partial_data"],
                }
            ],
        }
    else:
        recording_config = {
            "transcript": {"provider": {"meeting_captions": {}}},
        }

    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name or config.MEETING_BOT_NAME,
        "recording_config": recording_config,
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

    Tries three strategies in order:
    1. Bot transcript endpoint (works when meeting_captions were enabled)
    2. Async transcription via recording (triggers recallai_async if needed, polls for result)
    3. Bot media_shortcuts fallback

    Returns list of utterance dicts: [{participant: {name}, words: [{text}]}].
    """
    # Strategy 1: bot transcript endpoint (meeting captions)
    try:
        r = requests.get(_url(f"/bot/{bot_id}/transcript/"), headers=_headers(), timeout=30)
        if r.ok:
            data = r.json()
            result = data.get("results", []) if isinstance(data, dict) else data
            if result:
                return result
    except Exception as e:
        logger.error(f"Recall bot transcript error: {e}")

    # Strategy 2: async transcription via recording
    try:
        bot = get_bot(bot_id)
        if not bot:
            return []

        recordings = bot.get("recordings", [])
        if not recordings:
            return []

        recording_id = recordings[0].get("id")
        if not recording_id:
            return []

        utterances = _get_or_create_async_transcript(recording_id)
        if utterances:
            return utterances
    except Exception as e:
        logger.error(f"Recall async transcript error: {e}")

    # Strategy 3: media_shortcuts fallback
    try:
        if bot:
            shortcuts = bot.get("media_shortcuts", {})
            transcript_data = shortcuts.get("transcript", {}).get("data", [])
            if transcript_data:
                return transcript_data
    except Exception as e:
        logger.error(f"Recall transcript fallback error: {e}")

    return []


def _get_or_create_async_transcript(recording_id: str) -> list[dict]:
    """Get existing async transcript for a recording, or create one and wait.

    Returns utterance list or [].
    """
    import time

    # Check if a transcript already exists for this recording
    try:
        r = requests.get(
            _url(f"/bot/"),  # We need to find transcript via recording
            headers=_headers(), timeout=15,
        )
    except Exception:
        pass

    # Create async transcript
    try:
        r = requests.post(
            _url(f"/recording/{recording_id}/create_transcript/"),
            json={
                "provider": {"recallai_async": {}},
                "diarization": {"use_separate_streams_when_available": True},
            },
            headers=_headers(),
            timeout=30,
        )
        if not r.ok:
            # Might already exist — check the error
            if "already" in r.text.lower():
                logger.info(f"Async transcript already exists for recording {recording_id}")
            else:
                logger.error(f"create_transcript failed: {r.status_code} {r.text[:200]}")
                return []

        transcript_data = r.json()
        transcript_id = transcript_data.get("id")
        if not transcript_id:
            return []
    except Exception as e:
        logger.error(f"create_transcript error: {e}")
        return []

    # Poll for completion (max 120s)
    for _ in range(24):
        time.sleep(5)
        try:
            r = requests.get(
                _url(f"/transcript/{transcript_id}/"),
                headers=_headers(), timeout=15,
            )
            if not r.ok:
                continue
            data = r.json()
            status = data.get("status", {}).get("code", "")
            if status == "done":
                download_url = data.get("data", {}).get("download_url")
                if download_url:
                    dl = requests.get(download_url, timeout=30)
                    if dl.ok:
                        return dl.json()
                return []
            elif status == "failed":
                logger.error(f"Async transcript failed for recording {recording_id}")
                return []
        except Exception as e:
            logger.error(f"transcript poll error: {e}")

    logger.warning(f"Async transcript timed out for recording {recording_id}")
    return []


def output_audio(bot_id: str, mp3_bytes: bytes) -> bool:
    """Send mp3 audio to a live bot to play in the meeting.

    Returns True on success, False otherwise.
    """
    body = {
        "kind": "mp3",
        "b64_data": base64.b64encode(mp3_bytes).decode("ascii"),
    }
    try:
        r = requests.post(
            _url(f"/bot/{bot_id}/output_audio/"),
            json=body,
            headers=_headers(),
            timeout=30,
        )
    except Exception as e:
        logger.error(f"Recall output_audio error: {e}")
        return False

    if not r.ok:
        logger.error(f"Recall output_audio failed {r.status_code}: {r.text[:200]}")
        return False
    return True


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
