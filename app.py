"""Shams — MJ's personal AI chief of staff.

Flask server with:
- Telegram bot (long-polling — no webhook/ngrok needed)
- Supports text, images, voice notes, and documents
- Scheduled briefings (morning + evening via Telegram)
- /chat HTTP endpoint for testing
- /health endpoint
"""

from __future__ import annotations

import os
import base64
import logging
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

import config
import memory
import claude_client
import briefing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY


# ── Telegram helpers ─────────────────────────────────────────────────────────

TG_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}" if config.TELEGRAM_BOT_TOKEN else ""
TG_FILE_BASE = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}" if config.TELEGRAM_BOT_TOKEN else ""


def send_telegram(chat_id: str, text: str):
    """Send a Telegram message. Auto-chunks at 4096 chars."""
    if not TG_BASE:
        logger.warning(f"Telegram disabled — would send: {text[:80]}...")
        return
    chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
    for chunk in chunks:
        try:
            r = requests.post(f"{TG_BASE}/sendMessage", json={
                "chat_id": chat_id,
                "text": chunk,
            }, timeout=30)
            if not r.ok:
                logger.error(f"Telegram send failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


def download_telegram_file(file_id: str) -> bytes:
    """Download a file from Telegram by file_id. Returns raw bytes."""
    r = requests.get(f"{TG_BASE}/getFile", params={"file_id": file_id}, timeout=15)
    file_path = r.json()["result"]["file_path"]
    r2 = requests.get(f"{TG_FILE_BASE}/{file_path}", timeout=30)
    return r2.content


# ── Voice transcription ─────────────────────────────────────────────────────

def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe audio using OpenAI Whisper API."""
    if not config.OPENAI_API_KEY:
        return "[Voice note received but transcription not configured — set OPENAI_API_KEY]"

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"file": (filename, open(tmp_path, "rb"), "audio/ogg")},
            data={"model": "whisper-1"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("text", "")
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return f"[Voice transcription failed: {e}]"
    finally:
        os.unlink(tmp_path)


# ── Document text extraction ────────────────────────────────────────────────

def extract_document_text(file_bytes: bytes, file_name: str) -> str:
    """Extract text from a document. Supports PDF and plain text files."""
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""

    if ext == "pdf":
        try:
            import io
            # Try PyPDF2 first
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text[:10000]  # Cap at 10k chars
        except ImportError:
            # Fall back to sending as context description
            return f"[PDF file '{file_name}' received — install PyPDF2 for text extraction]"
        except Exception as e:
            return f"[Could not parse PDF: {e}]"

    elif ext in ("txt", "md", "csv", "json", "py", "js", "html", "xml", "yaml", "yml", "toml", "sql"):
        try:
            return file_bytes.decode("utf-8")[:10000]
        except UnicodeDecodeError:
            return f"[Could not decode {file_name} as text]"

    else:
        return f"[File '{file_name}' received — unsupported format for text extraction]"


# ── Message processing ──────────────────────────────────────────────────────

def process_message(msg: dict, chat_id: str):
    """Process a single Telegram message — text, photo, voice, or document."""

    # --- Text ---
    if msg.get("text"):
        text = msg["text"].strip()
        if text == "/start":
            send_telegram(chat_id, "Shams is here. Talk to me.")
            return
        logger.info(f"Message from MJ: {text[:100]}")
        reply = claude_client.chat(text)
        send_telegram(chat_id, reply)
        logger.info(f"Reply sent ({len(reply)} chars)")
        return

    # --- Photo ---
    if msg.get("photo"):
        # Telegram sends multiple sizes — grab the largest
        photo = msg["photo"][-1]
        file_id = photo["file_id"]
        caption = msg.get("caption", "")
        logger.info(f"Photo from MJ (caption: {caption[:50]})")

        img_bytes = download_telegram_file(file_id)
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        images = [{"data": img_b64, "media_type": "image/jpeg"}]

        reply = claude_client.chat(caption or "What's in this image?", images=images)
        send_telegram(chat_id, reply)
        memory.save_file("photo.jpg", "photo", "image/jpeg", len(img_bytes),
                         telegram_file_id=file_id, summary=reply[:500])
        logger.info(f"Photo reply sent ({len(reply)} chars)")
        return

    # --- Voice note ---
    if msg.get("voice"):
        file_id = msg["voice"]["file_id"]
        duration = msg["voice"].get("duration", 0)
        logger.info(f"Voice note from MJ ({duration}s)")

        audio_bytes = download_telegram_file(file_id)
        transcript = transcribe_voice(audio_bytes)
        logger.info(f"Transcript: {transcript[:100]}")

        # Send transcript + Shams reply
        reply = claude_client.chat(f"[Voice message transcription]: {transcript}")
        send_telegram(chat_id, reply)
        memory.save_file(f"voice_{duration}s.ogg", "voice", "audio/ogg", len(audio_bytes),
                         telegram_file_id=file_id, transcript=transcript, summary=reply[:500])
        logger.info(f"Voice reply sent ({len(reply)} chars)")
        return

    # --- Audio (voice notes sent as audio files) ---
    if msg.get("audio"):
        file_id = msg["audio"]["file_id"]
        logger.info("Audio file from MJ")

        audio_bytes = download_telegram_file(file_id)
        transcript = transcribe_voice(audio_bytes, msg["audio"].get("file_name", "audio.ogg"))
        logger.info(f"Transcript: {transcript[:100]}")

        reply = claude_client.chat(f"[Audio transcription]: {transcript}")
        send_telegram(chat_id, reply)
        memory.save_file(msg["audio"].get("file_name", "audio.ogg"), "voice", "audio/ogg", len(audio_bytes),
                         telegram_file_id=file_id, transcript=transcript, summary=reply[:500])
        logger.info(f"Audio reply sent ({len(reply)} chars)")
        return

    # --- Document ---
    if msg.get("document"):
        doc = msg["document"]
        file_id = doc["file_id"]
        file_name = doc.get("file_name", "unknown")
        mime = doc.get("mime_type", "")
        caption = msg.get("caption", "")
        logger.info(f"Document from MJ: {file_name} ({mime})")

        file_bytes = download_telegram_file(file_id)

        # If it's an image sent as document
        if mime and mime.startswith("image/"):
            img_b64 = base64.b64encode(file_bytes).decode("utf-8")
            images = [{"data": img_b64, "media_type": mime}]
            reply = claude_client.chat(caption or f"I sent you a file: {file_name}", images=images)
        else:
            doc_text = extract_document_text(file_bytes, file_name)
            prompt = f"[Document: {file_name}]\n\n{doc_text}"
            if caption:
                prompt = f"{caption}\n\n{prompt}"
            reply = claude_client.chat(prompt)

        send_telegram(chat_id, reply)
        ftype = "pdf" if file_name.lower().endswith(".pdf") else "document"
        if mime and mime.startswith("image/"):
            ftype = "photo"
        memory.save_file(file_name, ftype, mime, len(file_bytes),
                         telegram_file_id=file_id, summary=reply[:500],
                         transcript=doc_text if not mime.startswith("image/") else "")
        logger.info(f"Document reply sent ({len(reply)} chars)")
        return

    # --- Video note (round video messages) ---
    if msg.get("video_note"):
        send_telegram(chat_id, "I received your video — I can handle voice notes, photos, and documents. Send a voice note or photo instead.")
        return

    logger.info(f"Unhandled message type: {list(msg.keys())}")


# ── Polling ──────────────────────────────────────────────────────────────────

def telegram_polling():
    """Long-poll Telegram for new messages. Runs in a background thread."""
    import time
    offset = 0
    logger.info("Telegram polling started — waiting for messages...")

    while True:
        try:
            r = requests.get(f"{TG_BASE}/getUpdates", params={
                "offset": offset,
                "timeout": 30,
            }, timeout=35)

            if not r.ok:
                logger.error(f"Telegram getUpdates HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(5)
                continue

            data = r.json()
            if not data.get("ok"):
                logger.error(f"Telegram API error: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                msg = update.get("message")
                if not msg:
                    continue

                chat_id = str(msg["chat"]["id"])

                # Only respond to MJ
                if config.TELEGRAM_CHAT_ID and chat_id != config.TELEGRAM_CHAT_ID:
                    logger.info(f"Ignoring message from chat_id {chat_id}")
                    continue

                try:
                    process_message(msg, chat_id)
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    send_telegram(chat_id, f"Error: {e}")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"Telegram polling error: {e}", exc_info=True)
            time.sleep(5)


# ── Dashboard API ────────────────────────────────────────────────────────────

from dashboard_api import api as dashboard_blueprint
app.register_blueprint(dashboard_blueprint)


# ── Health & test endpoints ──────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "shams"}), 200


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


# ── Scheduled jobs ───────────────────────────────────────────────────────────

def send_morning_briefing():
    try:
        text = briefing.generate_morning_briefing()
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, text)
        memory.save_briefing("morning", text)
        memory.log_activity("shams", "briefing", "Morning briefing delivered", {"type": "morning", "channel": "telegram"})
        logger.info("Morning briefing sent")
    except Exception as e:
        memory.log_activity("shams", "error", f"Morning briefing failed: {e}")
        logger.error(f"Morning briefing failed: {e}")


def send_evening_briefing():
    try:
        text = briefing.generate_evening_briefing()
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, text)
        memory.save_briefing("evening", text)
        memory.log_activity("shams", "briefing", "Evening briefing delivered", {"type": "evening", "channel": "telegram"})
        logger.info("Evening briefing sent")
    except Exception as e:
        memory.log_activity("shams", "error", f"Evening briefing failed: {e}")
        logger.error(f"Evening briefing failed: {e}")


# ── Scheduled automation ────────────────────────────────────────────────────

def scheduled_inbox_triage():
    """Every 30 min: scan for new unread, triage, notify P1 via Telegram."""
    try:
        import google_client
        import anthropic
        import pathlib

        all_emails = []
        for account_key in config.GOOGLE_ACCOUNTS:
            try:
                emails = google_client.get_unread_emails_for_account(account_key, 20)
                all_emails.extend(emails)
            except Exception:
                pass

        if not all_emails:
            return

        # Check which message_ids we've already triaged
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            msg_ids = [e["message_id"] for e in all_emails]
            cur.execute("SELECT message_id FROM shams_email_triage WHERE message_id = ANY(%s)", (msg_ids,))
            already_triaged = {r[0] for r in cur.fetchall()}

        new_emails = [e for e in all_emails if e["message_id"] not in already_triaged]
        if not new_emails:
            return

        memory.log_activity("shams", "inbox_triage", f"Auto-triage: {len(new_emails)} new emails")

        persona_path = pathlib.Path(__file__).parent / "context" / "inbox_persona.md"
        inbox_persona = persona_path.read_text() if persona_path.exists() else "Triage emails by priority."
        api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        email_text = "\n\n---\n\n".join(
            f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
            f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
            for e in new_emails[:20]
        )
        prompt = (
            f"Triage these {min(len(new_emails), 20)} emails. For EACH email:\n\n"
            f"MESSAGE_ID: <id>\nPRIORITY: P1|P2|P3|P4\nROUTE: agent1,agent2\n"
            f"SUMMARY: one-line\nACTION: recommended action\nDRAFT: reply or NONE\n---\n\n"
            f"Emails:\n\n{email_text}"
        )

        response = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=4096,
            system=inbox_persona, messages=[{"role": "user", "content": prompt}],
        )
        result_text = response.content[0].text
        email_lookup = {e["message_id"]: e for e in new_emails}

        p1_emails = []
        for block in result_text.split("---"):
            block = block.strip()
            if not block:
                continue
            fields = {}
            for line in block.split("\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    fields[k.strip().upper()] = v.strip()

            msg_id = fields.get("MESSAGE_ID", "")
            email = email_lookup.get(msg_id)
            if not email:
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

            memory.save_triage_result(
                account=email["account"], message_id=msg_id,
                from_addr=email["from"], subject=email["subject"],
                snippet=email["snippet"], priority=priority,
                routed_to=routed_to, action=action, draft_reply=draft,
            )

            if priority == "P1":
                p1_emails.append(f"[{email['account']}] {email['subject']} — {action}")

        # P1 → immediate Telegram notification
        if p1_emails and config.TELEGRAM_CHAT_ID:
            msg = "🔴 **P1 EMAIL ALERT**\n\n" + "\n".join(p1_emails)
            send_telegram(config.TELEGRAM_CHAT_ID, msg)

    except Exception as e:
        logger.error(f"Scheduled inbox triage error: {e}", exc_info=True)


def agent_health_check():
    """Every 5 min: ping Rumi + Leo health endpoints, update agent status."""
    import requests as req
    checks = [
        ("rumi", config.RUMI_BASE_URL),
        ("leo", config.LEO_API_URL),
    ]
    for agent_name, base_url in checks:
        if not base_url:
            continue
        try:
            r = req.get(f"{base_url}/health", timeout=5)
            status = "active" if r.ok else "error"
        except Exception:
            status = "offline"
        memory.update_agent_status(agent_name, status)


def mission_stale_check():
    """Daily: flag missions stuck in 'active' for > 48 hours."""
    try:
        from config import DATABASE_URL
        import psycopg2, psycopg2.extras
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, assigned_agent FROM shams_missions "
                "WHERE status = 'active' AND updated_at < NOW() - INTERVAL '48 hours'"
            )
            stale = cur.fetchall()

        for m in stale:
            memory.log_activity(
                m.get("assigned_agent") or "shams", "alert",
                f"Mission #{m['id']} stale (active >48h): {m['title']}"
            )

        if stale and config.TELEGRAM_CHAT_ID:
            msg = f"⚠️ {len(stale)} stale mission(s) — active for >48h:\n"
            msg += "\n".join(f"• #{m['id']}: {m['title']}" for m in stale)
            send_telegram(config.TELEGRAM_CHAT_ID, msg)

    except Exception as e:
        logger.error(f"Mission stale check error: {e}")


# ── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure database tables exist
    memory.ensure_tables()
    logger.info("Database tables ready")

    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_morning_briefing, "cron", hour=config.BRIEFING_HOUR_UTC, minute=0)
    scheduler.add_job(send_evening_briefing, "cron", hour=config.EVENING_HOUR_UTC, minute=0)
    scheduler.add_job(scheduled_inbox_triage, "interval", minutes=30, id="inbox_triage")
    scheduler.add_job(agent_health_check, "interval", minutes=5, id="health_check")
    scheduler.add_job(mission_stale_check, "cron", hour=12, minute=0, id="stale_check")  # noon UTC
    scheduler.start()
    logger.info(f"Scheduler started — morning @ {config.BRIEFING_HOUR_UTC}:00 UTC, evening @ {config.EVENING_HOUR_UTC}:00 UTC")
    logger.info("Scheduled: inbox triage (30min), health check (5min), stale missions (daily)")

    # Telegram polling in background thread
    if config.TELEGRAM_BOT_TOKEN:
        t = threading.Thread(target=telegram_polling, daemon=True)
        t.start()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")

    # Serve React frontend (SPA catch-all)
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        import os
        static_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
        file_path = os.path.join(static_dir, path)
        if path and os.path.exists(file_path):
            from flask import send_from_directory
            return send_from_directory(static_dir, path)
        index = os.path.join(static_dir, "index.html")
        if os.path.exists(index):
            from flask import send_from_directory
            return send_from_directory(static_dir, "index.html")
        return jsonify({"service": "shams", "status": "no frontend built yet"}), 200

    # Flask
    app.run(host="0.0.0.0", port=config.FLASK_PORT)
