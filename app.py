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
import threading
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


# ── Recall.ai webhook ──────────────────────────────────────────────────────

@app.route("/api/recall/webhook", methods=["POST"])
def recall_webhook():
    """Handle Recall.ai bot status change webhooks."""
    import meeting_bot
    import recall_client as rc

    data = request.get_json(silent=True) or {}
    event_type = data.get("event") or data.get("type", "")
    bot_data = data.get("data", {}).get("bot") or data.get("data", {})
    bot_id = bot_data.get("id") or data.get("bot_id", "")
    status = bot_data.get("status_code") or data.get("status", "")

    logger.info(f"Recall webhook: event={event_type} bot={bot_id} status={status}")

    if status == "done" and bot_id:
        # Async: process in background to respond to webhook quickly
        threading.Thread(
            target=_process_recall_bot,
            args=(bot_id,),
            daemon=True,
        ).start()

    return jsonify({"ok": True}), 200


def _process_recall_bot(bot_id: str):
    """Background handler: pull transcript, process, deliver."""
    import meeting_bot
    import recall_client as rc
    import json

    try:
        meta_raw = memory.recall(f"recall_bot_{bot_id}")
        if not meta_raw:
            logger.error(f"No event meta found for bot {bot_id}")
            return
        event_meta = json.loads(meta_raw)

        utterances = rc.get_transcript(bot_id)
        transcript_text = rc.format_transcript(utterances)

        if not transcript_text or len(transcript_text) < 50:
            logger.warning(f"Transcript too short for bot {bot_id}, skipping")
            return

        meeting_bot.process_completed_meeting(
            bot_id=bot_id,
            transcript_text=transcript_text,
            event_meta=event_meta,
        )
    except Exception as e:
        logger.error(f"process_recall_bot error: {e}", exc_info=True)
    finally:
        # If this was a voice-sync bot, end the live session
        try:
            import voice_sync
            voice_sync.end_session(bot_id)
        except Exception:
            pass


@app.route("/api/recall/realtime", methods=["POST"])
def recall_realtime_webhook():
    """Receive real-time transcript events for active voice sync sessions.

    Handler is dispatched in a background thread so we return 200 immediately —
    Recall expects fast webhook responses, and the conversation pipeline
    (Claude turn + ElevenLabs TTS + Recall output_audio) takes 2-5 seconds.
    """
    payload = request.get_json(silent=True) or {}
    try:
        threading.Thread(
            target=_run_realtime_handler,
            args=(payload,),
            daemon=True,
        ).start()
    except Exception as e:
        logger.error(f"Realtime webhook dispatch error: {e}", exc_info=True)
    # Always 200 — Recall retries failures and we don't want a flood
    return jsonify({"ok": True}), 200


def _run_realtime_handler(payload: dict):
    """Run voice_sync.handle_realtime_event with broad error catching.

    Lives at module scope so it's monkeypatchable in tests; named so logs are
    greppable.
    """
    try:
        import voice_sync
        voice_sync.handle_realtime_event(payload)
    except Exception as e:
        logger.error(f"Realtime handler error: {e}", exc_info=True)


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
