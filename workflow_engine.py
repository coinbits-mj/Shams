"""Workflow engine — executes multi-step agent workflows."""

from __future__ import annotations

import logging
import memory
from agents.registry import call_agent

logger = logging.getLogger(__name__)


def run_next_step(workflow_id: int):
    """Execute the next pending step in a workflow."""
    wf = memory.get_workflow(workflow_id)
    if not wf or wf["status"] != "active":
        return

    step = memory.get_active_workflow_step(workflow_id)
    if not step:
        # No more steps — workflow is done
        memory.update_workflow_status(workflow_id, "completed")
        if wf.get("mission_id"):
            memory.update_mission(wf["mission_id"], status="review")
        memory.log_activity("shams", "workflow_completed", f"Workflow #{workflow_id} completed: {wf['title']}")
        memory.create_notification("workflow_completed", f"Workflow complete: {wf['title']}", "", "workflow", workflow_id)

        # Send Telegram notification
        try:
            import config
            if config.TELEGRAM_CHAT_ID:
                from telegram import send_telegram
                send_telegram(config.TELEGRAM_CHAT_ID,
                    f"Workflow complete: {wf['title']}\n\nAll {len(wf.get('steps', []))} steps finished.")
        except Exception:
            pass
        return

    step_num = step["step_number"]
    agent = step["agent_name"]
    instruction = step["instruction"]
    context = step.get("input_context", "")

    # Mark step as active
    memory.start_workflow_step(workflow_id, step_num)
    memory.log_activity(agent, "workflow_step",
        f"Workflow #{workflow_id} step {step_num}: {instruction[:80]}")

    if step.get("requires_approval"):
        # Create an action and pause — workflow resumes when approved
        action_id = memory.create_action(
            agent_name=agent,
            action_type="workflow_step",
            title=f"[Workflow #{workflow_id} Step {step_num}] {instruction[:100]}",
            description=f"Workflow: {wf['title']}\nStep {step_num}/{len(wf.get('steps', []))}\n\nInstruction: {instruction}",
            payload={"workflow_id": workflow_id, "step_number": step_num, "context": context[:500]},
            mission_id=wf.get("mission_id"),
        )
        # Link action to step
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE shams_workflow_steps SET action_id = %s WHERE workflow_id = %s AND step_number = %s",
                (action_id, workflow_id, step_num),
            )
        memory.create_notification("action_pending",
            f"Workflow step needs approval: {instruction[:80]}", "", "action", action_id)

        # Send Telegram with buttons
        try:
            import config
            if config.TELEGRAM_CHAT_ID:
                from telegram import send_telegram_with_buttons
                send_telegram_with_buttons(config.TELEGRAM_CHAT_ID,
                    f"Workflow: {wf['title']}\nStep {step_num}: {instruction}\n\nApprove to continue:",
                    [
                        {"text": "Approve", "callback_data": f"approve:{action_id}"},
                        {"text": "Reject", "callback_data": f"reject:{action_id}"},
                    ])
        except Exception:
            pass
        return  # Paused — will resume when action is approved

    # No approval needed — execute directly
    try:
        prompt = instruction
        if context:
            prompt = f"Context from previous step:\n{context}\n\n---\n\nYour task:\n{instruction}"

        result = call_agent(agent, prompt, max_tokens=2048)
        if not isinstance(result, str):
            result = str(result)

        # Advance workflow
        memory.advance_workflow_step(workflow_id, step_num, result)
        memory.log_activity(agent, "workflow_step_completed",
            f"Workflow #{workflow_id} step {step_num} done")

        # Auto-start next step
        run_next_step(workflow_id)

    except Exception as e:
        logger.error(f"Workflow #{workflow_id} step {step_num} failed: {e}", exc_info=True)
        memory.advance_workflow_step(workflow_id, step_num, f"Error: {e}")
        memory.update_workflow_status(workflow_id, "failed")
        memory.log_activity(agent, "error", f"Workflow #{workflow_id} step {step_num} failed: {e}")


def resume_after_approval(action_id: int):
    """Called when a workflow step's action is approved. Resumes the workflow."""
    action = memory.get_action(action_id)
    if not action:
        return

    payload = action.get("payload", {})
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)

    workflow_id = payload.get("workflow_id")
    step_number = payload.get("step_number")
    if not workflow_id or not step_number:
        return

    step = None
    wf = memory.get_workflow(workflow_id)
    if wf:
        for s in wf.get("steps", []):
            if s["step_number"] == step_number:
                step = s
                break

    if not step:
        return

    # Execute the approved step
    agent = step["agent_name"]
    instruction = step["instruction"]
    context = step.get("input_context", "")

    try:
        prompt = instruction
        if context:
            prompt = f"Context from previous step:\n{context}\n\n---\n\nYour task:\n{instruction}"

        result = call_agent(agent, prompt, max_tokens=2048)
        if not isinstance(result, str):
            result = str(result)

        memory.advance_workflow_step(workflow_id, step_number, result)
        memory.log_activity(agent, "workflow_step_completed",
            f"Workflow #{workflow_id} step {step_number} done (after approval)")

        # Continue to next step
        run_next_step(workflow_id)

    except Exception as e:
        logger.error(f"Workflow #{workflow_id} step {step_number} failed after approval: {e}")
        memory.update_workflow_status(workflow_id, "failed")
