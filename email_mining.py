"""Email mining pipeline — classify, extract, route, archive.

Spec: docs/superpowers/specs/2026-04-13-email-mining-pipeline-design.md
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

# ── Category taxonomy ────────────────────────────────────────────────────────

PRIORITY_CATEGORIES = {
    "coinbits_legal",
    "prime_trust_lawsuit",
    "investor_relations",
    "somerville_purchase",
}

ACTIONABLE_CATEGORIES = {
    "invoice",
    "customer_complaint",
    "deal_pitch",
    "personal",
}

NOISE_CATEGORIES = {
    "newsletter",
    "automated_notification",
    "transactional_receipt",
    "spam_adjacent",
    "other",
}

ALL_CATEGORIES = PRIORITY_CATEGORIES | ACTIONABLE_CATEGORIES | NOISE_CATEGORIES

# Categories that should NEVER have Gmail INBOX label removed automatically
# purely based on category (priority-based never-archive is handled separately
# in archive_in_gmail by checking priority == 'P1'). 'personal' stays in inbox.
NEVER_ARCHIVE_CATEGORIES = {"personal"}
# Legacy alias — kept for tests that reference NEVER_ARCHIVE.
NEVER_ARCHIVE = NEVER_ARCHIVE_CATEGORIES | PRIORITY_CATEGORIES

DEFAULT_MODEL = os.environ.get("EMAIL_MINING_MODEL", "claude-sonnet-4-6")

# ── Classifier ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are Shams's email triage classifier for MJ (Maher Janajri), founder of Queen City Coffee Roasters (QCC) and Coinbits. You read one email at a time and output a single JSON object with category, priority, and extracted entities.

# PRIORITY — assign independently of category

Use your judgment. Do NOT just pattern-match keywords.

**P1 — time-sensitive / high-stakes. Never auto-archive; MJ gets a Telegram ping.**
Anything where missing it for 48 hours could cause real harm. Examples (not exhaustive):
- Legal: attorneys, lawsuits, settlement demands, court filings, regulatory actions, subpoenas
- Financial: banking issues, fraud alerts on real accounts, large unexpected charges, tax deadlines, loan/investor term-sheet timelines
- People: real investors/partners/board reaching out (NOT mass investor-update blasts), counterparties, family/health matters, employee matters requiring response
- Counterparties with money on the line: real estate sellers/lawyers/escrow, acquisition targets mid-negotiation, vendor contract disputes
- Customer-at-risk: wholesale account threatening to leave, credible threat of chargeback/lawsuit, PR/reputational risk
- Explicit deadlines ("please respond by [date]") from credible human senders
- Things MJ specifically called out as priorities:
  * Coinbits wind-down (Cooley LLP + other counsel, distribution schedules, regulatory comms for the Coinbits shutdown)
  * Prime Trust lawsuit (any counsel correspondence, filings, settlement)
  * Investor relations (current or prospective investors/partners reaching out)
  * Somerville property purchase (real estate counsel, title/escrow, seller)

**P2 — actionable but not urgent.** Invoices, customer complaints, deal pitches, personal correspondence from friends/family, non-urgent operational requests.

**P3 — noise worth archiving.** Newsletters, automated platform notifications, transactional receipts.

**P4 — low-quality noise.** Spam-adjacent sales outreach, clearly auto-generated junk.

# CATEGORY — choose exactly one

Named priority buckets (use these when they fit — they help MJ filter later):
- coinbits_legal, prime_trust_lawsuit, investor_relations, somerville_purchase

Actionable buckets:
- invoice — a bill/invoice requesting payment
- customer_complaint — QCC customer complaining (product, shipping, subscription)
- deal_pitch — unsolicited acquisition/partnership/investment pitch
- personal — friends, family, non-business personal correspondence

Noise buckets:
- newsletter — marketing content, mass investor blasts, industry digests
- automated_notification — Mercury/Shopify/Stripe/GitHub/LinkedIn alerts
- transactional_receipt — order confirmations, shipping updates, auto receipts
- spam_adjacent — low-quality outreach, generic sales spam

Fallback:
- other — P1/P2 email that doesn't fit any named bucket above (e.g. a legal matter unrelated to the four named legal topics, an urgent banking issue, an employee matter). Use 'other' when the email is important but the named buckets don't fit — DO NOT force-fit it into a named bucket.

**IMPORTANT:** Priority is independent of category. An email can be `category='other'` with `priority='P1'`. That combination means "important but doesn't fit the named buckets" — it will still stay in MJ's inbox and fire a Telegram ping. Do not downgrade priority just because the category is 'other'.

# ENTITIES (JSON object — schema varies by category)

- invoice: {vendor, amount_cents, currency, invoice_number, due_date (YYYY-MM-DD or null)}
- customer_complaint: {customer_email, customer_name, order_id, issue_summary, severity ('low'|'med'|'high')}
- priority categories + any P1: {people:[...], firms:[...], action_needed: bool, deadline: YYYY-MM-DD | null, tldr: '...', why_priority: '...'}
- everything else: {action_needed: false}

For any P1 (regardless of category), include `tldr` and `why_priority` in entities so MJ can understand the ping at a glance.

# OUTPUT

Strict JSON. No prose, no markdown fences:
{"category": "<one_of_above>", "priority": "P1"|"P2"|"P3"|"P4", "entities": {...}}"""


def _call_sonnet(messages: list[dict], system: str) -> str:
    """Invoke Sonnet 4.6. Returns the raw text. Raises on API error."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return resp.content[0].text


def classify_and_extract(email: dict) -> dict:
    """Classify one email and extract entities.

    Returns {"category": str, "priority": str, "entities": dict}.
    On parser error, returns {"category": "_error", "priority": "P4", "entities": {"error": ...}}.
    """
    user_msg = (
        f"From: {email.get('from_addr','')}\n"
        f"Subject: {email.get('subject','')}\n\n"
        f"Snippet: {email.get('snippet','')}\n\n"
        f"Body (truncated):\n{(email.get('body') or '')[:8000]}"
    )

    try:
        raw = _call_sonnet(
            messages=[{"role": "user", "content": user_msg}],
            system=_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error(f"Classifier API error: {e}")
        return {"category": "_error", "priority": "P4", "entities": {"error": str(e)}}

    try:
        # Strip any accidental markdown fences.
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        parsed = json.loads(stripped)
    except Exception as e:
        logger.error(f"Classifier JSON parse error: {e}; raw={raw[:500]}")
        return {"category": "_error", "priority": "P4", "entities": {"error": "parse_failed", "raw": raw[:500]}}

    category = parsed.get("category", "other")
    if category not in ALL_CATEGORIES:
        logger.warning(f"Classifier returned unknown category '{category}'; falling back to 'other'")
        category = "other"

    priority = parsed.get("priority", "P3")
    if priority not in {"P1", "P2", "P3", "P4"}:
        priority = "P3"

    entities = parsed.get("entities", {}) or {}

    return {"category": category, "priority": priority, "entities": entities}


# ── Router ───────────────────────────────────────────────────────────────────

def route_extracted(
    archive_id: int | None,
    category: str,
    entities: dict,
    source_subject: str = "",
) -> None:
    """Route extracted data to the right downstream table based on category.

    No-op for categories that don't route (priority categories, noise, errors).
    """
    import memory

    if archive_id is None:
        return

    if category == "invoice":
        memory.insert_ap_invoice({
            "archive_id": archive_id,
            "vendor": entities.get("vendor"),
            "amount_cents": entities.get("amount_cents"),
            "currency": entities.get("currency", "USD"),
            "invoice_number": entities.get("invoice_number"),
            "due_date": entities.get("due_date"),
            "notes": None,
        })
        return

    if category == "customer_complaint":
        memory.insert_cx_complaint({
            "archive_id": archive_id,
            "customer_email": entities.get("customer_email"),
            "customer_name": entities.get("customer_name"),
            "issue_summary": entities.get("issue_summary"),
            "severity": entities.get("severity"),
        })
        return

    if category == "deal_pitch":
        title = entities.get("title") or source_subject or "Untitled deal"
        memory.create_deal(
            title=title,
            deal_type=entities.get("deal_type", "other"),
            value=float(entities.get("value", 0) or 0),
            contact=entities.get("contact", ""),
            source="email_mining",
            location=entities.get("location", ""),
            next_action=entities.get("next_action", ""),
            score=int(entities.get("score", 0) or 0),
            notes=entities.get("notes", ""),
        )
        return

    # Priority categories, noise, personal, _error — no routing.
    return


# ── Gmail-side archiver with safety net ──────────────────────────────────────

def _dry_run_enabled() -> bool:
    return os.environ.get("EMAIL_MINING_DRY_RUN", "").lower() in ("1", "true", "yes")


def archive_in_gmail(account_key: str, gmail_message_id: str, category: str,
                     priority: str = "P3") -> bool:
    """Archive an email in Gmail (remove INBOX + UNREAD labels), subject to safety rules.

    Returns True if Gmail was actually mutated, False if skipped.
    Hard guards:
      - Never archives P1 (Sonnet-judged high-stakes) regardless of category.
      - Never archives named priority categories (coinbits_legal, prime_trust_lawsuit,
        investor_relations, somerville_purchase) as a second safety net.
      - Never archives 'personal' (stays in inbox for human review).
      - Never archives '_error' rows.
      - No-op under EMAIL_MINING_DRY_RUN.
    """
    if priority == "P1":
        return False
    if category in PRIORITY_CATEGORIES:
        return False
    if category in NEVER_ARCHIVE_CATEGORIES:
        return False
    if category == "_error":
        return False
    if category not in ALL_CATEGORIES:
        logger.warning(f"archive_in_gmail: unknown category '{category}', refusing to archive")
        return False
    if _dry_run_enabled():
        logger.info(f"[DRY RUN] would archive {account_key}:{gmail_message_id} ({category}/{priority})")
        return False

    import google_client
    ok_archive = google_client.archive_email(account_key, gmail_message_id)
    ok_read = google_client.mark_read(account_key, gmail_message_id)
    return ok_archive and ok_read


# ── Telegram escalator ───────────────────────────────────────────────────────

_CATEGORY_EMOJI = {
    "coinbits_legal": "⚖️",
    "prime_trust_lawsuit": "🏛️",
    "investor_relations": "💼",
    "somerville_purchase": "🏠",
}

_CATEGORY_LABEL = {
    "coinbits_legal": "Coinbits Legal",
    "prime_trust_lawsuit": "Prime Trust Lawsuit",
    "investor_relations": "Investor Relations",
    "somerville_purchase": "Somerville Purchase",
}


def maybe_escalate(
    archive_id: int,
    category: str,
    gmail_thread_id: str,
    from_name: str,
    from_addr: str,
    subject: str,
    snippet: str,
    priority: str = "P3",
    tldr: str = "",
) -> bool:
    """Fire a Telegram ping if this is a new P1 thread (high-stakes per Sonnet's judgment).

    Named priority categories also trigger escalation (belt-and-suspenders), even if
    priority happens to be P2 for some reason. Returns True if a ping was sent.
    """
    import memory
    import telegram

    is_priority = priority == "P1" or category in PRIORITY_CATEGORIES
    if not is_priority:
        return False
    if memory.thread_already_escalated(gmail_thread_id):
        return False

    emoji = _CATEGORY_EMOJI.get(category, "🚨")
    label = _CATEGORY_LABEL.get(category, category.replace("_", " ").title())
    display_from = f"{from_name} <{from_addr}>" if from_name else from_addr

    body_lines = [
        f"🚨 {emoji} *{label}* — new P1 thread" if priority == "P1" else f"🚨 {emoji} *{label}* — new thread",
        f"From: {display_from}",
        f"Subject: {subject}",
    ]
    if tldr:
        body_lines.append(f"TL;DR: {tldr}")
    else:
        body_lines.append((snippet or "")[:200])
    body_lines.append(f"→ https://app.myshams.ai/inbox/{archive_id}")
    text = "\n".join(body_lines)

    try:
        telegram.send_message(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Telegram escalation failed: {e}")
        return False

    memory.record_thread_escalation(gmail_thread_id, category, archive_id)
    return True


# -- Orchestrator -------------------------------------------------------------

def process_email(email: dict) -> dict:
    """Run the full classify -> extract -> route -> archive pipeline on one email.

    `email` must contain at least: account, gmail_message_id, gmail_thread_id.
    Other fields (from_addr, subject, body, etc.) should be present for good classification.

    Returns: {archive_id, category, priority, gmail_archived, escalated}
    """
    import memory

    # 1. Classify + extract.
    classification = classify_and_extract(email)
    category = classification["category"]
    priority = classification["priority"]
    entities = classification["entities"]

    # 2. Write archive row (idempotent).
    archive_id = memory.insert_email_archive({
        **email,
        "category": category,
        "priority": priority,
        "entities": entities,
        "processed_model": DEFAULT_MODEL,
    })

    # 3. Route extracted data to destination tables.
    route_extracted(
        archive_id=archive_id,
        category=category,
        entities=entities,
        source_subject=email.get("subject", ""),
    )

    # 4. Archive in Gmail (with safety net — never archives P1 or named priority).
    gmail_archived = archive_in_gmail(
        account_key=email["account"],
        gmail_message_id=email["gmail_message_id"],
        category=category,
        priority=priority,
    )
    if gmail_archived and archive_id is not None:
        # Persist the archived flag.
        import db
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE shams_email_archive SET gmail_archived = TRUE WHERE id = %s",
                    (archive_id,),
                )

    # 5. Escalate via Telegram if P1 or named priority category + new thread.
    escalated = False
    is_priority = priority == "P1" or category in PRIORITY_CATEGORIES
    if archive_id is not None and is_priority:
        escalated = maybe_escalate(
            archive_id=archive_id,
            category=category,
            gmail_thread_id=email.get("gmail_thread_id", ""),
            from_name=email.get("from_name", ""),
            from_addr=email.get("from_addr", ""),
            subject=email.get("subject", ""),
            snippet=email.get("snippet", ""),
            priority=priority,
            tldr=entities.get("tldr", "") if isinstance(entities, dict) else "",
        )

    return {
        "archive_id": archive_id,
        "category": category,
        "priority": priority,
        "gmail_archived": gmail_archived,
        "escalated": escalated,
    }
