"""HTTP client that calls Rumi's internal API for P&L and business data."""

from __future__ import annotations

import logging
import requests
from config import RUMI_BASE_URL

logger = logging.getLogger(__name__)

_session = requests.Session()


def _get(path: str, params: dict | None = None) -> dict | None:
    try:
        r = _session.get(f"{RUMI_BASE_URL}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Rumi API error {path}: {e}")
        return None


def get_daily_pl(date: str = "yesterday") -> dict | None:
    """Fetch daily P&L snapshot. date format: YYYY-MM-DD or 'yesterday'."""
    return _get("/api/pl/daily", {"date": date})


def get_monthly_pl() -> dict | None:
    """Fetch current month P&L."""
    return _get("/api/pl/monthly")


def get_weekly_pl() -> dict | None:
    return _get("/api/pl/weekly")


def get_action_items() -> dict | None:
    return _get("/api/actions")


def get_scorecard() -> dict | None:
    return _get("/api/scorecard")


def get_cashflow_forecast() -> dict | None:
    return _get("/api/cashflow/forecast")


def get_cashflow_balance() -> dict | None:
    return _get("/api/cashflow/balance")


def get_labor_analysis() -> dict | None:
    return _get("/api/pl/labor/analysis")


def get_inventory_alerts() -> dict | None:
    return _get("/api/inventory/alerts")


def get_briefing_summary(location: str = "clifton") -> dict | None:
    """Fetch Rumi briefing summary for a location.
    Known locations: 'clifton', 'plainfield', 'combined'.
    Returns MTD totals, WoW variance, yesterday's P&L, prime cost %, margins.
    """
    return _get("/api/briefing/summary", {"location": location})


def get_briefing_bundle() -> dict | None:
    return _get("/api/briefing/bundle")


def get_pulse() -> dict | None:
    return _get("/api/pulse")
