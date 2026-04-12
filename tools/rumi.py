"""Rumi (QCC operations platform) tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_rumi_daily_pl",
    description="Get yesterday's P&L from Rumi (QCC's operations platform). Includes revenue, COGS, labor, overhead, net margin.",
    agent="ops",
    schema={
        "properties": {
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format, or 'yesterday'", "default": "yesterday"}
        },
    },
)
def get_rumi_daily_pl(date: str = "yesterday") -> str:
    import json
    import rumi_client

    result = rumi_client.get_daily_pl(date)
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_monthly_pl",
    description="Get month-to-date P&L from Rumi.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_monthly_pl() -> str:
    import json
    import rumi_client

    result = rumi_client.get_monthly_pl()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_scorecard",
    description="Get the QCC location health scorecard from Rumi.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_scorecard() -> str:
    import json
    import rumi_client

    result = rumi_client.get_scorecard()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_action_items",
    description="Get today's action items and alerts from Rumi.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_action_items() -> str:
    import json
    import rumi_client

    result = rumi_client.get_action_items()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_cashflow_forecast",
    description="Get cash flow forecast from Rumi (30/60/90 day projections).",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_cashflow_forecast() -> str:
    import json
    import rumi_client

    result = rumi_client.get_cashflow_forecast()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_labor",
    description="Get labor analysis from Rumi — costs by hour, daypart, employee.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_labor() -> str:
    import json
    import rumi_client

    result = rumi_client.get_labor_analysis()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."


@tool(
    name="get_rumi_inventory_alerts",
    description="Get inventory alerts from Rumi — low stock, reorder needed.",
    agent="ops",
    schema={
        "properties": {},
    },
)
def get_rumi_inventory_alerts() -> str:
    import json
    import rumi_client

    result = rumi_client.get_inventory_alerts()
    return json.dumps(result, indent=2) if result else "Rumi unavailable."
