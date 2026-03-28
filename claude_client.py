"""Claude API wrapper with memory injection."""

import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import memory

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """\
You are Shams — MJ's personal AI chief of staff.
You have persistent memory across conversations.
You manage his calendar, track open loops, surface decisions, and deliver briefings.
Be direct, concise, and proactive. No fluff."""


def _build_memory_context() -> str:
    """Gather persistent memory to inject into the system prompt."""
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


def chat(user_message: str) -> str:
    """Send a message to Claude with full memory context, return response."""
    # Save user message
    memory.save_message("user", user_message)

    # Build messages from recent conversation history
    recent = memory.get_recent_messages(30)
    messages = [{"role": r["role"], "content": r["content"]} for r in recent]

    # Inject memory into system prompt
    mem_context = _build_memory_context()
    system = SYSTEM_PROMPT
    if mem_context:
        system += f"\n\n# Current State\n{mem_context}"

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    )

    reply = response.content[0].text

    # Save assistant response
    memory.save_message("assistant", reply)

    return reply


def generate_briefing(briefing_type: str, context: str) -> str:
    """Generate a briefing without saving to conversation history."""
    mem_context = _build_memory_context()
    system = SYSTEM_PROMPT
    if mem_context:
        system += f"\n\n# Current State\n{mem_context}"

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": f"Generate a {briefing_type} briefing.\n\nContext:\n{context}"}],
    )

    return response.content[0].text
