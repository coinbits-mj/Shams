"""HTTP client for Leo Health Coach API — pulls biometrics, meals, trends."""

from __future__ import annotations

import logging
import requests
from config import LEO_API_URL, LEO_API_SECRET, LEO_USER_ID

logger = logging.getLogger(__name__)

_session = requests.Session()
if LEO_API_SECRET:
    _session.headers["Authorization"] = f"Bearer {LEO_API_SECRET}"


def _get(path: str) -> dict | None:
    if not LEO_API_URL:
        return None
    try:
        r = _session.get(f"{LEO_API_URL}{path}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Leo API error {path}: {e}")
        return None


def get_health_summary() -> dict | None:
    """Get latest health summary — weight, sleep, HRV, glucose, meals, streak."""
    return _get(f"/api/summary/{LEO_USER_ID}")


def get_trends() -> list | None:
    """Get 7-day health trends."""
    data = _get(f"/api/trends/{LEO_USER_ID}")
    return data if isinstance(data, list) else None


def get_health_brief() -> str:
    """Formatted health summary for Shams briefings."""
    summary = get_health_summary()
    if not summary:
        return "Leo: unavailable"

    lines = ["**Health (from Leo)**"]

    user = summary.get("user") or {}
    daily = summary.get("daily_summary") or {}

    if user.get("current_weight"):
        goal = f" → goal {user['goal_weight']} lbs" if user.get("goal_weight") else ""
        lines.append(f"- Weight: {user['current_weight']} lbs{goal}")

    if daily.get("sleep_hours"):
        lines.append(f"- Sleep: {daily['sleep_hours']:.1f} hrs")
    if daily.get("hrv"):
        lines.append(f"- HRV: {daily['hrv']:.0f}")
    if daily.get("readiness_score"):
        lines.append(f"- Readiness: {daily['readiness_score']}/100")
    if daily.get("glucose_avg"):
        lines.append(f"- Glucose avg: {daily['glucose_avg']:.0f} mg/dL")
    if daily.get("total_calories"):
        target = user.get("calorie_target", 0)
        lines.append(f"- Calories: {daily['total_calories']}/{target}")
    if daily.get("steps"):
        lines.append(f"- Steps: {daily['steps']:,}")
    if user.get("current_streak"):
        lines.append(f"- Streak: {user['current_streak']} days")

    meals = summary.get("todays_meals") or []
    if meals:
        lines.append(f"- Meals logged today: {len(meals)}")

    return "\n".join(lines)
