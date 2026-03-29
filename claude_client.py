"""Claude API wrapper with memory injection."""

import pathlib
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
import memory

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


def _build_system():
    """Build the full system prompt with knowledge base and memory."""
    mem_context = _build_memory_context()
    system = SYSTEM_PROMPT
    if KNOWLEDGE_BASE:
        system += f"\n\n# Knowledge Base\n{KNOWLEDGE_BASE}"
    if mem_context:
        system += f"\n\n# Live State (from memory)\n{mem_context}"
    return system


def chat(user_message: str, images: list = None) -> str:
    """Send a message to Claude with full memory context, return response.

    Args:
        user_message: The text message from the user.
        images: Optional list of dicts with 'data' (base64) and 'media_type' (e.g. 'image/jpeg').
    """
    # Save user message (text part only)
    label = user_message
    if images:
        label = f"[{len(images)} image(s)] {user_message}" if user_message else f"[{len(images)} image(s)]"
    memory.save_message("user", label)

    # Build messages from recent conversation history
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

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_build_system(),
        messages=messages,
    )

    reply = response.content[0].text
    memory.save_message("assistant", reply)

    return reply


def generate_briefing(briefing_type: str, context: str) -> str:
    """Generate a briefing without saving to conversation history."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_build_system(),
        messages=[{"role": "user", "content": f"Generate a {briefing_type} briefing.\n\nContext:\n{context}"}],
    )

    return response.content[0].text
