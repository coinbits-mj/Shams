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

# Categories that should NEVER have Gmail INBOX label removed automatically.
# Priority categories always stay in inbox. 'personal' stays in inbox (human domain).
NEVER_ARCHIVE = PRIORITY_CATEGORIES | {"personal"}

DEFAULT_MODEL = os.environ.get("EMAIL_MINING_MODEL", "claude-sonnet-4-6")

# ── Classifier ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are Shams's email triage classifier. You read one email at a time and output a single JSON object classifying it.

CATEGORIES (choose exactly one):

Priority (P1 — always escalate, never auto-archive):
- coinbits_legal: Counsel emails for Coinbits wind-down (Cooley LLP, named attorneys), distribution schedules, regulatory comms related to the Coinbits shutdown.
- prime_trust_lawsuit: Counsel correspondence, settlement offers, court filings, discovery requests, or anything referencing the Prime Trust litigation.
- investor_relations: Actual humans — current or prospective investors, partners — reaching out. NOT automated investor update newsletters (those are 'newsletter').
- somerville_purchase: Real estate counsel, purchase docs, title/escrow, seller correspondence for the Somerville property purchase.

Actionable (P2 — routed + auto-archived except 'personal'):
- invoice: A bill/invoice requesting payment.
- customer_complaint: A QCC customer complaining about product, shipping, subscription, etc.
- deal_pitch: An unsolicited pitch for an acquisition, partnership, or investment opportunity.
- personal: Friends, family, non-business personal correspondence.

Noise (P3/P4 — archived):
- newsletter: Marketing/newsletter content, investor update blasts, industry digests.
- automated_notification: Mercury, Shopify, Stripe, GitHub, LinkedIn alerts, platform notifications.
- transactional_receipt: Order confirmations, shipping updates, auto-generated receipts.
- spam_adjacent: Low-quality outreach, generic sales spam.
- other: Doesn't fit above — use sparingly.

ENTITIES (JSON object, schema varies by category):
- invoice: {vendor, amount_cents, currency, invoice_number, due_date (YYYY-MM-DD or null)}
- customer_complaint: {customer_email, customer_name, order_id, issue_summary, severity ('low'|'med'|'high')}
- priority categories: {people:[...], firms:[...], action_needed:bool, deadline:YYYY-MM-DD|null, tldr:'...'}
- everything else: {action_needed: false}

OUTPUT (STRICT JSON, no prose, no markdown fences):
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
