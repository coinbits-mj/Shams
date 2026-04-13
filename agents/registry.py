"""Agent registry — defines 5 agents, builds prompts, calls specialists."""

from __future__ import annotations

import json
import logging
import pathlib

logger = logging.getLogger(__name__)

CONTEXT_DIR = pathlib.Path(__file__).resolve().parent.parent / "context"

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS = {
    "shams": {
        "role": "Chief of Staff & Orchestrator",
        "persona_file": "shams_system_prompt.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
            "shams_knowledge_personal.md",
        ],
        "color": "#f59e0b",
    },
    "ops": {
        "role": "Operations, Research & Technical Agent",
        "persona_file": "ops.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
        ],
        "color": "#06b6d4",
    },
    "wakil": {
        "role": "Legal Strategist & Counsel",
        "persona_file": "wakil_persona.md",
        "knowledge_files": [
            "shams_knowledge_active_deals.md",
            "wakil_legal_cases.md",
        ],
        "color": "#a855f7",
    },
    "leo": {
        "role": "Health & Performance Coach",
        "persona_file": "leo_persona.md",
        "knowledge_files": [
            "shams_knowledge_personal.md",
        ],
        "color": "#22c55e",
    },
    "scout": {
        "role": "Market Intelligence & Research Agent",
        "persona_file": "scout_persona.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
        ],
        "color": "#ef4444",
    },
}

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_agent_system_prompt(agent_name: str, extra_context: str = "") -> str:
    """Build the full system prompt for an agent.

    Loads persona + knowledge files from context/ ON DEMAND.
    """
    agent = AGENTS.get(agent_name)
    if not agent:
        return f"You are {agent_name}."

    parts = []

    # Persona
    persona_path = CONTEXT_DIR / agent["persona_file"]
    if persona_path.exists():
        parts.append(persona_path.read_text())
    else:
        parts.append(f"You are {agent_name}, {agent['role']}.")

    # Knowledge files
    for kf in agent.get("knowledge_files", []):
        kf_path = CONTEXT_DIR / kf
        if kf_path.exists():
            parts.append(f"\n---\n{kf_path.read_text()}")

    # Extra context (live data, memory, etc.)
    if extra_context:
        parts.append(f"\n# Current Context\n{extra_context}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Agent caller — runs a tool-use loop with scoped tools
# ---------------------------------------------------------------------------


def call_agent(
    agent_name: str,
    message: str,
    history: list | None = None,
    extra_context: str = "",
) -> str:
    """Call a specialist agent with scoped tools. Runs a tool-use loop (max 5 iterations)."""
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from tools.registry import get_tool_definitions, execute

    agent = AGENTS.get(agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = build_agent_system_prompt(agent_name, extra_context)

    # Shams gets ALL tools (agent=None), specialists get scoped tools
    tool_scope = None if agent_name == "shams" else agent_name
    tools = get_tool_definitions(agent=tool_scope)

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    for _iteration in range(5):
        try:
            kwargs = {
                "model": CLAUDE_MODEL,
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            response = client.messages.create(**kwargs)
        except Exception as e:
            logger.error("Agent %s API error: %s", agent_name, e)
            return f"Error from {agent_name}: {e}"

        # If no tool use, extract text and return
        if response.stop_reason != "tool_use":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts)

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })

        messages.append({"role": "user", "content": tool_results})

    # Exhausted iterations — return whatever text we have
    text_parts = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_parts) if text_parts else f"{agent_name} reached max tool iterations."


# ---------------------------------------------------------------------------
# List agents (for dashboard)
# ---------------------------------------------------------------------------


def list_agents() -> list[dict]:
    """Return agent info for the dashboard."""
    return [
        {"name": name, "role": agent["role"], "color": agent["color"]}
        for name, agent in AGENTS.items()
    ]
