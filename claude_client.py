"""Claude API wrapper with memory injection and tool use."""

from __future__ import annotations

import json
import logging
import pathlib
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import memory

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_CONTEXT_DIR = pathlib.Path(__file__).parent / "context"


def _load_context_file(filename: str) -> str:
    path = _CONTEXT_DIR / filename
    if path.exists():
        return path.read_text()
    return ""


# Load the full Shams founding document + knowledge base at import time
SYSTEM_PROMPT = _load_context_file("shams_system_prompt.md")

_KNOWLEDGE_FILES = [
    "shams_knowledge_qcc_overview.md",
    "shams_knowledge_active_deals.md",
    "shams_knowledge_personal.md",
]
KNOWLEDGE_BASE = "\n\n---\n\n".join(
    _load_context_file(f) for f in _KNOWLEDGE_FILES if _load_context_file(f)
)


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the internet for current information. Use this for researching companies, market data, news, real estate listings, competitor intelligence, or any question that needs up-to-date information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and read the content of a specific URL. Use this to read articles, company websites, property listings, or any web page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_mercury_balances",
        "description": "Get current Mercury bank account balances across all entities — Clifton, Plainfield (café + production/wholesale), and Personal. Each API key may have multiple sub-accounts (checking, credit card, savings).",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all accounts.", "enum": ["clifton", "plainfield", "personal"]}
            },
        },
    },
    {
        "name": "get_mercury_transactions",
        "description": "Get recent Mercury bank transactions. Can filter by entity (clifton, plainfield, personal) or show all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Optional: 'clifton', 'plainfield', or 'personal'. Omit for all.", "enum": ["clifton", "plainfield", "personal"]},
                "days": {"type": "integer", "description": "Number of days to look back (default 7)", "default": 7}
            },
        },
    },
    {
        "name": "get_mercury_cash_summary",
        "description": "Get a formatted cash summary across all Mercury accounts (Clifton, Plainfield café + production, Personal) including balances and recent transactions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_daily_pl",
        "description": "Get yesterday's P&L from Rumi (QCC's operations platform). Includes revenue, COGS, labor, overhead, net margin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format, or 'yesterday'", "default": "yesterday"}
            },
        },
    },
    {
        "name": "get_rumi_monthly_pl",
        "description": "Get month-to-date P&L from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_scorecard",
        "description": "Get the QCC location health scorecard from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_action_items",
        "description": "Get today's action items and alerts from Rumi.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_cashflow_forecast",
        "description": "Get cash flow forecast from Rumi (30/60/90 day projections).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_labor",
        "description": "Get labor analysis from Rumi — costs by hour, daypart, employee.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_rumi_inventory_alerts",
        "description": "Get inventory alerts from Rumi — low stock, reorder needed.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "remember",
        "description": "Save a piece of information to persistent memory. Use this when Maher tells you something important to remember, or when you learn something that should persist across conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short key/label for the memory"},
                "value": {"type": "string", "description": "The information to remember"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "add_open_loop",
        "description": "Track a new open loop — something that needs follow-up or resolution. Use this when Maher mentions something pending, a task to do, or a decision to make.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the open loop"},
                "context": {"type": "string", "description": "Additional context"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "close_open_loop",
        "description": "Close an open loop that has been resolved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "loop_id": {"type": "integer", "description": "The ID of the loop to close"},
                "status": {"type": "string", "description": "'done' or 'dropped'", "default": "done"},
            },
            "required": ["loop_id"],
        },
    },
    {
        "name": "log_decision",
        "description": "Log a decision that was made. Use this when Maher makes a significant business or personal decision worth tracking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was decided"},
                "reasoning": {"type": "string", "description": "Why"},
                "outcome": {"type": "string", "description": "Expected outcome"},
            },
            "required": ["summary"],
        },
    },
]


# ── Tool execution ───────────────────────────────────────────────────────────

def _execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if name == "web_search":
            import web_search
            results = web_search.search_web(input_data["query"])
            return json.dumps(results, indent=2) if results else "No results found."

        elif name == "fetch_url":
            import web_search
            return web_search.fetch_url(input_data["url"])

        elif name == "get_mercury_balances":
            import mercury_client
            result = mercury_client.get_balances(input_data.get("account"))
            return json.dumps(result, indent=2) if result else "Mercury unavailable."

        elif name == "get_mercury_transactions":
            import mercury_client
            result = mercury_client.get_recent_transactions(input_data.get("account"), input_data.get("days", 7))
            return json.dumps(result, indent=2) if result else "Mercury unavailable."

        elif name == "get_mercury_cash_summary":
            import mercury_client
            return mercury_client.get_cash_summary()

        elif name == "get_rumi_daily_pl":
            import rumi_client
            result = rumi_client.get_daily_pl(input_data.get("date", "yesterday"))
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_monthly_pl":
            import rumi_client
            result = rumi_client.get_monthly_pl()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_scorecard":
            import rumi_client
            result = rumi_client.get_scorecard()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_action_items":
            import rumi_client
            result = rumi_client.get_action_items()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_cashflow_forecast":
            import rumi_client
            result = rumi_client.get_cashflow_forecast()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_labor":
            import rumi_client
            result = rumi_client.get_labor_analysis()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "get_rumi_inventory_alerts":
            import rumi_client
            result = rumi_client.get_inventory_alerts()
            return json.dumps(result, indent=2) if result else "Rumi unavailable."

        elif name == "remember":
            memory.remember(input_data["key"], input_data["value"])
            return f"Remembered: {input_data['key']}"

        elif name == "add_open_loop":
            loop_id = memory.add_open_loop(input_data["title"], input_data.get("context", ""))
            return f"Open loop #{loop_id} created: {input_data['title']}"

        elif name == "close_open_loop":
            memory.close_loop(input_data["loop_id"], input_data.get("status", "done"))
            return f"Loop #{input_data['loop_id']} closed."

        elif name == "log_decision":
            memory.log_decision(input_data["summary"], input_data.get("reasoning", ""), input_data.get("outcome", ""))
            return f"Decision logged: {input_data['summary']}"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        logger.error(f"Tool {name} error: {e}", exc_info=True)
        return f"Tool error: {e}"


# ── Memory context ───────────────────────────────────────────────────────────

def _build_memory_context() -> str:
    parts = []

    kv = memory.recall_all()
    if kv:
        parts.append("## Memory")
        for k, v in kv.items():
            parts.append(f"- **{k}**: {v}")

    loops = memory.get_open_loops()
    if loops:
        parts.append("\n## Open Loops")
        for loop in loops:
            parts.append(f"- [{loop['id']}] {loop['title']}: {loop['context']}")

    decisions = memory.get_recent_decisions(5)
    if decisions:
        parts.append("\n## Recent Decisions")
        for d in decisions:
            parts.append(f"- {d['summary']}")

    return "\n".join(parts)


def _build_system():
    mem_context = _build_memory_context()
    system = SYSTEM_PROMPT
    if KNOWLEDGE_BASE:
        system += f"\n\n# Knowledge Base\n{KNOWLEDGE_BASE}"
    if mem_context:
        system += f"\n\n# Live State (from memory)\n{mem_context}"

    system += "\n\n# Tools Available"
    system += "\nYou have tools to search the web, check Mercury bank balances and transactions, "
    system += "pull live P&L and operations data from Rumi, and manage persistent memory (remember things, "
    system += "track open loops, log decisions). Use them proactively — don't just talk about data, pull it."

    return system


# ── Chat (with tool use loop) ────────────────────────────────────────────────

def chat(user_message: str, images: list = None) -> str:
    """Send a message to Claude with tools, memory, and full context."""
    label = user_message
    if images:
        label = f"[{len(images)} image(s)] {user_message}" if user_message else f"[{len(images)} image(s)]"
    memory.save_message("user", label)

    recent = memory.get_recent_messages(30)
    messages = [{"role": r["role"], "content": r["content"]} for r in recent]

    # If this message has images, replace the last message with multimodal content
    if images:
        content_blocks = []
        for img in images:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                },
            })
        content_blocks.append({"type": "text", "text": user_message or "What's in this image?"})
        messages[-1] = {"role": "user", "content": content_blocks}

    # Tool use loop — Claude may call tools multiple times before responding
    max_iterations = 5
    for i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=TOOLS,
            messages=messages,
        )

        # If Claude is done (no tool calls), extract text and return
        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if b.type == "text"]
            reply = "\n".join(text_parts) if text_parts else ""
            memory.save_message("assistant", reply)
            return reply

        # Process tool calls
        tool_results = []
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                logger.info(f"Tool call: {block.name}({json.dumps(block.input)[:100]})")
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Add assistant message + tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # If we hit max iterations, return whatever text we have
    reply = "I ran into a limit processing your request. Here's what I have so far:\n\n" + "\n".join(text_parts)
    memory.save_message("assistant", reply)
    return reply


def generate_briefing(briefing_type: str, context: str) -> str:
    """Generate a briefing with tool access."""
    messages = [{"role": "user", "content": f"Generate a {briefing_type} briefing.\n\nContext:\n{context}"}]

    max_iterations = 5
    for i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts) if text_parts else ""

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                logger.info(f"Briefing tool call: {block.name}")
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "Briefing generation incomplete."
