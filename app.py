"""Shams — MJ's personal AI chief of staff.

Flask server with:
- Telegram bot (webhook mode)
- Supports text, images, voice notes, and documents
- Scheduled briefings (morning + evening via Telegram)
- /chat HTTP endpoint for testing
- /health endpoint
- Dashboard API
- Frontend SPA serving
"""

from __future__ import annotations

import os
import logging
import requests
from flask import Flask, request, jsonify, send_from_directory

import config
import memory
import claude_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend/dist")
app.secret_key = config.FLASK_SECRET_KEY


# ── Dashboard API ────────────────────────────────────────────────────────────

from api import register_blueprints
register_blueprints(app)


# ── Health ───────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "shams"}), 200


# ── Telegram webhook ─────────────────────────────────────────────────────────

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """Receive Telegram updates via webhook."""
    from telegram import process_message, handle_callback, send_telegram

    update = request.get_json(silent=True) or {}

    # Handle callback queries (button presses)
    callback = update.get("callback_query")
    if callback:
        logger.info(f"Telegram CALLBACK received: {callback.get('data')}")
        try:
            handle_callback(callback)
        except Exception as e:
            logger.error(f"Webhook callback error: {e}", exc_info=True)
        return jsonify({"ok": True})

    # Handle messages
    msg = update.get("message")
    if not msg:
        return jsonify({"ok": True})

    chat_id = str(msg["chat"]["id"])
    if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
        return jsonify({"ok": True})

    try:
        process_message(msg, chat_id)
    except Exception as e:
        logger.error(f"Webhook process error: {e}", exc_info=True)
        send_telegram(chat_id, f"Error: {e}")

    return jsonify({"ok": True})


# ── Chat HTTP ────────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    """Direct chat endpoint for testing without Telegram."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        reply = claude_client.chat(message)
        return jsonify({"reply": reply})
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure database tables exist
    memory.ensure_tables()
    logger.info("Database tables ready")

    # Start scheduler (briefings, inbox triage, health checks, etc.)
    from scheduler import init_scheduler
    scheduler = init_scheduler()

    # Telegram: register webhook
    from telegram import TG_BASE
    if config.TELEGRAM_BOT_TOKEN:
        try:
            base_url = os.environ.get("APP_URL", "https://app.myshams.ai")
            webhook_url = f"{base_url}/telegram/webhook"
            r = requests.post(
                f"{TG_BASE}/setWebhook",
                json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
                timeout=10,
            )
            if r.ok:
                logger.info(f"Telegram webhook registered: {webhook_url}")
            else:
                logger.error(f"Webhook registration failed: {r.text}")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")

    # Serve React frontend (SPA catch-all)
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        static_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
        file_path = os.path.join(static_dir, path)
        if path and os.path.exists(file_path):
            return send_from_directory(static_dir, path)
        index = os.path.join(static_dir, "index.html")
        if os.path.exists(index):
            return send_from_directory(static_dir, "index.html")
        return jsonify({"service": "shams", "status": "no frontend built yet"}), 200

    # Flask
    app.run(host="0.0.0.0", port=config.FLASK_PORT)
