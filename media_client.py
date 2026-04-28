"""HTTP client for the shams-media-bridge service."""

import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional

import httpx

BRIDGE_BASE_URL = os.environ.get("BRIDGE_BASE_URL", "https://media-bridge.myshams.ai")
BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY", "")
BRIDGE_HMAC_SECRET = os.environ.get("BRIDGE_HMAC_SECRET", "").encode()


class MediaClientError(Exception):
    pass


def _signed_headers(body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(BRIDGE_HMAC_SECRET, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BRIDGE_API_KEY}",
        "X-Shams-Timestamp": ts,
        "X-Shams-Signature": sig,
    }


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    r = httpx.post(f"{BRIDGE_BASE_URL}{path}", content=body, headers=_signed_headers(body), timeout=30)
    if r.status_code >= 400:
        raise MediaClientError(f"{r.status_code}: {r.text}")
    return r.json()


def _get(path: str) -> dict[str, Any]:
    r = httpx.get(f"{BRIDGE_BASE_URL}{path}", headers=_signed_headers(b""), timeout=15)
    if r.status_code >= 400:
        raise MediaClientError(f"{r.status_code}: {r.text}")
    return r.json()


def _track_request(media_type: str, result: dict[str, Any],
                   year: Optional[int] = None, season: Optional[int] = None) -> None:
    """Persist bridge IDs so Shams can check status later."""
    bridge_id = result.get("id")
    if not bridge_id:
        return
    try:
        import memory
        memory.upsert_media_request(
            media_type=media_type,
            title=result.get("title", ""),
            bridge_id=bridge_id,
            year=year,
            season=season,
            quality=result.get("quality", "1080p"),
            status=result.get("status", "unknown"),
            raw_response=result,
        )
    except Exception:
        # Never fail the user-facing media request because tracking failed.
        pass


def add_movie(title: str, year: Optional[int] = None, quality: str = "1080p") -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title, "quality": quality}
    if year is not None:
        payload["year"] = year
    result = _post("/media/movie", payload)
    _track_request("movie", result, year=year)
    return result


def add_tv(title: str, season: Optional[int] = None, year: Optional[int] = None, quality: str = "1080p") -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title, "quality": quality}
    if season is not None:
        payload["season"] = season
    if year is not None:
        payload["year"] = year
    result = _post("/media/tv", payload)
    _track_request("tv", result, year=year, season=season)
    return result


def get_status(media_id: str) -> dict[str, Any]:
    result = _get(f"/media/status/{media_id}")
    try:
        import memory
        memory.update_media_request_status(
            media_id,
            result.get("status", "unknown"),
            raw_response=result,
        )
    except Exception:
        pass
    return result


def delete(media_id: str, delete_files: bool = True) -> dict[str, Any]:
    return _post("/media/delete", {"id": media_id, "delete_files": delete_files})
