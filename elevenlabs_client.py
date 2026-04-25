"""ElevenLabs TTS client — text → mp3 bytes via Flash v2.5."""
from __future__ import annotations

import logging
import requests

import config

logger = logging.getLogger(__name__)

_BASE = "https://api.elevenlabs.io/v1"


def _headers() -> dict:
    return {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }


def tts(
    text: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    output_format: str = "mp3_44100_128",
) -> bytes | None:
    """Convert text to mp3 bytes. Returns None on failure or missing API key."""
    if not config.ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY not set — TTS disabled")
        return None

    voice = voice_id or config.ELEVENLABS_VOICE_ID
    if not voice:
        logger.error("No voice_id provided and ELEVENLABS_VOICE_ID not set")
        return None

    body = {
        "text": text,
        "model_id": model_id or config.ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    try:
        r = requests.post(
            f"{_BASE}/text-to-speech/{voice}",
            json=body,
            headers=_headers(),
            params={"output_format": output_format},
            timeout=30,
        )
    except Exception as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        return None

    if not r.ok:
        logger.error(f"ElevenLabs TTS failed {r.status_code}: {r.text[:300]}")
        return None

    return r.content


def list_voices() -> list[dict]:
    """List voices available on the ElevenLabs account."""
    if not config.ELEVENLABS_API_KEY:
        return []
    try:
        r = requests.get(f"{_BASE}/voices", headers=_headers(), timeout=15)
    except Exception as e:
        logger.error(f"ElevenLabs list_voices error: {e}")
        return []
    if not r.ok:
        logger.error(f"ElevenLabs list_voices failed {r.status_code}: {r.text[:200]}")
        return []
    return r.json().get("voices", [])
