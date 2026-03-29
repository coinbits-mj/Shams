"""Dashboard API — REST endpoints for the Shams web interface."""

from __future__ import annotations

import os
import json
import secrets
import logging
from functools import wraps
from datetime import datetime
from flask import Blueprint, request, jsonify, g

import config
import memory
import claude_client
import mercury_client
import rumi_client

logger = logging.getLogger(__name__)

ALLOWED_EMAIL = "maher@qcitycoffee.com"

api = Blueprint("dashboard", __name__, url_prefix="/api")


# ── Auth middleware ───────────────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("shams_session")
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if not token:
            return jsonify({"error": "Authentication required"}), 401
        email = memory.validate_session(token)
        if not email:
            return jsonify({"error": "Session expired"}), 401
        g.email = email
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ──────────────────────────────────────────────────────────────

@api.route("/auth/login", methods=["POST"])
def login():
    """Send magic link to email."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    # Always return same response to prevent email enumeration
    resp = {"ok": True, "message": "If that email is registered, a login link has been sent."}

    if email != ALLOWED_EMAIL:
        return jsonify(resp)

    token = secrets.token_urlsafe(48)
    memory.create_magic_link(email, token)

    # Build magic link URL
    base_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    link = f"{base_url}/api/auth/verify?token={token}"

    # For now, log the link (replace with email sending later)
    logger.info(f"Magic link for {email}: {link}")

    # TODO: Send email via SMTP or a service
    # For development, also return the link directly
    if os.environ.get("DEV_MODE"):
        resp["dev_link"] = link

    return jsonify(resp)


@api.route("/auth/verify", methods=["GET"])
def verify():
    """Handle magic link click."""
    token = request.args.get("token", "")
    email = memory.validate_magic_link(token)
    if not email:
        return jsonify({"error": "Invalid or expired link"}), 401

    session_token = secrets.token_urlsafe(48)
    memory.create_session(email, session_token)

    # Return JSON with session token
    return jsonify({"ok": True, "session": session_token, "email": email})


@api.route("/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"email": g.email})


@api.route("/auth/logout", methods=["POST"])
@require_auth
def logout():
    token = request.cookies.get("shams_session") or request.headers.get("Authorization", "")[7:]
    memory.delete_session(token)
    return jsonify({"ok": True})


# ── Chat ─────────────────────────────────────────────────────────────────────

@api.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "message required"}), 400
    reply = claude_client.chat(message)
    return jsonify({"reply": reply})


@api.route("/conversations", methods=["GET"])
@require_auth
def conversations():
    limit = request.args.get("limit", 100, type=int)
    messages = memory.get_recent_messages(limit)
    result = []
    for m in messages:
        d = dict(m)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)


# ── Memory ───────────────────────────────────────────────────────────────────

@api.route("/memory", methods=["GET"])
@require_auth
def get_memory():
    return jsonify(memory.recall_all())


@api.route("/memory", methods=["POST"])
@require_auth
def set_memory():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "key and value required"}), 400
    memory.remember(key, value)
    return jsonify({"ok": True})


@api.route("/memory/<key>", methods=["DELETE"])
@require_auth
def delete_memory(key):
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM shams_memory WHERE key = %s", (key,))
    return jsonify({"ok": True})


# ── Open Loops ───────────────────────────────────────────────────────────────

@api.route("/loops", methods=["GET"])
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


@api.route("/loops", methods=["POST"])
@require_auth
def add_loop():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    loop_id = memory.add_open_loop(title, data.get("context", ""))
    return jsonify({"id": loop_id})


@api.route("/loops/<int:loop_id>/close", methods=["POST"])
@require_auth
def close_loop(loop_id):
    data = request.get_json(silent=True) or {}
    memory.close_loop(loop_id, data.get("status", "done"))
    return jsonify({"ok": True})


# ── Decisions ────────────────────────────────────────────────────────────────

@api.route("/decisions", methods=["GET"])
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


@api.route("/decisions", methods=["POST"])
@require_auth
def add_decision():
    data = request.get_json(silent=True) or {}
    summary = data.get("summary", "").strip()
    if not summary:
        return jsonify({"error": "summary required"}), 400
    memory.log_decision(summary, data.get("reasoning", ""), data.get("outcome", ""))
    return jsonify({"ok": True})


# ── Briefings ────────────────────────────────────────────────────────────────

@api.route("/briefings", methods=["GET"])
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


# ── Files & Folders ──────────────────────────────────────────────────────────

@api.route("/folders", methods=["GET"])
@require_auth
def get_folders():
    parent_id = request.args.get("parent_id", None, type=int)
    folders = memory.get_folders(parent_id)
    result = []
    for f in folders:
        d = dict(f)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/folders", methods=["POST"])
@require_auth
def create_folder():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    folder_id = memory.create_folder(name, data.get("parent_id"))
    return jsonify({"id": folder_id})


@api.route("/files", methods=["GET"])
@require_auth
def get_files():
    folder_id = request.args.get("folder_id", None, type=int)
    file_type = request.args.get("type")
    limit = request.args.get("limit", 50, type=int)
    files = memory.get_files(folder_id, file_type, limit)
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        # Don't send full transcript in list view
        if d.get("transcript"):
            d["transcript_preview"] = d["transcript"][:200]
            del d["transcript"]
        result.append(d)
    return jsonify(result)


@api.route("/files/<int:file_id>", methods=["GET"])
@require_auth
def get_file(file_id):
    f = memory.get_file(file_id)
    if not f:
        return jsonify({"error": "not found"}), 404
    d = dict(f)
    if d.get("uploaded_at"):
        d["uploaded_at"] = d["uploaded_at"].isoformat()
    return jsonify(d)


@api.route("/files/<int:file_id>/move", methods=["POST"])
@require_auth
def move_file(file_id):
    data = request.get_json(silent=True) or {}
    folder_id = data.get("folder_id")
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("UPDATE shams_files SET folder_id = %s WHERE id = %s", (folder_id, file_id))
    return jsonify({"ok": True})


# ── Mercury ──────────────────────────────────────────────────────────────────

@api.route("/mercury/balances", methods=["GET"])
@require_auth
def mercury_balances():
    account = request.args.get("account")
    result = mercury_client.get_balances(account)
    return jsonify(result)


@api.route("/mercury/transactions", methods=["GET"])
@require_auth
def mercury_transactions():
    account = request.args.get("account")
    days = request.args.get("days", 7, type=int)
    result = mercury_client.get_recent_transactions(account, days)
    return jsonify(result or [])


# ── Rumi ─────────────────────────────────────────────────────────────────────

@api.route("/rumi/daily", methods=["GET"])
@require_auth
def rumi_daily():
    date = request.args.get("date", "yesterday")
    return jsonify(rumi_client.get_daily_pl(date) or {})


@api.route("/rumi/monthly", methods=["GET"])
@require_auth
def rumi_monthly():
    return jsonify(rumi_client.get_monthly_pl() or {})


@api.route("/rumi/scorecard", methods=["GET"])
@require_auth
def rumi_scorecard():
    return jsonify(rumi_client.get_scorecard() or {})
