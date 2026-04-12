"""Integrations — status checks + Google OAuth flow."""
from __future__ import annotations

import os
import logging
from flask import Blueprint, request, jsonify

import config
import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("integrations", __name__, url_prefix="/api")


@bp.route("/integrations/status", methods=["GET"])
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


@bp.route("/integrations/google/connect", methods=["GET"])
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


@bp.route("/integrations/google/callback", methods=["GET"])
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
