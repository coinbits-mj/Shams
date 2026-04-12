"""Memory (remember, open loops, decisions) tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="remember",
    description="Save a piece of information to persistent memory. Use this when Maher tells you something important to remember, or when you learn something that should persist across conversations.",
    schema={
        "properties": {
            "key": {"type": "string", "description": "Short key/label for the memory"},
            "value": {"type": "string", "description": "The information to remember"},
        },
        "required": ["key", "value"],
    },
)
def remember(key: str, value: str) -> str:
    import memory

    memory.remember(key, value)
    return f"Remembered: {key}"


@tool(
    name="add_open_loop",
    description="Track a new open loop — something that needs follow-up or resolution. Use this when Maher mentions something pending, a task to do, or a decision to make.",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Short title for the open loop"},
            "context": {"type": "string", "description": "Additional context"},
        },
        "required": ["title"],
    },
)
def add_open_loop(title: str, context: str = "") -> str:
    import memory

    loop_id = memory.add_open_loop(title, context)
    return f"Open loop #{loop_id} created: {title}"


@tool(
    name="close_open_loop",
    description="Close an open loop that has been resolved.",
    schema={
        "properties": {
            "loop_id": {"type": "integer", "description": "The ID of the loop to close"},
            "status": {"type": "string", "description": "'done' or 'dropped'", "default": "done"},
        },
        "required": ["loop_id"],
    },
)
def close_open_loop(loop_id: int, status: str = "done") -> str:
    import memory

    memory.close_loop(loop_id, status)
    return f"Loop #{loop_id} closed."


@tool(
    name="log_decision",
    description="Log a decision that was made. Use this when Maher makes a significant business or personal decision worth tracking.",
    schema={
        "properties": {
            "summary": {"type": "string", "description": "What was decided"},
            "reasoning": {"type": "string", "description": "Why"},
            "outcome": {"type": "string", "description": "Expected outcome"},
        },
        "required": ["summary"],
    },
)
def log_decision(summary: str, reasoning: str = "", outcome: str = "") -> str:
    import memory

    memory.log_decision(summary, reasoning, outcome)
    return f"Decision logged: {summary}"
