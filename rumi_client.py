"""HTTP client that calls Rumi's internal API for P&L and business data."""

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


def get_mtd_pl() -> dict | None:
    return _get("/api/pl/mtd")


def get_action_items() -> dict | None:
    return _get("/api/actions/today")


def get_scorecard() -> dict | None:
    return _get("/api/scorecard/today")


def get_cashflow_forecast() -> dict | None:
    return _get("/api/cashflow/forecast")


def get_labor_today() -> dict | None:
    return _get("/api/labor/today")


def get_inventory_alerts() -> dict | None:
    return _get("/api/inventory/alerts")
