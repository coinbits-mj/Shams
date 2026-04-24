# tools/meeting_tools.py
"""Claude tool for querying Shams's meeting notes archive."""
from __future__ import annotations

import json
import memory
from tools.registry import tool


@tool(
    name="search_meeting_notes",
    description="Search past meeting recordings and summaries. Find what was discussed, decided, or assigned in any meeting Shams attended.",
    agent=None,
    schema={
        "properties": {
            "query": {"type": "string", "description": "Free-text search (matches transcript + summary)"},
            "attendee": {"type": "string", "description": "Filter by attendee name or email"},
            "meeting_type": {"type": "string", "enum": ["legal", "operations", "deal", "interview", "general"]},
            "since": {"type": "string", "description": "ISO date — only meetings on/after this date"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": [],
    },
)
def search_meeting_notes_tool(query: str = "", attendee: str = "", meeting_type: str = "",
                              since: str = "", limit: int = 5) -> str:
    limit = max(1, min(int(limit or 5), 20))
    results = memory.search_meeting_notes(
        query=query, attendee=attendee, meeting_type=meeting_type,
        since=since, limit=limit,
    )
    if not results:
        return "No meeting notes match that search."
    lines = [f"Found {len(results)} meeting(s):"]
    for r in results:
        started = str(r.get("started_at", ""))[:16]
        title = r.get("title", "?")
        mtype = r.get("meeting_type", "?")
        dur = r.get("duration_min") or "?"
        summary = (r.get("summary") or "")[:200]
        actions = r.get("action_items") or []
        if isinstance(actions, str):
            actions = json.loads(actions)
        lines.append(f"\n{title} ({started}, {dur}min, {mtype})")
        lines.append(f"  {summary}")
        if actions:
            lines.append(f"  Action items: {len(actions)}")
            for a in actions[:3]:
                if isinstance(a, dict):
                    lines.append(f"    - {a.get('assignee','?')}: {a.get('task','')}")
    return "\n".join(lines)
