"""Shams — APScheduler setup, all scheduled jobs, dynamic task loading."""

from __future__ import annotations

import logging
import pathlib

import config
import memory
import claude_client
from telegram import send_telegram, send_telegram_with_buttons

logger = logging.getLogger(__name__)

_scheduler_ref = {"instance": None}  # module-level reference for dynamic task registration


# ── Briefings ────────────────────────────────────────────────────────────────

def run_overnight():
    """Run overnight ops loop. Scheduled at 3am ET."""
    import standup
    try:
        standup.run_overnight_loop()
        logger.info("Overnight loop completed")
    except Exception as e:
        memory.log_activity("shams", "error", f"Overnight loop failed: {e}")
        logger.error(f"Overnight loop failed: {e}")


def send_evening_briefing():
    import standup
    try:
        text = standup.generate_evening_briefing()
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, text)
        memory.save_briefing("evening", text)
        memory.log_activity("shams", "briefing", "Evening briefing delivered", {"type": "evening", "channel": "telegram"})
        logger.info("Evening briefing sent")
    except Exception as e:
        memory.log_activity("shams", "error", f"Evening briefing failed: {e}")
        logger.error(f"Evening briefing failed: {e}")


def deliver_standup():
    """Deliver morning standup via Telegram. Scheduled at 7am ET."""
    import standup
    try:
        standup.deliver_morning_standup()
        memory.log_activity("shams", "standup", "Morning standup delivered")
        logger.info("Morning standup delivered")
    except Exception as e:
        memory.log_activity("shams", "error", f"Morning standup delivery failed: {e}")
        logger.error(f"Morning standup delivery failed: {e}")


# ── P&L + Hosting ─────────────────────────────────────────────────────────

def send_weekly_pl_digest():
    """Send weekly P&L digest via Telegram. Scheduled Sunday 9pm ET (1am UTC Monday)."""
    try:
        pl = memory.get_pl_weekly()
        running = memory.get_pl_running_total()

        lines = ["📊 Shams Weekly P&L\n"]

        lines.append(f"Revenue: ${pl['revenue']:,.2f}")
        for cat, data in pl.get("revenue_breakdown", {}).items():
            label = cat.replace("_", " ").title()
            lines.append(f"  {label}: {data['count']}x (${data['total']:,.2f})")

        lines.append(f"\nCosts: ${pl['costs']:,.2f}")
        for cat, total in pl.get("cost_breakdown", {}).items():
            label = cat.replace("_", " ").title()
            if cat == "claude_api":
                tokens = pl.get("tokens", {})
                input_k = tokens.get("input", 0) // 1000
                output_k = tokens.get("output", 0) // 1000
                lines.append(f"  {label}: ${total:,.2f} ({input_k}K input / {output_k}K output)")
            else:
                lines.append(f"  {label}: ${total:,.2f}")

        net = pl["net"]
        roi = f"{pl['revenue'] / pl['costs']:.1f}x" if pl["costs"] > 0 else "∞"
        lines.append(f"\nNet: ${net:,.2f}")
        lines.append(f"ROI: {roi}")
        lines.append(f"\nRunning total: ${running['net']:,.2f}")

        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, "\n".join(lines))
        memory.log_activity("shams", "pl_digest", f"Weekly P&L: ${net:,.2f} net, {roi} ROI")
        logger.info("Weekly P&L digest sent")
    except Exception as e:
        logger.error(f"Weekly P&L digest failed: {e}", exc_info=True)


def log_daily_hosting():
    """Log daily Railway hosting cost. Scheduled at midnight UTC."""
    try:
        memory.log_pl_hosting_cost()
    except Exception as e:
        logger.error(f"Hosting cost logging failed: {e}")


# ── Dynamic scheduled tasks ────────────────────────────────────────────────

def _run_dynamic_task(task_id: int):
    """Execute a dynamic scheduled task."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM shams_scheduled_tasks WHERE id = %s AND enabled = TRUE", (task_id,))
        task = cur.fetchone()
    if not task:
        return

    try:
        result = claude_client.chat(task["prompt"])
        memory.mark_task_run(task_id, result)
        memory.log_activity(task["agent_name"], "scheduled_task", f"Task #{task_id} ({task['name']}): {result[:100]}")

        # Send result to Telegram
        if config.TELEGRAM_CHAT_ID and result:
            send_telegram(config.TELEGRAM_CHAT_ID, f"[Scheduled: {task['name']}]\n\n{result}")
    except Exception as e:
        logger.error(f"Scheduled task #{task_id} failed: {e}")
        memory.mark_task_run(task_id, f"Error: {e}")


def register_dynamic_task(task_id: int, cron_expression: str, prompt: str):
    """Register a dynamic task with the live scheduler."""
    _scheduler = _scheduler_ref["instance"]
    if not _scheduler:
        return
    parts = cron_expression.split()
    if len(parts) != 5:
        logger.error(f"Invalid cron expression for task #{task_id}: {cron_expression}")
        return
    _scheduler.add_job(
        _run_dynamic_task, "cron",
        args=[task_id],
        id=f"dynamic_task_{task_id}",
        minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4],
        replace_existing=True,
    )
    logger.info(f"Registered dynamic task #{task_id}: {cron_expression}")


def remove_dynamic_task(task_id: int):
    """Remove a dynamic task from the live scheduler."""
    _scheduler = _scheduler_ref["instance"]
    if not _scheduler:
        return
    try:
        _scheduler.remove_job(f"dynamic_task_{task_id}")
    except Exception:
        pass


def _load_dynamic_tasks():
    """Load all enabled scheduled tasks from DB into APScheduler on startup."""
    tasks = memory.get_scheduled_tasks(enabled_only=True)
    for task in tasks:
        try:
            register_dynamic_task(task["id"], task["cron_expression"], task["prompt"])
        except Exception as e:
            logger.error(f"Failed to load task #{task['id']}: {e}")
    if tasks:
        logger.info(f"Loaded {len(tasks)} dynamic scheduled tasks")


# ── Scheduled automation ────────────────────────────────────────────────────

def scheduled_inbox_triage():
    """Every 30 min: scan for new unread, triage, notify P1 via Telegram."""
    try:
        import google_client
        import anthropic

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
            f"Triage these {min(len(new_emails), 20)} emails into three tiers:\n\n"
            f"REPLY — Sender is a real person/contact, asks a question or is time-sensitive. Draft a reply.\n"
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

        reply_emails = []
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
            route_str = fields.get("ROUTE", "shams")
            routed_to = [r.strip() for r in route_str.split(",") if r.strip()]
            action = fields.get("ACTION", "")
            draft = fields.get("DRAFT", "")
            if draft.upper() == "NONE":
                draft = ""

            triage_id = memory.save_triage_result(
                account=email["account"], message_id=msg_id,
                from_addr=email["from"], subject=email["subject"],
                snippet=email["snippet"], tier=tier,
                routed_to=routed_to, action=action, draft_reply=draft,
            )

            if tier == "reply":
                reply_emails.append((triage_id, email, action, draft))

        # Reply tier -> immediate Telegram notification with action buttons
        if reply_emails and config.TELEGRAM_CHAT_ID:
            for triage_id, email, action, draft in reply_emails:
                msg = (
                    f"📬 REPLY NEEDED\n\n"
                    f"From: {email['from']}\n"
                    f"[{email['account']}] {email['subject']}\n\n"
                    f"Action: {action}"
                )
                buttons = [
                    {"text": "Archive", "callback_data": f"earchive:{triage_id}"},
                    {"text": "Star", "callback_data": f"estar:{triage_id}"},
                    {"text": "Snooze", "callback_data": f"esnooze:{triage_id}"},
                ]
                if draft:
                    buttons.insert(0, {"text": "Draft Reply", "callback_data": f"edraft:{triage_id}"})
                send_telegram_with_buttons(config.TELEGRAM_CHAT_ID, msg, buttons)

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


def smart_alerts_check():
    """Check all alert rules and fire notifications when conditions met."""
    try:
        rules = memory.get_alert_rules(enabled_only=True)
        if not rules:
            return

        # Gather metrics
        metrics = {}
        try:
            import mercury_client
            balances = mercury_client.get_balances()
            metrics["cash_total"] = balances.get("grand_total", 0) if balances else 0
        except Exception:
            pass
        try:
            import rumi_client
            daily = rumi_client.get_daily_pl("yesterday") or {}
            metrics["food_cost_pct"] = daily.get("food_cost_pct", 0)
            metrics["labor_cost_pct"] = daily.get("labor_cost_pct", 0)
            metrics["net_margin_pct"] = daily.get("net_margin_pct", 0)
            metrics["daily_revenue"] = daily.get("revenue", 0)
        except Exception:
            pass

        # Check deals approaching deadlines
        try:
            from config import DATABASE_URL
            import psycopg2, psycopg2.extras
            with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM shams_deals WHERE deadline IS NOT NULL "
                    "AND deadline <= CURRENT_DATE + INTERVAL '3 days' AND stage NOT IN ('closed', 'dead')"
                )
                metrics["deals_expiring_soon"] = cur.fetchone()["cnt"]
        except Exception:
            pass

        for rule in rules:
            metric_val = metrics.get(rule["metric"])
            if metric_val is None:
                continue
            threshold = float(rule["threshold"])
            triggered = False
            if rule["condition"] == "<" and metric_val < threshold:
                triggered = True
            elif rule["condition"] == ">" and metric_val > threshold:
                triggered = True
            elif rule["condition"] == "<=" and metric_val <= threshold:
                triggered = True
            elif rule["condition"] == ">=" and metric_val >= threshold:
                triggered = True

            if triggered:
                msg = rule["message_template"].replace("{value}", str(round(metric_val, 1)))
                memory.log_activity("shams", "smart_alert", msg)
                memory.create_notification("smart_alert", msg, "", "", None)
                memory.update_alert_rule(rule["id"], last_triggered="NOW()")
                if config.TELEGRAM_CHAT_ID:
                    send_telegram(config.TELEGRAM_CHAT_ID, f"Alert: {msg}")

    except Exception as e:
        logger.error(f"Smart alerts check error: {e}", exc_info=True)


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
            msg = f"{len(stale)} stale mission(s) — active for >48h:\n"
            msg += "\n".join(f"- #{m['id']}: {m['title']}" for m in stale)
            send_telegram(config.TELEGRAM_CHAT_ID, msg)

    except Exception as e:
        logger.error(f"Mission stale check error: {e}")


def _check_meeting_preps():
    """Poll for upcoming meetings and send prep briefs. Runs every 10 min."""
    try:
        from meeting_prep import check_upcoming_meetings
        sent = check_upcoming_meetings()
        if sent:
            logger.info(f"Meeting prep: sent {sent} brief(s)")
    except Exception as e:
        logger.error(f"Meeting prep check error: {e}")


def _check_meeting_bots():
    """Poll for both: (1) upcoming meetings to dispatch bots, (2) completed bots to process."""
    try:
        from meeting_bot import check_and_dispatch_bots
        dispatched = check_and_dispatch_bots()
        if dispatched:
            logger.info(f"Meeting bot: dispatched {dispatched} bot(s)")
    except Exception as e:
        logger.error(f"Meeting bot dispatch error: {e}")

    # Fallback poller: check for any bots that finished but webhook was missed
    try:
        import recall_client as rc
        import meeting_bot
        import json

        # Get all active bot IDs from memory (recall_bot_* keys)
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM shams_memory WHERE key LIKE 'recall_bot_%'")
                active_bots = cur.fetchall()

        for key, meta_raw in active_bots:
            bot_id = key.replace("recall_bot_", "")
            # Skip if already processed
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM shams_meeting_notes WHERE recall_bot_id = %s", (bot_id,))
                    if cur.fetchone():
                        continue

            bot = rc.get_bot(bot_id)
            if bot and bot.get("status_code") == "done":
                logger.info(f"Fallback poller: processing completed bot {bot_id}")
                utterances = rc.get_transcript(bot_id)
                transcript_text = rc.format_transcript(utterances)
                if transcript_text and len(transcript_text) >= 50:
                    event_meta = json.loads(meta_raw)
                    meeting_bot.process_completed_meeting(
                        bot_id=bot_id,
                        transcript_text=transcript_text,
                        event_meta=event_meta,
                    )
    except Exception as e:
        logger.error(f"Meeting bot fallback poller error: {e}")


# ── Scheduler init ──────────────────────────────────────────────────────────

def init_scheduler():
    """Create and start the APScheduler with all built-in jobs. Returns the scheduler instance."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    _scheduler_ref["instance"] = scheduler
    scheduler.add_job(run_overnight, "cron", hour=config.OVERNIGHT_HOUR_UTC, minute=0, id="overnight_loop")
    scheduler.add_job(deliver_standup, "cron", hour=config.STANDUP_HOUR_UTC, minute=0, id="morning_standup")
    scheduler.add_job(send_evening_briefing, "cron", hour=config.EVENING_HOUR_UTC, minute=0)
    scheduler.add_job(scheduled_inbox_triage, "interval", minutes=30, id="inbox_triage")
    scheduler.add_job(agent_health_check, "interval", minutes=5, id="health_check")
    # mission_stale_check removed — now handled by overnight loop forgetting check
    scheduler.add_job(smart_alerts_check, "interval", hours=1, id="smart_alerts")  # every hour
    scheduler.add_job(send_weekly_pl_digest, "cron", day_of_week="sun", hour=1, minute=0, id="weekly_pl")
    scheduler.add_job(log_daily_hosting, "cron", hour=0, minute=5, id="daily_hosting")
    scheduler.add_job(_check_meeting_preps, "interval", minutes=10, id="meeting_prep_check")
    scheduler.add_job(_check_meeting_bots, "interval", minutes=10, id="meeting_bot_check")
    scheduler.start()
    logger.info(f"Scheduler started — overnight @ {config.OVERNIGHT_HOUR_UTC}:00 UTC, standup @ {config.STANDUP_HOUR_UTC}:00 UTC, evening @ {config.EVENING_HOUR_UTC}:00 UTC")
    logger.info("Scheduled: inbox triage (30min), health check (5min), stale missions (daily), meeting prep (10min), meeting bots (10min)")

    # Load dynamic tasks from database
    _load_dynamic_tasks()

    return scheduler
