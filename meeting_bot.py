"""Meeting bot — smart filter, bot dispatch, transcript processing, summarization.

Spec: docs/superpowers/specs/2026-04-24-meeting-bot-design.md
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import anthropic

import config
import db
import memory
import recall_client
import telegram

logger = logging.getLogger(__name__)

MJ_ADDRESSES = {
    "maher@qcitycoffee.com",
    "maher@coinbits.app",
    "maher.janajri@gmail.com",
}

# ── Smart filter ─────────────────────────────────────────────────────────────

def extract_meeting_url(event: dict) -> str | None:
    """Extract a Google Meet or Zoom URL from a calendar event."""
    # Priority 1: hangout_link (Google Meet)
    hangout = (event.get("hangout_link") or "").strip()
    if hangout and "meet.google.com" in hangout:
        return hangout

    # Priority 2: location field, then description
    for field in ("location", "description"):
        text = event.get(field) or ""
        # Google Meet
        m = re.search(r"https://meet\.google\.com/[a-z\-]+", text)
        if m:
            return m.group(0)
        # Zoom
        m = re.search(r"https://[a-z0-9]+\.zoom\.us/j/\S+", text)
        if m:
            return m.group(0).rstrip(")")

    return None


def should_join(event: dict) -> bool:
    """Apply smart filter: should Shams dispatch a bot for this event?"""
    # Must have a meeting link
    if not extract_meeting_url(event):
        return False

    # Must have 2+ attendees (not just MJ)
    attendees = event.get("attendees", [])
    non_self = [a for a in attendees if not a.get("self")]
    if len(non_self) < 1:
        return False

    # All-day event check (start has no "T")
    start_raw = event.get("start", "")
    if "T" not in start_raw:
        return False

    # Duration check
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end_raw = event.get("end", "")
        end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        duration_hours = (end_dt - start_dt).total_seconds() / 3600
        if duration_hours > config.MEETING_MAX_DURATION_HOURS:
            return False
    except Exception:
        pass

    # Exclude patterns
    title = (event.get("summary") or "").lower()
    for pattern in config.MEETING_EXCLUDE_PATTERNS:
        if pattern.strip() and pattern.strip() in title:
            return False

    # MJ declined?
    for a in attendees:
        if a.get("self") and a.get("response") == "declined":
            return False

    return True


# ── Bot dispatch ─────────────────────────────────────────────────────────────

def _bots_today_count() -> int:
    """Count how many bots Shams has dispatched today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"meeting_bots_dispatched_{today}"
    val = memory.recall(key)
    return int(val) if val else 0


def _increment_bots_today():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"meeting_bots_dispatched_{today}"
    current = _bots_today_count()
    memory.remember(key, str(current + 1))


def dispatch_bot(event: dict) -> dict | None:
    """Dispatch a Recall.ai bot for a calendar event.

    Returns the bot dict or None on failure. Checks daily limit.
    """
    if config.MEETING_BOT_DISABLED:
        return None

    if _bots_today_count() >= config.MEETING_BOT_MAX_DAILY:
        logger.warning("Meeting bot daily limit reached")
        return None

    meeting_url = extract_meeting_url(event)
    if not meeting_url:
        return None

    # Schedule join 1 min before start (Recall.ai handles joining at the right time)
    start_raw = event.get("start", "")
    join_at = None
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        join_at = (start_dt - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass

    bot = recall_client.create_bot(
        meeting_url=meeting_url,
        bot_name=config.MEETING_BOT_NAME,
        join_at=join_at,
    )

    if bot:
        _increment_bots_today()
        event_id = event.get("event_id", "")
        title = event.get("summary", "Untitled")
        logger.info(f"Meeting bot dispatched: {title} (bot={bot.get('id')}, event={event_id})")

        # Store bot→event mapping in memory for webhook lookup
        memory.remember(
            f"recall_bot_{bot['id']}",
            json.dumps({
                "event_id": event_id,
                "title": title,
                "start": start_raw,
                "end": event.get("end", ""),
                "attendees": event.get("attendees", []),
                "platform": "google_meet" if "meet.google.com" in meeting_url else "zoom",
            }),
        )

    return bot


# ── Calendar poller integration ──────────────────────────────────────────────

def check_and_dispatch_bots() -> int:
    """Poll calendar for upcoming meetings, dispatch bots for ones passing smart filter.

    Called every 10 min by scheduler. Only dispatches for meetings starting in 5-15 min.
    Returns count of bots dispatched.
    """
    if config.MEETING_BOT_DISABLED:
        return 0

    import google_client

    events = google_client.get_todays_events()
    if not events:
        return 0

    now = datetime.now(timezone.utc)
    dispatched = 0

    for event in events:
        start_raw = event.get("start", "")
        if not start_raw or "T" not in start_raw:
            continue
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        mins_until = (start_dt - now).total_seconds() / 60

        # Only dispatch if meeting is 5-15 min away
        if mins_until < 5 or mins_until > 15:
            continue

        if not should_join(event):
            continue

        event_id = event.get("event_id", "")
        today_str = now.strftime("%Y-%m-%d")
        dispatch_key = f"meeting_bot_dispatched_{event_id}_{today_str}"

        if memory.recall(dispatch_key):
            continue

        bot = dispatch_bot(event)
        if bot:
            memory.remember(dispatch_key, bot.get("id", ""))
            dispatched += 1

            # Send a heads-up via Telegram
            title = event.get("summary", "Untitled")
            telegram.send_message(
                f"\U0001f916 Joining *{title}* in ~{int(mins_until)}min — I'll send notes after.",
                parse_mode="Markdown",
            )

    return dispatched


# ── Meeting type detection ───────────────────────────────────────────────────

LEGAL_DOMAINS = {"sewkis.com", "amslawgrp.com", "cooley.com", "rajehsaadeh.com", "meyersroman.com", "schmendel.com"}
DEAL_KEYWORDS = {"deal", "nda", "loi", "partnership", "acquisition", "alignment", "investment", "term sheet"}
OPS_KEYWORDS = {"standup", "stand-up", "check-in", "check in", "weekly", "ops", "huddle", "daily"}
INTERVIEW_KEYWORDS = {"interview", "barista", "candidate", "hire", "hiring"}

PERSONA_MAP = {
    "legal": "wakil",
    "operations": "rumi",
    "deal": "scout",
    "interview": "shams",
    "general": "shams",
}


def detect_meeting_type(title: str, attendees: list[dict]) -> str:
    """Detect meeting type from title keywords + attendee domains."""
    title_lower = title.lower()

    # Check attendee domains for legal firms
    for a in attendees:
        email = a.get("email", "")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in LEGAL_DOMAINS:
            return "legal"

    # Check title keywords
    for kw in INTERVIEW_KEYWORDS:
        if kw in title_lower:
            return "interview"
    for kw in DEAL_KEYWORDS:
        if kw in title_lower:
            return "deal"
    for kw in OPS_KEYWORDS:
        if kw in title_lower:
            return "operations"

    # Check if any attendee is in the deals table
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                emails = [a.get("email", "") for a in attendees if a.get("email")]
                if emails:
                    cur.execute(
                        "SELECT 1 FROM shams_deals WHERE contact = ANY(%s) AND stage NOT IN ('closed','dead') LIMIT 1",
                        (emails,),
                    )
                    if cur.fetchone():
                        return "deal"
    except Exception:
        pass

    return "general"


# ── Cross-referencing ────────────────────────────────────────────────────────

def _gather_cross_references(attendee_emails: list[str]) -> dict:
    """Pull email history + commitments + missions for attendees."""
    refs = {"emails": {}, "commitments": [], "missions": []}

    if not attendee_emails:
        return refs

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Recent emails (last 30d)
            for email in attendee_emails[:10]:
                cur.execute(
                    """SELECT from_addr, subject, date FROM shams_email_archive
                       WHERE (from_addr = %s OR %s = ANY(to_addrs))
                         AND date > NOW() - INTERVAL '30 days'
                       ORDER BY date DESC LIMIT 3""",
                    (email, email),
                )
                rows = cur.fetchall()
                if rows:
                    refs["emails"][email] = [
                        {"from": r[0], "subject": r[1], "date": str(r[2])[:10]}
                        for r in rows
                    ]

            # Open commitments
            cur.execute(
                """SELECT id, recipient_email, commitment_text, commitment_type,
                          EXTRACT(DAY FROM (NOW() - promised_at))::INT AS days_old
                   FROM shams_open_commitments
                   WHERE status = 'open' AND recipient_email = ANY(%s)""",
                (attendee_emails,),
            )
            refs["commitments"] = [
                {"id": r[0], "to": r[1], "text": r[2], "type": r[3], "days_old": r[4]}
                for r in cur.fetchall()
            ]

            # Active missions
            for email in attendee_emails[:5]:
                name_part = email.split("@")[0]
                cur.execute(
                    "SELECT id, title FROM shams_missions WHERE status='active' AND (title ILIKE %s OR description ILIKE %s) LIMIT 3",
                    (f"%{name_part}%", f"%{name_part}%"),
                )
                for r in cur.fetchall():
                    refs["missions"].append({"id": r[0], "title": r[1]})

    return refs


# ── Summarization ────────────────────────────────────────────────────────────

SUMMARY_MODEL = os.environ.get("MEETING_SUMMARY_MODEL", "claude-haiku-4-5")

_SUMMARY_SYSTEM = """You are Shams, MJ's chief of staff. Summarize this meeting transcript.

OUTPUT strict JSON:
{
  "summary": "2-4 sentence summary of what was discussed and decided",
  "action_items": [{"assignee": "Name", "task": "what they need to do", "deadline": "date or null"}],
  "decisions": [{"decision": "what was decided", "context": "why/context"}],
  "commitments_made": [{"to": "recipient name or email", "text": "what MJ promised", "deadline": "date or null"}],
  "commitments_resolved": [{"commitment_text": "the original promise", "how": "how it was resolved in this meeting"}]
}

RULES:
- action_items: ONLY concrete tasks with a clear owner. Not vague "discuss later."
- commitments_made: ONLY promises MJ explicitly made (not others)
- commitments_resolved: match against OPEN COMMITMENTS provided in context. If someone confirms something MJ promised was done, include it.
- Keep summary SHORT. MJ reads on Telegram.
- If transcript is garbled/empty, return {"summary":"Transcript unavailable","action_items":[],"decisions":[],"commitments_made":[],"commitments_resolved":[]}"""


def process_completed_meeting(
    bot_id: str,
    transcript_text: str,
    event_meta: dict,
) -> dict | None:
    """Process a completed meeting: summarize, cross-ref, store, deliver.

    event_meta: {event_id, title, start, end, attendees, platform}
    Returns the stored meeting notes dict, or None on failure.
    """
    title = event_meta.get("title", "Untitled")
    attendees = event_meta.get("attendees", [])
    attendee_emails = [a.get("email", "") for a in attendees if a.get("email") and a.get("email") not in MJ_ADDRESSES]
    platform = event_meta.get("platform", "google_meet")

    # Detect type + persona
    explicit_type = event_meta.get("meeting_type")
    explicit_persona = event_meta.get("persona")
    if explicit_type:
        meeting_type = explicit_type
    else:
        meeting_type = detect_meeting_type(event_meta.get("title", ""), event_meta.get("attendees", []))
    persona = explicit_persona or PERSONA_MAP.get(meeting_type, "shams")

    # Cross-references
    refs = _gather_cross_references(attendee_emails)

    # Build context for LLM
    ctx_lines = []
    if refs["commitments"]:
        ctx_lines.append("OPEN COMMITMENTS TO ATTENDEES:")
        for c in refs["commitments"]:
            ctx_lines.append(f'  To {c["to"]}: "{c["text"]}" ({c["days_old"]}d ago)')
    if refs["emails"]:
        ctx_lines.append("RECENT EMAIL THREADS:")
        for email, threads in refs["emails"].items():
            for t in threads:
                ctx_lines.append(f"  {t['date']} — {t['from']}: {t['subject']}")
    if refs["missions"]:
        ctx_lines.append("RELATED MISSIONS:")
        for m in refs["missions"]:
            ctx_lines.append(f"  [{m['id']}] {m['title']}")

    persona_note = ""
    if persona == "wakil":
        persona_note = "\nThis is a LEGAL meeting. Focus on legal implications, deadlines, litigation risks."
    elif persona == "rumi":
        persona_note = "\nThis is an OPS meeting. Focus on task status, blockers, accountability."
    elif persona == "scout":
        persona_note = "\nThis is a DEAL meeting. Focus on deal terms, next steps, relationship signals."

    ctx_block = chr(10).join(ctx_lines) if ctx_lines else "(no prior context with these attendees)"
    user_msg = (
        f"Meeting: {title}\n"
        f"Attendees: {', '.join(a.get('name') or a.get('email', '?') for a in attendees)}\n"
        f"{persona_note}\n\n"
        f"{ctx_block}\n\n"
        f"TRANSCRIPT:\n{transcript_text[:30000]}"
    )

    # Call LLM
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=2000,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"Meeting summary LLM error: {e}")
        parsed = {
            "summary": f"Meeting '{title}' completed but summary generation failed.",
            "action_items": [],
            "decisions": [],
            "commitments_made": [],
            "commitments_resolved": [],
        }

    # Auto-create commitments
    created_ids = []
    import commitments as commitments_mod
    for c in parsed.get("commitments_made", []):
        inserted = commitments_mod.persist_commitments(
            archive_id=0,  # no email source
            account="qcc",
            recipient_email=c.get("to"),
            recipient_name=c.get("to"),
            promised_at=event_meta.get("start"),
            commitments=[{"type": "other", "text": c.get("text", ""), "deadline_raw": c.get("deadline")}],
        )
        if inserted:
            created_ids.append(inserted)

    # Auto-resolve commitments
    resolved_ids = []
    for c in parsed.get("commitments_resolved", []):
        for open_c in refs["commitments"]:
            if c.get("commitment_text", "").lower() in open_c.get("text", "").lower():
                commitments_mod.mark_fulfilled(open_c["id"])
                resolved_ids.append(open_c["id"])

    # Calculate duration
    duration_min = None
    try:
        s = datetime.fromisoformat(event_meta["start"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(event_meta["end"].replace("Z", "+00:00"))
        duration_min = int((e - s).total_seconds() / 60)
    except Exception:
        pass

    # Store in DB
    notes_data = {
        "event_id": event_meta.get("event_id"),
        "recall_bot_id": bot_id,
        "title": title,
        "started_at": event_meta.get("start"),
        "ended_at": event_meta.get("end"),
        "duration_min": duration_min,
        "attendees": attendees,
        "platform": platform,
        "transcript": transcript_text[:100000],
        "summary": parsed.get("summary", ""),
        "action_items": parsed.get("action_items", []),
        "decisions": parsed.get("decisions", []),
        "commitments_created": created_ids,
        "commitments_resolved": resolved_ids,
        "persona_used": persona,
        "meeting_type": meeting_type,
    }

    notes_id = memory.insert_meeting_notes(notes_data)
    notes_data["id"] = notes_id

    # Deliver via Telegram
    _send_telegram_summary(notes_data)

    # Deliver via email
    _send_email_summary(notes_data)

    return notes_data


# ── Delivery ─────────────────────────────────────────────────────────────────

def _send_telegram_summary(notes: dict):
    """Send terse meeting summary via Telegram."""
    title = notes.get("title", "Untitled")
    duration = notes.get("duration_min") or "?"
    attendees = notes.get("attendees", [])
    names = [a.get("name") or a.get("email", "?").split("@")[0] for a in attendees if not a.get("self")]

    lines = [f"\U0001f4cb *{title}* just ended ({duration} min)"]
    if names:
        lines.append(f"\U0001f465 {', '.join(names[:8])}")

    decisions = notes.get("decisions", [])
    if decisions:
        lines.append("\n\U0001f4cc Decisions:")
        for d in decisions[:5]:
            lines.append(f"- {d.get('decision', '')}")

    actions = notes.get("action_items", [])
    if actions:
        lines.append("\n\u26a1 Action items:")
        for a in actions[:8]:
            assignee = a.get("assignee", "?")
            task = a.get("task", "")
            lines.append(f"- {assignee}: {task}")

    if notes.get("commitments_created"):
        lines.append(f"\n\u26a0\ufe0f {len(notes['commitments_created'])} new commitment(s) auto-tracked")
    if notes.get("commitments_resolved"):
        lines.append(f"\u2705 {len(notes['commitments_resolved'])} commitment(s) resolved")

    text = "\n".join(lines)
    try:
        telegram.send_message(text, parse_mode="Markdown")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shams_meeting_notes SET telegram_sent=TRUE WHERE id=%s", (notes.get("id"),))
    except Exception as e:
        logger.error(f"Telegram meeting summary failed: {e}")


def _send_email_summary(notes: dict):
    """Send meeting summary email via Resend."""
    if not config.RESEND_API_KEY:
        return

    try:
        import resend
        resend.api_key = config.RESEND_API_KEY

        title = notes.get("title", "Untitled")
        summary = notes.get("summary", "")
        actions = notes.get("action_items", [])
        decisions = notes.get("decisions", [])

        action_html = "".join(f"<li><b>{a.get('assignee','?')}</b>: {a.get('task','')}</li>" for a in actions)
        decision_html = "".join(f"<li>{d.get('decision','')}</li>" for d in decisions)

        decisions_block = f"<h3>Decisions</h3><ul>{decision_html}</ul>" if decisions else ""
        actions_block = f"<h3>Action Items</h3><ul>{action_html}</ul>" if actions else ""

        html = (
            '<div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">'
            f'<h2 style="color: #1a1a2e;">\U0001f4cb {title}</h2>'
            f'<p style="color: #64748b;">{notes.get("duration_min", "?")} min \u00b7 {notes.get("meeting_type", "general")} \u00b7 {notes.get("persona_used", "shams")} lens</p>'
            f"<h3>Summary</h3><p>{summary}</p>"
            f"{decisions_block}"
            f"{actions_block}"
            '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">'
            '<p style="color: #94a3b8; font-size: 12px;">Generated by Shams \u00b7 Reply to query this meeting</p>'
            "</div>"
        )

        resend.Emails.send({
            "from": config.RESEND_FROM_EMAIL,
            "to": ["maher@qcitycoffee.com"],
            "subject": f"\U0001f4cb Meeting Notes: {title}",
            "html": html,
        })

        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shams_meeting_notes SET email_sent=TRUE WHERE id=%s", (notes.get("id"),))
    except Exception as e:
        logger.error(f"Email meeting summary failed: {e}")
