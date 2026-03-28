"""Shams — MJ's personal AI chief of staff.

Flask server with:
- WhatsApp webhook (incoming messages → Claude with memory)
- Scheduled briefings (morning + evening via WhatsApp)
- Health check endpoint
"""

import os
import logging
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client as TwilioClient
from twilio.request_validator import RequestValidator

import config
import memory
import claude_client
import briefing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

twilio_client = TwilioClient(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
twilio_validator = RequestValidator(config.TWILIO_AUTH_TOKEN)


# ── WhatsApp helpers ─────────────────────────────────────────────────────────

def send_whatsapp(to: str, text: str):
    """Send a WhatsApp message via Twilio."""
    # Twilio WhatsApp has a 1600 char limit per message — split if needed
    chunks = [text[i:i+1600] for i in range(0, len(text), 1600)]
    for chunk in chunks:
        try:
            twilio_client.messages.create(
                from_=config.TWILIO_WHATSAPP_NUMBER,
                to=to,
                body=chunk,
            )
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")


# ── Webhook ──────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Handle incoming WhatsApp messages from Twilio."""
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()

    if not body:
        return "", 204

    # Only respond to MJ's number
    if from_number != config.MAHER_WHATSAPP_NUMBER:
        logger.info(f"Ignoring message from {from_number}")
        return "", 204

    logger.info(f"Message from MJ: {body[:100]}")

    try:
        reply = claude_client.chat(body)
        send_whatsapp(from_number, reply)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        send_whatsapp(from_number, f"Error: {e}")

    return "", 204


# ── Health ───────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "shams"}), 200


# ── Scheduled jobs ───────────────────────────────────────────────────────────

def send_morning_briefing():
    try:
        text = briefing.generate_morning_briefing()
        send_whatsapp(config.MAHER_WHATSAPP_NUMBER, text)
        memory.save_briefing("morning", text)
        logger.info("Morning briefing sent")
    except Exception as e:
        logger.error(f"Morning briefing failed: {e}")


def send_evening_briefing():
    try:
        text = briefing.generate_evening_briefing()
        send_whatsapp(config.MAHER_WHATSAPP_NUMBER, text)
        memory.save_briefing("evening", text)
        logger.info("Evening briefing sent")
    except Exception as e:
        logger.error(f"Evening briefing failed: {e}")


# ── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure database tables exist
    memory.ensure_tables()
    logger.info("Database tables ready")

    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_morning_briefing, "cron", hour=config.BRIEFING_HOUR_UTC, minute=0)
    scheduler.add_job(send_evening_briefing, "cron", hour=config.EVENING_HOUR_UTC, minute=0)
    scheduler.start()
    logger.info(f"Scheduler started — morning @ {config.BRIEFING_HOUR_UTC}:00 UTC, evening @ {config.EVENING_HOUR_UTC}:00 UTC")

    # Flask
    app.run(host="0.0.0.0", port=config.FLASK_PORT)
