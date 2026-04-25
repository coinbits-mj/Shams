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


class TestSession:
    def test_create_and_get_session(self):
        import voice_sync
        voice_sync._SESSIONS.clear()

        s = voice_sync.create_session("bot-1")
        assert s["bot_id"] == "bot-1"
        assert s["mode"] == "active"
        assert s["history"] == []
        assert s["pending_words"] == []

        again = voice_sync.get_session("bot-1")
        assert again is s

    def test_append_user_and_assistant_turns(self):
        import voice_sync
        voice_sync._SESSIONS.clear()

        voice_sync.create_session("bot-2")
        voice_sync.append_user_turn("bot-2", "what's on my calendar?")
        voice_sync.append_assistant_turn("bot-2", "Brandon at 2pm.")

        h = voice_sync.get_session("bot-2")["history"]
        assert h == [
            {"role": "user", "content": "what's on my calendar?"},
            {"role": "assistant", "content": "Brandon at 2pm."},
        ]

    def test_end_session_removes_state(self):
        import voice_sync
        voice_sync._SESSIONS.clear()

        voice_sync.create_session("bot-3")
        voice_sync.end_session("bot-3")
        assert voice_sync.get_session("bot-3") is None

    def test_set_mode_passive(self):
        import voice_sync
        voice_sync._SESSIONS.clear()

        voice_sync.create_session("bot-4")
        voice_sync.set_mode("bot-4", "passive")
        assert voice_sync.get_session("bot-4")["mode"] == "passive"
