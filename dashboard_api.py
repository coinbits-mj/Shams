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
import group_chat

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

    # Send via Resend
    if config.RESEND_API_KEY:
        try:
            import resend
            resend.api_key = config.RESEND_API_KEY
            resend.Emails.send({
                "from": config.RESEND_FROM_EMAIL,
                "to": [email],
                "subject": "Shams — Login Link",
                "html": f"""
                <div style="font-family: -apple-system, sans-serif; max-width: 400px; margin: 0 auto; padding: 40px 20px;">
                    <h1 style="color: #f59e0b; font-size: 24px;">Shams</h1>
                    <p style="color: #64748b; margin: 16px 0;">Click below to log in to your dashboard:</p>
                    <a href="{link}" style="display: inline-block; padding: 12px 24px; background: #f59e0b; color: #0f172a; text-decoration: none; border-radius: 8px; font-weight: 600;">
                        Log In
                    </a>
                    <p style="color: #475569; font-size: 12px; margin-top: 24px;">Link expires in 15 minutes.</p>
                </div>
                """,
            })
            logger.info(f"Magic link sent to {email}")
        except Exception as e:
            logger.error(f"Resend email failed: {e}")
    else:
        logger.info(f"Magic link (no Resend configured): {link}")

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


# ── Group Chat (War Room) ────────────────────────────────────────────────────

@api.route("/group-chat", methods=["POST"])
@require_auth
def group_chat_send():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "message required"}), 400
    responses = group_chat.send_group_message(message)
    return jsonify({"responses": responses})


@api.route("/group-chat/history", methods=["GET"])
@require_auth
def group_chat_history():
    limit = request.args.get("limit", 50, type=int)
    messages = memory.get_group_messages(limit)
    result = []
    for m in messages:
        d = dict(m)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)


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


# ── Integrations ─────────────────────────────────────────────────────────────

@api.route("/integrations/status", methods=["GET"])
@require_auth
def integration_status():
    """Check status of all integrations."""
    import requests as req

    statuses = {}

    statuses["telegram"] = "connected" if config.TELEGRAM_BOT_TOKEN else "unconfigured"
    statuses["claude"] = "connected" if config.ANTHROPIC_API_KEY else "unconfigured"
    statuses["whisper"] = "connected" if config.OPENAI_API_KEY else "unconfigured"

    for key_name, status_key in [
        ("MERCURY_API_KEY_CLIFTON", "mercury_clifton"),
        ("MERCURY_API_KEY_PLAINFIELD", "mercury_plainfield"),
        ("MERCURY_API_KEY_PERSONAL", "mercury_personal"),
        ("MERCURY_API_KEY_COINBITS", "mercury_coinbits"),
    ]:
        statuses[status_key] = "connected" if getattr(config, key_name, "") else "unconfigured"

    try:
        r = req.get(f"{config.RUMI_BASE_URL}/health", timeout=5)
        statuses["rumi"] = "connected" if r.ok else "error"
    except Exception:
        statuses["rumi"] = "error"

    statuses["resend"] = "connected" if config.RESEND_API_KEY else "unconfigured"

    google_tokens = bool(memory.recall("google_access_token"))
    google_configured = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    if google_tokens:
        statuses["google_calendar"] = "connected"
        statuses["gmail"] = "connected"
    elif google_configured:
        statuses["google_calendar"] = "ready"
        statuses["gmail"] = "ready"
    else:
        statuses["google_calendar"] = "unconfigured"
        statuses["gmail"] = "unconfigured"

    rumi_ok = statuses["rumi"] == "connected"
    statuses["square"] = "connected" if rumi_ok else "unconfigured"
    statuses["marginedge"] = "connected" if rumi_ok else "unconfigured"
    statuses["slack"] = "connected" if rumi_ok else "unconfigured"

    # Leo
    if config.LEO_API_URL:
        try:
            r = req.get(f"{config.LEO_API_URL}/health", timeout=5)
            statuses["leo"] = "connected" if r.ok else "error"
        except Exception:
            statuses["leo"] = "error"
    else:
        statuses["leo"] = "unconfigured"

    return jsonify(statuses)


@api.route("/integrations/google/connect", methods=["GET"])
@require_auth
def google_oauth_start():
    """Start Google OAuth flow — redirects user to Google consent screen."""
    if not config.GOOGLE_CLIENT_ID:
        return jsonify({"error": "GOOGLE_CLIENT_ID not configured"}), 400

    base_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    redirect_uri = f"{base_url}/api/integrations/google/callback"
    scopes = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly"

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={config.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scopes}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return jsonify({"url": auth_url})


@api.route("/integrations/google/callback", methods=["GET"])
def google_oauth_callback():
    """Handle Google OAuth callback — exchange code for tokens."""
    code = request.args.get("code")
    if not code:
        return "Missing code", 400

    base_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    redirect_uri = f"{base_url}/api/integrations/google/callback"

    import requests as req
    r = req.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })

    if r.ok:
        tokens = r.json()
        # Store tokens in memory table
        memory.remember("google_access_token", tokens.get("access_token", ""))
        memory.remember("google_refresh_token", tokens.get("refresh_token", ""))
        memory.remember("google_token_expiry", str(tokens.get("expires_in", 0)))
        logger.info("Google OAuth connected successfully")
        # Redirect back to integrations page
        return f'<html><script>window.location.href="/integrations";</script><p>Connected! Redirecting...</p></html>'
    else:
        logger.error(f"Google OAuth error: {r.status_code} {r.text}")
        return f"OAuth failed: {r.text}", 400


# ── Agents ───────────────────────────────────────────────────────────────────

@api.route("/agents", methods=["GET"])
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


@api.route("/agents/<name>/status", methods=["PATCH"])
@require_auth
def update_agent_status(name):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "idle")
    memory.update_agent_status(name, status)
    return jsonify({"ok": True})


# ── Missions ─────────────────────────────────────────────────────────────────

@api.route("/missions", methods=["GET"])
@require_auth
def get_missions():
    status = request.args.get("status")
    agent = request.args.get("agent")
    missions = memory.get_missions(status, agent)
    result = []
    for m in missions:
        d = dict(m)
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/missions", methods=["POST"])
@require_auth
def create_mission():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    mission_id = memory.create_mission(
        title, data.get("description", ""), data.get("priority", "normal"),
        data.get("assigned_agent"), data.get("tags", [])
    )
    memory.log_activity("shams", "mission_created", f"Mission #{mission_id}: {title}")
    return jsonify({"id": mission_id})


@api.route("/missions/<int:mission_id>", methods=["PATCH"])
@require_auth
def update_mission(mission_id):
    data = request.get_json(silent=True) or {}
    memory.update_mission(mission_id, **data)
    if data.get("status"):
        memory.log_activity("shams", "mission_update", f"Mission #{mission_id} → {data['status']}")
    return jsonify({"ok": True})


# ── Activity Feed ────────────────────────────────────────────────────────────

@api.route("/feed", methods=["GET"])
@require_auth
def get_feed():
    limit = request.args.get("limit", 50, type=int)
    agent = request.args.get("agent")
    feed = memory.get_activity_feed(limit, agent)
    result = []
    for f in feed:
        d = dict(f)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)
