"""Group chat — Maher talks to Shams, Rumi, and Leo simultaneously.
Each agent responds from their own perspective with their own data."""

from __future__ import annotations

import json
import logging
import concurrent.futures
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import memory
import rumi_client
import leo_client
import mercury_client

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

AGENT_PROMPTS = {
    "shams": {
        "system": (
            "You are Shams — Maher's AI chief of staff. You're in a group chat with Rumi (QCC operations) "
            "and Leo (health coach). Keep your responses concise (2-4 sentences). Focus on strategy, deals, "
            "decisions, and the big picture. Don't repeat what the other agents will cover — they handle "
            "their own domains. If the question is purely about ops or health, you can say 'Rumi has this' "
            "or 'Leo's got you' and add only your strategic take if relevant."
        ),
        "get_context": lambda: _shams_context(),
    },
    "rumi": {
        "system": (
            "You are Rumi — QCC's operations intelligence agent. You're in a group chat with Shams (chief of staff) "
            "and Leo (health coach). Keep responses concise (2-4 sentences). You own: P&L, revenue, COGS, labor, "
            "inventory, Square data, Mercury transactions, vendor management. Only respond if the question "
            "touches your domain. If it's about health or strategy, stay quiet — respond with just '—' if you "
            "have nothing to add."
        ),
        "get_context": lambda: _rumi_context(),
    },
    "leo": {
        "system": (
            "You are Leo — Maher's health coach. You're in a group chat with Shams (chief of staff) "
            "and Rumi (QCC operations). Keep responses concise (2-4 sentences). You own: weight, sleep, HRV, "
            "glucose, nutrition, exercise, recovery, discipline score. Only respond if the question touches "
            "your domain. If it's about business, stay quiet — respond with just '—' if you have nothing to add."
        ),
        "get_context": lambda: _leo_context(),
    },
}


def _shams_context() -> str:
    parts = []
    kv = memory.recall_all()
    if kv:
        parts.append("Memory: " + "; ".join(f"{k}={v}" for k, v in list(kv.items())[:10]))
    loops = memory.get_open_loops()
    if loops:
        parts.append("Open loops: " + "; ".join(l["title"] for l in loops[:5]))
    cash = mercury_client.get_balances()
    if cash:
        parts.append(f"Cash position: ${cash.get('grand_total', 0):,.0f}")
    return "\n".join(parts) if parts else "No additional context."


def _rumi_context() -> str:
    parts = []
    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        parts.append(f"Yesterday P&L: revenue ${pl.get('revenue', 0):,.0f}, "
                      f"net margin {pl.get('net_margin_pct', 0):.1f}%, "
                      f"food cost {pl.get('food_cost_pct', 0):.1f}%")
    actions = rumi_client.get_action_items()
    if actions and actions.get("items"):
        items = actions["items"][:3]
        parts.append("Action items: " + "; ".join(str(a.get("text", a)) for a in items))
    return "\n".join(parts) if parts else "Rumi data unavailable."


def _leo_context() -> str:
    summary = leo_client.get_health_summary()
    if not summary:
        return "Leo data unavailable."
    user = summary.get("user") or {}
    daily = summary.get("daily_summary") or {}
    parts = []
    if user.get("current_weight"):
        parts.append(f"Weight: {user['current_weight']} lbs")
    if daily.get("sleep_hours"):
        parts.append(f"Sleep: {daily['sleep_hours']:.1f}h")
    if daily.get("hrv"):
        parts.append(f"HRV: {daily['hrv']:.0f}")
    if daily.get("total_calories"):
        parts.append(f"Calories: {daily['total_calories']}/{user.get('calorie_target', '?')}")
    if user.get("current_streak"):
        parts.append(f"Streak: {user['current_streak']}d")
    return ", ".join(parts) if parts else "No health data today."


def _get_agent_response(agent_name: str, user_message: str, history: list) -> str:
    """Get one agent's response."""
    agent = AGENT_PROMPTS[agent_name]

    # Build conversation from group history
    messages = []
    for msg in history[-20:]:
        if msg["agent_name"] == "maher":
            messages.append({"role": "user", "content": msg["content"]})
        else:
            prefix = f"[{msg['agent_name']}]: " if msg["agent_name"] != agent_name else ""
            role = "assistant" if msg["agent_name"] == agent_name else "user"
            if role == "user":
                messages.append({"role": "user", "content": f"{prefix}{msg['content']}"})
            else:
                messages.append({"role": "assistant", "content": msg["content"]})

    # Add the new message
    messages.append({"role": "user", "content": user_message})

    # Deduplicate consecutive same-role messages
    deduped = []
    for m in messages:
        if deduped and deduped[-1]["role"] == m["role"]:
            deduped[-1]["content"] += "\n" + m["content"]
        else:
            deduped.append(m)

    # Ensure starts with user
    if deduped and deduped[0]["role"] != "user":
        deduped = deduped[1:]
    if not deduped:
        deduped = [{"role": "user", "content": user_message}]

    # Get context
    try:
        context = agent["get_context"]()
    except Exception as e:
        context = f"Context error: {e}"

    system = agent["system"] + f"\n\nCurrent data:\n{context}"

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=system,
            messages=deduped,
        )
        text = response.content[0].text.strip()
        # If agent has nothing to say
        if text in ("—", "-", "N/A", ""):
            return None
        return text
    except Exception as e:
        logger.error(f"Group chat {agent_name} error: {e}")
        return None


def send_group_message(user_message: str) -> list[dict]:
    """Send a message to the group chat. Returns list of agent responses."""
    # Save user message
    memory.save_group_message("maher", user_message)

    # Get recent history for context
    history = memory.get_group_messages(30)

    # Call all agents in parallel
    responses = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_get_agent_response, name, user_message, history): name
            for name in AGENT_PROMPTS
        }
        for future in concurrent.futures.as_completed(futures):
            agent_name = futures[future]
            try:
                reply = future.result()
                if reply:
                    memory.save_group_message(agent_name, reply)
                    memory.log_activity(agent_name, "group_chat", reply[:100])
                    responses.append({"agent": agent_name, "content": reply})
            except Exception as e:
                logger.error(f"Group chat {agent_name} error: {e}")

    # Sort: shams first, then rumi, then leo
    order = {"shams": 0, "rumi": 1, "leo": 2}
    responses.sort(key=lambda r: order.get(r["agent"], 9))

    return responses
