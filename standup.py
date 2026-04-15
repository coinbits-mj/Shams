"""Overnight ops loop + morning standup delivery.

Replaces briefing.py. Two entry points:
- run_overnight_loop(): 3am ET — autonomous data gathering + actions
- deliver_morning_standup(): 7am ET — Telegram delivery with drip-feed
"""
from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone

import anthropic

import config
import memory
import google_client
import mercury_client
import rumi_client
from telegram import send_telegram, send_telegram_with_buttons

logger = logging.getLogger(__name__)

# ── Trust tier configuration ───────────────────────────────────────────────

TRUST_TIERS = {
    # Low risk — 5 approvals, <20% rejection
    "email_archive": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "mission_create": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "loop_close": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "reminder_ack": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    # Medium risk — 15 approvals, <10% rejection
    "email_draft": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "deal_create": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "deal_update": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "prep_brief": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "relationship_followup": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    # High risk — 30 approvals, <5% rejection
    "scout_outreach": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
    "email_send": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
    "action_execute": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
}

# Map standup item types to trust action types
STANDUP_TRUST_MAP = {
    "reply": "email_draft",
    "prep": "prep_brief",
    "reminder": "reminder_ack",
    "scout_outreach": "scout_outreach",
    "scout_info": "deal_create",
    "relationship": "relationship_followup",
}

# ── P&L configuration ─────────────────────────────────────────────────────

PL_CONFIG = {
    "hourly_rate": 250,
    "time_values": {  # minutes saved per action
        "email_triage": 0.5,
        "draft_reply": 5,
        "prep_brief": 15,
        "reminder": 10,
        "auto_approve": 2,
        "scout_finding": 20,
        "relationship_followup": 10,
    },
    "deal_advance_bonus": 500,
    "token_pricing": {
        "input_per_million": 3.00,
        "output_per_million": 15.00,
    },
    "railway_monthly": 75,
}


def _log_revenue(category: str, count: int, description: str = ""):
    """Log P&L revenue for a batch of actions."""
    if count <= 0:
        return
    minutes = count * PL_CONFIG["time_values"].get(category, 0)
    if minutes <= 0:
        return
    amount = round((minutes / 60) * PL_CONFIG["hourly_rate"], 4)
    memory.log_pl_revenue(category, amount, description, {"count": count, "minutes": minutes})


# ── Relationship intelligence ──────────────────────────────────────────────

NOISE_DOMAINS = {
    "shopify.com", "squareup.com", "klaviyo.com", "recharge.io",
    "github.com", "railway.app", "google.com", "apple.com",
    "amazonses.com", "sendgrid.net", "mailchimp.com", "stripe.com",
    "paypal.com", "intuit.com", "quickbooks.com",
}

NOISE_PREFIXES = {"noreply", "no-reply", "notifications", "support", "info", "mailer-daemon", "postmaster"}


def _is_noise_contact(email: str) -> bool:
    """Check if an email address is noise (automated sender, not a real relationship)."""
    if not email:
        return True
    email = email.lower().strip()
    local = email.split("@")[0] if "@" in email else ""
    domain = email.split("@")[1] if "@" in email else ""
    if local in NOISE_PREFIXES:
        return True
    if domain in NOISE_DOMAINS:
        return True
    return False


def _calculate_warmth(
    last_inbound: datetime | None,
    last_outbound: datetime | None,
    last_meeting: datetime | None,
    touchpoint_count: int,
    channels: list[str],
    has_active_deal: bool,
) -> int:
    """Calculate warmth score 0-100 for a contact."""
    now = datetime.now(timezone.utc)

    # Find most recent touchpoint
    timestamps = [t for t in [last_inbound, last_outbound, last_meeting] if t]
    if not timestamps:
        return 0

    for i, ts in enumerate(timestamps):
        if ts.tzinfo is None:
            timestamps[i] = ts.replace(tzinfo=timezone.utc)

    latest = max(timestamps)
    days_since = (now - latest).days

    # Decay rate: frequent contacts decay slower
    decay_rate = 1.5 if touchpoint_count > 12 else 3.0
    base = max(0, 100 - (days_since * decay_rate))

    # Direction boost: inbound more recent than outbound = they're engaging
    if last_inbound and last_outbound:
        li = last_inbound if last_inbound.tzinfo else last_inbound.replace(tzinfo=timezone.utc)
        lo = last_outbound if last_outbound.tzinfo else last_outbound.replace(tzinfo=timezone.utc)
        if li > lo:
            base = min(100, base + 5)

    # Multi-channel bonus
    if len(channels) >= 2:
        base = min(100, base + 10)

    # Deal floor
    if has_active_deal:
        base = max(20, base)

    return int(base)


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
    # Prevent duplicate runs (e.g., during Railway deploy overlap)
    latest = memory.get_latest_overnight_run()
    if latest and latest.get("started_at"):
        started = latest["started_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
        if age_minutes < 30:
            logger.warning("Overnight loop skipped — another run started %d minutes ago", int(age_minutes))
            return latest.get("results", {}) if isinstance(latest.get("results"), dict) else {}

    run_id = memory.create_overnight_run()
    results = {
        "email": {"reply": [], "read": [], "archived": [], "archive_summary": ""},
        "mercury": {"balances": {}, "alerts": [], "recent_transactions": []},
        "rumi": {"revenue": 0, "cogs": 0, "margin": 0, "orders": 0, "alerts": [], "action_items": []},
        "calendar": {"events": [], "prep_briefs": [], "conflicts": []},
        "reminders": [],
        "scout": {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0},
        "relationships": {"contacts_updated": 0, "new_contacts": 0, "cooling": [], "cold": [], "follow_ups_drafted": 0},
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

    # Step 6: Scout research sweep
    try:
        results["scout"] = _step_scout_sweep()
        memory.log_activity("scout", "overnight", "Scout sweep complete", {
            "findings": len(results["scout"]["findings"]),
            "new_deals": results["scout"]["new_deals"],
            "searches_run": results["scout"]["searches_run"],
        })
    except Exception as e:
        logger.error(f"Overnight Scout sweep failed: {e}", exc_info=True)
        results["scout"] = {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0}
        status = "partial"

    # Step 7: Relationship scan
    try:
        results["relationships"] = _step_relationship_scan()
        memory.log_activity("shams", "overnight", "Relationship scan complete", {
            "contacts_updated": results["relationships"]["contacts_updated"],
            "cooling": len(results["relationships"]["cooling"]),
            "cold": len(results["relationships"]["cold"]),
        })
    except Exception as e:
        logger.error(f"Overnight relationship scan failed: {e}", exc_info=True)
        results["relationships"] = {"contacts_updated": 0, "new_contacts": 0, "cooling": [], "cold": [], "follow_ups_drafted": 0}
        status = "partial"

    # Step 8: Open commitments scan — sent emails from last 24h, extract promises
    try:
        results["commitments"] = _step_commitments_check()
        memory.log_activity("shams", "overnight", "Commitments scan complete", {
            "scanned": results["commitments"]["scanned"],
            "extracted": results["commitments"]["commitments_extracted"],
            "overdue_surfaced": results["commitments"]["overdue_count"],
        })
    except Exception as e:
        logger.error(f"Overnight commitments scan failed: {e}", exc_info=True)
        results["commitments"] = {"scanned": 0, "commitments_extracted": 0, "overdue": [], "overdue_count": 0, "error": str(e)}
        status = "partial"

    # Step 9: Crypto ticker — BTC/ETH spot price + 24h change
    try:
        results["crypto"] = _step_crypto_ticker()
    except Exception as e:
        logger.error(f"Crypto ticker fetch failed: {e}", exc_info=True)
        results["crypto"] = {}

    # Save results
    summary = _build_overnight_summary(results)
    memory.update_overnight_run(run_id, status=status, results=results, summary=summary)
    memory.log_activity("shams", "overnight", f"Overnight loop {status}", {"run_id": run_id})

    return results


# ── Step implementations ───────────────────────────────────────────────────


def _step_email_sweep() -> dict:
    """Nightly email mining — replaces the old triage job.

    Fetches unread messages across all three accounts, runs each through
    email_mining.process_email(), and returns a summary for the standup digest.
    """
    import email_mining
    import google_client

    stats = {
        "per_account": {},
        "categories": {},
        "escalated": 0,
        "archived": 0,
        "errors": 0,
    }

    for account_key in ("qcc", "coinbits", "personal"):
        acct_stats = {"processed": 0, "errors": 0}
        try:
            # Pull up to 100 unread per account per night.
            message_stubs = google_client.get_unread_emails_for_account(account_key, max_results=100)
        except Exception as e:
            logger.error(f"nightly sweep list error {account_key}: {e}")
            stats["errors"] += 1
            stats["per_account"][account_key] = {"error": str(e)}
            continue

        for stub in message_stubs:
            try:
                full = google_client.fetch_full_message(account_key, stub["message_id"])
                if not full:
                    acct_stats["errors"] += 1
                    continue
                result = email_mining.process_email(full)
                acct_stats["processed"] += 1
                stats["categories"][result["category"]] = stats["categories"].get(result["category"], 0) + 1
                if result.get("gmail_archived"):
                    stats["archived"] += 1
                if result.get("escalated"):
                    stats["escalated"] += 1
            except Exception as e:
                logger.error(f"nightly sweep process error {account_key}:{stub.get('message_id')}: {e}")
                acct_stats["errors"] += 1

        stats["per_account"][account_key] = acct_stats

    return stats


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
    """Pull yesterday's P&L + per-location MTD briefing + inventory alerts + actions."""
    result = {
        "revenue": 0, "cogs": 0, "margin": 0, "orders": 0,
        "wholesale_orders": 0, "alerts": [], "action_items": [],
        "locations": {},  # {clifton: {...}, plainfield: {...}}
    }

    # Yesterday's combined P&L (legacy field — kept for existing overview logic)
    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        result["revenue"] = pl.get("revenue", 0)
        result["cogs"] = pl.get("cogs", 0)
        result["margin"] = pl.get("net_margin_pct", 0)
        result["orders"] = pl.get("order_count", 0)
        result["wholesale_orders"] = pl.get("wholesale_count", 0)

    # Per-location MTD briefings — WoW variance + MTD rev + MTD margin
    for loc in ("clifton", "plainfield"):
        try:
            b = rumi_client.get_briefing_summary(location=loc)
            if not b:
                continue
            result["locations"][loc] = {
                "mtd_revenue": b.get("mtd_revenue", 0),
                "mtd_net_profit": b.get("mtd_net_profit", 0),
                "mtd_margin_pct": b.get("mtd_avg_net_margin_pct", 0),
                "mtd_prime_cost_pct": b.get("mtd_avg_prime_cost_pct", 0),
                "mtd_days": b.get("mtd_days", 0),
                "yesterday_revenue": b.get("revenue", 0),
                "yesterday_margin_pct": b.get("net_margin_pct", 0),
                "wow_change_pct": b.get("revenue_wow_change_pct"),
                "prime_cost_pct": b.get("prime_cost_pct"),
            }
        except Exception as e:
            logger.error(f"Rumi briefing fetch failed for {loc}: {e}")

    try:
        action_items = rumi_client.get_action_items()
        if action_items and action_items.get("items"):
            result["action_items"] = action_items["items"][:5]
    except Exception as e:
        logger.error(f"Rumi action items fetch failed: {e}")

    try:
        inventory = rumi_client.get_inventory_alerts()
        if inventory:
            result["alerts"] = inventory if isinstance(inventory, list) else [inventory]
    except Exception as e:
        logger.error(f"Rumi inventory alerts fetch failed: {e}")

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

    # Log P&L revenue
    _log_revenue("prep_brief", len(prep_briefs), f"{len(prep_briefs)} prep briefs drafted")

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
        created = loop.get("created_at")
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days if created else 0
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
            created = a["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
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

    # Log P&L revenue
    _log_revenue("reminder", len(reminders), f"{len(reminders)} reminders caught")

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


# ── Scout sweep ────────────────────────────────────────────────────────────


def _step_scout_sweep() -> dict:
    """Run Scout's daily research sweep across all 6 domains."""
    result = _call_scout()
    # Log P&L revenue
    findings_count = len(result.get("findings", []))
    _log_revenue("scout_finding", findings_count, f"{findings_count} Scout findings")
    return result


def _call_scout() -> dict:
    """Call the Scout agent with a research prompt and parse results."""
    from agents.registry import call_agent

    # Determine which rotating queries to run today (cycle by day of week)
    rotating_queries = [
        '"coffee roaster" restructuring OR closing NJ',
        'NJ small business acquisition opportunities',
        'commercial real estate coffee Middlesex OR Union OR Passaic county',
        'specialty coffee M&A 2026',
        'NJ small business grants OR incentives 2026',
        'coffee equipment auction OR liquidation NJ NY',
        'new coffee roaster opening NJ',
    ]
    day_of_week = datetime.now(timezone.utc).weekday()  # 0=Monday
    # Pick 2 rotating queries based on day
    rotate_start = (day_of_week * 2) % len(rotating_queries)
    todays_rotating = [
        rotating_queries[rotate_start % len(rotating_queries)],
        rotating_queries[(rotate_start + 1) % len(rotating_queries)],
    ]

    core_queries = [
        '"coffee roaster for sale" OR "cafe for sale" NJ 2026',
        'commercial space lease Somerville OR Clifton OR Plainfield NJ',
        'specialty coffee industry news',
    ]
    all_queries = core_queries + todays_rotating

    # Build existing deals context for dedup
    existing_deals = memory.get_deals(limit=50)
    deals_context = ""
    if existing_deals:
        deals_context = "\n\nExisting deals in pipeline (check before creating duplicates):\n"
        for d in existing_deals:
            deals_context += f"- #{d['id']} [{d.get('stage', '?')}] {d['title']}"
            if d.get("location"):
                deals_context += f" ({d['location']})"
            deals_context += "\n"

    prompt = (
        f"Run your daily research sweep. Search each of these queries using web_search, "
        f"then follow up on promising results with fetch_url.\n\n"
        f"Queries to search:\n"
        + "\n".join(f"- {q}" for q in all_queries)
        + f"\n{deals_context}\n"
        f"For each finding worth tracking:\n"
        f"1. Check existing deals with list_deals to avoid duplicates\n"
        f"2. If it's new and scores 6+, create it with create_deal\n"
        f"3. If it matches an existing deal, update it with update_deal (add a note)\n"
        f"4. For deals scored 8+, include a draft outreach message in the notes\n\n"
        f"Score findings 1-10 based on: relevance to QCC, financial fit, location, timing.\n\n"
        f"After all searches, summarize your findings in this exact format "
        f"(one block per finding, separated by ---):\n\n"
        f"FINDING: <title>\n"
        f"TYPE: acquisition|real_estate|partnership|vendor|regulatory|competitor\n"
        f"SCORE: <1-10>\n"
        f"DEAL_ID: <id if created, or EXISTING:<id> if updated, or SKIP if below 6>\n"
        f"SUMMARY: <one paragraph>\n"
        f"OUTREACH: <draft message or NONE>\n"
        f"---"
    )

    # Call Scout agent — it has web_search, fetch_url, create_deal, update_deal, list_deals
    scout_response = call_agent("scout", prompt)

    # Parse findings from Scout's response
    findings = []
    new_deals = 0
    updated_deals = 0

    for block in scout_response.split("---"):
        block = block.strip()
        if not block:
            continue

        fields = {}
        current_key = None
        for line in block.split("\n"):
            matched = False
            for key in ("FINDING", "TYPE", "SCORE", "DEAL_ID", "SUMMARY", "OUTREACH"):
                if line.upper().startswith(key + ":"):
                    _, _, v = line.partition(":")
                    fields[key] = v.strip()
                    current_key = key
                    matched = True
                    break
            if not matched and current_key in ("SUMMARY", "OUTREACH"):
                fields[current_key] = fields.get(current_key, "") + "\n" + line

        if not fields.get("FINDING"):
            continue

        try:
            score = int(fields.get("SCORE", "0"))
        except ValueError:
            score = 0

        deal_id_raw = fields.get("DEAL_ID", "")
        deal_id = None
        if deal_id_raw.startswith("EXISTING:"):
            try:
                deal_id = int(deal_id_raw.split(":")[1])
            except (ValueError, IndexError):
                pass
            updated_deals += 1
        elif deal_id_raw not in ("SKIP", ""):
            try:
                deal_id = int(deal_id_raw)
            except ValueError:
                pass
            new_deals += 1

        outreach = fields.get("OUTREACH", "").strip()
        if outreach.upper() == "NONE":
            outreach = ""

        findings.append({
            "title": fields.get("FINDING", ""),
            "type": fields.get("TYPE", "other"),
            "score": score,
            "deal_id": deal_id,
            "summary": fields.get("SUMMARY", "").strip(),
            "outreach": outreach,
        })

    return {
        "findings": findings,
        "searches_run": len(all_queries),
        "new_deals": new_deals,
        "updated_deals": updated_deals,
    }


# ── Relationship scan ──────────────────────────────────────────────────────


def _step_relationship_scan() -> dict:
    """Scan email + calendar + deals for relationship signals, update warmth scores."""
    contacts_updated = 0
    new_contacts = 0

    # Extract contacts from today's triaged emails (already processed by email sweep)
    try:
        recent_emails = memory.get_triaged_emails(limit=50)
        for email in recent_emails:
            from_addr = email.get("from_addr", "")
            if not from_addr or _is_noise_contact(from_addr):
                continue
            # Extract name from "Name <email>" format
            if "<" in from_addr and ">" in from_addr:
                name = from_addr.split("<")[0].strip().strip('"')
                addr = from_addr.split("<")[1].split(">")[0].strip()
            else:
                name = from_addr.split("@")[0]
                addr = from_addr
            if _is_noise_contact(addr):
                continue
            cid = memory.upsert_contact(name=name, email=addr, source="email", channel="email", direction="inbound")
            if cid:
                contacts_updated += 1
    except Exception as e:
        logger.error(f"Relationship scan email extraction failed: {e}")

    # Extract contacts from today's calendar events
    try:
        events = google_client.get_todays_events()
        for event in events:
            # Calendar events don't have attendee emails in the current API response
            # but the event summary often contains names we can match
            pass  # Attendee extraction requires Calendar API attendees field — future enhancement
    except Exception as e:
        logger.error(f"Relationship scan calendar extraction failed: {e}")

    # Ensure deal contacts are tracked
    try:
        from config import DATABASE_URL
        import psycopg2, psycopg2.extras
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, contact FROM shams_deals WHERE stage NOT IN ('closed', 'dead') AND contact != ''"
            )
            deals = cur.fetchall()
        for deal in deals:
            contact_str = deal.get("contact", "")
            if not contact_str:
                continue
            # Try to extract email from contact field
            email = None
            if "@" in contact_str:
                parts = contact_str.split()
                for p in parts:
                    if "@" in p:
                        email = p.strip("<>(),")
                        break
            name = contact_str.split("<")[0].strip() if "<" in contact_str else contact_str
            if email and not _is_noise_contact(email):
                memory.upsert_contact(name=name, email=email, source="deal", channel="email", deal_id=deal["id"])
    except Exception as e:
        logger.error(f"Relationship scan deal extraction failed: {e}")

    # Recalculate warmth scores
    memory.update_all_warmth_scores()

    # Find cooling and cold contacts
    cooling = memory.get_cooling_contacts(threshold=49)
    cold = [c for c in cooling if c.get("warmth_score", 0) < 25]
    cooling_only = [c for c in cooling if c.get("warmth_score", 0) >= 25]

    # Draft follow-ups for cooling/cold contacts
    follow_ups = []
    if cooling:
        try:
            api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            contacts_text = "\n".join(
                f"- {c['name']} ({c.get('email', c.get('phone', '?'))}) — "
                f"warmth: {c['warmth_score']}/100, "
                f"last contact: {_days_since(c)} days ago, "
                f"channels: {', '.join(c.get('channels', []))}"
                + (f", deal: #{c['deal_id']}" if c.get("deal_id") else "")
                for c in cooling[:5]
            )
            prompt = (
                f"Draft brief, natural follow-up messages for these contacts that Maher is losing touch with. "
                f"Keep it casual and genuine — Maher is direct and concise. One message per contact.\n\n"
                f"{contacts_text}\n\n"
                f"Format:\nNAME: <name>\nDRAFT: <message>\n---"
            )
            response = api_client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content[0].text.split("---"):
                block = block.strip()
                if not block:
                    continue
                name_val, draft_val = "", ""
                for line in block.split("\n"):
                    if line.startswith("NAME:"):
                        name_val = line[5:].strip()
                    elif line.startswith("DRAFT:"):
                        draft_val = line[6:].strip()
                    elif draft_val:
                        draft_val += "\n" + line
                if name_val and draft_val:
                    follow_ups.append({"name": name_val, "draft": draft_val.strip()})
        except Exception as e:
            logger.error(f"Relationship follow-up drafting failed: {e}")

    # Attach drafts to matching contacts
    cooling_with_drafts = []
    for c in cooling:
        entry = {
            "id": c["id"],
            "name": c["name"],
            "email": c.get("email"),
            "phone": c.get("phone"),
            "channels": c.get("channels", []),
            "warmth": c.get("warmth_score", 0),
            "days_silent": _days_since(c),
            "deal_id": c.get("deal_id"),
            "draft": "",
        }
        for fu in follow_ups:
            if fu["name"].lower() in c["name"].lower() or c["name"].lower() in fu["name"].lower():
                entry["draft"] = fu["draft"]
                break
        cooling_with_drafts.append(entry)

    # Log P&L revenue for relationship management
    _log_revenue("reminder", len(cooling), f"{len(cooling)} relationship follow-ups surfaced")

    total_contacts = memory.get_contact_count()

    return {
        "contacts_updated": contacts_updated,
        "new_contacts": new_contacts,
        "total_contacts": total_contacts,
        "cooling": [c for c in cooling_with_drafts if c["warmth"] >= 25],
        "cold": [c for c in cooling_with_drafts if c["warmth"] < 25],
        "follow_ups_drafted": len(follow_ups),
    }


def _days_since(contact: dict) -> int:
    """Calculate days since last interaction with a contact."""
    now = datetime.now(timezone.utc)
    timestamps = []
    for field in ("last_inbound", "last_outbound", "last_meeting"):
        ts = contact.get(field)
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamps.append(ts)
    if not timestamps:
        return 999
    latest = max(timestamps)
    return (now - latest).days


# ── Crypto ticker step ─────────────────────────────────────────────────────


def _step_crypto_ticker() -> dict:
    """Fetch BTC + ETH spot price + 24h change from CoinGecko. Returns {} on any failure."""
    import requests
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin,ethereum",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"CoinGecko unreachable: {e}")
        return {}
    if not r.ok:
        logger.error(f"CoinGecko error {r.status_code}")
        return {}
    try:
        data = r.json()
    except Exception:
        return {}
    out = {}
    if "bitcoin" in data:
        out["btc"] = {
            "usd": data["bitcoin"].get("usd"),
            "change_24h": data["bitcoin"].get("usd_24h_change"),
        }
    if "ethereum" in data:
        out["eth"] = {
            "usd": data["ethereum"].get("usd"),
            "change_24h": data["ethereum"].get("usd_24h_change"),
        }
    return out


# ── Open commitments step ─────────────────────────────────────────────────


def _step_commitments_check() -> dict:
    """Nightly: pull last 24h of sent emails, extract commitments, surface overdue.

    Returns: {scanned, commitments_extracted, overdue, overdue_count}
    """
    import commitments
    import google_client

    stats = {
        "scanned": 0,
        "commitments_extracted": 0,
        "errors": 0,
        "per_account": {},
    }

    accounts = ("qcc", "coinbits", "personal")
    for account_key in accounts:
        acct_stats = {"scanned": 0, "extracted": 0, "errors": 0}
        try:
            stubs = google_client.search_emails(
                query=f"in:sent newer_than:2d",
                max_results=50,
            )
            stubs = [s for s in stubs if s.get("account") == account_key]
        except Exception as e:
            logger.error(f"commitments: gmail search error {account_key}: {e}")
            stats["errors"] += 1
            continue

        for stub in stubs:
            mid = stub.get("message_id")
            try:
                full = google_client.fetch_full_message(account_key, mid)
                if not full or full.get("from_addr") not in commitments.MJ_ADDRESSES:
                    continue

                # Ensure archive row exists (idempotent)
                archive_id = memory.insert_email_archive({
                    **full,
                    "category": "other",
                    "priority": "P3",
                    "entities": {},
                    "processed_model": "commitments-step",
                })
                if not archive_id:
                    continue

                full["id"] = archive_id
                c = commitments.extract_commitments_from_email(full)
                if c:
                    inserted = commitments.persist_commitments(
                        archive_id=archive_id,
                        account=account_key,
                        recipient_email=(full.get("to_addrs") or [None])[0],
                        recipient_name=full.get("from_name"),
                        promised_at=full.get("date"),
                        commitments=c,
                    )
                    acct_stats["extracted"] += inserted
                    stats["commitments_extracted"] += inserted

                acct_stats["scanned"] += 1
                stats["scanned"] += 1
            except Exception as e:
                logger.error(f"commitments: process error {account_key}:{mid}: {e}")
                acct_stats["errors"] += 1
                stats["errors"] += 1

        stats["per_account"][account_key] = acct_stats

    # Pull the top overdue commitments for the morning standup
    try:
        overdue = commitments.get_overdue_commitments(days_overdue=3, limit=5)
    except Exception as e:
        logger.error(f"commitments: get_overdue error: {e}")
        overdue = []

    stats["overdue"] = overdue
    stats["overdue_count"] = len(overdue)
    return stats


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

    scout = results.get("scout", {})
    if scout.get("findings"):
        parts.append(f"Scout: {len(scout['findings'])} findings, {scout.get('new_deals', 0)} new deals")

    rels = results.get("relationships", {})
    total_cooling = len(rels.get("cooling", [])) + len(rels.get("cold", []))
    if total_cooling:
        parts.append(f"Relationships: {total_cooling} need attention")

    return " | ".join(parts)


# ── Morning Standup Delivery ───────────────────────────────────────────────


def deliver_morning_standup():
    """Deliver the morning standup via Telegram. Called at 7am ET by scheduler.

    Phase 1: Send overview message
    Phase 2: Drip-feed action items (reply drafts, prep briefs, reminders)
    """
    # Prevent duplicate standup delivery
    old_state = memory.get_standup_state()
    if old_state and old_state.get("phase") == "dripping":
        started_run = old_state.get("run_id")
        latest = memory.get_latest_overnight_run()
        if latest and latest.get("id") == started_run:
            logger.warning("Standup already in progress for run #%s — skipping", started_run)
            return

    # Clear any stale standup state from a previous day
    if old_state:
        memory.clear_standup_state()

    run = memory.get_latest_overnight_run()
    if not run or run.get("status") == "failed":
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID,
                          "Overnight loop didn't run or failed. Check the logs.")
        return

    # Guard against stale overnight data (e.g., if overnight loop didn't run today)
    started = run.get("started_at")
    if started and started < datetime.now(timezone.utc) - timedelta(hours=6):
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID,
                          "Overnight loop didn't run today — last run is stale. Check the logs.")
        return

    results = run.get("results", {})
    if isinstance(results, str):
        results = json.loads(results)

    # Phase 1: Build action items, filtering auto-approved
    action_items, auto_approved = _build_action_items_with_trust(results)

    # Execute auto-approved items silently
    if auto_approved:
        _execute_auto_approved(auto_approved)

    # Phase 2: Overview
    overview = _build_overview_message(results)
    if config.TELEGRAM_CHAT_ID:
        if auto_approved:
            auto_summary = _build_auto_approve_summary(auto_approved)
            overview += f"\n✅ {len(auto_approved)} auto-approved ({auto_summary})"
        send_telegram(config.TELEGRAM_CHAT_ID, overview)

    if not action_items:
        # Everything was auto-approved or nothing needed input
        auto_summary = _build_auto_approve_summary(auto_approved)
        if config.TELEGRAM_CHAT_ID:
            if auto_approved:
                send_telegram(config.TELEGRAM_CHAT_ID,
                              f"✅ Standup done. Everything auto-approved today. {auto_summary}. Have a good one.")
            else:
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

    # Rumi — per-location MTD line (preferred when available), fallback to yesterday-only
    rumi = results.get("rumi", {})
    locs = rumi.get("locations") or {}

    def _fmt_money(n: float) -> str:
        n = n or 0
        if abs(n) >= 1000:
            return f"${n/1000:.1f}K"
        return f"${n:,.0f}"

    def _fmt_loc(label: str, data: dict) -> str:
        rev = data.get("mtd_revenue", 0)
        mgn = data.get("mtd_margin_pct", 0)
        wow = data.get("wow_change_pct")
        chunks = [f"{label} {_fmt_money(rev)} MTD {mgn:.0f}%"]
        if wow is not None and abs(wow) >= 5:
            sign = "-" if wow < 0 else "+"
            marker = " ⚠️" if wow <= -10 else ""
            chunks.append(f"WoW {sign}{abs(wow):.0f}%{marker}")
        return " · ".join(chunks)

    if locs:
        loc_lines = []
        if locs.get("clifton"):
            loc_lines.append(_fmt_loc("Clif", locs["clifton"]))
        if locs.get("plainfield"):
            loc_lines.append(_fmt_loc("Plain", locs["plainfield"]))
        if loc_lines:
            lines.append(f"📊 {' · '.join(loc_lines)}")
    elif rumi.get("revenue"):
        # Fallback: no per-location data, show old yesterday-only line
        margin_pct = rumi.get("margin", 0)
        margin_display = f"{margin_pct:.0%}" if isinstance(margin_pct, float) and margin_pct < 1 else f"{margin_pct:.1f}%"
        orders = rumi.get("orders", 0)
        lines.append(f"📊 Yesterday: ${rumi['revenue']:,.0f} / {margin_display} / {orders} orders")

    # Calendar
    calendar = results.get("calendar", {})
    events = calendar.get("events", [])
    prep_briefs = calendar.get("prep_briefs", [])
    if events:
        prep_note = f" · ⚠️ {len(prep_briefs)} need prep" if prep_briefs else ""
        lines.append(f"📅 {len(events)} meetings today{prep_note}")

    # Reminders — surface top 1-2 actual items, not just a count
    reminders = results.get("reminders", [])
    if reminders:
        # Prefer deadline-based reminders (sorted by soonest), fallback to stale missions
        def _rem_key(r):
            t = r.get("type", "")
            # deadlines first (closer = higher priority), then stale
            if t in {"mission_deadline", "deal_deadline"}:
                return (0, r.get("title", "") or "")
            return (1, r.get("title", "") or "")
        top = sorted(reminders, key=_rem_key)[:2]
        chunks = []
        for r in top:
            title = (r.get("title") or "?").strip()
            if len(title) > 32:
                title = title[:32] + "…"
            chunks.append(title)
        more = len(reminders) - len(top)
        tail = f" · +{more}" if more > 0 else ""
        lines.append(f"🔔 {' · '.join(chunks)}{tail}")

    # Scout
    scout = results.get("scout", {})
    new_deals = scout.get("new_deals", 0)
    updated_deals = scout.get("updated_deals", 0)
    if new_deals or updated_deals:
        parts = []
        if new_deals:
            parts.append(f"{new_deals} new lead{'s' if new_deals != 1 else ''}")
        if updated_deals:
            parts.append(f"{updated_deals} deal{'s' if updated_deals != 1 else ''} updated")
        lines.append(f"🔍 {' · '.join(parts)}")

    # Relationships
    rels = results.get("relationships", {})
    cooling_count = len(rels.get("cooling", []))
    cold_count = len(rels.get("cold", []))
    if cooling_count or cold_count:
        parts_rel = []
        if cooling_count:
            parts_rel.append(f"{cooling_count} cooling")
        if cold_count:
            parts_rel.append(f"{cold_count} going cold")
        lines.append(f"🤝 {' · '.join(parts_rel)}")

    # Crypto ticker (BTC + ETH)
    crypto = results.get("crypto") or {}
    if crypto.get("btc"):
        def _fmt_crypto(tag: str, data: dict) -> str:
            usd = data.get("usd") or 0
            pct = data.get("change_24h")
            if usd >= 10000:
                price = f"${usd/1000:.0f}K"
            elif usd >= 1000:
                price = f"${usd/1000:.1f}K"
            else:
                price = f"${usd:,.0f}"
            if pct is not None:
                sign = "-" if pct < 0 else "+"
                return f"{tag} {price} ({sign}{abs(pct):.1f}%)"
            return f"{tag} {price}"
        parts_c = [_fmt_crypto("BTC", crypto["btc"])]
        if crypto.get("eth"):
            parts_c.append(_fmt_crypto("ETH", crypto["eth"]))
        lines.append(f"🪙 {' · '.join(parts_c)}")

    # Open commitments (unfulfilled promises MJ made in sent emails)
    commit = results.get("commitments", {})
    overdue = commit.get("overdue", []) or []
    if overdue:
        # Format: 🔴 Open: Annie→Mo 14d · Brandon 7 items
        chunks = []
        for oc in overdue[:3]:
            recip = (oc.get("recipient_name") or oc.get("recipient_email") or "?").split("@")[0][:20]
            days = oc.get("days_old") or 0
            chunks.append(f"{recip} {days}d")
        more = len(overdue) - 3
        tail = f" · +{more} more" if more > 0 else ""
        lines.append(f"🔴 Open: {' · '.join(chunks)}{tail}")

    # Daily P&L
    try:
        pl = memory.get_pl_daily()
        if pl["revenue"] > 0 or pl["costs"] > 0:
            roi = f"{pl['revenue'] / pl['costs']:.0f}x" if pl["costs"] > 0 else "∞"
            lines.append(f"💎 Yesterday: earned ${pl['revenue']:,.2f}, cost ${pl['costs']:,.2f} — ROI: {roi}")
    except Exception:
        pass  # Skip P&L line if no data yet

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

    # 4. Scout findings (high-score with outreach, then informational)
    scout = results.get("scout", {})
    for f in scout.get("findings", []):
        if f.get("score", 0) >= 8 and f.get("outreach"):
            items.append({
                "type": "scout_outreach",
                "title": f.get("title", ""),
                "finding_type": f.get("type", ""),
                "score": f.get("score", 0),
                "summary": f.get("summary", ""),
                "outreach": f.get("outreach", ""),
                "deal_id": f.get("deal_id"),
            })
        elif f.get("score", 0) >= 6:
            items.append({
                "type": "scout_info",
                "title": f.get("title", ""),
                "finding_type": f.get("type", ""),
                "score": f.get("score", 0),
                "summary": f.get("summary", ""),
                "deal_id": f.get("deal_id"),
            })

    # 5. Relationship follow-ups
    rels = results.get("relationships", {})
    for c in rels.get("cold", []) + rels.get("cooling", []):
        items.append({
            "type": "relationship",
            "contact_id": c.get("id"),
            "name": c.get("name", ""),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "channels": c.get("channels", []),
            "warmth": c.get("warmth", 0),
            "days_silent": c.get("days_silent", 0),
            "deal_id": c.get("deal_id"),
            "draft": c.get("draft", ""),
        })

    return items


def _build_action_items_with_trust(results: dict) -> tuple[list[dict], list[dict]]:
    """Build action items, separating auto-approved from manual.

    Returns (manual_items, auto_approved_items).
    """
    all_items = _build_action_items(results)
    manual = []
    auto_approved = []

    for item in all_items:
        action_type = STANDUP_TRUST_MAP.get(item["type"])
        if action_type and memory.should_auto_approve_action(action_type):
            auto_approved.append(item)
        else:
            manual.append(item)

    return manual, auto_approved


def _execute_auto_approved(items: list[dict]):
    """Execute auto-approved standup items silently."""
    for item in items:
        try:
            if item["type"] == "reply":
                # Save draft to Gmail
                if item.get("message_id") and item.get("draft"):
                    google_client.create_draft_reply(item["account"], item["message_id"], item["draft"])
                    memory.log_activity("shams", "auto_approved", f"Draft auto-saved: {item.get('subject', '')}")
            elif item["type"] == "prep":
                memory.log_activity("shams", "auto_approved", f"Prep brief auto-approved: {item.get('event', '')}")
            elif item["type"] == "reminder":
                memory.log_activity("shams", "auto_approved", f"Reminder auto-acked: {item.get('title', '')}")
            elif item["type"] == "scout_outreach":
                memory.log_activity("shams", "auto_approved", f"Scout outreach auto-approved: {item.get('title', '')}")
            elif item["type"] == "scout_info":
                memory.log_activity("shams", "auto_approved", f"Scout finding auto-acked: {item.get('title', '')}")
        except Exception as e:
            logger.error(f"Auto-approve execution failed for {item.get('type')}: {e}")

    # Log P&L revenue for auto-approved items
    _log_revenue("auto_approve", len(items), f"{len(items)} actions auto-approved")


def _build_auto_approve_summary(items: list[dict]) -> str:
    """Build a short summary of what was auto-approved."""
    counts = {}
    for item in items:
        label = {
            "reply": "email draft",
            "prep": "prep brief",
            "reminder": "reminder",
            "scout_outreach": "scout outreach",
            "scout_info": "scout finding",
        }.get(item["type"], item["type"])
        counts[label] = counts.get(label, 0) + 1

    parts = []
    for label, count in counts.items():
        parts.append(f"{count} {label}{'s' if count != 1 else ''}")
    return ", ".join(parts) if parts else "0 items"


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
            {"text": "✓ Save draft", "callback_data": f"su_send:{idx}"},
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

    elif item["type"] == "scout_outreach":
        msg = (
            f"🔍 Scout: {item['title']}\n"
            f"{item['summary']}\n"
            f"Score: {item['score']}/10\n\n"
            f"Draft outreach: {item['outreach']}"
        )
        buttons = [
            {"text": "✓ Save draft", "callback_data": f"su_ok:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
            {"text": "Create mission", "callback_data": f"su_mission:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "scout_info":
        msg = (
            f"🔍 Scout: {item['title']}\n"
            f"{item['summary']}\n"
            f"Score: {item['score']}/10"
        )
        buttons = [
            {"text": "Got it", "callback_data": f"su_ok:{idx}"},
            {"text": "Create mission", "callback_data": f"su_mission:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "relationship":
        cold_label = "Going cold" if item["warmth"] < 25 else "Cooling"
        msg = (
            f"🤝 {cold_label}: {item['name']}\n"
            f"Last contact: {item['days_silent']} days ago\n"
            f"Warmth: {item['warmth']}/100"
        )
        if item.get("draft"):
            msg += f"\n\nDraft: {item['draft']}"

        buttons = []
        channels = item.get("channels", [])
        if "email" in channels and item.get("email"):
            buttons.append({"text": "📧 Email", "callback_data": f"su_email:{idx}"})
        if "imessage" in channels and item.get("phone"):
            buttons.append({"text": "💬 iMessage", "callback_data": f"su_imsg:{idx}"})
        if "whatsapp" in channels and item.get("phone"):
            buttons.append({"text": "💚 WhatsApp", "callback_data": f"su_wa:{idx}"})
        if not buttons and item.get("email"):
            buttons.append({"text": "📧 Email", "callback_data": f"su_email:{idx}"})
        buttons.append({"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"})
        buttons.append({"text": "Skip", "callback_data": f"su_skip:{idx}"})
        buttons.append({"text": "😴 7d", "callback_data": f"su_snooze7:{idx}"})
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


# ── Evening Briefing (kept from briefing.py) ───────────────────────────────


def generate_evening_briefing() -> str:
    """Generate an evening wrap-up briefing."""
    import claude_client
    import leo_client

    parts = []

    # Tomorrow's calendar
    events = google_client.get_upcoming_events(1)
    if events:
        parts.append("## Tomorrow's Calendar")
        for e in events:
            parts.append(f"- {e['start']} — {e['summary']}")

    # MTD P&L
    mtd = rumi_client.get_monthly_pl()
    if mtd:
        parts.append(f"\n## MTD P&L")
        parts.append(f"- Revenue: ${mtd.get('revenue', 0):,.0f}")
        parts.append(f"- Net margin: {mtd.get('net_margin_pct', 0):.1f}%")

    # Open loops
    loops = memory.get_open_loops()
    if loops:
        parts.append("\n## Open Loops (still open)")
        for loop in loops:
            parts.append(f"- [{loop['id']}] {loop['title']}")

    context = "\n".join(parts)
    return claude_client.generate_briefing("evening", context)
