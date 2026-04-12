"""Briefings — memory KV, open loops, decisions, briefings."""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("briefings", __name__, url_prefix="/api")


# ── Memory ───────────────────────────────────────────────────────────────────

@bp.route("/memory", methods=["GET"])
@require_auth
def get_memory():
    return jsonify(memory.recall_all())


@bp.route("/memory", methods=["POST"])
@require_auth
def set_memory():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "key and value required"}), 400
    memory.remember(key, value)
    return jsonify({"ok": True})


@bp.route("/memory/<key>", methods=["DELETE"])
@require_auth
def delete_memory(key):
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM shams_memory WHERE key = %s", (key,))
    return jsonify({"ok": True})


# ── Open Loops ───────────────────────────────────────────────────────────────

@bp.route("/loops", methods=["GET"])
@require_auth
def get_loops():
    status = request.args.get("status", "open")
    if status == "all":
        from config import DATABASE_URL
        import psycopg2, psycopg2.extras
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM shams_open_loops ORDER BY created_at DESC LIMIT 100")
            rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k in ("created_at", "updated_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            result.append(d)
        return jsonify(result)
    loops = memory.get_open_loops()
    result = []
    for l in loops:
        d = dict(l)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/loops", methods=["POST"])
@require_auth
def add_loop():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    loop_id = memory.add_open_loop(title, data.get("context", ""))
    return jsonify({"id": loop_id})


@bp.route("/loops/<int:loop_id>/close", methods=["POST"])
@require_auth
def close_loop(loop_id):
    data = request.get_json(silent=True) or {}
    memory.close_loop(loop_id, data.get("status", "done"))
    return jsonify({"ok": True})


# ── Decisions ────────────────────────────────────────────────────────────────

@bp.route("/decisions", methods=["GET"])
@require_auth
def get_decisions():
    limit = request.args.get("limit", 20, type=int)
    decisions = memory.get_recent_decisions(limit)
    result = []
    for d in decisions:
        dd = dict(d)
        if dd.get("created_at"):
            dd["created_at"] = dd["created_at"].isoformat()
        result.append(dd)
    return jsonify(result)


@bp.route("/decisions", methods=["POST"])
@require_auth
def add_decision():
    data = request.get_json(silent=True) or {}
    summary = data.get("summary", "").strip()
    if not summary:
        return jsonify({"error": "summary required"}), 400
    memory.log_decision(summary, data.get("reasoning", ""), data.get("outcome", ""))
    return jsonify({"ok": True})


# ── Briefings ────────────────────────────────────────────────────────────────

@bp.route("/briefings", methods=["GET"])
@require_auth
def get_briefings():
    limit = request.args.get("limit", 20, type=int)
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM shams_briefings ORDER BY delivered_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("delivered_at"):
            d["delivered_at"] = d["delivered_at"].isoformat()
        result.append(d)
    return jsonify(result)
