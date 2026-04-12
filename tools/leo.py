"""Leo (health data) tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_leo_health_summary",
    description="Get Maher's latest health data from Leo — weight, sleep, HRV, readiness, glucose, calories, steps, streak, today's meals.",
    agent="leo",
    schema={
        "properties": {},
    },
)
def get_leo_health_summary() -> str:
    import json
    import leo_client

    result = leo_client.get_health_summary()
    return json.dumps(result, indent=2, default=str) if result else "Leo unavailable."


@tool(
    name="get_leo_trends",
    description="Get Maher's 7-day health trends from Leo — daily weight, sleep, HRV, calories, steps.",
    agent="leo",
    schema={
        "properties": {},
    },
)
def get_leo_trends() -> str:
    import json
    import leo_client

    result = leo_client.get_trends()
    return json.dumps(result, indent=2, default=str) if result else "Leo unavailable."
