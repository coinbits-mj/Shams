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
    "\n\nYou are in a group chat with Maher and other agents. "
    "CRITICAL RULES:\n"
    "1. ONLY respond if Maher directly addresses you by name, OR explicitly asks all agents to weigh in, "
    "OR the question is squarely in your domain and no other agent covers it.\n"
    "2. If it's not for you, respond with just '—'. Err on the side of silence.\n"
    "3. When you do respond, keep it to 1-3 sentences. No preamble, no 'Great question!', just the answer.\n"
    "4. Never repeat what another agent already said or will say.\n"
    "5. Don't volunteer unsolicited advice or opinions outside your lane."
)

# Tools available to Scout in group chat
SCOUT_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the internet for current information.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and read a web page.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
]


def _execute_scout_tool(name: str, input_data: dict) -> str:
    """Execute a tool for Scout in group chat."""
    import json as _json
    if name == "web_search":
        import web_search
        results = web_search.search_web(input_data["query"])
        return _json.dumps(results, indent=2) if results else "No results found."
    elif name == "fetch_url":
        import web_search
        return web_search.fetch_url(input_data["url"])
    return f"Unknown tool: {name}"


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
    # All triaged emails (including archived history)
    try:
        emails = memory.get_triaged_emails(limit=100)
        if emails:
            by_priority = {}
            for e in emails:
                p = e.get("priority", "P4")
                if p not in by_priority:
                    by_priority[p] = []
                by_priority[p].append(e)
            inbox_lines = ["Recent inbox:"]
            for p in ["P1", "P2", "P3", "P4"]:
                group = by_priority.get(p, [])
                if group:
                    inbox_lines.append(f"  {p} ({len(group)}):")
                    for e in group[:5]:
                        routed = ",".join(e.get("routed_to") or [])
                        inbox_lines.append(f"    - [{e.get('account')}] {e.get('subject','')} (from: {e.get('from_addr','')}) → {routed} | {e.get('action','')}")
            parts.append("\n".join(inbox_lines))
    except Exception:
        pass
    return "\n".join(parts)


def _rumi_context() -> str:
    parts = []
    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        parts.append(f"Yesterday P&L: revenue ${pl.get('revenue', 0):,.0f}, "
                      f"net margin {pl.get('net_margin_pct', 0):.1f}%, "
                      f"food cost {pl.get('food_cost_pct', 0):.1f}%")
    try:
        emails = memory.get_triaged_emails(limit=100)
        rumi_emails = [e for e in emails if "rumi" in (e.get("routed_to") or [])]
        if rumi_emails:
            parts.append(f"Emails routed to you ({len(rumi_emails)}):")
            for e in rumi_emails[:8]:
                parts.append(f"  [{e.get('priority')}] {e.get('subject','')} — {e.get('action','')}")
    except Exception:
        pass
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
    try:
        emails = memory.get_triaged_emails(limit=100)
        wakil_emails = [e for e in emails if "wakil" in (e.get("routed_to") or [])]
        if wakil_emails:
            parts.append(f"Emails routed to you ({len(wakil_emails)}):")
            for e in wakil_emails[:10]:
                parts.append(f"  [{e.get('priority')}] {e.get('subject','')} from {e.get('from_addr','')} — {e.get('action','')}")
    except Exception:
        pass
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
        kwargs = {
            "model": agent.get("model", "claude-sonnet-4-20250514"),
            "max_tokens": 600,
            "system": system,
            "messages": deduped,
        }

        # Scout gets web search tools
        if agent_name == "scout":
            kwargs["tools"] = SCOUT_TOOLS
            kwargs["max_tokens"] = 1200  # more room for tool use

        response = client.messages.create(**kwargs)

        # Handle tool use loop for Scout (max 3 iterations)
        if agent_name == "scout":
            for _ in range(3):
                if response.stop_reason != "tool_use":
                    break
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = _execute_scout_tool(block.name, block.input)
                        memory.log_activity("scout", "tool_call", f"[war room] {block.name}: {block.input.get('query', block.input.get('url', ''))[:80]}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result[:3000],
                        })
                deduped.append({"role": "assistant", "content": response.content})
                deduped.append({"role": "user", "content": tool_results})
                response = client.messages.create(**{**kwargs, "messages": deduped})

        text_parts = [b.text for b in response.content if b.type == "text"]
        text = "\n".join(text_parts).strip()
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
