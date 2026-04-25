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

    def test_passive_mode_question_without_shams_is_silent(self, monkeypatch):
        """Bare question mark in passive mode must NOT wake Shams."""
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-c4")
        voice_sync.set_mode("bot-c4", "passive")

        class FakeAPI:
            class messages:
                @staticmethod
                def create(**kw):
                    raise AssertionError("Claude should not be called for non-wake-word question")

        monkeypatch.setattr(voice_sync, "_anthropic_client", lambda: FakeAPI())
        monkeypatch.setattr(voice_sync, "build_live_context", lambda u: {
            "calendar_today": [], "overdue_commitments": [], "mentioned_emails": {}
        })

        # Question to a teammate, NOT addressed to Shams
        assert voice_sync.process_user_turn("bot-c4", "do you have that report ready?") is None


class TestSpeak:
    def test_speak_calls_tts_then_output_audio(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-s1")

        captured = {"tts_text": None, "audio_bot": None, "audio_bytes": None}

        def fake_tts(text, voice_id=None):
            captured["tts_text"] = text
            return b"\xff\xfbMP3"

        def fake_output_audio(bot_id, mp3_bytes):
            captured["audio_bot"] = bot_id
            captured["audio_bytes"] = mp3_bytes
            return True

        monkeypatch.setattr(voice_sync, "_tts", fake_tts)
        monkeypatch.setattr(voice_sync, "_output_audio", fake_output_audio)

        ok = voice_sync.speak("bot-s1", "hello mj")
        assert ok is True
        assert captured["tts_text"] == "hello mj"
        assert captured["audio_bot"] == "bot-s1"
        assert captured["audio_bytes"] == b"\xff\xfbMP3"

    def test_speak_returns_false_when_tts_fails(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-s2")

        monkeypatch.setattr(voice_sync, "_tts", lambda text, voice_id=None: None)
        monkeypatch.setattr(voice_sync, "_output_audio", lambda *a, **kw: True)

        assert voice_sync.speak("bot-s2", "hi") is False

    def test_speak_marks_session_speaking_then_clears(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-s3")

        seen_speaking = []

        def fake_tts(text, voice_id=None):
            seen_speaking.append(voice_sync.get_session("bot-s3")["speaking"])
            return b"X"

        monkeypatch.setattr(voice_sync, "_tts", fake_tts)
        monkeypatch.setattr(voice_sync, "_output_audio", lambda *a, **kw: True)

        voice_sync.speak("bot-s3", "hi")
        # While TTS was running, speaking was True; afterwards it's False
        assert seen_speaking == [True]
        assert voice_sync.get_session("bot-s3")["speaking"] is False


class TestWebhookGlue:
    def _payload(self, bot_id, text, is_final=True, speaker="Maher"):
        return {
            "event": "transcript.data",
            "data": {
                "bot": {"id": bot_id},
                "data": {
                    "words": [{"text": w} for w in text.split()],
                    "participant": {"name": speaker},
                    "is_final": is_final,
                },
            },
        }

    def test_buffers_partial_does_not_speak(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-w1")

        spoken = []
        monkeypatch.setattr(voice_sync, "process_user_turn", lambda *a, **kw: "should not be called")
        monkeypatch.setattr(voice_sync, "speak", lambda *a, **kw: spoken.append(a) or True)
        monkeypatch.setattr(voice_sync, "is_turn_complete", lambda bot_id: False)

        voice_sync.handle_realtime_event(self._payload("bot-w1", "hey there", is_final=False))

        assert voice_sync.get_session("bot-w1")["pending_words"] == ["hey there"]
        assert spoken == []

    def test_full_turn_triggers_claude_then_speak(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-w2")

        # Stage: pre-fill buffer, then signal turn-complete
        monkeypatch.setattr(voice_sync, "is_turn_complete", lambda bot_id: True)

        seen = {"utterance": None, "spoken": None}

        def fake_process(bot_id, utterance):
            seen["utterance"] = utterance
            return "ok got it"

        def fake_speak(bot_id, text):
            seen["spoken"] = (bot_id, text)
            return True

        monkeypatch.setattr(voice_sync, "process_user_turn", fake_process)
        monkeypatch.setattr(voice_sync, "speak", fake_speak)

        voice_sync.handle_realtime_event(
            self._payload("bot-w2", "what's next on calendar", is_final=True)
        )

        assert seen["utterance"] == "what's next on calendar"
        assert seen["spoken"] == ("bot-w2", "ok got it")

    def test_ignores_non_mj_speakers(self, monkeypatch):
        """When MJ adds someone to the call, only MJ's utterances drive Shams turns."""
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-w3")

        monkeypatch.setattr(voice_sync, "is_turn_complete", lambda bot_id: True)
        called = {"speak": 0}
        monkeypatch.setattr(voice_sync, "process_user_turn", lambda *a, **kw: "x")
        monkeypatch.setattr(voice_sync, "speak", lambda *a, **kw: called.__setitem__("speak", called["speak"] + 1) or True)

        # Speaker that's not MJ → ignore
        voice_sync.handle_realtime_event(
            self._payload("bot-w3", "hi shams", is_final=True, speaker="Brandon")
        )
        assert called["speak"] == 0

    def test_unknown_bot_id_is_ignored(self):
        import voice_sync
        voice_sync._SESSIONS.clear()
        # Should not raise even though no session exists
        voice_sync.handle_realtime_event({
            "event": "transcript.data",
            "data": {"bot": {"id": "nope"}, "data": {"words": [{"text": "hi"}]}},
        })

    def test_empty_drained_text_does_not_call_claude(self, monkeypatch):
        import voice_sync
        voice_sync._SESSIONS.clear()
        voice_sync.create_session("bot-w5")

        monkeypatch.setattr(voice_sync, "is_turn_complete", lambda bot_id: True)
        monkeypatch.setattr(voice_sync, "drain_pending", lambda bot_id: "")

        called = {"n": 0}
        monkeypatch.setattr(voice_sync, "process_user_turn", lambda *a, **kw: called.__setitem__("n", called["n"]+1) or "x")
        monkeypatch.setattr(voice_sync, "speak", lambda *a, **kw: True)

        voice_sync.handle_realtime_event({
            "event": "transcript.data",
            "data": {"bot": {"id": "bot-w5"}, "data": {"words": [], "participant": {"name": "Maher"}, "is_final": True}},
        })
        assert called["n"] == 0


class TestRealtimeEndpoint:
    def test_realtime_endpoint_dispatches_to_handler(self, monkeypatch):
        import app as shams_app, voice_sync

        seen = {"payload": None}
        # Patch the module-scope helper that the route invokes synchronously
        # so we don't need to wait for a background thread in the test.
        def fake_run(p):
            seen["payload"] = p
        monkeypatch.setattr(shams_app, "_run_realtime_handler", fake_run)
        # Make Thread call the target inline so observation is synchronous.
        class InlineThread:
            def __init__(self, target=None, args=(), daemon=None, **kw):
                self._target = target
                self._args = args
            def start(self):
                self._target(*self._args)
        monkeypatch.setattr("app.threading.Thread", InlineThread, raising=False)

        client = shams_app.app.test_client()
        body = {"event": "transcript.data", "data": {"bot": {"id": "bot-rt"}, "data": {"words": [{"text": "hi"}]}}}
        r = client.post("/api/recall/realtime", json=body)

        assert r.status_code == 200
        assert seen["payload"]["event"] == "transcript.data"

    def test_realtime_endpoint_returns_200_even_on_handler_error(self, monkeypatch):
        import app as shams_app

        def boom(p): raise RuntimeError("kaboom")

        # Patch the inline helper to raise — exception MUST not escape the route.
        monkeypatch.setattr(shams_app, "_run_realtime_handler", boom)
        # Make threading.Thread inline so the exception happens inside the request.
        class InlineThread:
            def __init__(self, target=None, args=(), daemon=None, **kw):
                self._target = target
                self._args = args
            def start(self):
                self._target(*self._args)
        monkeypatch.setattr("app.threading.Thread", InlineThread, raising=False)

        client = shams_app.app.test_client()
        r = client.post("/api/recall/realtime", json={"event": "x", "data": {}})
        # Recall retries 4xx/5xx — we always 200 to drain the queue
        assert r.status_code == 200


class TestSmartPing:
    def test_in_window_default_9_to_11_et(self, monkeypatch):
        import voice_sync
        from datetime import datetime, timezone

        # 13:30 UTC = 9:30 ET (during DST). Adjust per SYNC_WINDOW_*_UTC default 13–15.
        assert voice_sync._in_window(datetime(2026, 4, 25, 13, 30, tzinfo=timezone.utc)) is True
        assert voice_sync._in_window(datetime(2026, 4, 25, 12, 30, tzinfo=timezone.utc)) is False
        assert voice_sync._in_window(datetime(2026, 4, 25, 15, 30, tzinfo=timezone.utc)) is False

    def test_skip_weekends_when_enabled(self, monkeypatch):
        import voice_sync, config
        from datetime import datetime, timezone
        monkeypatch.setattr(config, "SYNC_SKIP_WEEKENDS", True)
        # 2026-04-25 is a Saturday
        assert voice_sync._is_weekend(datetime(2026, 4, 25, 14, 0, tzinfo=timezone.utc)) is True
        # 2026-04-27 is a Monday
        assert voice_sync._is_weekend(datetime(2026, 4, 27, 14, 0, tzinfo=timezone.utc)) is False

    def test_pinged_today_flag_blocks_repeat(self, monkeypatch):
        import voice_sync
        memory_calls = {}
        monkeypatch.setattr(voice_sync, "_recall", lambda key: "1" if key.startswith("sync_pinged_") else None)
        assert voice_sync._already_pinged_today("2026-04-25") is True
        monkeypatch.setattr(voice_sync, "_recall", lambda key: None)
        assert voice_sync._already_pinged_today("2026-04-25") is False

    def test_calendar_block_free_no_event_in_30min(self, monkeypatch):
        import voice_sync
        from datetime import datetime, timezone, timedelta

        now = datetime(2026, 4, 27, 14, 0, tzinfo=timezone.utc)

        # Event starts in 45 min → block free
        monkeypatch.setattr(voice_sync, "_get_remaining_today", lambda: [
            {"summary": "Brandon", "start": (now + timedelta(minutes=45)).isoformat()}
        ])
        assert voice_sync._next_30min_free(now) is True

        # Event starts in 20 min → block NOT free
        monkeypatch.setattr(voice_sync, "_get_remaining_today", lambda: [
            {"summary": "Brandon", "start": (now + timedelta(minutes=20)).isoformat()}
        ])
        assert voice_sync._next_30min_free(now) is False

    def test_should_ping_combines_all_conditions(self, monkeypatch):
        import voice_sync, config
        from datetime import datetime, timezone

        now = datetime(2026, 4, 27, 14, 0, tzinfo=timezone.utc)  # Mon 10am ET, in window

        monkeypatch.setattr(config, "SYNC_DISABLED", False)
        monkeypatch.setattr(config, "SYNC_MEET_URL", "https://meet.google.com/xyz")
        monkeypatch.setattr(voice_sync, "_already_pinged_today", lambda d: False)
        monkeypatch.setattr(voice_sync, "_next_30min_free", lambda n: True)

        assert voice_sync.should_ping(now=now) is True

        # Disable
        monkeypatch.setattr(config, "SYNC_DISABLED", True)
        assert voice_sync.should_ping(now=now) is False
