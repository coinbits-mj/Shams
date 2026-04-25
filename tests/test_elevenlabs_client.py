# tests/test_elevenlabs_client.py
from __future__ import annotations

import pytest


class TestElevenLabsTTS:
    def test_tts_returns_mp3_bytes(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        captured = {}

        class R:
            ok = True
            status_code = 200
            content = b"\xff\xfbFAKEMP3DATA"

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            captured["headers"] = kwargs.get("headers", {})
            captured["params"] = kwargs.get("params", {})
            return R()

        monkeypatch.setattr("requests.post", fake_post)

        out = elevenlabs_client.tts("hello world", voice_id="VOICE123")

        assert out == b"\xff\xfbFAKEMP3DATA"
        assert "VOICE123" in captured["url"]
        assert captured["json"]["text"] == "hello world"
        assert captured["json"]["model_id"] == "eleven_flash_v2_5"
        assert captured["headers"]["xi-api-key"] == "fake"
        assert captured["params"]["output_format"].startswith("mp3_")

    def test_tts_returns_none_on_error(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        class R:
            ok = False
            status_code = 500
            text = "server error"
            content = b""

        monkeypatch.setattr("requests.post", lambda *a, **kw: R())
        assert elevenlabs_client.tts("hello", voice_id="X") is None

    def test_tts_returns_none_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        # Should not even attempt the request
        called = {"n": 0}
        def fake_post(*a, **kw):
            called["n"] += 1
            raise AssertionError("should not be called")
        monkeypatch.setattr("requests.post", fake_post)

        assert elevenlabs_client.tts("hello", voice_id="X") is None
        assert called["n"] == 0

    def test_list_voices_returns_list(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        class R:
            ok = True
            def json(self):
                return {"voices": [
                    {"voice_id": "v1", "name": "Brian"},
                    {"voice_id": "v2", "name": "Adam"},
                ]}

        monkeypatch.setattr("requests.get", lambda *a, **kw: R())
        voices = elevenlabs_client.list_voices()
        assert len(voices) == 2
        assert voices[0]["voice_id"] == "v1"

    def test_tts_payload_includes_voice_settings(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        captured = {}

        class R:
            ok = True
            status_code = 200
            content = b"\xff\xfbX"

        def fake_post(url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        elevenlabs_client.tts("hi", voice_id="V")

        vs = captured["json"]["voice_settings"]
        assert vs["stability"] == 0.5
        assert vs["similarity_boost"] == 0.75
        assert vs["style"] == 0.0
        assert vs["use_speaker_boost"] is True

    def test_tts_returns_none_when_voice_id_missing(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "fake")
        monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
        import importlib, config, elevenlabs_client
        importlib.reload(config); importlib.reload(elevenlabs_client)

        called = {"n": 0}
        def fake_post(*a, **kw):
            called["n"] += 1
            raise AssertionError("should not be called")
        monkeypatch.setattr("requests.post", fake_post)

        # No voice_id arg, no env default -> should short-circuit to None
        assert elevenlabs_client.tts("hi") is None
        assert called["n"] == 0
