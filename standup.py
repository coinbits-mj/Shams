"""Overnight ops loop + morning standup delivery.

Replaces briefing.py. Two entry points:
- run_overnight_loop(): 3am ET — autonomous data gathering + actions
- deliver_morning_standup(): 7am ET — Telegram delivery with drip-feed
"""
from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone

import anthropic

import config
import memory
import google_client
import mercury_client
import rumi_client
from telegram import send_telegram, send_telegram_with_buttons

logger = logging.getLogger(__name__)


# ── Overnight Loop ─────────────────────────────────────────────────────────


def run_overnight_loop() -> dict:
    """Run the full overnight ops loop. Called at 3am ET by scheduler.

    Steps:
    1. Email sweep — triage all accounts, auto-archive, draft replies
    2. Mercury balance check — pull balances, flag anomalies
    3. Rumi ops check — yesterday's P&L, inventory alerts
    4. Calendar scan — today's events, cross-ref missions, draft prep
    5. Forgetting check — stale missions, approaching deadlines, orphaned loops

    Returns structured results dict. Also saves to shams_overnight_runs.
    """
    run_id = memory.create_overnight_run()
    results = {
        "email": {"reply": [], "read": [], "archived": [], "archive_summary": ""},
        "mercury": {"balances": {}, "alerts": [], "recent_transactions": []},
        "rumi": {"revenue": 0, "cogs": 0, "margin": 0, "orders": 0, "alerts": [], "action_items": []},
        "calendar": {"events": [], "prep_briefs": [], "conflicts": []},
        "reminders": [],
    }
    status = "completed"

    # Step 1: Email sweep
    try:
        results["email"] = _step_email_sweep()
        memory.log_activity("shams", "overnight", "Email sweep complete", {
            "reply": len(results["email"]["reply"]),
            "read": len(results["email"]["read"]),
            "archived": len(results["email"]["archived"]),
        })
    except Exception as e:
        logger.error(f"Overnight email sweep failed: {e}", exc_info=True)
        results["email"]["error"] = str(e)
        status = "partial"

    # Step 2: Mercury balance check
    try:
        results["mercury"] = _step_mercury_check()
        memory.log_activity("shams", "overnight", "Mercury check complete", {
            "alerts": len(results["mercury"]["alerts"]),
        })
    except Exception as e:
        logger.error(f"Overnight Mercury check failed: {e}", exc_info=True)
        results["mercury"]["error"] = str(e)
        status = "partial"

    # Step 3: Rumi ops check
    try:
        results["rumi"] = _step_rumi_check()
        memory.log_activity("shams", "overnight", "Rumi ops check complete")
    except Exception as e:
        logger.error(f"Overnight Rumi check failed: {e}", exc_info=True)
        results["rumi"]["error"] = str(e)
        status = "partial"

    # Step 4: Calendar scan
    try:
        results["calendar"] = _step_calendar_scan()
        memory.log_activity("shams", "overnight", "Calendar scan complete", {
            "events": len(results["calendar"]["events"]),
            "prep_briefs": len(results["calendar"]["prep_briefs"]),
        })
    except Exception as e:
        logger.error(f"Overnight calendar scan failed: {e}", exc_info=True)
        results["calendar"]["error"] = str(e)
        status = "partial"

    # Step 5: Forgetting check
    try:
        results["reminders"] = _step_forgetting_check()
        memory.log_activity("shams", "overnight", "Forgetting check complete", {
            "reminders": len(results["reminders"]),
        })
    except Exception as e:
        logger.error(f"Overnight forgetting check failed: {e}", exc_info=True)
        status = "partial"

    # Save results
    summary = _build_overnight_summary(results)
    memory.update_overnight_run(run_id, status=status, results=results, summary=summary)
    memory.log_activity("shams", "overnight", f"Overnight loop {status}", {"run_id": run_id})

    return results


# ── Step implementations ───────────────────────────────────────────────────


def _step_email_sweep() -> dict:
    """Triage all accounts, auto-archive junk, draft replies."""
    all_emails = []
    for account_key in config.GOOGLE_ACCOUNTS:
        try:
            emails = google_client.get_unread_emails_for_account(account_key, 50)
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Email fetch failed for {account_key}: {e}")

    if not all_emails:
        return {"reply": [], "read": [], "archived": [], "archive_summary": "No unread emails."}

    # Check which we've already triaged
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        msg_ids = [e["message_id"] for e in all_emails]
        cur.execute("SELECT message_id FROM shams_email_triage WHERE message_id = ANY(%s)", (msg_ids,))
        already_triaged = {r[0] for r in cur.fetchall()}

    new_emails = [e for e in all_emails if e["message_id"] not in already_triaged]
    if not new_emails:
        return {"reply": [], "read": [], "archived": [], "archive_summary": "No new emails since last triage."}

    # Classify with Claude
    persona_path = pathlib.Path(__file__).parent / "context" / "inbox_persona.md"
    inbox_persona = persona_path.read_text() if persona_path.exists() else "Triage emails by tier."
    api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    email_text = "\n\n---\n\n".join(
        f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
        f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
        for e in new_emails[:30]
    )
    prompt = (
        f"Triage these {min(len(new_emails), 30)} emails into three tiers:\n\n"
        f"REPLY — Sender is a real person/contact, asks a question or is time-sensitive. "
        f"Draft a reply in Maher's voice (direct, concise, professional).\n"
        f"READ — Informational from a known source. No reply needed but worth seeing.\n"
        f"ARCHIVE — Promotional, spam, automated notifications with no useful info.\n\n"
        f"For EACH email:\n"
        f"MESSAGE_ID: <id>\nTIER: reply|read|archive\nSUMMARY: one-line\nACTION: recommended action\nDRAFT: reply or NONE\n---\n\n"
        f"Emails:\n\n{email_text}"
    )

    response = api_client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=4096,
        system=inbox_persona, messages=[{"role": "user", "content": prompt}],
    )
    result_text = response.content[0].text
    email_lookup = {e["message_id"]: e for e in new_emails}

    reply_list, read_list, archived_list = [], [], []

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

        tier = fields.get("TIER", "archive").lower()
        if tier not in ("reply", "read", "archive"):
            tier = "archive"
        action_text = fields.get("ACTION", "")
        draft = fields.get("DRAFT", "")
        summary_text = fields.get("SUMMARY", "")
        if draft.upper() == "NONE":
            draft = ""

        triage_id = memory.save_triage_result(
            account=email["account"], message_id=msg_id,
            from_addr=email["from"], subject=email["subject"],
            snippet=email["snippet"], tier=tier,
            routed_to=[], action=action_text, draft_reply=draft,
        )

        entry = {
            "triage_id": triage_id, "account": email["account"],
            "message_id": msg_id, "from": email["from"],
            "subject": email["subject"], "summary": summary_text,
            "draft": draft,
        }

        if tier == "reply":
            reply_list.append(entry)
        elif tier == "read":
            read_list.append(entry)
        else:
            # Auto-archive
            try:
                google_client.archive_email(email["account"], msg_id)
                google_client.mark_read(email["account"], msg_id)
                memory.mark_email_archived(triage_id)
            except Exception as e:
                logger.error(f"Auto-archive failed for {msg_id}: {e}")
            archived_list.append(entry)

    # Generate archive summary in Shams's words
    archive_summary = ""
    if archived_list:
        subjects = [a["subject"] for a in archived_list[:20]]
        summary_prompt = (
            f"Summarize what was auto-archived in one casual sentence. "
            f"Group by type (e.g., 'Shopify notifications', 'newsletters'). "
            f"Be specific about the sources.\n\nArchived subjects:\n"
            + "\n".join(f"- {s}" for s in subjects)
        )
        summary_resp = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=200,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        archive_summary = summary_resp.content[0].text

    return {
        "reply": reply_list,
        "read": read_list,
        "archived": archived_list,
        "archive_summary": archive_summary,
    }


def _step_mercury_check() -> dict:
    """Pull Mercury balances and flag anomalies."""
    balances_data = mercury_client.get_balances()
    if not balances_data:
        return {"balances": {}, "alerts": [], "recent_transactions": []}

    balances = {}
    alerts = []
    entities = balances_data.get("entities", [])
    for entity in entities:
        name = entity.get("name", "unknown").lower()
        balance = entity.get("balance", 0)
        balances[name] = balance
        if balance < 5000:
            alerts.append({
                "type": "low_balance",
                "account": name,
                "balance": balance,
                "message": f"{name} balance is ${balance:,.0f} (below $5,000)",
            })

    # Check recent transactions for large amounts
    recent = []
    try:
        txns = mercury_client.get_recent_transactions()
        if txns:
            for txn in txns[:10]:
                amount = abs(txn.get("amount", 0))
                if amount >= 5000:
                    alerts.append({
                        "type": "large_transaction",
                        "account": txn.get("account", ""),
                        "amount": txn.get("amount", 0),
                        "description": txn.get("description", ""),
                        "message": f"Large transaction: ${amount:,.0f} — {txn.get('description', '')}",
                    })
                recent.append(txn)
    except Exception as e:
        logger.error(f"Mercury transactions fetch failed: {e}")

    return {
        "balances": balances,
        "grand_total": balances_data.get("grand_total", sum(balances.values())),
        "alerts": alerts,
        "recent_transactions": recent,
    }


def _step_rumi_check() -> dict:
    """Pull yesterday's P&L, inventory alerts, action items from Rumi."""
    result = {
        "revenue": 0, "cogs": 0, "margin": 0, "orders": 0,
        "wholesale_orders": 0, "alerts": [], "action_items": [],
    }

    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        result["revenue"] = pl.get("revenue", 0)
        result["cogs"] = pl.get("cogs", 0)
        margin = pl.get("net_margin_pct", 0)
        result["margin"] = margin
        result["orders"] = pl.get("order_count", 0)
        result["wholesale_orders"] = pl.get("wholesale_count", 0)

    try:
        action_items = rumi_client.get_action_items()
        if action_items and action_items.get("items"):
            result["action_items"] = action_items["items"][:5]
    except Exception:
        pass

    try:
        inventory = rumi_client.get_inventory_alerts()
        if inventory:
            result["alerts"] = inventory if isinstance(inventory, list) else [inventory]
    except Exception:
        pass

    return result


def _step_calendar_scan() -> dict:
    """Pull today's events, cross-reference with missions, draft prep briefs."""
    events = google_client.get_todays_events()
    if not events:
        return {"events": [], "prep_briefs": [], "conflicts": []}

    formatted_events = []
    for e in events:
        start = e.get("start", "")
        # Extract time from ISO datetime
        if "T" in start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                start_display = dt.strftime("%-I:%M %p")
            except Exception:
                start_display = start
        else:
            start_display = start
        formatted_events.append({
            "summary": e.get("summary", ""),
            "start": start_display,
            "start_raw": e.get("start", ""),
            "end_raw": e.get("end", ""),
            "location": e.get("location", ""),
        })

    # Cross-reference with active missions and open loops
    missions = memory.get_missions(status="active")
    open_loops = memory.get_open_loops()

    prep_briefs = []
    if formatted_events and (missions or open_loops):
        api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        events_text = "\n".join(f"- {e['start']}: {e['summary']}" for e in formatted_events)
        missions_text = "\n".join(f"- [{m['id']}] {m['title']}: {m.get('description', '')[:100]}" for m in missions[:10])
        loops_text = "\n".join(f"- [{l['id']}] {l['title']}: {l.get('context', '')[:100]}" for l in open_loops[:10])

        prompt = (
            f"Today's calendar:\n{events_text}\n\n"
            f"Active missions:\n{missions_text or 'None'}\n\n"
            f"Open loops:\n{loops_text or 'None'}\n\n"
            f"For each meeting that relates to a mission or open loop, write a brief prep doc "
            f"(2-3 paragraphs: context, key points to discuss, what Maher should push for). "
            f"Also flag if any meeting needs prep that isn't covered by a mission.\n\n"
            f"Respond in this format for each meeting that needs prep:\n"
            f"EVENT: <event summary>\nBRIEF: <prep text>\n---"
        )
        response = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content[0].text.split("---"):
            block = block.strip()
            if not block:
                continue
            fields = {}
            current_key = None
            for line in block.split("\n"):
                if line.startswith("EVENT:"):
                    fields["event"] = line[6:].strip()
                    current_key = "event"
                elif line.startswith("BRIEF:"):
                    fields["brief"] = line[6:].strip()
                    current_key = "brief"
                elif current_key == "brief":
                    fields["brief"] = fields.get("brief", "") + "\n" + line
            if fields.get("event") and fields.get("brief"):
                prep_briefs.append(fields)

    return {
        "events": formatted_events,
        "prep_briefs": prep_briefs,
        "conflicts": [],
    }


def _step_forgetting_check() -> list[dict]:
    """Scan active state for things MJ might be forgetting."""
    reminders = []

    # Stale missions (active for 3+ days with no update)
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, title, description, assigned_agent, updated_at FROM shams_missions "
            "WHERE status = 'active' AND updated_at < NOW() - INTERVAL '3 days'"
        )
        stale_missions = cur.fetchall()

        # Approaching deadlines (next 7 days)
        cur.execute(
            "SELECT id, title, description, end_date FROM shams_missions "
            "WHERE status IN ('active', 'assigned', 'inbox') AND end_date IS NOT NULL "
            "AND end_date <= CURRENT_DATE + INTERVAL '7 days' AND end_date >= CURRENT_DATE"
        )
        deadline_missions = cur.fetchall()

        cur.execute(
            "SELECT id, title, deadline FROM shams_deals "
            "WHERE stage NOT IN ('closed', 'dead') AND deadline IS NOT NULL "
            "AND deadline <= CURRENT_DATE + INTERVAL '7 days' AND deadline >= CURRENT_DATE"
        )
        deadline_deals = cur.fetchall()

    for m in stale_missions:
        reminders.append({
            "type": "stale_mission",
            "title": m["title"],
            "why": f"Active but no updates since {m['updated_at'].strftime('%b %d') if m.get('updated_at') else 'unknown'}",
            "mission_id": m["id"],
            "suggestion": "Review and update status, or create next steps",
        })

    for m in deadline_missions:
        reminders.append({
            "type": "deadline",
            "title": m["title"],
            "why": f"Due {m['end_date'].strftime('%b %d') if m.get('end_date') else 'soon'}",
            "mission_id": m["id"],
            "suggestion": "Check progress and prioritize",
        })

    for d in deadline_deals:
        reminders.append({
            "type": "deal_deadline",
            "title": d["title"],
            "why": f"Deadline {d['deadline'].strftime('%b %d') if d.get('deadline') else 'soon'}",
            "suggestion": "Review and take action",
        })

    # Orphaned open loops — open loops with no recent activity
    loops = memory.get_open_loops()
    for loop in loops:
        age_days = (datetime.now(timezone.utc) - loop["created_at"].replace(tzinfo=timezone.utc)).days if loop.get("created_at") else 0
        if age_days > 7:
            reminders.append({
                "type": "orphaned_loop",
                "title": loop["title"],
                "why": f"Open for {age_days} days with no resolution",
                "loop_id": loop["id"],
                "suggestion": "Close, create a mission, or schedule time",
            })

    # Pending actions stuck for 24+ hours
    pending = memory.get_actions(status="pending")
    for a in pending:
        if a.get("created_at"):
            age_hours = (datetime.now(timezone.utc) - a["created_at"].replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age_hours > 24:
                reminders.append({
                    "type": "stale_action",
                    "title": a["title"],
                    "why": f"Pending for {int(age_hours)} hours",
                    "action_id": a["id"],
                    "suggestion": "Approve, reject, or review",
                })

    # If there are reminders that could use work product, draft next steps
    if reminders and any(r["type"] in ("stale_mission", "deadline") for r in reminders):
        _draft_reminder_work_product(reminders)

    return reminders


def _draft_reminder_work_product(reminders: list[dict]):
    """Use Claude to draft next-step recommendations for stale/deadline items."""
    items_needing_drafts = [r for r in reminders if r["type"] in ("stale_mission", "deadline")]
    if not items_needing_drafts:
        return

    api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    items_text = "\n".join(
        f"- {r['title']} ({r['type']}): {r['why']}"
        for r in items_needing_drafts[:5]
    )
    prompt = (
        f"For each of these items Maher might be forgetting, draft a short next-step "
        f"recommendation (2-3 sentences). Be specific and actionable.\n\n{items_text}\n\n"
        f"Format:\nITEM: <title>\nDRAFT: <recommendation>\n---"
    )
    response = api_client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    drafts = {}
    for block in response.content[0].text.split("---"):
        block = block.strip()
        if not block:
            continue
        item_title, draft_text = "", ""
        for line in block.split("\n"):
            if line.startswith("ITEM:"):
                item_title = line[5:].strip()
            elif line.startswith("DRAFT:"):
                draft_text = line[6:].strip()
        if item_title:
            drafts[item_title.lower()] = draft_text

    # Attach drafts to matching reminders
    for r in reminders:
        draft = drafts.get(r["title"].lower(), "")
        if draft:
            r["draft"] = draft


# ── Summary builder ────────────────────────────────────────────────────────


def _build_overnight_summary(results: dict) -> str:
    """Build a human-readable summary of overnight results for logging."""
    parts = []
    email = results.get("email", {})
    parts.append(f"Email: {len(email.get('reply', []))} reply, {len(email.get('read', []))} read, {len(email.get('archived', []))} archived")

    mercury = results.get("mercury", {})
    total = mercury.get("grand_total", 0)
    if total:
        parts.append(f"Cash: ${total:,.0f}")
    if mercury.get("alerts"):
        parts.append(f"Mercury alerts: {len(mercury['alerts'])}")

    rumi = results.get("rumi", {})
    if rumi.get("revenue"):
        parts.append(f"Yesterday: ${rumi['revenue']:,.0f} rev / {rumi.get('margin', 0):.0%} margin")

    calendar = results.get("calendar", {})
    parts.append(f"Calendar: {len(calendar.get('events', []))} events, {len(calendar.get('prep_briefs', []))} prep briefs")

    reminders = results.get("reminders", [])
    if reminders:
        parts.append(f"Reminders: {len(reminders)} items")

    return " | ".join(parts)


# ── Morning Standup Delivery ───────────────────────────────────────────────


def deliver_morning_standup():
    """Deliver the morning standup via Telegram. Called at 7am ET by scheduler.

    Phase 1: Send overview message
    Phase 2: Drip-feed action items (reply drafts, prep briefs, reminders)
    """
    run = memory.get_latest_overnight_run()
    if not run or run.get("status") == "failed":
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID,
                          "Overnight loop didn't run or failed. Check the logs.")
        return

    results = run.get("results", {})
    if isinstance(results, str):
        results = json.loads(results)

    # Phase 1: Overview
    overview = _build_overview_message(results)
    if config.TELEGRAM_CHAT_ID:
        send_telegram(config.TELEGRAM_CHAT_ID, overview)

    # Phase 2: Build action items list and start dripping
    action_items = _build_action_items(results)

    if not action_items:
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, "Nothing needs your input today. Have a good one.")
        return

    # Save standup state and send first item
    memory.set_standup_state({
        "phase": "dripping",
        "run_id": run["id"],
        "items": action_items,
        "current_index": 0,
        "sent_count": 0,
        "handled": {},
    })

    _send_next_standup_item()


def _build_overview_message(results: dict) -> str:
    """Build the single overview Telegram message."""
    from datetime import date
    today = date.today().strftime("%a %b %-d")
    lines = [f"☀️ Morning Standup — {today}\n"]

    # Email
    email = results.get("email", {})
    reply_count = len(email.get("reply", []))
    read_count = len(email.get("read", []))
    archived_count = len(email.get("archived", []))
    lines.append(f"📬 {reply_count} replies drafted · {read_count} to read · {archived_count} archived")
    archive_summary = email.get("archive_summary", "")
    if archive_summary:
        lines.append(f"   {archive_summary}")

    # Mercury
    mercury = results.get("mercury", {})
    total = mercury.get("grand_total", 0)
    if total:
        alert_text = ""
        for alert in mercury.get("alerts", []):
            if alert.get("type") == "low_balance":
                acct = alert.get("account", "").title()
                bal = alert.get("balance", 0)
                alert_text = f" · ⚠️ {acct} low (${bal:,.0f})"
                break
        lines.append(f"💰 Total cash: ${total:,.0f}{alert_text}")

    # Rumi
    rumi = results.get("rumi", {})
    if rumi.get("revenue"):
        margin_pct = rumi.get("margin", 0)
        if isinstance(margin_pct, float) and margin_pct < 1:
            margin_display = f"{margin_pct:.0%}"
        else:
            margin_display = f"{margin_pct:.1f}%"
        orders = rumi.get("orders", 0)
        lines.append(f"📊 Yesterday: ${rumi['revenue']:,.0f} rev / {margin_display} margin / {orders} orders")

    # Calendar
    calendar = results.get("calendar", {})
    events = calendar.get("events", [])
    prep_briefs = calendar.get("prep_briefs", [])
    if events:
        prep_note = f" · ⚠️ {len(prep_briefs)} need prep" if prep_briefs else ""
        lines.append(f"📅 {len(events)} meetings today{prep_note}")

    # Reminders
    reminders = results.get("reminders", [])
    if reminders:
        lines.append(f"🔔 {len(reminders)} things you might be forgetting")

    lines.append("\nWalking you through action items now ↓")

    return "\n".join(lines)


def _build_action_items(results: dict) -> list[dict]:
    """Build ordered list of action items for drip-feed."""
    items = []

    # 1. Reply drafts (most time-sensitive)
    email = results.get("email", {})
    reply_emails = email.get("reply", [])
    for i, r in enumerate(reply_emails):
        items.append({
            "type": "reply",
            "index_label": f"Reply {i+1}/{len(reply_emails)}",
            "from": r.get("from", ""),
            "subject": r.get("subject", ""),
            "draft": r.get("draft", ""),
            "triage_id": r.get("triage_id"),
            "account": r.get("account", ""),
            "message_id": r.get("message_id", ""),
        })

    # 2. Prep briefs
    calendar = results.get("calendar", {})
    for brief in calendar.get("prep_briefs", []):
        items.append({
            "type": "prep",
            "event": brief.get("event", ""),
            "brief": brief.get("brief", ""),
        })

    # 3. Reminders
    for r in results.get("reminders", []):
        items.append({
            "type": "reminder",
            "title": r.get("title", ""),
            "why": r.get("why", ""),
            "suggestion": r.get("suggestion", ""),
            "draft": r.get("draft", ""),
            "mission_id": r.get("mission_id"),
            "loop_id": r.get("loop_id"),
            "action_id": r.get("action_id"),
        })

    return items


def _send_next_standup_item():
    """Send the next action item in the standup drip-feed."""
    state = memory.get_standup_state()
    if not state or state.get("phase") != "dripping":
        return

    items = state.get("items", [])
    idx = state.get("current_index", 0)

    if idx >= len(items):
        _finish_standup(state)
        return

    item = items[idx]
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    if item["type"] == "reply":
        msg = (
            f"📬 {item['index_label']}\n"
            f"From: {item['from']}\n"
            f"Re: {item['subject']}\n\n"
            f"Draft: {item['draft']}"
        )
        buttons = [
            {"text": "✓ Send", "callback_data": f"su_send:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "prep":
        msg = (
            f"📋 Prep: {item['event']}\n\n"
            f"{item['brief']}"
        )
        buttons = [
            {"text": "👍 Looks good", "callback_data": f"su_ok:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "reminder":
        msg = (
            f"🔔 Don't forget: {item['title']}\n"
            f"{item['why']}"
        )
        if item.get("draft"):
            msg += f"\n\nSuggested next steps: {item['draft']}"

        buttons = [
            {"text": "Got it", "callback_data": f"su_ok:{idx}"},
            {"text": "Snooze", "callback_data": f"su_snooze:{idx}"},
        ]
        if item.get("mission_id"):
            pass  # Already a mission
        else:
            buttons.append({"text": "Create mission", "callback_data": f"su_mission:{idx}"})
        send_telegram_with_buttons(chat_id, msg, buttons)


def _finish_standup(state: dict):
    """Send wrap-up message and clear state."""
    handled = state.get("handled", {})
    sent = sum(1 for v in handled.values() if v == "sent")
    skipped = sum(1 for v in handled.values() if v == "skip")
    items = state.get("items", [])

    parts = []
    if sent:
        parts.append(f"{sent} email draft{'s' if sent != 1 else ''} saved to Gmail")
    if skipped:
        parts.append(f"{skipped} skipped")

    # Get archived count from overnight run
    run = memory.get_latest_overnight_run()
    if run:
        results = run.get("results", {})
        if isinstance(results, str):
            results = json.loads(results)
        archived = len(results.get("email", {}).get("archived", []))
        if archived:
            parts.append(f"{archived} archived")

    summary = ", ".join(parts) if parts else "All done"

    if config.TELEGRAM_CHAT_ID:
        send_telegram(config.TELEGRAM_CHAT_ID, f"✅ Standup done. {summary}. Have a good one.")

    memory.clear_standup_state()
