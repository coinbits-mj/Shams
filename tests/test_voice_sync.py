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


class TestTurnDetection:
    def test_buffer_partial_words(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-t1")

        # Frozen "now" so the test isn't time-flaky.
        now = {"t": 100.0}
        monkeypatch.setattr(voice_sync.time, "monotonic", lambda: now["t"])

        voice_sync.buffer_words("bot-t1", "hey", is_final=False)
        now["t"] += 0.2
        voice_sync.buffer_words("bot-t1", "shams", is_final=False)

        s = voice_sync.get_session("bot-t1")
        assert s["pending_words"] == ["hey", "shams"]
        assert voice_sync.is_turn_complete("bot-t1") is False

    def test_turn_complete_after_silence(self, monkeypatch):
        import voice_sync, config
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-t2")

        now = {"t": 200.0}
        monkeypatch.setattr(voice_sync.time, "monotonic", lambda: now["t"])

        voice_sync.buffer_words("bot-t2", "what's", is_final=True)
        voice_sync.buffer_words("bot-t2", "next", is_final=True)
        # Advance just past the configured pause threshold
        now["t"] += config.SYNC_PAUSE_SECONDS + 0.1
        assert voice_sync.is_turn_complete("bot-t2") is True

    def test_drain_pending_returns_text_and_clears(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-t3")
        monkeypatch.setattr(voice_sync.time, "monotonic", lambda: 50.0)

        voice_sync.buffer_words("bot-t3", "hello", is_final=True)
        voice_sync.buffer_words("bot-t3", "there", is_final=True)
        text = voice_sync.drain_pending("bot-t3")
        assert text == "hello there"
        assert voice_sync.get_session("bot-t3")["pending_words"] == []

    def test_is_turn_complete_false_when_no_words(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-t4")
        monkeypatch.setattr(voice_sync.time, "monotonic", lambda: 0.0)
        assert voice_sync.is_turn_complete("bot-t4") is False


class TestLiveContext:
    def test_extract_mentioned_first_names(self):
        import voice_sync
        names = voice_sync.extract_mentioned_names(
            "tell brandon and Adam I'll send the LOI to richard tomorrow"
        )
        assert "brandon" in [n.lower() for n in names]
        assert "adam" in [n.lower() for n in names]
        assert "richard" in [n.lower() for n in names]
        # Stopwords filtered
        assert "i'll" not in [n.lower() for n in names]
        assert "the" not in [n.lower() for n in names]

    def test_build_live_context_pulls_calendar_and_commitments(self, monkeypatch):
        import voice_sync

        monkeypatch.setattr(voice_sync, "_get_remaining_today", lambda: [
            {"summary": "Brandon", "start": "2026-04-25T18:00:00Z"},
        ])
        monkeypatch.setattr(voice_sync, "_get_overdue_commitments", lambda: [
            {"to": "richard@x.com", "text": "send LOI", "days_old": 50},
        ])
        monkeypatch.setattr(voice_sync, "_get_recent_emails_for_names", lambda names: {
            "brandon": [{"from": "brandon@qcc", "subject": "Tomorrow"}],
        })

        ctx = voice_sync.build_live_context(utterance="anything from brandon?")
        assert "Brandon" in ctx["calendar_today"][0]["summary"]
        assert ctx["overdue_commitments"][0]["days_old"] == 50
        assert "brandon" in ctx["mentioned_emails"]

    def test_format_context_for_prompt_is_concise(self, monkeypatch):
        import voice_sync
        ctx = {
            "calendar_today": [{"summary": "Brandon", "start": "2026-04-25T18:00:00Z"}],
            "overdue_commitments": [{"to": "richard@x.com", "text": "send LOI", "days_old": 50}],
            "mentioned_emails": {},
        }
        text = voice_sync.format_context_for_prompt(ctx)
        assert "Brandon" in text
        assert "50" in text  # days_old
        assert len(text) < 1500  # Live conversations want short context

    def test_format_context_empty_returns_empty(self):
        import voice_sync
        assert voice_sync.format_context_for_prompt({}) == ""
        assert voice_sync.format_context_for_prompt({
            "calendar_today": [],
            "overdue_commitments": [],
            "mentioned_emails": {},
        }) == ""

    def test_extract_filters_voice_filler_and_verbs(self):
        import voice_sync
        names = voice_sync.extract_mentioned_names(
            "how are you doing today, going to talk to brandon about the deal"
        )
        # Brandon comes through; common voice filler does NOT
        lower = [n.lower() for n in names]
        assert "brandon" in lower
        for noise in ("you", "doing", "today", "going", "talk", "about", "the", "deal"):
            assert noise not in lower, f"{noise!r} leaked through stopwords"


class TestClaudeTurn:
    def test_process_user_turn_calls_claude_with_history_and_context(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-c1")
        voice_sync.append_user_turn("bot-c1", "earlier msg")
        voice_sync.append_assistant_turn("bot-c1", "earlier reply")

        captured = {}

        class FakeMsg:
            content = [type("X", (), {"text": "Brandon at 2pm. Anything else?"})()]

        class FakeAPI:
            class messages:
                @staticmethod
                def create(**kw):
                    captured.update(kw)
                    return FakeMsg()

        monkeypatch.setattr(voice_sync, "_anthropic_client", lambda: FakeAPI())
        monkeypatch.setattr(voice_sync, "build_live_context", lambda utterance: {
            "calendar_today": [{"summary": "Brandon", "start": "2026-04-25T18:00:00Z"}],
            "overdue_commitments": [],
            "mentioned_emails": {},
        })

        reply = voice_sync.process_user_turn("bot-c1", "what's next?")

        assert reply == "Brandon at 2pm. Anything else?"
        # System contains both the personality and the live context
        sys_msg = captured["system"]
        assert "chief of staff" in sys_msg.lower()
        assert "Brandon" in sys_msg
        # History was passed including the new user turn
        msgs = captured["messages"]
        assert msgs[-1] == {"role": "user", "content": "what's next?"}
        assert any(m["content"] == "earlier reply" for m in msgs)

    def test_process_user_turn_truncates_long_reply(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-c2")

        long_reply = " ".join(f"Sentence number {i}." for i in range(1, 12))

        class FakeMsg:
            content = [type("X", (), {"text": long_reply})()]

        class FakeAPI:
            class messages:
                @staticmethod
                def create(**kw):
                    return FakeMsg()

        monkeypatch.setattr(voice_sync, "_anthropic_client", lambda: FakeAPI())
        monkeypatch.setattr(voice_sync, "build_live_context", lambda u: {
            "calendar_today": [], "overdue_commitments": [], "mentioned_emails": {}
        })

        reply = voice_sync.process_user_turn("bot-c2", "ramble please")
        assert reply.count(".") <= 3

    def test_process_user_turn_passive_mode_returns_none_unless_addressed(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-c3")
        voice_sync.set_mode("bot-c3", "passive")

        class FakeAPI:
            class messages:
                @staticmethod
                def create(**kw):
                    raise AssertionError("Claude should not be called in passive mode unless addressed")

        monkeypatch.setattr(voice_sync, "_anthropic_client", lambda: FakeAPI())
        monkeypatch.setattr(voice_sync, "build_live_context", lambda u: {
            "calendar_today": [], "overdue_commitments": [], "mentioned_emails": {}
        })

        # Not addressed
        assert voice_sync.process_user_turn("bot-c3", "thinking out loud here") is None
        # Addressed by name → speak
        # Need to allow the call now
        called = {"n": 0}
        class FakeMsg:
            content = [type("X", (), {"text": "yes?"})()]
        class FakeAPI2:
            class messages:
                @staticmethod
                def create(**kw):
                    called["n"] += 1
                    return FakeMsg()
        monkeypatch.setattr(voice_sync, "_anthropic_client", lambda: FakeAPI2())
        reply = voice_sync.process_user_turn("bot-c3", "shams what time is it")
        assert reply == "yes?"
        assert called["n"] == 1
