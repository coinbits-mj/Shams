"""Group chat — Maher talks to all agents simultaneously.
Each agent responds from their own perspective with their own data."""

from __future__ import annotations

import json
import logging
import concurrent.futures
import anthropic
from config import ANTHROPIC_API_KEY
import memory
import rumi_client
import leo_client
import mercury_client
from agents.registry import AGENT_DEFS, build_agent_system_prompt

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Which agents participate in group chat and their context builders
GROUP_AGENTS = {
    "shams": lambda: _shams_context(),
    "rumi": lambda: _rumi_context(),
    "leo": lambda: _leo_context(),
    "wakil": lambda: _wakil_context(),
    "scout": lambda: "",
}

GROUP_INSTRUCTION = (
    "\n\nYou are in a group chat with Maher and other agents. Keep responses concise (2-5 sentences). "
    "Only respond if the question touches your domain. If it's outside your area, respond with just '—'. "
    "Don't repeat what other agents will cover. Be direct, no preamble."
)


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
    return "\n".join(parts)


def _rumi_context() -> str:
    parts = []
    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        parts.append(f"Yesterday P&L: revenue ${pl.get('revenue', 0):,.0f}, "
                      f"net margin {pl.get('net_margin_pct', 0):.1f}%, "
                      f"food cost {pl.get('food_cost_pct', 0):.1f}%")
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
    if user.get("current_streak"):
        parts.append(f"Streak: {user['current_streak']}d")
    return ", ".join(parts) if parts else "No health data."


def _wakil_context() -> str:
    parts = ["Active case: PCT v. Coinbits (Bankr. D. Del.). Strategy: motion to dismiss, then settle from strength."]
    # Check if there are any triaged legal emails in memory
    legal_emails = memory.recall("inbox_legal_queue")
    if legal_emails:
        parts.append(f"Pending legal emails: {legal_emails}")
    return "\n".join(parts)


def _get_agent_response(agent_name: str, user_message: str, history: list) -> str | None:
    """Get one agent's response in the group chat."""
    # Build conversation from history
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

    messages.append({"role": "user", "content": user_message})

    # Deduplicate consecutive same-role
    deduped = []
    for m in messages:
        if deduped and deduped[-1]["role"] == m["role"]:
            deduped[-1]["content"] += "\n" + m["content"]
        else:
            deduped.append(m)
    if deduped and deduped[0]["role"] != "user":
        deduped = deduped[1:]
    if not deduped:
        deduped = [{"role": "user", "content": user_message}]

    # Get context
    context_fn = GROUP_AGENTS.get(agent_name, lambda: "")
    try:
        context = context_fn()
    except Exception as e:
        context = f"Context error: {e}"

    system = build_agent_system_prompt(agent_name, context) + GROUP_INSTRUCTION

    try:
        agent = AGENT_DEFS.get(agent_name, {})
        response = client.messages.create(
            model=agent.get("model", "claude-sonnet-4-20250514"),
            max_tokens=600,
            system=system,
            messages=deduped,
        )
        text = response.content[0].text.strip()
        if text in ("—", "-", "N/A", ""):
            return None
        return text
    except Exception as e:
        logger.error(f"Group chat {agent_name} error: {e}")
        return None


def send_group_message(user_message: str) -> list[dict]:
    """Send a message to the group chat. All agents respond in parallel."""
    memory.save_group_message("maher", user_message)
    history = memory.get_group_messages(30)

    responses = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(GROUP_AGENTS)) as executor:
        futures = {
            executor.submit(_get_agent_response, name, user_message, history): name
            for name in GROUP_AGENTS
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

    # Sort by role importance
    order = {"shams": 0, "wakil": 1, "rumi": 2, "leo": 3, "scout": 4, "builder": 5}
    responses.sort(key=lambda r: order.get(r["agent"], 9))

    return responses
