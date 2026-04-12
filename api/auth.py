"""Auth — middleware + login/verify/me/logout routes."""
from __future__ import annotations

import os
import secrets
import logging
from functools import wraps
from flask import Blueprint, request, jsonify, g

import config
import memory

logger = logging.getLogger(__name__)

ALLOWED_EMAIL = "maher@qcitycoffee.com"

bp = Blueprint("auth", __name__, url_prefix="/api")


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

@bp.route("/auth/login", methods=["POST"])
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


@bp.route("/auth/verify", methods=["GET"])
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


@bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"email": g.email})


@bp.route("/auth/logout", methods=["POST"])
@require_auth
def logout():
    token = request.cookies.get("shams_session") or request.headers.get("Authorization", "")[7:]
    memory.delete_session(token)
    return jsonify({"ok": True})
