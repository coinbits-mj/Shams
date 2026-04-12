"""Inbox — email scan, triage, archive, batch."""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("inbox", __name__, url_prefix="/api")


@bp.route("/inbox/scan", methods=["POST"])
@require_auth
def inbox_scan():
    """Deep scan: pull unread from all accounts, triage with Claude, save results."""
    import google_client
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, GOOGLE_ACCOUNTS

    data = request.get_json(silent=True) or {}
    max_per_account = data.get("max_per_account", 50)

    # Pull unread from each connected account
    all_emails = []
    for account_key in GOOGLE_ACCOUNTS:
        try:
            emails = google_client.get_unread_emails_for_account(account_key, max_per_account)
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Inbox scan error for {account_key}: {e}")

    if not all_emails:
        return jsonify({"ok": True, "triaged": 0, "message": "No unread emails found."})

    memory.log_activity("shams", "inbox_scan", f"Scanning {len(all_emails)} unread emails across all accounts")

    # Load inbox persona
    import pathlib
    persona_path = pathlib.Path(__file__).parent.parent / "context" / "inbox_persona.md"
    inbox_persona = persona_path.read_text() if persona_path.exists() else "Triage emails by priority."

    # Triage in batches of 20
    triaged = 0
    client_api = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for i in range(0, len(all_emails), 20):
        batch = all_emails[i:i + 20]
        email_text = "\n\n---\n\n".join(
            f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
            f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
            for e in batch
        )

        prompt = (
            f"Triage these {len(batch)} emails. For EACH email, output a block in this exact format:\n\n"
            f"MESSAGE_ID: <the message_id from above>\n"
            f"PRIORITY: P1|P2|P3|P4\n"
            f"ROUTE: agent1,agent2\n"
            f"SUMMARY: one-line summary\n"
            f"ACTION: recommended action\n"
            f"DRAFT: draft reply (P1/P2 only, or NONE)\n"
            f"---\n\n"
            f"Emails:\n\n{email_text}"
        )

        try:
            response = client_api.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=inbox_persona,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text

            # Parse structured blocks
            email_lookup = {e["message_id"]: e for e in batch}
            blocks = result_text.split("---")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                fields = {}
                for line in block.split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        fields[key.strip().upper()] = val.strip()

                msg_id = fields.get("MESSAGE_ID", "")
                email = email_lookup.get(msg_id)
                if not email and batch:
                    # Try to match by position if MESSAGE_ID parsing failed
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

                if email:
                    memory.save_triage_result(
                        account=email["account"],
                        message_id=msg_id,
                        from_addr=email["from"],
                        subject=email["subject"],
                        snippet=email["snippet"],
                        priority=priority,
                        routed_to=routed_to,
                        action=action,
                        draft_reply=draft,
                    )
                    triaged += 1

        except Exception as e:
            logger.error(f"Triage batch error: {e}")

    memory.log_activity("shams", "inbox_scan", f"Triaged {triaged} emails")
    return jsonify({"ok": True, "triaged": triaged, "total_unread": len(all_emails)})


@bp.route("/inbox", methods=["GET"])
@require_auth
def get_inbox():
    priority = request.args.get("priority")
    account = request.args.get("account")
    archived_param = request.args.get("archived")
    archived = None
    if archived_param == "true":
        archived = True
    elif archived_param == "false":
        archived = False
    limit = request.args.get("limit", 100, type=int)
    emails = memory.get_triaged_emails(priority, account, archived, limit)
    result = []
    for e in emails:
        d = dict(e)
        if d.get("triaged_at"):
            d["triaged_at"] = d["triaged_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/inbox/<int:triage_id>/archive", methods=["POST"])
@require_auth
def archive_email(triage_id):
    """Archive in DB AND in Gmail."""
    import google_client
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if e:
        google_client.archive_email(e["account"], e["message_id"])
        memory.log_activity("shams", "email_archived", f"Archived: {e['subject']}")
    memory.mark_email_archived(triage_id)
    return jsonify({"ok": True})


@bp.route("/inbox/<int:triage_id>/star", methods=["POST"])
@require_auth
def star_email(triage_id):
    import google_client
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if e:
        google_client.star_email(e["account"], e["message_id"])
        memory.log_activity("shams", "email_starred", f"Starred: {e['subject']}")
    return jsonify({"ok": True})


@bp.route("/inbox/<int:triage_id>/draft", methods=["POST"])
@require_auth
def draft_reply(triage_id):
    """Create a draft reply in Gmail."""
    import google_client
    data = request.get_json(silent=True) or {}
    body = data.get("body", "")
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT account, message_id, subject, draft_reply FROM shams_email_triage WHERE id = %s", (triage_id,))
        e = cur.fetchone()
    if not e:
        return jsonify({"error": "not found"}), 404
    body = body or e.get("draft_reply") or ""
    if not body:
        return jsonify({"error": "no body"}), 400
    result = google_client.create_draft_reply(e["account"], e["message_id"], body)
    if result:
        memory.log_activity("shams", "draft_created", f"Draft created: {e['subject']}")
        return jsonify({"ok": True, "draft_id": result.get("id")})
    return jsonify({"error": "draft failed"}), 500


@bp.route("/inbox/zero/next", methods=["GET"])
@require_auth
def inbox_zero_next():
    """Get the next email for inbox zero session — highest priority unarchived."""
    emails = memory.get_triaged_emails(archived=False, limit=1)
    if not emails:
        return jsonify({"done": True})
    e = dict(emails[0])
    if e.get("triaged_at"):
        e["triaged_at"] = e["triaged_at"].isoformat()
    return jsonify({"done": False, "email": e})


@bp.route("/inbox/batch-archive", methods=["POST"])
@require_auth
def batch_archive():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    count = memory.batch_archive_emails(ids)
    memory.log_activity("shams", "inbox_archive", f"Archived {count} emails")
    return jsonify({"ok": True, "archived": count})
