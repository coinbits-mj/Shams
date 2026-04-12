"""Action proposal and agent routing tools."""
from __future__ import annotations

import logging

from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="propose_action",
    description="Propose an action for Maher to approve before execution. Use this when you want to take an action that affects the real world — archiving emails, creating PRs, sending messages, drafting documents, etc. The action will appear in the dashboard for approval.",
    schema={
        "properties": {
            "action_type": {
                "type": "string",
                "description": "Type of action",
                "enum": ["archive_email", "send_message", "create_pr", "draft_document", "research", "schedule_meeting", "other"]
            },
            "title": {"type": "string", "description": "Short title describing the action (e.g. 'Archive 12 promotional emails')"},
            "description": {"type": "string", "description": "Detailed description of what will happen if approved"},
            "payload": {
                "type": "object",
                "description": "Action-specific data (email IDs, code diff, message content, etc.)"
            },
            "mission_id": {"type": "integer", "description": "Optional mission ID this action relates to"},
        },
        "required": ["action_type", "title"],
    },
)
def propose_action(action_type: str, title: str, description: str = "", payload: dict = None, mission_id: int = None) -> str:
    import memory

    action_id = memory.create_action(
        agent_name="shams",
        action_type=action_type,
        title=title,
        description=description,
        payload=payload,
        mission_id=mission_id,
    )
    memory.increment_trust("shams", "total_proposed")
    # Check auto-approve
    if memory.should_auto_approve("shams"):
        memory.update_action_status(action_id, "approved")
        memory.increment_trust("shams", "total_approved")
        memory.log_activity("shams", "action_auto_approved", f"Action #{action_id} auto-approved: {title}")
        return f"Action #{action_id} auto-approved: {title}"
    memory.log_activity("shams", "action_proposed", f"Action #{action_id}: {title}")
    memory.create_notification("action_pending", title, "", "action", action_id)
    # Send Telegram with approve/reject buttons
    try:
        import config as _cfg
        if _cfg.TELEGRAM_CHAT_ID:
            from telegram import send_telegram_with_buttons
            send_telegram_with_buttons(_cfg.TELEGRAM_CHAT_ID,
                f"Action #{action_id}: {title}\n{description}",
                [
                    {"text": "Approve", "callback_data": f"approve:{action_id}"},
                    {"text": "Reject", "callback_data": f"reject:{action_id}"},
                ])
    except Exception:
        pass
    return f"Action #{action_id} proposed: {title}. Waiting for Maher's approval (dashboard or Telegram)."


@tool(
    name="route_to_specialist",
    description="Send a message to a specialist agent with optional context from a previous action. The agent responds with their expertise. Use to delegate work or get a specialist's input.",
    schema={
        "properties": {
            "agent": {"type": "string", "enum": ["ops", "wakil", "leo"]},
            "query": {"type": "string", "description": "What you need from this agent"},
            "context_from_action_id": {"type": "integer", "description": "Optional: action ID whose result to include as context"},
        },
        "required": ["agent", "query"],
    },
)
def route_to_specialist(agent: str, query: str, context_from_action_id: int = None) -> str:
    import memory
    from agents.registry import call_agent

    extra = ""
    if context_from_action_id:
        action = memory.get_action(context_from_action_id)
        if action:
            extra = f"Context from previous action #{action['id']}:\n{action.get('result', '')}"
    response = call_agent(
        agent,
        query,
        extra_context=extra,
    )
    memory.log_activity(agent, "routed_message",
        f"Message from Shams: {query[:80]}")
    return f"[{agent}]: {response}"
