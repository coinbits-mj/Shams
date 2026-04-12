"""Agents — list, detail, status, activity feed."""
from __future__ import annotations

import json
import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("agents", __name__, url_prefix="/api")


@bp.route("/agents", methods=["GET"])
@require_auth
def get_agents():
    agents = memory.get_agents()
    result = []
    for a in agents:
        d = dict(a)
        for k in ("last_heartbeat", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if d.get("config") and isinstance(d["config"], str):
            d["config"] = json.loads(d["config"])
        result.append(d)
    return jsonify(result)


@bp.route("/agents/<name>", methods=["GET"])
@require_auth
def get_agent_detail(name):
    """Get full agent detail: info, trust, missions, recent actions, activity."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras

    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Agent info
        cur.execute("SELECT * FROM shams_agents WHERE name = %s", (name,))
        agent = cur.fetchone()
        if not agent:
            return jsonify({"error": "not found"}), 404

        # Trust score
        cur.execute("SELECT * FROM shams_trust_scores WHERE agent_name = %s", (name,))
        trust = cur.fetchone()

        # Missions
        cur.execute(
            "SELECT id, title, status, priority, created_at, updated_at FROM shams_missions "
            "WHERE assigned_agent = %s ORDER BY created_at DESC LIMIT 20", (name,)
        )
        missions = cur.fetchall()

        # Recent actions
        cur.execute(
            "SELECT id, action_type, title, status, created_at FROM shams_actions "
            "WHERE agent_name = %s ORDER BY created_at DESC LIMIT 20", (name,)
        )
        actions = cur.fetchall()

        # Recent activity
        cur.execute(
            "SELECT event_type, content, timestamp FROM shams_activity_feed "
            "WHERE agent_name = %s ORDER BY timestamp DESC LIMIT 30", (name,)
        )
        activity = cur.fetchall()

    d = dict(agent)
    for k in ("last_heartbeat", "created_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    if d.get("config") and isinstance(d["config"], str):
        d["config"] = json.loads(d["config"])

    if trust:
        td = dict(trust)
        if td.get("updated_at"):
            td["updated_at"] = td["updated_at"].isoformat()
        total = td.get("total_approved", 0) + td.get("total_rejected", 0)
        td["approval_rate"] = round(td["total_approved"] / total * 100, 1) if total > 0 else 0
        d["trust"] = td
    else:
        d["trust"] = None

    d["missions"] = []
    for m in missions:
        md = dict(m)
        for k in ("created_at", "updated_at"):
            if md.get(k):
                md[k] = md[k].isoformat()
        d["missions"].append(md)

    d["actions"] = []
    for a in actions:
        ad = dict(a)
        if ad.get("created_at"):
            ad["created_at"] = ad["created_at"].isoformat()
        d["actions"].append(ad)

    d["activity"] = []
    for f in activity:
        fd = dict(f)
        if fd.get("timestamp"):
            fd["timestamp"] = fd["timestamp"].isoformat()
        d["activity"].append(fd)

    return jsonify(d)


@bp.route("/agents/<name>/status", methods=["PATCH"])
@require_auth
def update_agent_status(name):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "idle")
    memory.update_agent_status(name, status)
    return jsonify({"ok": True})


# ── Activity Feed ────────────────────────────────────────────────────────────

@bp.route("/feed", methods=["GET"])
@require_auth
def get_feed():
    limit = request.args.get("limit", 50, type=int)
    agent = request.args.get("agent")
    event_type = request.args.get("event_type")
    feed = memory.get_activity_feed(limit, agent, event_type)
    result = []
    for f in feed:
        d = dict(f)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)
