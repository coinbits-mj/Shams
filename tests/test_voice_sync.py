# tests/test_voice_sync.py
from __future__ import annotations

import importlib
import os


class TestConfig:
    def test_voice_sync_defaults_present(self, monkeypatch):
        for k in (
            "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
            "SYNC_WINDOW_START_UTC", "SYNC_WINDOW_END_UTC",
            "SYNC_SKIP_WEEKENDS", "SYNC_MEET_URL", "SYNC_BOT_NAME",
            "SYNC_PAUSE_SECONDS", "SYNC_REALTIME_TRANSCRIPT_PROVIDER",
            "SYNC_DISABLED",
        ):
            monkeypatch.delenv(k, raising=False)

        import config
        importlib.reload(config)

        assert config.ELEVENLABS_API_KEY == ""
        assert config.ELEVENLABS_VOICE_ID == ""
        assert config.SYNC_WINDOW_START_UTC == 13   # 9am ET
        assert config.SYNC_WINDOW_END_UTC == 15     # 11am ET
        assert config.SYNC_SKIP_WEEKENDS is True
        assert config.SYNC_MEET_URL == ""
        assert config.SYNC_BOT_NAME == "Shams"
        assert config.SYNC_PAUSE_SECONDS == 1.5
        assert config.SYNC_REALTIME_TRANSCRIPT_PROVIDER == "deepgram_streaming"
        assert config.SYNC_DISABLED is False
