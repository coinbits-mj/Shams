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
