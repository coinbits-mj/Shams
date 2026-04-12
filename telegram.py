"""Shams — Telegram message handling, callbacks, voice/photo/doc processing."""

from __future__ import annotations

import os
import base64
import logging
import tempfile
import requests

import config
import memory
import claude_client

logger = logging.getLogger(__name__)

# ── Telegram helpers ─────────────────────────────────────────────────────────

TG_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}" if config.TELEGRAM_BOT_TOKEN else ""
TG_FILE_BASE = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}" if config.TELEGRAM_BOT_TOKEN else ""


def send_telegram_with_buttons(chat_id: str, text: str, buttons: list):
    """Send a Telegram message with inline keyboard buttons."""
    if not TG_BASE:
        return
    keyboard = {"inline_keyboard": [buttons]}
    try:
        r = requests.post(f"{TG_BASE}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "reply_markup": keyboard,
        }, timeout=30)
        if not r.ok:
            logger.error(f"Telegram buttons send failed: {r.status_code}")
    except Exception as e:
        logger.error(f"Telegram buttons send failed: {e}")


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

        if text.startswith("/movie "):
            import media_client
            parts = text[len("/movie "):].strip().rsplit(" ", 1)
            if parts and parts[-1] in ("1080p", "2160p"):
                title, quality = " ".join(parts[:-1]) if len(parts) > 1 else parts[0], parts[-1]
            else:
                title, quality = text[len("/movie "):].strip(), "1080p"
            try:
                result = media_client.add_movie(title=title, quality=quality)
                send_telegram(chat_id, f"Added {result['title']} ({result['quality']}). I'll let you know when it's ready.")
            except Exception as e:
                send_telegram(chat_id, f"Failed to add '{title}': {e}")
            return

        if text.startswith("/tv "):
            import media_client, re
            rest = text[len("/tv "):].strip()
            m = re.match(r"^(?P<title>.+?)(?:\s+s(?P<season>\d+))?(?:\s+(?P<quality>1080p|2160p))?$", rest, re.I)
            if not m:
                send_telegram(chat_id, "Usage: /tv <title> [s<N>] [1080p|2160p]")
                return
            title = m.group("title").strip()
            season = int(m.group("season")) if m.group("season") else None
            quality = m.group("quality") or "1080p"
            try:
                result = media_client.add_tv(title=title, season=season, quality=quality)
                send_telegram(chat_id, f"Added {result['title']} ({result['quality']}). I'll let you know when it's ready.")
            except Exception as e:
                send_telegram(chat_id, f"Failed to add '{title}': {e}")
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


# ── Telegram callback handler ───────────────────────────────────────────────

def _ack_callback(cb_id: str, text: str = "Done"):
    requests.post(f"{TG_BASE}/answerCallbackQuery", json={
        "callback_query_id": cb_id, "text": text,
    }, timeout=10)


def _handle_email_action(action_type: str, triage_id: int, cb_id: str, chat_id: str):
    """Handle inbox zero email actions from Telegram."""
    import google_client
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM shams_email_triage WHERE id = %s", (triage_id,))
        email = cur.fetchone()

    if not email:
        _ack_callback(cb_id, "Email not found")
        return

    if action_type == "earchive":
        success = google_client.archive_email(email["account"], email["message_id"])
        if success:
            memory.mark_email_archived(triage_id)
            memory.log_activity("shams", "email_archived", f"Archived: {email['subject']}")
            _ack_callback(cb_id, "Archived")
            send_telegram(chat_id, f"Archived: {email['subject']}")
        else:
            _ack_callback(cb_id, "Archive failed")

    elif action_type == "estar":
        success = google_client.star_email(email["account"], email["message_id"])
        if success:
            memory.log_activity("shams", "email_starred", f"Starred: {email['subject']}")
            _ack_callback(cb_id, "Starred")
            send_telegram(chat_id, f"Starred: {email['subject']}")
        else:
            _ack_callback(cb_id, "Star failed")

    elif action_type == "esnooze":
        memory.log_activity("shams", "email_snoozed", f"Snoozed: {email['subject']}")
        _ack_callback(cb_id, "Snoozed for 4 hours")
        send_telegram(chat_id, f"Snoozed: {email['subject']}")

    elif action_type == "edraft":
        if email.get("draft_reply"):
            success = google_client.create_draft_reply(email["account"], email["message_id"], email["draft_reply"])
            if success:
                memory.log_activity("shams", "draft_created", f"Draft created for: {email['subject']}")
                _ack_callback(cb_id, "Draft saved to Gmail")
                send_telegram(chat_id, f"Draft saved in Gmail. Open Gmail to review and send.\nSubject: {email['subject']}")
            else:
                _ack_callback(cb_id, "Draft failed")
        else:
            _ack_callback(cb_id, "No draft available")

    elif action_type == "edelegate":
        memory.log_activity("wakil", "email_delegated", f"Email routed to Wakil: {email['subject']}")
        _ack_callback(cb_id, "Routed to Wakil")
        send_telegram(chat_id, f"Routed to Wakil: {email['subject']}")


def handle_callback(callback):
    """Handle inline button presses from Telegram."""
    cb_data = callback.get("data", "")
    cb_id = callback["id"]
    chat_id = str(callback["message"]["chat"]["id"])

    parts = cb_data.split(":")
    if len(parts) != 2:
        return

    action_type, action_id_str = parts
    try:
        action_id = int(action_id_str)
    except ValueError:
        return

    # Email actions (earchive, estar, esnooze, edraft, edelegate)
    if action_type.startswith("e"):
        _handle_email_action(action_type, action_id, cb_id, chat_id)
        return

    a = memory.get_action(action_id)
    if not a or a["status"] != "pending":
        requests.post(f"{TG_BASE}/answerCallbackQuery", json={
            "callback_query_id": cb_id,
            "text": f"Action already {a['status'] if a else 'not found'}",
        }, timeout=10)
        return

    if action_type == "approve":
        memory.update_action_status(action_id, "approved")
        memory.increment_trust(a["agent_name"], "total_approved")
        memory.log_activity(a["agent_name"], "action_approved", f"Action #{action_id} approved via Telegram")
        memory.create_notification("action_approved", f"Approved: {a['title']}", "", "action", action_id)
        requests.post(f"{TG_BASE}/answerCallbackQuery", json={
            "callback_query_id": cb_id, "text": "Approved!",
        }, timeout=10)
        send_telegram(chat_id, f"Action #{action_id} approved: {a['title']}")

        # Check if this is a workflow step — resume workflow
        payload = a.get("payload", {})
        if isinstance(payload, str):
            import json as _json
            payload = _json.loads(payload)
        if payload.get("workflow_id"):
            try:
                from workflow_engine import resume_after_approval
                resume_after_approval(action_id)
            except Exception as e:
                logger.error(f"Workflow resume failed: {e}")

    elif action_type == "reject":
        memory.update_action_status(action_id, "rejected")
        memory.increment_trust(a["agent_name"], "total_rejected")
        memory.log_activity(a["agent_name"], "action_rejected", f"Action #{action_id} rejected via Telegram")
        requests.post(f"{TG_BASE}/answerCallbackQuery", json={
            "callback_query_id": cb_id, "text": "Rejected.",
        }, timeout=10)
        send_telegram(chat_id, f"Action #{action_id} rejected: {a['title']}")
