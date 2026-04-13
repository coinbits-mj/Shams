# claude_client.py — chat loop + prompt assembly (slim rewrite)
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import config
import memory
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from tools.registry import discover_tools, get_tool_definitions, execute

log = logging.getLogger(__name__)

CONTEXT_DIR = Path(__file__).parent / "context"
CORE_PROMPT_FILE = CONTEXT_DIR / "shams_system_prompt.md"

# Discover all tools at import time
discover_tools()

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    """Return current UTC time. Extracted for easy mocking in tests."""
    return datetime.now(timezone.utc)


def _build_core_prompt() -> str:
    """Load the static system prompt (identity + tone + routing)."""
    if CORE_PROMPT_FILE.exists():
        return CORE_PROMPT_FILE.read_text()
    return ""


def _build_hot_context() -> str:
    """Rotating context block based on time of day (ET approximation)."""
    now = _now()
    et_hour = (now.hour - 4) % 24
    parts: list[str] = []

    parts.append(f"**Current time (UTC):** {now.strftime('%Y-%m-%d %H:%M')}")

    # Time-slot specific context
    try:
        if et_hour < 5:
            # Overnight: balances, deadlines, recent decisions
            decisions = memory.get_recent_decisions(5)
            if decisions:
                parts.append("\n## Recent Decisions")
                for d in decisions:
                    parts.append(f"- {d['summary']}")
        elif et_hour < 10:
            # Morning: overnight results + pending actions
            overnight = memory.get_latest_overnight_run()
            if overnight and overnight.get("summary"):
                parts.append(f"\n## Overnight Summary\n{overnight['summary']}")
            actions = memory.get_actions(status="pending")
            if actions:
                parts.append("\n## Pending Actions")
                for a in actions[:5]:
                    parts.append(f"- [{a.get('id','')}] {a.get('title','')}")
        elif et_hour < 18:
            # Daytime: active missions, recent activity
            missions = memory.get_missions(status="active")
            if missions:
                parts.append("\n## Active Missions")
                for m in missions[:5]:
                    parts.append(f"- [{m.get('id','')}] {m.get('title','')}")
            activity = memory.get_activity_feed(limit=5)
            if activity:
                parts.append("\n## Recent Activity")
                for a in activity:
                    parts.append(f"- {a.get('content','')[:80]}")
        else:
            # Evening: day's decisions, completed actions
            decisions = memory.get_recent_decisions(5)
            if decisions:
                parts.append("\n## Today's Decisions")
                for d in decisions:
                    parts.append(f"- {d['summary']}")
            actions = memory.get_actions(status="done")
            if actions:
                parts.append("\n## Completed Actions")
                for a in actions[:5]:
                    parts.append(f"- {a.get('title','')}")
    except Exception:
        log.exception("Error loading time-slot context")

    # Always: open loops (first 5)
    try:
        loops = memory.get_open_loops()
        if loops:
            parts.append("\n## Open Loops")
            for loop in loops[:5]:
                parts.append(f"- [{loop['id']}] {loop['title']}: {loop.get('context','')}")
    except Exception:
        log.debug("Could not load open loops", exc_info=True)

    # Always: key memories (first 10)
    try:
        kv = memory.recall_all()
        if kv:
            parts.append("\n## Key Memories")
            for i, (k, v) in enumerate(kv.items()):
                if i >= 10:
                    break
                parts.append(f"- **{k}**: {v}")
    except Exception:
        log.debug("Could not load memories", exc_info=True)

    return "\n".join(parts)


def _build_system() -> str:
    """Combine core prompt + hot context + connected accounts + tool instructions."""
    core = _build_core_prompt()
    hot = _build_hot_context()

    system = core
    if hot:
        system += "\n\n---\n\n# Live Context\n" + hot

    # Connected Google accounts
    try:
        connected = []
        for acct_key, acct_email in config.GOOGLE_ACCOUNTS.items():
            token = memory.recall(f"google_{acct_key}_access_token")
            if token:
                connected.append(f"{acct_key} ({acct_email})")
        if connected:
            system += (
                f"\n\n# Connected Email Accounts\n"
                f"You have access to these Gmail accounts: {', '.join(connected)}. "
                f"When triaging email or answering questions about email, you pull from ALL connected accounts."
            )
    except Exception:
        log.debug("Could not check connected accounts", exc_info=True)

    # Tool usage instructions
    system += "\n\n# CRITICAL: Proactive Memory & Tracking"
    system += (
        "\nYou MUST use your memory tools automatically — never wait for Maher to ask you to remember something."
        "\n- **remember**: Save ANY new fact, preference, update, or context Maher shares."
        "\n- **add_open_loop**: When Maher mentions ANYTHING that needs follow-up — create an open loop."
        "\n- **log_decision**: When Maher makes or confirms a decision — log it with reasoning."
        "\n- **close_open_loop**: When something previously tracked gets resolved, close it."
        "\n\nYou are Maher's memory. Everything he tells you persists. Act like it."
    )

    return system


# ── Chat (with tool use loop) ────────────────────────────────────────────────


def chat(user_message: str, images: list | None = None) -> str:
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
    text_parts: list[str] = []
    max_iterations = 5
    for _i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=get_tool_definitions(),
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
                log.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:100])
                result = execute(block.name, block.input)
                # Ensure result is a string for the API
                if not isinstance(result, str):
                    result = json.dumps(result)
                # Log tool call to activity feed
                try:
                    memory.log_activity(
                        "shams", "tool_call",
                        f"{block.name}: {json.dumps(block.input)[:120]}",
                        {"tool": block.name, "input": block.input, "result_preview": (result or "")[:200]},
                    )
                except Exception:
                    log.debug("Could not log activity", exc_info=True)
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


def generate_briefing(briefing_type: str, context: str = "") -> str:
    """Generate a briefing with tool access (no conversation history)."""
    messages = [{"role": "user", "content": f"Generate a {briefing_type} briefing.\n\nContext:\n{context}"}]

    max_iterations = 5
    for _i in range(max_iterations):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=_build_system(),
            tools=get_tool_definitions(),
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if b.type == "text"]
            briefing = "\n".join(text_parts) if text_parts else ""
            try:
                memory.save_briefing(briefing_type, briefing, "telegram")
            except Exception:
                log.debug("Could not save briefing", exc_info=True)
            return briefing

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log.info("Briefing tool call: %s", block.name)
                result = execute(block.name, block.input)
                if not isinstance(result, str):
                    result = json.dumps(result)
                try:
                    memory.log_activity(
                        "shams", "tool_call",
                        f"[briefing] {block.name}: {json.dumps(block.input)[:120]}",
                        {"tool": block.name, "context": "briefing"},
                    )
                except Exception:
                    log.debug("Could not log activity", exc_info=True)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "Briefing generation incomplete."
