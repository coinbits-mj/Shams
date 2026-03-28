"""Scheduled briefing logic — morning and evening briefings."""

import logging
import json
from datetime import date

import memory
import claude_client
import rumi_client
import google_client

logger = logging.getLogger(__name__)


def build_morning_context() -> str:
    """Gather all context for the morning briefing."""
    parts = []

    # Calendar
    events = google_client.get_todays_events()
    if events:
        parts.append("## Today's Calendar")
        for e in events:
            parts.append(f"- {e['start']} — {e['summary']}" + (f" @ {e['location']}" if e['location'] else ""))
    else:
        parts.append("## Today's Calendar\nNo events scheduled.")

    # Unread emails (top 5)
    emails = google_client.get_unread_emails(5)
    if emails:
        parts.append("\n## Unread Emails (top 5)")
        for e in emails:
            parts.append(f"- **{e['from']}**: {e['subject']}")

    # Rumi P&L (yesterday)
    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        parts.append(f"\n## Yesterday's P&L (Queen City)")
        parts.append(f"- Revenue: ${pl.get('revenue', 0):,.0f}")
        parts.append(f"- Net margin: {pl.get('net_margin_pct', 0):.1f}%")
        parts.append(f"- Food cost: {pl.get('food_cost_pct', 0):.1f}%")
        parts.append(f"- Labor: {pl.get('labor_pct', 0):.1f}%")

    # Action items
    actions = rumi_client.get_action_items()
    if actions and actions.get("items"):
        parts.append("\n## Action Items")
        for a in actions["items"][:5]:
            parts.append(f"- {a.get('text', a)}")

    # Open loops
    loops = memory.get_open_loops()
    if loops:
        parts.append("\n## Open Loops")
        for loop in loops:
            parts.append(f"- {loop['title']}")

    return "\n".join(parts)


def build_evening_context() -> str:
    """Gather context for evening wrap-up."""
    parts = []

    # Tomorrow's calendar
    events = google_client.get_upcoming_events(1)
    if events:
        parts.append("## Tomorrow's Calendar")
        for e in events:
            parts.append(f"- {e['start']} — {e['summary']}")

    # MTD P&L
    mtd = rumi_client.get_mtd_pl()
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

    return "\n".join(parts)


def generate_morning_briefing() -> str:
    context = build_morning_context()
    return claude_client.generate_briefing("morning", context)


def generate_evening_briefing() -> str:
    context = build_evening_context()
    return claude_client.generate_briefing("evening", context)
