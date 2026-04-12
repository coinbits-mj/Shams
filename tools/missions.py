"""Mission, scheduled task, and workflow tools."""
from __future__ import annotations

import logging

from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="create_mission",
    description="Create a new mission (task/project) for an agent to work on. Use this when Maher mentions a task, project, or follow-up that should be tracked. Assign to the right agent based on domain.",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Short mission title"},
            "description": {"type": "string", "description": "What needs to be done"},
            "priority": {"type": "string", "enum": ["urgent", "high", "normal", "low"], "default": "normal"},
            "assigned_agent": {"type": "string", "description": "Agent to assign: shams, rumi, leo, wakil, scout, builder"},
        },
        "required": ["title"],
    },
)
def create_mission(title: str, description: str = "", priority: str = "normal", assigned_agent: str = None) -> str:
    import memory

    mission_id = memory.create_mission(
        title=title,
        description=description,
        priority=priority,
        assigned_agent=assigned_agent,
        tags=[],
    )
    agent = assigned_agent or "unassigned"
    memory.log_activity("shams", "mission_created", f"Mission #{mission_id}: {title} → {agent}")
    memory.create_notification("mission_created", f"New mission: {title}", f"Assigned to {agent}", "mission", mission_id)
    return f"Mission #{mission_id} created: {title} (assigned to {agent})"


@tool(
    name="update_mission",
    description="Update the status or result of an existing mission. Use this when a mission progresses, gets blocked, or is completed.",
    schema={
        "properties": {
            "mission_id": {"type": "integer", "description": "The mission ID to update"},
            "status": {"type": "string", "enum": ["inbox", "assigned", "active", "review", "done", "dropped"]},
            "result": {"type": "string", "description": "Result or outcome when completing a mission"},
        },
        "required": ["mission_id"],
    },
)
def update_mission(mission_id: int, status: str = None, result: str = None) -> str:
    import memory

    kwargs = {}
    if status:
        kwargs["status"] = status
    if result:
        kwargs["result"] = result
    memory.update_mission(mission_id, **kwargs)
    status_label = status or "updated"
    memory.log_activity("shams", "mission_update",
        f"Mission #{mission_id} → {status_label}")
    memory.create_notification("mission_updated", f"Mission #{mission_id} → {status_label}", "", "mission", mission_id)
    return f"Mission #{mission_id} updated."


@tool(
    name="schedule_task",
    description="Create a recurring scheduled task. Use when Maher says 'every Monday...', 'from now on...', 'daily at 8am...', etc. Creates a persistent job that runs automatically on schedule.",
    schema={
        "properties": {
            "name": {"type": "string", "description": "Short name for this task"},
            "cron_expression": {"type": "string", "description": "Cron expression in UTC (e.g. '0 14 * * 1' for Monday 9am ET / 2pm UTC, '0 12 * * 1-5' for weekdays 7am ET)"},
            "prompt": {"type": "string", "description": "The instruction to execute each run"},
        },
        "required": ["name", "cron_expression", "prompt"],
    },
)
def schedule_task(name: str, cron_expression: str, prompt: str) -> str:
    import memory

    task_id = memory.create_scheduled_task(
        name=name,
        cron_expression=cron_expression,
        prompt=prompt,
    )
    # Register with live scheduler
    try:
        from scheduler import register_dynamic_task
        register_dynamic_task(task_id, cron_expression, prompt)
    except Exception as e:
        logger.warning(f"Could not register task live (will load on restart): {e}")
    memory.log_activity("shams", "task_scheduled",
        f"Scheduled task #{task_id}: {name} ({cron_expression})")
    memory.create_notification("task_scheduled", f"Recurring task created: {name}", cron_expression, "", None)
    return f"Scheduled task #{task_id} created: {name}\nSchedule: {cron_expression}\nPrompt: {prompt}"


@tool(
    name="list_scheduled_tasks",
    description="List all scheduled recurring tasks.",
    schema={"properties": {}},
)
def list_scheduled_tasks() -> str:
    import memory

    tasks = memory.get_scheduled_tasks()
    if not tasks:
        return "No scheduled tasks."
    lines = []
    for t in tasks:
        status = "enabled" if t["enabled"] else "disabled"
        last = t["last_run_at"].isoformat() if t.get("last_run_at") else "never"
        lines.append(f"#{t['id']}: {t['name']} [{status}] — cron: {t['cron_expression']} — last run: {last}")
    return "\n".join(lines)


@tool(
    name="cancel_scheduled_task",
    description="Cancel/disable a scheduled task by ID.",
    schema={
        "properties": {
            "task_id": {"type": "integer", "description": "ID of the task to cancel"},
        },
        "required": ["task_id"],
    },
)
def cancel_scheduled_task(task_id: int) -> str:
    import memory

    memory.update_scheduled_task(task_id, enabled=False)
    try:
        from scheduler import remove_dynamic_task
        remove_dynamic_task(task_id)
    except Exception:
        pass
    return f"Scheduled task #{task_id} disabled."


@tool(
    name="create_workflow",
    description="Create a multi-step workflow that chains agents together. Each step runs in sequence — the output of one step feeds into the next agent. Use for complex requests needing multiple agents (e.g. research → draft → review).",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Workflow title"},
            "description": {"type": "string", "description": "What this workflow accomplishes"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "enum": ["shams", "rumi", "leo", "wakil", "scout", "builder"]},
                        "instruction": {"type": "string", "description": "What this agent should do in this step"},
                        "requires_approval": {"type": "boolean"},
                    },
                    "required": ["agent_name", "instruction"],
                },
            },
        },
        "required": ["title", "steps"],
    },
)
def create_workflow(title: str, steps: list, description: str = "") -> str:
    import memory

    workflow_id = memory.create_workflow(
        title=title,
        description=description,
        steps=steps,
    )
    step_list = "\n".join(
        f"  {i+1}. {s['agent_name']}: {s['instruction'][:80]}"
        for i, s in enumerate(steps)
    )
    memory.log_activity("shams", "workflow_created",
        f"Workflow #{workflow_id}: {title} ({len(steps)} steps)")
    memory.create_notification("workflow_created", f"Workflow: {title}", f"{len(steps)} steps", "workflow", workflow_id)
    # Start first step
    try:
        from workflow_engine import run_next_step
        run_next_step(workflow_id)
    except Exception as e:
        logger.warning(f"Could not auto-start workflow: {e}")
    return f"Workflow #{workflow_id} created: {title}\nSteps:\n{step_list}\n\nStep 1 is starting now."
