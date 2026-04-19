"""Media (Jellyfin) tools."""
from __future__ import annotations

from tools.registry import tool


def _bridge_id_from_result(result: dict) -> str | None:
    for key in ("id", "media_id", "bridge_id"):
        val = result.get(key)
        if val is not None:
            return str(val)
    return None


def _humanize_eta(seconds):
    if seconds is None:
        return None
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h{minutes}m" if minutes else f"{hours}h"


@tool(
    name="add_media",
    description="Request a movie or TV show be downloaded into the user's Jellyfin library. Use when the user asks for media by name. Returns once the request is accepted (download happens asynchronously).",
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
    import json
    import media_client
    import memory

    media_type = type
    if media_type == "movie":
        result = media_client.add_movie(title=title, year=year, quality=quality)
    elif media_type == "tv":
        result = media_client.add_tv(title=title, season=season, year=year, quality=quality)
    else:
        return json.dumps({"error": f"Unknown media type: {media_type}"})

    bridge_id = _bridge_id_from_result(result) if isinstance(result, dict) else None
    status = (result.get("status") if isinstance(result, dict) else None) or "requested"
    try:
        download_id = memory.record_media_download(
            media_type=media_type,
            title=result.get("title", title) if isinstance(result, dict) else title,
            bridge_id=bridge_id,
            year=year,
            season=season,
            quality=quality,
            status=status,
        )
        result = dict(result) if isinstance(result, dict) else {"title": title}
        result["tracking_id"] = download_id
    except Exception as e:
        result = dict(result) if isinstance(result, dict) else {"title": title}
        result["tracking_error"] = str(e)

    return json.dumps(result)


@tool(
    name="list_downloads",
    description="List media (movies, TV) that MJ has asked to download, with current bridge status and progress. Use when MJ asks what's downloading, what's pending, or whether a title is ready.",
    schema={
        "properties": {
            "include_completed": {
                "type": "boolean",
                "description": "If true, include recently completed/failed items. Defaults to false (active downloads only).",
            },
            "limit": {"type": "integer", "description": "Max items to return when include_completed is true. Defaults to 20."},
        },
        "required": [],
    },
)
def list_downloads(include_completed: bool = False, limit: int = 20) -> str:
    import json
    import media_client
    import memory

    if include_completed:
        rows = memory.get_recent_media_downloads(limit=limit)
    else:
        rows = memory.get_active_media_downloads()

    items = []
    for row in rows:
        item = {
            "tracking_id": row["id"],
            "title": row["title"],
            "type": row["media_type"],
            "quality": row.get("quality"),
            "year": row.get("year"),
            "season": row.get("season"),
            "status": row.get("status"),
            "progress_pct": row.get("progress_pct"),
            "eta": _humanize_eta(row.get("eta_seconds")),
            "requested_at": row["requested_at"].isoformat() if row.get("requested_at") else None,
            "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
        }
        # Live refresh from the bridge if we have a bridge id and it's active
        if row.get("bridge_id") and row.get("status", "").lower() not in {
            "downloaded", "ready", "completed", "imported", "failed", "canceled",
        }:
            try:
                live = media_client.get_status(row["bridge_id"])
                item["live"] = live
            except Exception as e:
                item["live_error"] = str(e)
        items.append(item)

    return json.dumps({"count": len(items), "items": items})
