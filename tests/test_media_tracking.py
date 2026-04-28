from __future__ import annotations

import json

import pytest

import media_client
import memory

pytestmark = pytest.mark.usefixtures("setup_db")


def test_upsert_media_request_records_bridge_id_and_status():
    request_id = memory.upsert_media_request(
        media_type="movie",
        title="_Test Movie",
        bridge_id="radarr:99991",
        year=1984,
        quality="1080p",
        status="searching",
        raw_response={"id": "radarr:99991", "status": "searching"},
    )

    row = memory.get_media_request("radarr:99991")

    assert request_id is not None
    assert row["bridge_id"] == "radarr:99991"
    assert row["media_type"] == "movie"
    assert row["title"] == "_Test Movie"
    assert row["year"] == 1984
    assert row["quality"] == "1080p"
    assert row["last_status"] == "searching"
    assert row["raw_response"]["status"] == "searching"


def test_list_media_requests_returns_recent_first():
    memory.upsert_media_request(
        media_type="movie",
        title="_Downloaded Movie",
        bridge_id="radarr:99992",
        quality="1080p",
        status="downloaded",
    )
    memory.upsert_media_request(
        media_type="movie",
        title="_Searching Movie",
        bridge_id="radarr:99993",
        quality="1080p",
        status="searching",
    )

    rows = memory.list_media_requests(status="searching", limit=5)

    assert any(r["bridge_id"] == "radarr:99993" for r in rows)
    assert all(r["last_status"] == "searching" for r in rows)


def test_add_movie_tracks_media_request(monkeypatch):
    def fake_post(path, payload):
        assert path == "/media/movie"
        assert payload == {"title": "Kubo", "quality": "1080p", "year": 2016}
        return {"id": "radarr:99994", "status": "searching", "title": "Kubo", "quality": "1080p"}

    monkeypatch.setattr(media_client, "_post", fake_post)

    result = media_client.add_movie("Kubo", year=2016, quality="1080p")
    row = memory.get_media_request("radarr:99994")

    assert result["id"] == "radarr:99994"
    assert row["title"] == "Kubo"
    assert row["last_status"] == "searching"


def test_get_status_updates_tracked_request(monkeypatch):
    memory.upsert_media_request(
        media_type="movie",
        title="_Status Movie",
        bridge_id="radarr:99995",
        quality="1080p",
        status="searching",
    )

    def fake_get(path):
        assert path == "/media/status/radarr:99995"
        return {"id": "radarr:99995", "status": "downloaded", "progress": 100.0, "eta_seconds": None}

    monkeypatch.setattr(media_client, "_get", fake_get)

    result = media_client.get_status("radarr:99995")
    row = memory.get_media_request("radarr:99995")

    assert result["status"] == "downloaded"
    assert row["last_status"] == "downloaded"
    assert row["raw_response"]["progress"] == 100.0


def test_format_media_status_message_is_honest_about_searching():
    from tools.media import _format_media_status_message

    message = _format_media_status_message(
        {"title": "The Iron Giant", "last_status": "searching", "bridge_id": "radarr:15"}
    )

    assert "searching" in message.lower()
    assert "not downloading yet" in message.lower()
    assert "downloaded" not in message.lower()


def test_media_tools_registered_after_discovery():
    from tools.registry import _registry, discover_tools

    _registry.clear()
    discover_tools()

    assert "add_media" in _registry
    assert "get_media_status" in _registry
    assert "list_media_requests" in _registry
