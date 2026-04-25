"""Send 3 ElevenLabs voice samples to MJ via Telegram.

Usage:
    python scripts/voice_samples.py

Picks a fixed shortlist of pre-built voices (calm/measured executive male) by
voice_id. After MJ picks one, set ELEVENLABS_VOICE_ID on Railway.
"""
from __future__ import annotations

import os
import sys
import requests

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import elevenlabs_client

# ElevenLabs prebuilt voices — calm professional male candidates.
# IDs from the public ElevenLabs library (verified at integration time).
CANDIDATES = [
    {"voice_id": "nPczCjzI2devNBz1zQrb", "name": "Brian — calm narrator"},
    {"voice_id": "iP95p4xoKVk53GoZ742B", "name": "Chris — warm advisor"},
    {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh — measured executive"},
]

SAMPLE_TEXT = (
    "Hey Maher, it's Shams. Quick check-in: Brandon's call is in two hours, "
    "and you still owe Richard the LOI from fifty days ago. Want me to draft it?"
)


def send_audio_to_mj(audio_bytes: bytes, caption: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("Telegram not configured", file=sys.stderr)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendVoice"
    r = requests.post(
        url,
        data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption},
        files={"voice": ("sample.ogg", audio_bytes, "audio/ogg")},
        timeout=30,
    )
    if not r.ok:
        # Fall back to sendAudio with mp3 if sendVoice rejects mp3
        url2 = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendAudio"
        r2 = requests.post(
            url2,
            data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption},
            files={"audio": ("sample.mp3", audio_bytes, "audio/mpeg")},
            timeout=30,
        )
        if not r2.ok:
            print(f"Telegram audio send failed: {r2.status_code} {r2.text[:200]}", file=sys.stderr)


def main() -> int:
    if not config.ELEVENLABS_API_KEY:
        print("ELEVENLABS_API_KEY not set", file=sys.stderr)
        return 1

    for c in CANDIDATES:
        print(f"Generating sample for {c['name']} ({c['voice_id']})...")
        mp3 = elevenlabs_client.tts(SAMPLE_TEXT, voice_id=c["voice_id"])
        if not mp3:
            print(f"  failed", file=sys.stderr)
            continue
        send_audio_to_mj(mp3, f"{c['name']} — voice_id: {c['voice_id']}")
        print(f"  sent")
    print("Done. Reply with the voice_id you want, then set ELEVENLABS_VOICE_ID on Railway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
