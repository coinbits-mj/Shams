# tests/test_meeting_bot.py
from __future__ import annotations

import json
import pytest


class TestRecallClient:
    def test_create_bot_returns_bot_id(self, monkeypatch):
        import recall_client

        def fake_post(url, **kwargs):
            class R:
                ok = True
                status_code = 201
                def json(self):
                    return {"id": "bot-uuid-123", "status_code": "ready"}
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        result = recall_client.create_bot("https://meet.google.com/abc-def-ghi")
        assert result["id"] == "bot-uuid-123"

    def test_create_bot_with_join_at(self, monkeypatch):
        import recall_client

        captured = {}
        def fake_post(url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            class R:
                ok = True
                status_code = 201
                def json(self):
                    return {"id": "bot-456"}
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        recall_client.create_bot("https://meet.google.com/abc", join_at="2026-04-24T14:00:00Z")
        assert captured["json"]["join_at"] == "2026-04-24T14:00:00Z"

    def test_create_bot_failure_returns_none(self, monkeypatch):
        import recall_client

        def fake_post(url, **kwargs):
            class R:
                ok = False
                status_code = 400
                text = "bad request"
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        result = recall_client.create_bot("https://bad-url")
        assert result is None

    def test_get_bot_returns_status(self, monkeypatch):
        import recall_client

        def fake_get(url, **kwargs):
            class R:
                ok = True
                def json(self):
                    return {"id": "bot-123", "status_code": "done", "media_shortcuts": {"transcript": {"data": []}}}
            return R()

        monkeypatch.setattr("requests.get", fake_get)
        result = recall_client.get_bot("bot-123")
        assert result["status_code"] == "done"

    def test_get_transcript_returns_utterances(self, monkeypatch):
        import recall_client

        def fake_get(url, **kwargs):
            class R:
                ok = True
                def json(self):
                    return {"results": [
                        {"speaker": "Brandon", "words": [{"text": "Let's"}, {"text": "start"}]},
                        {"speaker": "Maher", "words": [{"text": "Sounds"}, {"text": "good"}]},
                    ]}
            return R()

        monkeypatch.setattr("requests.get", fake_get)
        result = recall_client.get_transcript("bot-123")
        assert len(result) == 2
        assert result[0]["speaker"] == "Brandon"

    def test_output_audio_posts_b64_mp3(self, monkeypatch):
        import recall_client

        captured = {}
        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            class R:
                ok = True
                status_code = 200
                def json(self):
                    return {"ok": True}
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        ok = recall_client.output_audio("bot-xyz", b"\xff\xfbFAKEMP3")
        assert ok is True
        assert "/bot/bot-xyz/output_audio/" in captured["url"]
        assert captured["json"]["kind"] == "mp3"
        # b64 of bytes — must be a string, not bytes
        assert isinstance(captured["json"]["b64_data"], str)
        assert len(captured["json"]["b64_data"]) > 0

    def test_output_audio_returns_false_on_failure(self, monkeypatch):
        import recall_client

        class R:
            ok = False
            status_code = 500
            text = "boom"

        monkeypatch.setattr("requests.post", lambda *a, **kw: R())
        assert recall_client.output_audio("bot-xyz", b"data") is False


class TestSmartFilter:
    def test_passes_normal_meeting(self):
        import meeting_bot
        event = {
            "summary": "Weekly Standup",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True, "response": "accepted"},
                {"email": "brandon@qcitycoffee.com", "self": False, "response": "accepted"},
            ],
            "hangout_link": "https://meet.google.com/abc-def-ghi",
        }
        assert meeting_bot.should_join(event) is True

    def test_rejects_no_meeting_link(self):
        import meeting_bot
        event = {
            "summary": "Coffee chat",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "friend@gmail.com", "self": False},
            ],
            "hangout_link": "",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_solo_event(self):
        import meeting_bot
        event = {
            "summary": "Focus time",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T16:00:00-04:00",
            "attendees": [{"email": "maher@qcitycoffee.com", "self": True}],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_excluded_title(self):
        import meeting_bot
        event = {
            "summary": "Lunch with friends",
            "start": "2026-04-24T12:00:00-04:00",
            "end": "2026-04-24T13:00:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "friend@gmail.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_declined_event(self):
        import meeting_bot
        event = {
            "summary": "Meeting",
            "start": "2026-04-24T14:00:00-04:00",
            "end": "2026-04-24T14:30:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True, "response": "declined"},
                {"email": "someone@x.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_long_event(self):
        import meeting_bot
        event = {
            "summary": "All-day conference",
            "start": "2026-04-24T09:00:00-04:00",
            "end": "2026-04-24T17:00:00-04:00",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "speaker@conf.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_rejects_all_day_event(self):
        import meeting_bot
        event = {
            "summary": "Company offsite",
            "start": "2026-04-24",
            "end": "2026-04-25",
            "attendees": [
                {"email": "maher@qcitycoffee.com", "self": True},
                {"email": "team@x.com", "self": False},
            ],
            "hangout_link": "https://meet.google.com/abc",
        }
        assert meeting_bot.should_join(event) is False

    def test_extracts_meeting_url_from_hangout_link(self):
        import meeting_bot
        event = {
            "hangout_link": "https://meet.google.com/abc-def-ghi",
            "location": "",
            "description": "",
        }
        assert meeting_bot.extract_meeting_url(event) == "https://meet.google.com/abc-def-ghi"

    def test_extracts_zoom_url_from_description(self):
        import meeting_bot
        event = {
            "hangout_link": "",
            "location": "",
            "description": "Join Zoom: https://us06web.zoom.us/j/123456789?pwd=abc123 some other text",
        }
        url = meeting_bot.extract_meeting_url(event)
        assert url and "zoom.us" in url


class TestMeetingTypeDetection:
    def test_detects_legal_meeting(self):
        import meeting_bot
        attendees = [{"email": "counsel@sewkis.com", "name": "Miller"}]
        assert meeting_bot.detect_meeting_type("FRE 408 Discussion", attendees) == "legal"

    def test_detects_standup(self):
        import meeting_bot
        attendees = [{"email": "brandon@qcitycoffee.com"}]
        assert meeting_bot.detect_meeting_type("Daily Stand-Up", attendees) == "operations"

    def test_detects_deal_meeting(self):
        import meeting_bot
        attendees = [{"email": "richard@rhrcoffee.com"}]
        assert meeting_bot.detect_meeting_type("NDA Review + LOI", attendees) == "deal"

    def test_detects_interview(self):
        import meeting_bot
        attendees = [{"email": "annie@gmail.com"}]
        assert meeting_bot.detect_meeting_type("Annie — Barista Interview", attendees) == "interview"

    def test_defaults_to_general(self):
        import meeting_bot
        attendees = [{"email": "someone@company.com"}]
        assert meeting_bot.detect_meeting_type("Quick sync", attendees) == "general"


class TestProcessTranscript:
    def test_process_builds_summary_and_stores(self, monkeypatch):
        import meeting_bot

        # Mock the LLM call
        def fake_create(**kwargs):
            class Content:
                text = json.dumps({
                    "summary": "Discussed Q2 targets. Brandon will follow up on vendor pricing.",
                    "action_items": [{"assignee": "Brandon", "task": "Follow up on vendor pricing", "deadline": None}],
                    "decisions": [{"decision": "Push Q2 launch to May", "context": "Waiting on vendor"}],
                    "commitments_made": [{"to": "Brandon", "text": "send the pricing sheet", "deadline": "Friday"}],
                    "commitments_resolved": [],
                })
            class Resp:
                content = [Content()]
            return Resp()

        monkeypatch.setattr("anthropic.Anthropic", lambda **kw: type("C", (), {"messages": type("M", (), {"create": staticmethod(fake_create)})()})())

        # Mock DB + delivery
        stored = {}
        monkeypatch.setattr("memory.insert_meeting_notes", lambda data: stored.update(data) or 1)
        monkeypatch.setattr("telegram.send_message", lambda text, **kw: None)

        # Mock _gather_cross_references to avoid DB calls
        monkeypatch.setattr(meeting_bot, "_gather_cross_references", lambda emails: {"emails": {}, "commitments": [], "missions": []})

        # Mock commitments.persist_commitments to avoid DB calls
        import commitments as commitments_mod
        monkeypatch.setattr(commitments_mod, "persist_commitments", lambda **kw: 1)

        # Mock _send_email_summary to avoid needing resend
        monkeypatch.setattr(meeting_bot, "_send_email_summary", lambda notes: None)

        # Mock _send_telegram_summary to avoid DB calls inside it
        monkeypatch.setattr(meeting_bot, "_send_telegram_summary", lambda notes: None)

        result = meeting_bot.process_completed_meeting(
            bot_id="bot-123",
            transcript_text="Brandon: Let's push to May.\nMaher: Agreed. I'll send the pricing sheet by Friday.",
            event_meta={
                "event_id": "evt-1",
                "title": "Weekly Ops",
                "start": "2026-04-24T14:00:00Z",
                "end": "2026-04-24T14:30:00Z",
                "attendees": [{"email": "brandon@qcitycoffee.com", "name": "Brandon"}],
                "platform": "google_meet",
            },
        )
        assert result is not None
        assert stored.get("summary")
        assert len(stored.get("action_items", [])) == 1
