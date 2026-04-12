"""Mercury bank account tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_mercury_balances",
    description="Get current Mercury bank account balances across all entities — Clifton, Plainfield (café + production/wholesale), and Personal. Each API key may have multiple sub-accounts (checking, credit card, savings).",
    agent="ops",
    schema={
        "properties": {
            "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all accounts.", "enum": ["clifton", "plainfield", "personal", "coinbits"]}
        },
    },
)
def get_mercury_balances(account: str = None) -> str:
    import json
    import mercury_client

    result = mercury_client.get_balances(account)
    return json.dumps(result, indent=2) if result else "Mercury unavailable."


@tool(
    name="get_mercury_transactions",
    description="Get recent Mercury bank transactions. Can filter by entity (clifton, plainfield, personal) or show all.",
    agent="ops",
    schema={
        "properties": {
            "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all.", "enum": ["clifton", "plainfield", "personal", "coinbits"]},
            "days": {"type": "integer", "description": "Number of days to look back (default 7)", "default": 7}
        },
    },
)
def get_mercury_transactions(account: str = None, days: int = 7) -> str:
    import json
    import mercury_client

    result = mercury_client.get_recent_transactions(account, days)
    return json.dumps(result, indent=2) if result else "Mercury unavailable."


@tool(
    name="get_mercury_cash_summary",
    description="Get a formatted cash summary across all Mercury accounts (Clifton, Plainfield café + production, Personal) including balances and recent transactions.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_mercury_cash_summary() -> str:
    import mercury_client

    return mercury_client.get_cash_summary()
