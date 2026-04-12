"""Media (Jellyfin) tools."""
from __future__ import annotations

from tools.registry import tool


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

    media_type = type
    if media_type == "movie":
        result = media_client.add_movie(title=title, year=year, quality=quality)
    elif media_type == "tv":
        result = media_client.add_tv(title=title, season=season, year=year, quality=quality)
    else:
        result = {"error": f"Unknown media type: {media_type}"}
    return json.dumps(result)
