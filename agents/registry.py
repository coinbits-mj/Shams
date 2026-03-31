"""Agent registry — defines all agents, their personas, tools, and knowledge."""

from __future__ import annotations

import json
import logging
import pathlib
import anthropic
import concurrent.futures
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

AGENTS_DIR = pathlib.Path(__file__).parent
CONTEXT_DIR = pathlib.Path(__file__).parent.parent / "context"

# Agent definitions — each agent has a persona, model, and knowledge files
AGENT_DEFS = {
    "shams": {
        "role": "Chief of Staff & Orchestrator",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "shams_system_prompt.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
            "shams_knowledge_personal.md",
        ],
        "color": "#f59e0b",
    },
    "rumi": {
        "role": "QCC Operations Intelligence",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "rumi_persona.md",
        "knowledge_files": ["shams_knowledge_qcc_overview.md"],
        "color": "#06b6d4",
    },
    "leo": {
        "role": "Health & Performance Coach",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "leo_persona.md",
        "knowledge_files": ["shams_knowledge_personal.md"],
        "color": "#22c55e",
    },
    "wakil": {
        "role": "Legal Strategist & Counsel",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "wakil_persona.md",
        "knowledge_files": [
            "shams_knowledge_active_deals.md",
            "wakil_legal_cases.md",
        ],
        "color": "#a855f7",
    },
    "scout": {
        "role": "Market Intelligence & Research",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "scout_persona.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
        ],
        "color": "#ef4444",
    },
    "builder": {
        "role": "Software Engineer & Code Agent",
        "model": "claude-sonnet-4-20250514",
        "persona_file": "builder_persona.md",
        "knowledge_files": [],
        "color": "#3b82f6",
    },
}

# Inbox is NOT a standalone agent — it's a skill Shams uses.
# The persona file is loaded by Shams when triaging email.


def _load_file(filename: str) -> str:
    """Load a context file from the context/ directory or agents/ directory."""
    for base in [CONTEXT_DIR, AGENTS_DIR]:
        path = base / filename
        if path.exists():
            return path.read_text()
    return ""


def build_agent_system_prompt(agent_name: str, extra_context: str = "") -> str:
    """Build the full system prompt for an agent."""
    agent = AGENT_DEFS.get(agent_name)
    if not agent:
        return f"You are {agent_name}."

    parts = []

    # Persona
    persona = _load_file(agent["persona_file"])
    if persona:
        parts.append(persona)
    else:
        parts.append(f"You are {agent_name}, {agent['role']}.")

    # Knowledge base
    for kf in agent.get("knowledge_files", []):
        content = _load_file(kf)
        if content:
            parts.append(f"\n---\n{content}")

    # Extra context (live data, memory, etc.)
    if extra_context:
        parts.append(f"\n# Current Context\n{extra_context}")

    return "\n\n".join(parts)


def call_agent(agent_name: str, message: str, history: list = None,
               tools: list = None, extra_context: str = "", max_tokens: int = 2048) -> str:
    """Call a specific agent with a message and optional conversation history."""
    agent = AGENT_DEFS.get(agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found."

    system = build_agent_system_prompt(agent_name, extra_context)

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    kwargs = {
        "model": agent.get("model", "claude-sonnet-4-20250514"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        response = client.messages.create(**kwargs)

        # Handle tool use loop
        if response.stop_reason == "tool_use" and tools:
            # Return raw response for caller to handle tools
            return response

        text_parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_parts)

    except Exception as e:
        logger.error(f"Agent {agent_name} error: {e}")
        return f"Error from {agent_name}: {e}"


def call_agents_parallel(agent_names: list, message: str, extra_contexts: dict = None) -> dict:
    """Call multiple agents in parallel. Returns {agent_name: response}."""
    extra_contexts = extra_contexts or {}
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agent_names)) as executor:
        futures = {
            executor.submit(call_agent, name, message, extra_context=extra_contexts.get(name, "")): name
            for name in agent_names
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = f"Error: {e}"

    return results


def list_agents() -> list[dict]:
    """List all available agents."""
    return [
        {"name": name, "role": agent["role"], "color": agent["color"]}
        for name, agent in AGENT_DEFS.items()
    ]
