"""Open commitments — extract promises MJ made in outbound emails.

Scans outbound emails (from MJ's addresses) and uses Haiku to extract commitments
like "I'll send X", "let me get back to you by Friday", "I'll draft the doc tonight".
Stores them in shams_open_commitments so Shams can surface overdue ones during
morning standup.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

import config
import db

logger = logging.getLogger(__name__)

MJ_ADDRESSES = {
    "maher@qcitycoffee.com",
    "maher@coinbits.app",
    "maher.janajri@gmail.com",
}

MODEL = os.environ.get("COMMITMENTS_MODEL", "claude-haiku-4-5")

_SYSTEM_PROMPT = """You extract explicit promises/commitments from emails MJ sent.

A COMMITMENT is something MJ said he WILL DO in the future — not what someone else will do, not a summary, not a question.

Examples of commitments:
- "I'll send you the contract tomorrow" → {"type":"send","text":"send you the contract tomorrow","deadline":"tomorrow"}
- "Let me get back to you by Friday" → {"type":"reply","text":"get back to you","deadline":"Friday"}
- "I'll draft the memo tonight" → {"type":"draft","text":"draft the memo","deadline":"tonight"}
- "I'll check with the lawyer and circle back" → {"type":"check","text":"check with the lawyer and circle back","deadline":null}
- "Will forward you the file" → {"type":"send","text":"forward you the file","deadline":null}

NOT commitments:
- "Thanks for sending" (no future action)
- "Can you let me know?" (asking someone else)
- "FYI" (informational)
- "Sounds good" (acknowledgment)
- Summaries of what was discussed

OUTPUT: strict JSON, no prose, no markdown fences.
{"commitments": [{"type":"send|reply|draft|check|confirm|other","text":"...","deadline":"<ISO date | 'tomorrow' | 'Friday' | 'next week' | null>"}]}

If NO commitments, return {"commitments": []}."""


def _call_haiku(messages: list[dict], system: str) -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL, max_tokens=800, system=system, messages=messages,
    )
    return resp.content[0].text


def _strip_quoted(body: str) -> str:
    """Remove quoted/forwarded content so we only classify what MJ actually wrote.

    Cuts at common markers: 'On <date>, <name> wrote:', '> ' line prefix, '---------- Forwarded',
    '>>> ' prefix. Keeps leading new content only.
    """
    import re
    markers = [
        r"\n\s*On .{0,80}wrote:\s*\n",
        r"\n\s*---------- Forwarded message ----------",
        r"\n\s*-----Original Message-----",
        r"\n\s*Begin forwarded message:",
        r"\n\s*From: .{0,80}\n\s*Sent: ",
        r"\n\s*From: .{0,80}\n\s*Date: ",
    ]
    lowest = len(body)
    for m in markers:
        match = re.search(m, body, flags=re.IGNORECASE)
        if match:
            lowest = min(lowest, match.start())
    body = body[:lowest]
    # Drop lines that start with '>' (quoted text).
    lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def extract_commitments_from_email(email: dict) -> list[dict]:
    """Extract commitments from one outbound email row.

    `email` is a dict with keys: id, from_addr, to_addrs, subject, body, date.
    Returns list of commitment dicts: [{type, text, deadline}, ...].
    On parse/API error, returns [].
    """
    if email.get("from_addr") not in MJ_ADDRESSES:
        return []

    raw_body = email.get("body") or ""
    body = _strip_quoted(raw_body)[:6000]
    if len(body.strip()) < 30:
        return []

    user = (
        f"Subject: {email.get('subject','')}\n"
        f"To: {', '.join(email.get('to_addrs') or [])}\n\n"
        f"Body (MJ's own text only — quoted/forwarded content already stripped):\n{body}"
    )

    try:
        raw = _call_haiku(
            messages=[{"role": "user", "content": user}],
            system=_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error(f"commitment extract API error for archive_id={email.get('id')}: {e}")
        return []

    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]

    try:
        parsed = json.loads(stripped)
    except Exception:
        logger.warning(f"bad JSON from Haiku for archive_id={email.get('id')}: {raw[:200]}")
        return []

    out = []
    for c in parsed.get("commitments", []):
        t = (c.get("type") or "other").lower()
        if t not in {"send", "reply", "draft", "check", "confirm", "other"}:
            t = "other"
        text = (c.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "type": t,
            "text": text[:500],
            "deadline_raw": c.get("deadline"),
        })
    return out


def _resolve_deadline(deadline_raw: Any, promised_at: Any) -> str | None:
    """Best-effort conversion of a fuzzy deadline to an ISO date.

    Returns YYYY-MM-DD or None.
    """
    import datetime as _dt
    if not deadline_raw:
        return None

    s = str(deadline_raw).strip().lower()
    if not s or s == "null":
        return None

    # Already ISO?
    try:
        dt = _dt.datetime.fromisoformat(s.replace("z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        pass

    base = promised_at
    if isinstance(base, str):
        try:
            base = _dt.datetime.fromisoformat(base.replace("z", "+00:00"))
        except Exception:
            base = _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc)
    if not base:
        base = _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc)

    relative = {
        "today": 0, "tomorrow": 1, "tmrw": 1,
        "next week": 7, "next monday": 7, "this week": 3,
        "end of week": 4, "eow": 4, "friday": None, "monday": None,
        "tuesday": None, "wednesday": None, "thursday": None,
        "saturday": None, "sunday": None,
        "next month": 30, "this month": 14,
    }
    if s in relative:
        offset = relative[s]
        if offset is not None:
            return (base + _dt.timedelta(days=offset)).date().isoformat()
        # Named weekday — find next occurrence
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target = weekdays.index(s)
        cur = base.weekday()
        delta = (target - cur) % 7 or 7
        return (base + _dt.timedelta(days=delta)).date().isoformat()

    return None


def _parse_recipient(raw: str | None) -> tuple[str | None, str | None]:
    """Parse a Gmail To-header value like '"Jane Smith" <jane@x.com>' into (name, email)."""
    if not raw:
        return None, None
    s = raw.strip()
    name = None
    email = s
    if "<" in s and ">" in s:
        name_part = s.split("<")[0].strip().strip('"').strip()
        email = s.split("<")[1].split(">")[0].strip()
        if name_part and "@" not in name_part:
            name = name_part
    # If email looks like "name email.com" (no @), it's garbage
    if "@" not in (email or ""):
        return name, None
    return name, email


def persist_commitments(archive_id: int, account: str, recipient_email: str | None,
                        recipient_name: str | None, promised_at: Any,
                        commitments: list[dict]) -> int:
    """Insert commitments into shams_open_commitments.

    Skips duplicates where the same archive_id + commitment_text already exists.
    Returns count of rows inserted.
    """
    if not commitments:
        return 0

    # Clean recipient: if raw includes "<email>" header, parse out the bare email + name
    parsed_name, parsed_email = _parse_recipient(recipient_email)
    if parsed_email:
        recipient_email = parsed_email
    if parsed_name and not recipient_name:
        recipient_name = parsed_name

    inserted = 0
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for c in commitments:
                deadline = _resolve_deadline(c.get("deadline_raw"), promised_at)
                cur.execute(
                    """
                    INSERT INTO shams_open_commitments
                        (source_archive_id, account, recipient_email, recipient_name,
                         commitment_text, commitment_type, promised_at, deadline)
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM shams_open_commitments
                        WHERE source_archive_id = %s
                          AND commitment_text = %s
                    )
                    RETURNING id
                    """,
                    (
                        archive_id, account, recipient_email, recipient_name,
                        c["text"], c["type"], promised_at, deadline,
                        archive_id, c["text"],
                    ),
                )
                if cur.fetchone():
                    inserted += 1
    return inserted


def get_overdue_commitments(days_overdue: int = 3, limit: int = 10) -> list[dict]:
    """Return the oldest N open commitments older than `days_overdue` days.

    Used by morning standup to surface top unfulfilled items.
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, recipient_email, recipient_name, commitment_text,
                       commitment_type, promised_at, deadline,
                       EXTRACT(DAY FROM (NOW() - promised_at))::INT AS days_old
                FROM shams_open_commitments
                WHERE status = 'open'
                  AND promised_at < NOW() - INTERVAL '%s days'
                ORDER BY promised_at ASC
                LIMIT %s
                """,
                (days_overdue, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def mark_fulfilled(commitment_id: int, via_archive_id: int | None = None) -> bool:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE shams_open_commitments
                SET status='fulfilled', fulfilled_at=NOW(),
                    fulfilled_via_archive_id=%s
                WHERE id=%s AND status='open'
                """,
                (via_archive_id, commitment_id),
            )
            return cur.rowcount > 0


def mark_ignored(commitment_id: int) -> bool:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE shams_open_commitments SET status='ignored' WHERE id=%s AND status='open'",
                (commitment_id,),
            )
            return cur.rowcount > 0
