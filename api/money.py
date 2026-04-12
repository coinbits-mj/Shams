"""Money — today dashboard, money view, Rumi daily/monthly/scorecard."""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify

import memory
import mercury_client
import rumi_client
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("money", __name__, url_prefix="/api")


# ── Today (Daily Standup) ────────────────────────────────────────────────────

@bp.route("/today", methods=["GET"])
@require_auth
def get_today():
    """Single endpoint that aggregates everything MJ needs to see right now."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    result = {}

    # Cash position
    try:
        balances = mercury_client.get_balances()
        result["cash"] = balances if balances else {}
    except Exception:
        result["cash"] = {}

    # P&L (yesterday + MTD)
    try:
        daily = rumi_client.get_daily_pl("yesterday")
        monthly = rumi_client.get_monthly_pl()
        result["pl"] = {"daily": daily or {}, "monthly": monthly or {}}
    except Exception:
        result["pl"] = {"daily": {}, "monthly": {}}

    # Pending actions
    try:
        actions = memory.get_actions(status="pending", limit=10)
        result["pending_actions"] = [{
            "id": a["id"], "agent_name": a["agent_name"], "title": a["title"],
            "action_type": a["action_type"],
            "created_at": a["created_at"].isoformat() if a.get("created_at") else "",
        } for a in actions]
    except Exception:
        result["pending_actions"] = []

    # Missions needing attention (review + active)
    try:
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, status, priority, assigned_agent, updated_at "
                "FROM shams_missions WHERE status IN ('review', 'active', 'assigned') "
                "ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
                "updated_at DESC LIMIT 15"
            )
            missions = cur.fetchall()
        result["missions"] = [{
            **{k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(m).items()}
        } for m in missions]
    except Exception:
        result["missions"] = []

    # P1/P2 emails
    try:
        emails = memory.get_triaged_emails(archived=False, limit=50)
        urgent = [e for e in emails if e.get("priority") in ("P1", "P2")]
        result["urgent_emails"] = [{
            "id": e["id"], "priority": e["priority"], "subject": e["subject"],
            "from_addr": e["from_addr"], "account": e["account"],
            "action": e.get("action", ""), "routed_to": e.get("routed_to", []),
            "triaged_at": e["triaged_at"].isoformat() if e.get("triaged_at") else "",
        } for e in urgent[:10]]
    except Exception:
        result["urgent_emails"] = []

    # Active workflows
    try:
        workflows = memory.get_workflows(status="active")
        result["workflows"] = [{
            "id": w["id"], "title": w["title"], "current_step": w.get("current_step", 1),
            "created_at": w["created_at"].isoformat() if w.get("created_at") else "",
        } for w in workflows[:5]]
    except Exception:
        result["workflows"] = []

    # Health summary
    try:
        import leo_client
        health = leo_client.get_health_summary()
        if health:
            user = health.get("user") or {}
            daily = health.get("daily_summary") or {}
            result["health"] = {
                "weight": user.get("current_weight"),
                "sleep": daily.get("sleep_hours"),
                "hrv": daily.get("hrv"),
                "streak": user.get("current_streak"),
                "calories": daily.get("calories"),
                "steps": daily.get("steps"),
            }
        else:
            result["health"] = {}
    except Exception:
        result["health"] = {}

    # Notification counts
    try:
        result["counts"] = memory.get_notification_counts()
    except Exception:
        result["counts"] = {}

    # Recent activity (last 5 important events)
    try:
        feed = memory.get_activity_feed(limit=10)
        result["recent_activity"] = [{
            "agent_name": f["agent_name"], "event_type": f["event_type"],
            "content": f["content"],
            "timestamp": f["timestamp"].isoformat() if f.get("timestamp") else "",
        } for f in feed[:5]]
    except Exception:
        result["recent_activity"] = []

    return jsonify(result)


# ── Money View ──────────────────────────────────────────────────────────────

@bp.route("/money", methods=["GET"])
@require_auth
def get_money():
    """Unified financial dashboard — cash, P&L, trends, alerts."""
    result = {}

    # Cash across all Mercury accounts
    try:
        result["cash"] = mercury_client.get_balances() or {}
    except Exception:
        result["cash"] = {}

    # Recent transactions (last 7 days)
    try:
        result["transactions"] = mercury_client.get_recent_transactions(days=7) or []
    except Exception:
        result["transactions"] = []

    # Daily P&L
    try:
        result["daily_pl"] = rumi_client.get_daily_pl("yesterday") or {}
    except Exception:
        result["daily_pl"] = {}

    # Monthly P&L
    try:
        result["monthly_pl"] = rumi_client.get_monthly_pl() or {}
    except Exception:
        result["monthly_pl"] = {}

    # Cash flow forecast
    try:
        result["forecast"] = rumi_client.get_cashflow_forecast() or {}
    except Exception:
        result["forecast"] = {}

    # Labor analysis
    try:
        result["labor"] = rumi_client.get_labor_analysis() or {}
    except Exception:
        result["labor"] = {}

    # Scorecard
    try:
        result["scorecard"] = rumi_client.get_scorecard() or {}
    except Exception:
        result["scorecard"] = {}

    # Alerts — flag anything concerning
    alerts = []
    cash_total = result["cash"].get("grand_total", 0)
    if cash_total and cash_total < 50000:
        alerts.append({"level": "warning", "message": f"Cash below $50K: ${cash_total:,.0f}"})
    if cash_total and cash_total < 25000:
        alerts.append({"level": "critical", "message": f"Cash critically low: ${cash_total:,.0f}"})

    daily = result["daily_pl"]
    if daily.get("food_cost_pct") and daily["food_cost_pct"] > 35:
        alerts.append({"level": "warning", "message": f"Food cost high: {daily['food_cost_pct']:.1f}%"})
    if daily.get("labor_cost_pct") and daily["labor_cost_pct"] > 35:
        alerts.append({"level": "warning", "message": f"Labor cost high: {daily['labor_cost_pct']:.1f}%"})
    if daily.get("net_margin_pct") is not None and daily["net_margin_pct"] < 0:
        alerts.append({"level": "critical", "message": f"Negative margin: {daily['net_margin_pct']:.1f}%"})

    result["alerts"] = alerts

    return jsonify(result)


# ── Rumi ─────────────────────────────────────────────────────────────────────

@bp.route("/rumi/daily", methods=["GET"])
@require_auth
def rumi_daily():
    date = request.args.get("date", "yesterday")
    return jsonify(rumi_client.get_daily_pl(date) or {})


@bp.route("/rumi/monthly", methods=["GET"])
@require_auth
def rumi_monthly():
    return jsonify(rumi_client.get_monthly_pl() or {})


@bp.route("/rumi/scorecard", methods=["GET"])
@require_auth
def rumi_scorecard():
    return jsonify(rumi_client.get_scorecard() or {})
