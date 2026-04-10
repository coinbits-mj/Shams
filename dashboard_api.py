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
    """Handle magic link click — sets session and redirects to app."""
    token = request.args.get("token", "")
    email = memory.validate_magic_link(token)
    if not email:
        return """<html><body style="background:#0d1117;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
        <div style="text-align:center"><h2>Link expired or invalid</h2><p>Request a new login link.</p><a href="/login" style="color:#38bdf8">Go to login</a></div>
        </body></html>""", 401

    session_token = secrets.token_urlsafe(48)
    memory.create_session(email, session_token)

    # Redirect to app — JS stores the session token and navigates
    base_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    return f"""<html><body style="background:#0d1117">
    <script>
        localStorage.setItem('shams_session', '{session_token}');
        window.location.href = '/';
    </script>
    <p style="color:#64748b;font-family:sans-serif;text-align:center;margin-top:40vh">Logging in...</p>
    </body></html>"""


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


# ── Today (Daily Standup) ────────────────────────────────────────────────────

@api.route("/today", methods=["GET"])
@require_auth
def get_today():
    """Single endpoint that aggregates everything MJ needs to see right now."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    result = {}

    # Cash position
    try:
        import mercury_client
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

@api.route("/money", methods=["GET"])
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


# ── Chat ─────────────────────────────────────────────────────────────────────

def _process_uploaded_files(req) -> tuple:
    """Extract message and file data from a multipart or JSON request.
    Returns (message, images_list, doc_text).
    """
    import base64

    images = []
    doc_text = ""

    # Multipart form
    if req.content_type and "multipart" in req.content_type:
        message = req.form.get("message", "").strip()
        files = req.files.getlist("files")
        for f in files:
            file_bytes = f.read()
            mime = f.content_type or ""
            fname = f.filename or "upload"

            if mime.startswith("image/"):
                img_b64 = base64.b64encode(file_bytes).decode("utf-8")
                images.append({"data": img_b64, "media_type": mime})
                # Save to files table
                memory.save_file(fname, "photo", mime, len(file_bytes),
                                 summary=f"Uploaded via dashboard: {fname}")
            elif mime == "application/pdf":
                from app import extract_document_text
                text = extract_document_text(file_bytes, fname)
                doc_text += f"\n\n[Document: {fname}]\n{text}"
                memory.save_file(fname, "pdf", mime, len(file_bytes),
                                 transcript=text[:2000],
                                 summary=f"Uploaded via dashboard: {fname}")
            else:
                # Try text extraction for other docs
                from app import extract_document_text
                text = extract_document_text(file_bytes, fname)
                doc_text += f"\n\n[Document: {fname}]\n{text}"
                memory.save_file(fname, "document", mime, len(file_bytes),
                                 transcript=text[:2000],
                                 summary=f"Uploaded via dashboard: {fname}")
    else:
        data = req.get_json(silent=True) or {}
        message = data.get("message", "").strip()

    return message, images, doc_text


@api.route("/chat", methods=["POST"])
@require_auth
def chat():
    message, images, doc_text = _process_uploaded_files(request)

    if doc_text:
        message = (message + doc_text) if message else doc_text.strip()
    if not message and not images:
        return jsonify({"error": "message or file required"}), 400

    reply = claude_client.chat(message or "What's in this file?", images=images if images else None)
    return jsonify({"reply": reply})


# ── Group Chat (War Room) ────────────────────────────────────────────────────

@api.route("/group-chat", methods=["POST"])
@require_auth
def group_chat_send():
    message, images, doc_text = _process_uploaded_files(request)

    if doc_text:
        message = (message + doc_text) if message else doc_text.strip()
    if not message:
        return jsonify({"error": "message required"}), 400

    # For War Room, prepend file context to the message
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

    google_configured = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    for acct_key, acct_email in config.GOOGLE_ACCOUNTS.items():
        has_token = bool(memory.recall(f"google_{acct_key}_access_token"))
        if has_token:
            statuses[f"google_{acct_key}"] = "connected"
        elif google_configured:
            statuses[f"google_{acct_key}"] = "ready"
        else:
            statuses[f"google_{acct_key}"] = "unconfigured"

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

    statuses["github"] = "connected" if config.GITHUB_TOKEN else "unconfigured"
    statuses["docuseal"] = "connected" if config.DOCUSEAL_API_URL else "unconfigured"

    return jsonify(statuses)


@api.route("/integrations/google/connect", methods=["GET"])
@require_auth
def google_oauth_start():
    """Start Google OAuth flow for a specific account."""
    if not config.GOOGLE_CLIENT_ID:
        return jsonify({"error": "GOOGLE_CLIENT_ID not configured"}), 400

    account = request.args.get("account", "personal")
    email_hint = config.GOOGLE_ACCOUNTS.get(account, "")

    base_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    redirect_uri = f"{base_url}/api/integrations/google/callback"
    scopes = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar.readonly"

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={config.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scopes}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={account}&"
        f"login_hint={email_hint}"
    )
    return jsonify({"url": auth_url})


@api.route("/integrations/google/callback", methods=["GET"])
def google_oauth_callback():
    """Handle Google OAuth callback — exchange code for tokens."""
    code = request.args.get("code")
    account = request.args.get("state", "personal")
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
        # Store tokens per account
        memory.remember(f"google_{account}_access_token", tokens.get("access_token", ""))
        memory.remember(f"google_{account}_refresh_token", tokens.get("refresh_token", ""))
        memory.remember(f"google_{account}_expiry", str(tokens.get("expires_in", 0)))
        logger.info(f"Google OAuth connected for {account} ({config.GOOGLE_ACCOUNTS.get(account, '')})")
        return f'<html><script>window.location.href="/integrations";</script><p>{account} connected! Redirecting...</p></html>'
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


@api.route("/agents/<name>", methods=["GET"])
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


@api.route("/missions/<int:mission_id>", methods=["GET"])
@require_auth
def get_mission(mission_id):
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM shams_missions WHERE id = %s", (mission_id,))
        mission = cur.fetchone()
        if not mission:
            return jsonify({"error": "not found"}), 404

        # Get related actions
        cur.execute("SELECT * FROM shams_actions WHERE mission_id = %s ORDER BY created_at", (mission_id,))
        actions = cur.fetchall()

        # Get linked files
        cur.execute(
            "SELECT id, filename, file_type, summary, uploaded_at FROM shams_files WHERE mission_id = %s ORDER BY uploaded_at",
            (mission_id,)
        )
        files = cur.fetchall()

        # Get related activity feed entries (matching mission ID in content)
        cur.execute(
            "SELECT * FROM shams_activity_feed WHERE content LIKE %s ORDER BY timestamp",
            (f"%Mission #{mission_id}%",)
        )
        activity = cur.fetchall()

    d = dict(mission)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()

    d["actions"] = []
    for a in actions:
        ad = dict(a)
        for k in ("created_at", "resolved_at"):
            if ad.get(k):
                ad[k] = ad[k].isoformat()
        if ad.get("payload") and isinstance(ad["payload"], str):
            ad["payload"] = json.loads(ad["payload"])
        d["actions"].append(ad)

    d["files"] = []
    for fi in files:
        fid = dict(fi)
        if fid.get("uploaded_at"):
            fid["uploaded_at"] = fid["uploaded_at"].isoformat()
        d["files"].append(fid)

    d["activity"] = []
    for f in activity:
        fd = dict(f)
        if fd.get("timestamp"):
            fd["timestamp"] = fd["timestamp"].isoformat()
        if fd.get("metadata") and isinstance(fd["metadata"], str):
            fd["metadata"] = json.loads(fd["metadata"])
        d["activity"].append(fd)

    return jsonify(d)


@api.route("/missions/<int:mission_id>", methods=["PATCH"])
@require_auth
def update_mission(mission_id):
    data = request.get_json(silent=True) or {}
    memory.update_mission(mission_id, **data)
    if data.get("status"):
        memory.log_activity("shams", "mission_update", f"Mission #{mission_id} → {data['status']}")
    return jsonify({"ok": True})


# ── Projects (Gantt) ────────────────────────────────────────────────────────

@api.route("/projects", methods=["GET"])
@require_auth
def get_projects():
    status = request.args.get("status")
    projects = memory.get_projects(status)
    result = []
    for p in projects:
        d = dict(p)
        for k in ("created_at", "updated_at", "start_date", "target_date"):
            if d.get(k):
                d[k] = d[k].isoformat() if hasattr(d[k], 'isoformat') else str(d[k])
        result.append(d)
    return jsonify(result)


@api.route("/projects/<int:project_id>", methods=["GET"])
@require_auth
def get_project(project_id):
    proj = memory.get_project_with_missions(project_id)
    if not proj:
        return jsonify({"error": "not found"}), 404
    for k in ("created_at", "updated_at", "start_date", "target_date"):
        if proj.get(k):
            proj[k] = proj[k].isoformat() if hasattr(proj[k], 'isoformat') else str(proj[k])
    for m in proj.get("missions", []):
        for k in ("created_at", "updated_at", "start_date", "end_date"):
            if m.get(k):
                m[k] = m[k].isoformat() if hasattr(m[k], 'isoformat') else str(m[k])
    return jsonify(proj)


@api.route("/projects", methods=["POST"])
@require_auth
def create_project():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    pid = memory.create_project(
        title=title, brief=data.get("brief", ""),
        start_date=data.get("start_date"), target_date=data.get("target_date"),
        color=data.get("color", "#38bdf8"),
    )
    return jsonify({"id": pid})


@api.route("/projects/<int:project_id>", methods=["PATCH"])
@require_auth
def update_project(project_id):
    data = request.get_json(silent=True) or {}
    memory.update_project(project_id, **data)
    return jsonify({"ok": True})


@api.route("/projects/<int:project_id>/gantt", methods=["GET"])
@require_auth
def get_project_gantt(project_id):
    """Get project with missions formatted for Gantt rendering."""
    proj = memory.get_project_with_missions(project_id)
    if not proj:
        return jsonify({"error": "not found"}), 404

    # Build Gantt data
    gantt = {
        "id": proj["id"],
        "title": proj["title"],
        "brief": proj.get("brief", ""),
        "color": proj.get("color", "#38bdf8"),
        "start_date": str(proj["start_date"]) if proj.get("start_date") else None,
        "target_date": str(proj["target_date"]) if proj.get("target_date") else None,
        "status": proj["status"],
        "tasks": [],
    }
    for m in proj.get("missions", []):
        gantt["tasks"].append({
            "id": m["id"],
            "title": m["title"],
            "status": m["status"],
            "priority": m["priority"],
            "assigned_agent": m.get("assigned_agent"),
            "start_date": str(m["start_date"]) if m.get("start_date") else None,
            "end_date": str(m["end_date"]) if m.get("end_date") else None,
            "depends_on": m.get("depends_on") or [],
        })
    return jsonify(gantt)


@api.route("/gantt", methods=["GET"])
@require_auth
def get_all_gantt():
    """Get all active projects with their missions for the full Gantt view."""
    projects = memory.get_projects("active")
    result = []
    for p in projects:
        proj = memory.get_project_with_missions(p["id"])
        if not proj:
            continue
        gantt = {
            "id": proj["id"],
            "title": proj["title"],
            "brief": proj.get("brief", ""),
            "color": proj.get("color", "#38bdf8"),
            "start_date": str(proj["start_date"]) if proj.get("start_date") else None,
            "target_date": str(proj["target_date"]) if proj.get("target_date") else None,
            "status": proj["status"],
            "tasks": [],
        }
        for m in proj.get("missions", []):
            gantt["tasks"].append({
                "id": m["id"],
                "title": m["title"],
                "status": m["status"],
                "priority": m["priority"],
                "assigned_agent": m.get("assigned_agent"),
                "start_date": str(m["start_date"]) if m.get("start_date") else None,
                "end_date": str(m["end_date"]) if m.get("end_date") else None,
                "depends_on": m.get("depends_on") or [],
                "file_count": m.get("file_count", 0),
            })
        result.append(gantt)
    return jsonify(result)


# ── Signatures (DocuSeal) ───────────────────────────────────────────────────

@api.route("/signatures/templates", methods=["GET"])
@require_auth
def get_signature_templates():
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify({"error": "DocuSeal not configured"}), 400
    return jsonify(docuseal_client.list_templates())


@api.route("/signatures/templates", methods=["POST"])
@require_auth
def upload_signature_template():
    """Upload a PDF to create a signing template."""
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify({"error": "DocuSeal not configured"}), 400

    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400

    f = request.files["file"]
    name = request.form.get("name", f.filename or "Document")
    pdf_bytes = f.read()

    result = docuseal_client.create_template_from_pdf(name, pdf_bytes)
    if result:
        memory.log_activity("shams", "template_created", f"Signing template created: {name}")
        return jsonify(result)
    return jsonify({"error": "Failed to create template"}), 500


@api.route("/signatures/send", methods=["POST"])
@require_auth
def send_signature():
    """Send a template for signing."""
    import docuseal_client
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    signers = data.get("signers", [])
    message = data.get("message", "")

    if not template_id or not signers:
        return jsonify({"error": "template_id and signers required"}), 400

    submitters = [{"email": s["email"], "name": s.get("name", ""), "role": "First Party"} for s in signers]
    result = docuseal_client.send_for_signature(template_id, submitters, send_email=True, message=message)
    if result:
        memory.log_activity("shams", "signature_sent",
            f"Sent template #{template_id} to {', '.join(s['email'] for s in signers)}")
        return jsonify(result)
    return jsonify({"error": "Failed to send"}), 500


@api.route("/signatures/submissions", methods=["GET"])
@require_auth
def get_submissions():
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify([])
    return jsonify(docuseal_client.list_submissions(limit=20))


@api.route("/signatures/status", methods=["GET"])
@require_auth
def signatures_status():
    import docuseal_client
    return jsonify({"configured": docuseal_client.is_configured()})


# ── Mission File Room ───────────────────────────────────────────────────────

@api.route("/missions/<int:mission_id>/files", methods=["GET"])
@require_auth
def get_mission_files(mission_id):
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, filename, file_type, mime_type, file_size, summary, file_category, "
            "version, uploaded_by, uploaded_at FROM shams_files "
            "WHERE mission_id = %s ORDER BY uploaded_at DESC",
            (mission_id,)
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/missions/<int:mission_id>/files", methods=["POST"])
@require_auth
def upload_mission_file(mission_id):
    """Upload a file to a mission's file room."""
    import base64

    if not request.content_type or "multipart" not in request.content_type:
        return jsonify({"error": "multipart form required"}), 400

    files = request.files.getlist("files")
    category = request.form.get("category", "")
    description = request.form.get("description", "")

    uploaded = []
    for f in files:
        file_bytes = f.read()
        mime = f.content_type or ""
        fname = f.filename or "upload"

        # Extract text for searchability
        transcript = ""
        if mime == "application/pdf":
            try:
                from app import extract_document_text
                transcript = extract_document_text(file_bytes, fname)
            except Exception:
                pass
        elif mime.startswith("text/") or fname.endswith(('.txt', '.md', '.csv', '.json')):
            try:
                transcript = file_bytes.decode("utf-8")[:10000]
            except Exception:
                pass

        # Check for existing version
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(version) FROM shams_files WHERE mission_id = %s AND filename = %s",
                (mission_id, fname)
            )
            max_ver = cur.fetchone()[0]
        version = (max_ver or 0) + 1

        file_id = memory.save_file(
            filename=fname,
            file_type=category or ("pdf" if mime == "application/pdf" else "document"),
            mime_type=mime,
            file_size=len(file_bytes),
            summary=description or f"Uploaded to mission #{mission_id}",
            transcript=transcript[:5000] if transcript else "",
            mission_id=mission_id,
        )

        # Update category, version, uploaded_by
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE shams_files SET file_category = %s, version = %s, uploaded_by = %s WHERE id = %s",
                (category, version, g.email or "maher", file_id)
            )

        memory.log_activity("shams", "file_uploaded",
            f"File uploaded to mission #{mission_id}: {fname} (v{version})",
            {"file_id": file_id, "mission_id": mission_id})
        memory.create_notification("file_uploaded", f"New file: {fname}", f"Mission #{mission_id}", "file", file_id)

        uploaded.append({"id": file_id, "filename": fname, "version": version})

    return jsonify({"ok": True, "files": uploaded})


@api.route("/files/search", methods=["GET"])
@require_auth
def search_files():
    """Search across all files by name or content."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, filename, file_type, summary, mission_id, uploaded_at "
            "FROM shams_files WHERE filename ILIKE %s OR summary ILIKE %s OR transcript ILIKE %s "
            "ORDER BY uploaded_at DESC LIMIT 20",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/files/recent", methods=["GET"])
@require_auth
def recent_files():
    """Get most recent files across all missions."""
    limit = request.args.get("limit", 10, type=int)
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT f.id, f.filename, f.file_type, f.summary, f.mission_id, f.file_category, "
            "f.version, f.uploaded_by, f.uploaded_at, m.title as mission_title "
            "FROM shams_files f LEFT JOIN shams_missions m ON f.mission_id = m.id "
            "ORDER BY f.uploaded_at DESC LIMIT %s",
            (limit,)
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)


# ── Alert Rules ─────────────────────────────────────────────────────────────

@api.route("/alert-rules", methods=["GET"])
@require_auth
def get_alert_rules():
    rules = memory.get_alert_rules()
    result = []
    for r in rules:
        d = dict(r)
        for k in ("last_triggered", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat() if hasattr(d[k], 'isoformat') else str(d[k])
        if d.get("threshold"):
            d["threshold"] = float(d["threshold"])
        result.append(d)
    return jsonify(result)


@api.route("/alert-rules", methods=["POST"])
@require_auth
def create_alert_rule():
    data = request.get_json(silent=True) or {}
    rule_id = memory.create_alert_rule(
        name=data.get("name", ""),
        metric=data.get("metric", ""),
        condition=data.get("condition", "<"),
        threshold=data.get("threshold", 0),
        message_template=data.get("message_template", ""),
    )
    return jsonify({"id": rule_id})


@api.route("/alert-rules/<int:rule_id>", methods=["PATCH"])
@require_auth
def update_alert_rule(rule_id):
    data = request.get_json(silent=True) or {}
    memory.update_alert_rule(rule_id, **{k: v for k, v in data.items() if k in ("name", "enabled", "threshold", "condition", "message_template")})
    return jsonify({"ok": True})


# ── Delegations (MJ's Outbox) ───────────────────────────────────────────────

@api.route("/delegations", methods=["GET"])
@require_auth
def get_delegations():
    """Everything MJ has asked for — missions, actions, workflows — in one view."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    items = []

    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Active missions
        cur.execute(
            "SELECT id, title, status, priority, assigned_agent, created_at, updated_at, result "
            "FROM shams_missions WHERE status NOT IN ('done', 'dropped') ORDER BY created_at DESC LIMIT 30"
        )
        for m in cur.fetchall():
            items.append({
                "type": "mission", "id": m["id"], "title": m["title"],
                "status": m["status"], "agent": m["assigned_agent"],
                "priority": m["priority"], "result": m.get("result", ""),
                "created_at": m["created_at"].isoformat() if m.get("created_at") else "",
                "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else "",
            })

        # Pending/executing actions
        cur.execute(
            "SELECT id, agent_name, action_type, title, status, created_at, resolved_at, result "
            "FROM shams_actions WHERE status IN ('pending', 'approved', 'executing') ORDER BY created_at DESC LIMIT 20"
        )
        for a in cur.fetchall():
            items.append({
                "type": "action", "id": a["id"], "title": a["title"],
                "status": a["status"], "agent": a["agent_name"],
                "action_type": a["action_type"], "result": a.get("result", ""),
                "created_at": a["created_at"].isoformat() if a.get("created_at") else "",
                "updated_at": a["resolved_at"].isoformat() if a.get("resolved_at") else "",
            })

        # Active workflows
        cur.execute(
            "SELECT id, title, status, current_step, created_at, updated_at "
            "FROM shams_workflows WHERE status = 'active' ORDER BY created_at DESC LIMIT 10"
        )
        for w in cur.fetchall():
            items.append({
                "type": "workflow", "id": w["id"], "title": w["title"],
                "status": f"step {w['current_step']}", "agent": "shams",
                "created_at": w["created_at"].isoformat() if w.get("created_at") else "",
                "updated_at": w["updated_at"].isoformat() if w.get("updated_at") else "",
            })

        # Recently completed (last 10)
        cur.execute(
            "SELECT id, title, status, assigned_agent, result, updated_at "
            "FROM shams_missions WHERE status IN ('done', 'dropped') ORDER BY updated_at DESC LIMIT 10"
        )
        for m in cur.fetchall():
            items.append({
                "type": "mission", "id": m["id"], "title": m["title"],
                "status": m["status"], "agent": m["assigned_agent"],
                "result": m.get("result", ""),
                "created_at": "", "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else "",
                "completed": True,
            })

    # Sort: incomplete first (by created_at desc), then completed
    incomplete = sorted([i for i in items if not i.get("completed")], key=lambda x: x.get("created_at", ""), reverse=True)
    completed = [i for i in items if i.get("completed")]
    return jsonify({"active": incomplete, "completed": completed})


# ── Deals ───────────────────────────────────────────────────────────────────

@api.route("/deals", methods=["GET"])
@require_auth
def get_deals():
    stage = request.args.get("stage")
    deals = memory.get_deals(stage)
    result = []
    for d in deals:
        dd = dict(d)
        for k in ("created_at", "updated_at", "deadline"):
            if dd.get(k):
                dd[k] = dd[k].isoformat() if hasattr(dd[k], 'isoformat') else str(dd[k])
        if dd.get("value"):
            dd["value"] = float(dd["value"])
        result.append(dd)
    return jsonify(result)


@api.route("/deals", methods=["POST"])
@require_auth
def create_deal():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    deal_id = memory.create_deal(title=title, **{k: v for k, v in data.items() if k != "title"})
    memory.log_activity("shams", "deal_created", f"Deal #{deal_id}: {title}")
    return jsonify({"id": deal_id})


@api.route("/deals/<int:deal_id>", methods=["PATCH"])
@require_auth
def update_deal(deal_id):
    data = request.get_json(silent=True) or {}
    memory.update_deal(deal_id, **data)
    if data.get("stage"):
        memory.log_activity("shams", "deal_updated", f"Deal #{deal_id} → {data['stage']}")
    return jsonify({"ok": True})


# ── Notifications ───────────────────────────────────────────────────────────

@api.route("/notifications", methods=["GET"])
@require_auth
def get_notifications():
    notifs = memory.get_unseen_notifications(30)
    result = []
    for n in notifs:
        d = dict(n)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/notifications/mark-seen", methods=["POST"])
@require_auth
def mark_seen():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    memory.mark_notifications_seen(ids)
    return jsonify({"ok": True})


@api.route("/notifications/counts", methods=["GET"])
@require_auth
def notification_counts():
    counts = memory.get_notification_counts()
    return jsonify(counts)


# ── Inbox Triage ────────────────────────────────────────────────────────────

@api.route("/inbox/scan", methods=["POST"])
@require_auth
def inbox_scan():
    """Deep scan: pull unread from all accounts, triage with Claude, save results."""
    import google_client
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, GOOGLE_ACCOUNTS

    data = request.get_json(silent=True) or {}
    max_per_account = data.get("max_per_account", 50)

    # Pull unread from each connected account
    all_emails = []
    for account_key in GOOGLE_ACCOUNTS:
        try:
            emails = google_client.get_unread_emails_for_account(account_key, max_per_account)
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Inbox scan error for {account_key}: {e}")

    if not all_emails:
        return jsonify({"ok": True, "triaged": 0, "message": "No unread emails found."})

    memory.log_activity("shams", "inbox_scan", f"Scanning {len(all_emails)} unread emails across all accounts")

    # Load inbox persona
    import pathlib
    persona_path = pathlib.Path(__file__).parent / "context" / "inbox_persona.md"
    inbox_persona = persona_path.read_text() if persona_path.exists() else "Triage emails by priority."

    # Triage in batches of 20
    triaged = 0
    client_api = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for i in range(0, len(all_emails), 20):
        batch = all_emails[i:i + 20]
        email_text = "\n\n---\n\n".join(
            f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
            f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
            for e in batch
        )

        prompt = (
            f"Triage these {len(batch)} emails. For EACH email, output a block in this exact format:\n\n"
            f"MESSAGE_ID: <the message_id from above>\n"
            f"PRIORITY: P1|P2|P3|P4\n"
            f"ROUTE: agent1,agent2\n"
            f"SUMMARY: one-line summary\n"
            f"ACTION: recommended action\n"
            f"DRAFT: draft reply (P1/P2 only, or NONE)\n"
            f"---\n\n"
            f"Emails:\n\n{email_text}"
        )

        try:
            response = client_api.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=inbox_persona,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text

            # Parse structured blocks
            email_lookup = {e["message_id"]: e for e in batch}
            blocks = result_text.split("---")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                fields = {}
                for line in block.split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        fields[key.strip().upper()] = val.strip()

                msg_id = fields.get("MESSAGE_ID", "")
                email = email_lookup.get(msg_id)
                if not email and batch:
                    # Try to match by position if MESSAGE_ID parsing failed
                    continue

                priority = fields.get("PRIORITY", "P4")
                if priority not in ("P1", "P2", "P3", "P4"):
                    priority = "P4"
                route_str = fields.get("ROUTE", "shams")
                routed_to = [r.strip() for r in route_str.split(",") if r.strip()]
                action = fields.get("ACTION", "")
                draft = fields.get("DRAFT", "")
                if draft.upper() == "NONE":
                    draft = ""

                if email:
                    memory.save_triage_result(
                        account=email["account"],
                        message_id=msg_id,
                        from_addr=email["from"],
                        subject=email["subject"],
                        snippet=email["snippet"],
                        priority=priority,
                        routed_to=routed_to,
                        action=action,
                        draft_reply=draft,
                    )
                    triaged += 1

        except Exception as e:
            logger.error(f"Triage batch error: {e}")

    memory.log_activity("shams", "inbox_scan", f"Triaged {triaged} emails")
    return jsonify({"ok": True, "triaged": triaged, "total_unread": len(all_emails)})


@api.route("/inbox", methods=["GET"])
@require_auth
def get_inbox():
    priority = request.args.get("priority")
    account = request.args.get("account")
    archived_param = request.args.get("archived")
    archived = None
    if archived_param == "true":
        archived = True
    elif archived_param == "false":
        archived = False
    limit = request.args.get("limit", 100, type=int)
    emails = memory.get_triaged_emails(priority, account, archived, limit)
    result = []
    for e in emails:
        d = dict(e)
        if d.get("triaged_at"):
            d["triaged_at"] = d["triaged_at"].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/inbox/<int:triage_id>/archive", methods=["POST"])
@require_auth
def archive_email(triage_id):
    """Archive in DB AND in Gmail."""
    import google_client
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if e:
        google_client.archive_email(e["account"], e["message_id"])
        memory.log_activity("shams", "email_archived", f"Archived: {e['subject']}")
    memory.mark_email_archived(triage_id)
    return jsonify({"ok": True})


@api.route("/inbox/<int:triage_id>/star", methods=["POST"])
@require_auth
def star_email(triage_id):
    import google_client
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if e:
        google_client.star_email(e["account"], e["message_id"])
        memory.log_activity("shams", "email_starred", f"Starred: {e['subject']}")
    return jsonify({"ok": True})


@api.route("/inbox/<int:triage_id>/draft", methods=["POST"])
@require_auth
def draft_reply(triage_id):
    """Create a draft reply in Gmail."""
    import google_client
    data = request.get_json(silent=True) or {}
    body = data.get("body", "")
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject, draft_reply FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if not e:
        return jsonify({"error": "not found"}), 404
    body = body or e.get("draft_reply") or ""
    if not body:
        return jsonify({"error": "no body"}), 400
    result = google_client.create_draft_reply(e["account"], e["message_id"], body)
    if result:
        memory.log_activity("shams", "draft_created", f"Draft created: {e['subject']}")
        return jsonify({"ok": True, "draft_id": result.get("id")})
    return jsonify({"error": "draft failed"}), 500


@api.route("/inbox/zero/next", methods=["GET"])
@require_auth
def inbox_zero_next():
    """Get the next email for inbox zero session — highest priority unarchived."""
    emails = memory.get_triaged_emails(archived=False, limit=1)
    if not emails:
        return jsonify({"done": True})
    e = dict(emails[0])
    if e.get("triaged_at"):
        e["triaged_at"] = e["triaged_at"].isoformat()
    return jsonify({"done": False, "email": e})


@api.route("/inbox/batch-archive", methods=["POST"])
@require_auth
def batch_archive():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    count = memory.batch_archive_emails(ids)
    memory.log_activity("shams", "inbox_archive", f"Archived {count} emails")
    return jsonify({"ok": True, "archived": count})


# ── Actions ─────────────────────────────────────────────────────────────────

def _auto_advance_mission(action: dict):
    """If an action is linked to a mission, check if all actions are done and advance."""
    mission_id = action.get("mission_id")
    if not mission_id:
        return
    actions = memory.get_actions_for_mission(mission_id)
    all_done = all(a["status"] in ("completed", "rejected") for a in actions)
    if all_done:
        memory.update_mission(mission_id, status="review")
        memory.log_activity(action["agent_name"], "mission_update", f"Mission #{mission_id} → review (all actions complete)")
        memory.create_notification("mission_updated", f"Mission #{mission_id} ready for review", "", "mission", mission_id)


@api.route("/actions", methods=["GET"])
@require_auth
def get_actions():
    status = request.args.get("status")
    agent = request.args.get("agent")
    limit = request.args.get("limit", 50, type=int)
    actions = memory.get_actions(status, agent, limit)
    result = []
    for a in actions:
        d = dict(a)
        for k in ("created_at", "resolved_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if d.get("payload") and isinstance(d["payload"], str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return jsonify(result)


@api.route("/actions/<int:action_id>", methods=["GET"])
@require_auth
def get_action(action_id):
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    d = dict(a)
    for k in ("created_at", "resolved_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    if d.get("payload") and isinstance(d["payload"], str):
        d["payload"] = json.loads(d["payload"])
    return jsonify(d)


@api.route("/actions/<int:action_id>/approve", methods=["POST"])
@require_auth
def approve_action(action_id):
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "pending":
        return jsonify({"error": f"Action is already {a['status']}"}), 400
    memory.update_action_status(action_id, "approved")
    memory.increment_trust(a["agent_name"], "total_approved")
    memory.log_activity(a["agent_name"], "action_approved", f"Action #{action_id} approved: {a['title']}")

    # Check if this is a workflow step — resume workflow
    payload = a.get("payload", {})
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    if payload.get("workflow_id"):
        try:
            from workflow_engine import resume_after_approval
            resume_after_approval(action_id)
        except Exception as e:
            logger.error(f"Workflow resume failed: {e}")

    return jsonify({"ok": True})


@api.route("/actions/<int:action_id>/reject", methods=["POST"])
@require_auth
def reject_action(action_id):
    data = request.get_json(silent=True) or {}
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "pending":
        return jsonify({"error": f"Action is already {a['status']}"}), 400
    memory.update_action_status(action_id, "rejected", data.get("reason", ""))
    memory.increment_trust(a["agent_name"], "total_rejected")
    memory.log_activity(a["agent_name"], "action_rejected", f"Action #{action_id} rejected: {a['title']}")
    return jsonify({"ok": True})


@api.route("/actions/<int:action_id>/execute", methods=["POST"])
@require_auth
def execute_action(action_id):
    """Execute an approved action."""
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "approved":
        return jsonify({"error": f"Action must be approved first (currently {a['status']})"}), 400

    memory.update_action_status(action_id, "executing")
    payload = a["payload"] if isinstance(a["payload"], dict) else json.loads(a["payload"] or "{}")

    try:
        if a["action_type"] == "create_pr":
            import github_client
            import re
            # Generate a branch name from the title
            branch = "shams/" + re.sub(r'[^a-z0-9]+', '-', payload.get("title", "change").lower())[:50].strip('-')
            pr = github_client.create_pr_with_files(
                repo_key=payload["repo"],
                branch_name=branch,
                title=payload["title"],
                description=payload.get("description", ""),
                files=payload.get("files", []),
            )
            result = f"PR #{pr['number']} created: {pr['url']}"
            memory.update_action_status(action_id, "completed", result)
            memory.log_activity("builder", "action_completed", f"Action #{action_id}: {result}")
            memory.create_notification("action_completed", f"PR created: {payload['title']}", result, "action", action_id)
            _auto_advance_mission(a)
            return jsonify({"ok": True, "result": result, "pr": pr})
        else:
            # Generic actions — mark completed, no auto-execution
            memory.update_action_status(action_id, "completed", "Executed manually")
            memory.log_activity(a["agent_name"], "action_completed", f"Action #{action_id} executed")
            memory.create_notification("action_completed", a["title"], "", "action", action_id)
            _auto_advance_mission(a)
            return jsonify({"ok": True, "result": "Action marked as executed"})

    except Exception as e:
        error_msg = str(e)
        memory.update_action_status(action_id, "failed", error_msg)
        memory.log_activity(a["agent_name"], "error", f"Action #{action_id} failed: {error_msg}")
        logger.error(f"Action execution error: {e}", exc_info=True)
        return jsonify({"error": error_msg}), 500


@api.route("/actions/batch-approve", methods=["POST"])
@require_auth
def batch_approve_actions():
    data = request.get_json(silent=True) or {}
    action_ids = data.get("ids", [])
    approved = 0
    for aid in action_ids:
        a = memory.get_action(aid)
        if a and a["status"] == "pending":
            memory.update_action_status(aid, "approved")
            memory.log_activity(a["agent_name"], "action_approved", f"Action #{aid} approved: {a['title']}")
            approved += 1
    return jsonify({"ok": True, "approved": approved})


# ── Trust Scores ────────────────────────────────────────────────────────────

@api.route("/trust", methods=["GET"])
@require_auth
def get_trust():
    scores = memory.get_all_trust_scores()
    result = []
    for s in scores:
        d = dict(s)
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        # Calculate approval rate
        total = d.get("total_approved", 0) + d.get("total_rejected", 0)
        d["approval_rate"] = round(d["total_approved"] / total * 100, 1) if total > 0 else 0
        d["eligible_for_auto"] = d["total_proposed"] >= 10 and d["approval_rate"] >= 90
        result.append(d)
    return jsonify(result)


@api.route("/trust/<agent_name>/auto-approve", methods=["POST"])
@require_auth
def toggle_auto_approve(agent_name):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", False)
    memory.set_auto_approve(agent_name, enabled)
    memory.log_activity("shams", "trust_update",
        f"Auto-approve {'enabled' if enabled else 'disabled'} for {agent_name}")
    return jsonify({"ok": True})


# ── Scheduled Tasks ─────────────────────────────────────────────────────────

@api.route("/scheduled-tasks", methods=["GET"])
@require_auth
def get_scheduled_tasks():
    tasks = memory.get_scheduled_tasks()
    result = []
    for t in tasks:
        d = dict(t)
        for k in ("last_run_at", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/scheduled-tasks/<int:task_id>", methods=["PATCH"])
@require_auth
def update_scheduled_task(task_id):
    data = request.get_json(silent=True) or {}
    memory.update_scheduled_task(task_id, **{k: v for k, v in data.items() if k in ("name", "cron_expression", "prompt", "enabled")})
    if data.get("enabled") is False:
        try:
            from app import remove_dynamic_task
            remove_dynamic_task(task_id)
        except Exception:
            pass
    elif data.get("enabled") is True and data.get("cron_expression"):
        try:
            from app import register_dynamic_task
            register_dynamic_task(task_id, data["cron_expression"], data.get("prompt", ""))
        except Exception:
            pass
    return jsonify({"ok": True})


@api.route("/scheduled-tasks/<int:task_id>", methods=["DELETE"])
@require_auth
def delete_scheduled_task(task_id):
    memory.delete_scheduled_task(task_id)
    try:
        from app import remove_dynamic_task
        remove_dynamic_task(task_id)
    except Exception:
        pass
    return jsonify({"ok": True})


@api.route("/scheduled-tasks/<int:task_id>/run", methods=["POST"])
@require_auth
def run_scheduled_task(task_id):
    from app import _run_dynamic_task
    _run_dynamic_task(task_id)
    return jsonify({"ok": True})


# ── Workflows ──────────────────────────────────────────────────────────────

@api.route("/workflows", methods=["GET"])
@require_auth
def get_workflows():
    status = request.args.get("status")
    workflows = memory.get_workflows(status)
    result = []
    for w in workflows:
        d = dict(w)
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@api.route("/workflows/<int:workflow_id>", methods=["GET"])
@require_auth
def get_workflow(workflow_id):
    wf = memory.get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "not found"}), 404
    for k in ("created_at", "updated_at"):
        if wf.get(k):
            wf[k] = wf[k].isoformat()
    for step in wf.get("steps", []):
        for k in ("started_at", "completed_at"):
            if step.get(k):
                step[k] = step[k].isoformat()
    return jsonify(wf)


@api.route("/workflows/<int:workflow_id>/pause", methods=["POST"])
@require_auth
def pause_workflow(workflow_id):
    memory.update_workflow_status(workflow_id, "paused")
    return jsonify({"ok": True})


@api.route("/workflows/<int:workflow_id>/resume", methods=["POST"])
@require_auth
def resume_workflow(workflow_id):
    memory.update_workflow_status(workflow_id, "active")
    from workflow_engine import run_next_step
    run_next_step(workflow_id)
    return jsonify({"ok": True})


# ── Activity Feed ────────────────────────────────────────────────────────────

@api.route("/feed", methods=["GET"])
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
