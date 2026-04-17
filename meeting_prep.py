"""Meeting prep — fire a contextual brief ~15 min before each calendar event.

Pulls attendee email history from shams_email_archive, linked missions/deals,
open commitments, then synthesizes a terse Telegram brief via Haiku.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic

import config
import db
import memory
import telegram

logger = logging.getLogger(__name__)

MJ_ADDRESSES = {
    "maher@qcitycoffee.com",
    "maher@coinbits.app",
    "maher.janajri@gmail.com",
}

PREP_MODEL = os.environ.get("MEETING_PREP_MODEL", "claude-haiku-4-5")
PREP_LEAD_MINUTES = int(os.environ.get("MEETING_PREP_LEAD_MINUTES", "15"))


def check_upcoming_meetings() -> int:
    """Poll job: scan calendar for meetings starting in the next 10-20 min.

    Fires a prep brief for any event that hasn't been prepped yet today.
    Designed to run every 10 min via APScheduler interval job.
    Returns count of preps sent.
    """
    import google_client

    events = google_client.get_todays_events()
    if not events:
        return 0

    now = datetime.now(timezone.utc)
    sent = 0

    for event in events:
        start_raw = event.get("start", "")
        if not start_raw or "T" not in start_raw:
            continue
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        mins_until = (start_dt - now).total_seconds() / 60

        # Only prep if meeting is 5-20 min away (window covers our 10-min poll interval)
        if mins_until < 5 or mins_until > 20:
            continue

        event_id = event.get("event_id", "")
        today_str = now.strftime("%Y-%m-%d")
        prep_key = f"meeting_prepped_{event_id}_{today_str}"

        # Skip if already prepped today
        if memory.recall(prep_key):
            continue

        try:
            brief = build_prep_brief(event)
            if brief and config.TELEGRAM_CHAT_ID:
                telegram.send_message(brief, parse_mode="Markdown")
                sent += 1
            memory.remember(prep_key, "sent")
            logger.info(f"meeting prep sent: {event.get('summary')} (starts in {mins_until:.0f}m)")
        except Exception as e:
            logger.error(f"meeting prep failed for {event.get('summary')}: {e}", exc_info=True)

    return sent


def build_prep_brief(event: dict) -> str | None:
    """Build a terse prep brief for one calendar event.

    Returns formatted Telegram message, or None if nothing useful to surface.
    """
    summary = event.get("summary", "Untitled")
    start_raw = event.get("start", "")
    location = event.get("location", "")
    attendees = event.get("attendees", [])
    hangout = event.get("hangout_link", "")

    # Parse start time for display
    start_display = ""
    try:
        dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        start_display = dt.strftime("%-I:%M%p").lower()
    except Exception:
        start_display = start_raw

    # Get attendee emails (exclude MJ)
    attendee_emails = [
        a["email"] for a in attendees
        if a.get("email") and a["email"] not in MJ_ADDRESSES and not a.get("self")
    ]
    attendee_names = {
        a["email"]: a.get("name") or a["email"].split("@")[0]
        for a in attendees if a.get("email")
    }
    rsvp_status = {
        a["email"]: a.get("response", "")
        for a in attendees if a.get("email") and a["email"] not in MJ_ADDRESSES
    }

    # Gather context
    context = _gather_attendee_context(attendee_emails)
    commitments_ctx = _gather_commitments_context(attendee_emails)
    missions_ctx = _gather_missions_context(attendee_emails, summary)

    # RSVP line
    rsvp_parts = []
    for email, status in rsvp_status.items():
        name = attendee_names.get(email, email.split("@")[0])
        icon = {"accepted": "✅", "declined": "❌", "tentative": "❓"}.get(status, "⬜")
        rsvp_parts.append(f"{icon} {name}")

    # Synthesize with Haiku
    synthesized = _synthesize_brief(
        summary=summary,
        start_display=start_display,
        location=location,
        attendee_emails=attendee_emails,
        attendee_names=attendee_names,
        email_context=context,
        commitments_context=commitments_ctx,
        missions_context=missions_ctx,
    )

    # Build message
    lines = [f"📅 *{summary}* — in ~{PREP_LEAD_MINUTES} min"]

    loc_link = ""
    if location:
        loc_link = f" · {location}"
    if hangout:
        loc_link += f" · [Meet link]({hangout})"
    if loc_link:
        lines.append(start_display + loc_link)
    else:
        lines.append(start_display)

    if rsvp_parts:
        lines.append(" ".join(rsvp_parts))

    if synthesized:
        lines.append("")
        lines.append(synthesized)

    return "\n".join(lines)


def _gather_attendee_context(emails: list[str]) -> dict[str, list[dict]]:
    """Pull recent emails involving each attendee from shams_email_archive."""
    if not emails:
        return {}
    result = {}
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for email in emails[:10]:
                cur.execute(
                    """
                    SELECT from_addr, subject, date, category, snippet
                    FROM shams_email_archive
                    WHERE (from_addr = %s OR %s = ANY(to_addrs))
                      AND date > NOW() - INTERVAL '60 days'
                    ORDER BY date DESC LIMIT 5
                    """,
                    (email, email),
                )
                rows = cur.fetchall()
                if rows:
                    result[email] = [
                        {"from": r[0], "subject": r[1], "date": str(r[2])[:10], "category": r[3], "snippet": (r[4] or "")[:150]}
                        for r in rows
                    ]
    return result


def _gather_commitments_context(emails: list[str]) -> list[dict]:
    """Pull open commitments MJ made to any of these attendees."""
    if not emails:
        return []
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recipient_email, commitment_text, commitment_type,
                       promised_at, EXTRACT(DAY FROM (NOW() - promised_at))::INT AS days_old
                FROM shams_open_commitments
                WHERE status = 'open' AND recipient_email = ANY(%s)
                ORDER BY promised_at
                """,
                (emails,),
            )
            return [
                {"to": r[0], "text": r[1], "type": r[2], "days_old": r[4]}
                for r in cur.fetchall()
            ]


def _gather_missions_context(emails: list[str], event_title: str) -> list[dict]:
    """Pull active missions that mention any attendee email or relate to the event title."""
    keywords = event_title.lower().split()[:5]
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            conditions = []
            params = []
            for email in emails[:5]:
                conditions.append("(title ILIKE %s OR description ILIKE %s)")
                params.extend([f"%{email.split('@')[0]}%", f"%{email.split('@')[0]}%"])
            for kw in keywords:
                if len(kw) >= 4:
                    conditions.append("(title ILIKE %s)")
                    params.append(f"%{kw}%")
            if not conditions:
                return []
            where = " OR ".join(conditions)
            cur.execute(
                f"SELECT id, title, description FROM shams_missions WHERE status = 'active' AND ({where}) LIMIT 5",
                params,
            )
            return [{"id": r[0], "title": r[1], "desc": (r[2] or "")[:100]} for r in cur.fetchall()]


def _synthesize_brief(
    summary: str,
    start_display: str,
    location: str,
    attendee_emails: list[str],
    attendee_names: dict,
    email_context: dict,
    commitments_context: list,
    missions_context: list,
) -> str:
    """Use Haiku to synthesize a terse meeting prep.

    Returns 3-5 bullet-pointed lines. Empty string if no useful context.
    """
    if not email_context and not commitments_context and not missions_context:
        return ""

    # Build context block for the LLM
    ctx_lines = []

    if email_context:
        ctx_lines.append("RECENT EMAILS WITH ATTENDEES:")
        for email, threads in email_context.items():
            name = attendee_names.get(email, email)
            ctx_lines.append(f"  {name} ({email}):")
            for t in threads:
                ctx_lines.append(f"    [{t['date']}] {t['from']} — {t['subject']}")

    if commitments_context:
        ctx_lines.append("\nOPEN COMMITMENTS TO ATTENDEES:")
        for c in commitments_context:
            ctx_lines.append(f"  To {c['to']}: \"{c['text']}\" ({c['days_old']}d ago)")

    if missions_context:
        ctx_lines.append("\nRELATED ACTIVE MISSIONS:")
        for m in missions_context:
            ctx_lines.append(f"  [{m['id']}] {m['title']}: {m['desc']}")

    system = """You are Shams, MJ's chief of staff. Write a terse meeting prep.

RULES:
- 3-5 bullet points MAX (emoji prefix each)
- Each bullet: ONE short, specific, actionable insight
- Surface: key context from recent threads, unfulfilled commitments, gaps (no resume, no reply), RSVP concerns
- If there's an open commitment to an attendee, ALWAYS surface it ("⚠️ you told X you'd do Y, 11d ago")
- Suggest ONE concrete action if appropriate ("nudge Mo for resume?", "confirm NDA is signed?")
- NO pleasantries, NO "here's your prep", NO prose — just the bullets
- If no useful context exists, return EMPTY STRING (literally nothing)"""

    user = f"Meeting: {summary}\nTime: {start_display}\nLocation: {location}\n\n{chr(10).join(ctx_lines)}"

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=PREP_MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"meeting prep synthesis error: {e}")
        return ""
