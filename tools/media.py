"""Media server tools for Shams.

These tools submit requests to the media bridge and expose honest status checks.
A bridge response of "searching" means Radarr/Sonarr accepted the request, not
that a download has started yet.
"""
from __future__ import annotations

import json

from tools.registry import tool


def _format_media_status_message(row: dict) -> str:
    """Return a user-facing, non-overconfident media status sentence."""
    title = row.get("title") or row.get("id") or row.get("bridge_id") or "Unknown title"
    bridge_id = row.get("bridge_id") or row.get("id", "")
    status = (row.get("last_status") or row.get("status") or "unknown").lower()
    raw = row.get("raw_response") or row
    progress = raw.get("progress")
    eta = raw.get("eta_seconds")

    suffix = f" ({bridge_id})" if bridge_id else ""
    if status == "downloaded":
        return f"{title}{suffix}: downloaded. If it is not visible in Jellyfin yet, trigger or wait for a library scan."
    if status == "downloading":
        detail = f" — {progress}%" if progress is not None else ""
        if eta:
            detail += f", ETA ~{int(eta // 60)} min"
        return f"{title}{suffix}: downloading{detail}."
    if status == "searching":
        return f"{title}{suffix}: searching — Radarr/Sonarr accepted it, but it is not downloading yet. It may need a better release/indexer result or a manual retry."
    if status in {"queued", "importing"}:
        return f"{title}{suffix}: {status}."
    return f"{title}{suffix}: status is {status}."


def _find_request(identifier: str) -> dict | None:
    import memory

    row = memory.get_media_request(identifier)
    if row:
        return dict(row)
    return None


@tool(
    name="add_media",
    description=(
        "Request a movie or TV show be added to the media server. Returns when Radarr/Sonarr accepts the request; "
        "download happens asynchronously. If status is 'searching', tell the user it is not downloading yet."
    ),
    schema={
        "properties": {
            "type": {"type": "string", "enum": ["movie", "tv"], "description": "'movie' or 'tv'"},
            "title": {"type": "string", "description": "Title of the movie or show"},
            "year": {"type": "integer", "description": "Optional release year; disambiguates remakes"},
            "season": {"type": "integer", "description": "Optional season number (TV only)"},
            "quality": {"type": "string", "enum": ["1080p", "2160p"], "description": "Preferred quality; default 1080p"},
        },
        "required": ["type", "title"],
    },
)
def add_media(type: str, title: str, year: int = None, season: int = None, quality: str = "1080p") -> str:
    import media_client

    media_type = type
    if media_type == "movie":
        result = media_client.add_movie(title=title, year=year, quality=quality)
    elif media_type == "tv":
        result = media_client.add_tv(title=title, season=season, year=year, quality=quality)
    else:
        return json.dumps({"error": f"Unknown media type: {media_type}"})

    status_line = _format_media_status_message({
        "bridge_id": result.get("id"),
        "title": result.get("title", title),
        "last_status": result.get("status", "unknown"),
        "raw_response": result,
    })
    return json.dumps({**result, "status_message": status_line})


@tool(
    name="get_media_status",
    description=(
        "Check the latest status for a media request by bridge id (radarr:18) or title. "
        "Use this when the user asks why something has not downloaded or whether media is ready."
    ),
    schema={
        "properties": {
            "id_or_title": {"type": "string", "description": "Bridge id like radarr:18, or a title substring"},
        },
        "required": ["id_or_title"],
    },
)
def get_media_status(id_or_title: str) -> str:
    import media_client

    row = _find_request(id_or_title)
    if not row:
        return json.dumps({"error": f"No tracked media request found for: {id_or_title}"})

    bridge_id = row["bridge_id"]
    try:
        live = media_client.get_status(bridge_id)
        row["last_status"] = live.get("status", row.get("last_status", "unknown"))
        row["raw_response"] = live
    except Exception as e:
        row["status_error"] = str(e)

    return json.dumps({**row, "status_message": _format_media_status_message(row)}, default=str)


@tool(
    name="list_media_requests",
    description=(
        "List recent media requests and their known statuses. Useful for questions like 'what downloads are stuck?' "
        "or 'what did I request recently?'"
    ),
    schema={
        "properties": {
            "status": {"type": "string", "description": "Optional status filter, e.g. searching, downloading, downloaded"},
            "limit": {"type": "integer", "description": "Max rows to return; default 20"},
        },
    },
)
def list_media_requests(status: str = None, limit: int = 20) -> str:
    import memory

    rows = [dict(r) for r in memory.list_media_requests(status=status, limit=limit)]
    for row in rows:
        row["status_message"] = _format_media_status_message(row)
    return json.dumps({"requests": rows}, default=str)
