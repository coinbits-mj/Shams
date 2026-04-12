"""Settings — alert rules, delegations, notifications, scheduled tasks, workflows."""
from __future__ import annotations

import json
import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("settings", __name__, url_prefix="/api")


# ── Alert Rules ─────────────────────────────────────────────────────────────

@bp.route("/alert-rules", methods=["GET"])
@require_auth
def get_alert_rules():
    rules = memory.get_alert_rules()
    result = []
    for r in rules:
        d = dict(r)
        for k in ("last_triggered", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat() if hasattr(d[k], 'isoformat') else str(d[k])
        if d.get("threshold"):
            d["threshold"] = float(d["threshold"])
        result.append(d)
    return jsonify(result)


@bp.route("/alert-rules", methods=["POST"])
@require_auth
def create_alert_rule():
    data = request.get_json(silent=True) or {}
    rule_id = memory.create_alert_rule(
        name=data.get("name", ""),
        metric=data.get("metric", ""),
        condition=data.get("condition", "<"),
        threshold=data.get("threshold", 0),
        message_template=data.get("message_template", ""),
    )
    return jsonify({"id": rule_id})


@bp.route("/alert-rules/<int:rule_id>", methods=["PATCH"])
@require_auth
def update_alert_rule(rule_id):
    data = request.get_json(silent=True) or {}
    memory.update_alert_rule(rule_id, **{k: v for k, v in data.items() if k in ("name", "enabled", "threshold", "condition", "message_template")})
    return jsonify({"ok": True})


# ── Delegations (MJ's Outbox) ───────────────────────────────────────────────

@bp.route("/delegations", methods=["GET"])
@require_auth
def get_delegations():
    """Everything MJ has asked for — missions, actions, workflows — in one view."""
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    items = []

    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Active missions
        cur.execute(
            "SELECT id, title, status, priority, assigned_agent, created_at, updated_at, result "
            "FROM shams_missions WHERE status NOT IN ('done', 'dropped') ORDER BY created_at DESC LIMIT 30"
        )
        for m in cur.fetchall():
            items.append({
                "type": "mission", "id": m["id"], "title": m["title"],
                "status": m["status"], "agent": m["assigned_agent"],
                "priority": m["priority"], "result": m.get("result", ""),
                "created_at": m["created_at"].isoformat() if m.get("created_at") else "",
                "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else "",
            })

        # Pending/executing actions
        cur.execute(
            "SELECT id, agent_name, action_type, title, status, created_at, resolved_at, result "
            "FROM shams_actions WHERE status IN ('pending', 'approved', 'executing') ORDER BY created_at DESC LIMIT 20"
        )
        for a in cur.fetchall():
            items.append({
                "type": "action", "id": a["id"], "title": a["title"],
                "status": a["status"], "agent": a["agent_name"],
                "action_type": a["action_type"], "result": a.get("result", ""),
                "created_at": a["created_at"].isoformat() if a.get("created_at") else "",
                "updated_at": a["resolved_at"].isoformat() if a.get("resolved_at") else "",
            })

        # Active workflows
        cur.execute(
            "SELECT id, title, status, current_step, created_at, updated_at "
            "FROM shams_workflows WHERE status = 'active' ORDER BY created_at DESC LIMIT 10"
        )
        for w in cur.fetchall():
            items.append({
                "type": "workflow", "id": w["id"], "title": w["title"],
                "status": f"step {w['current_step']}", "agent": "shams",
                "created_at": w["created_at"].isoformat() if w.get("created_at") else "",
                "updated_at": w["updated_at"].isoformat() if w.get("updated_at") else "",
            })

        # Recently completed (last 10)
        cur.execute(
            "SELECT id, title, status, assigned_agent, result, updated_at "
            "FROM shams_missions WHERE status IN ('done', 'dropped') ORDER BY updated_at DESC LIMIT 10"
        )
        for m in cur.fetchall():
            items.append({
                "type": "mission", "id": m["id"], "title": m["title"],
                "status": m["status"], "agent": m["assigned_agent"],
                "result": m.get("result", ""),
                "created_at": "", "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else "",
                "completed": True,
            })

    # Sort: incomplete first (by created_at desc), then completed
    incomplete = sorted([i for i in items if not i.get("completed")], key=lambda x: x.get("created_at", ""), reverse=True)
    completed = [i for i in items if i.get("completed")]
    return jsonify({"active": incomplete, "completed": completed})


# ── Notifications ───────────────────────────────────────────────────────────

@bp.route("/notifications", methods=["GET"])
@require_auth
def get_notifications():
    notifs = memory.get_unseen_notifications(30)
    result = []
    for n in notifs:
        d = dict(n)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/notifications/mark-seen", methods=["POST"])
@require_auth
def mark_seen():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    memory.mark_notifications_seen(ids)
    return jsonify({"ok": True})


@bp.route("/notifications/counts", methods=["GET"])
@require_auth
def notification_counts():
    counts = memory.get_notification_counts()
    return jsonify(counts)


# ── Scheduled Tasks ─────────────────────────────────────────────────────────

@bp.route("/scheduled-tasks", methods=["GET"])
@require_auth
def get_scheduled_tasks():
    tasks = memory.get_scheduled_tasks()
    result = []
    for t in tasks:
        d = dict(t)
        for k in ("last_run_at", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/scheduled-tasks/<int:task_id>", methods=["PATCH"])
@require_auth
def update_scheduled_task(task_id):
    data = request.get_json(silent=True) or {}
    memory.update_scheduled_task(task_id, **{k: v for k, v in data.items() if k in ("name", "cron_expression", "prompt", "enabled")})
    if data.get("enabled") is False:
        try:
            from scheduler import remove_dynamic_task
            remove_dynamic_task(task_id)
        except Exception:
            pass
    elif data.get("enabled") is True and data.get("cron_expression"):
        try:
            from scheduler import register_dynamic_task
            register_dynamic_task(task_id, data["cron_expression"], data.get("prompt", ""))
        except Exception:
            pass
    return jsonify({"ok": True})


@bp.route("/scheduled-tasks/<int:task_id>", methods=["DELETE"])
@require_auth
def delete_scheduled_task(task_id):
    memory.delete_scheduled_task(task_id)
    try:
        from scheduler import remove_dynamic_task
        remove_dynamic_task(task_id)
    except Exception:
        pass
    return jsonify({"ok": True})


@bp.route("/scheduled-tasks/<int:task_id>/run", methods=["POST"])
@require_auth
def run_scheduled_task(task_id):
    from scheduler import _run_dynamic_task
    _run_dynamic_task(task_id)
    return jsonify({"ok": True})


# ── Workflows ──────────────────────────────────────────────────────────────

@bp.route("/workflows", methods=["GET"])
@require_auth
def get_workflows():
    status = request.args.get("status")
    workflows = memory.get_workflows(status)
    result = []
    for w in workflows:
        d = dict(w)
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/workflows/<int:workflow_id>", methods=["GET"])
@require_auth
def get_workflow(workflow_id):
    wf = memory.get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "not found"}), 404
    for k in ("created_at", "updated_at"):
        if wf.get(k):
            wf[k] = wf[k].isoformat()
    for step in wf.get("steps", []):
        for k in ("started_at", "completed_at"):
            if step.get(k):
                step[k] = step[k].isoformat()
    return jsonify(wf)


@bp.route("/workflows/<int:workflow_id>/pause", methods=["POST"])
@require_auth
def pause_workflow(workflow_id):
    memory.update_workflow_status(workflow_id, "paused")
    return jsonify({"ok": True})


@bp.route("/workflows/<int:workflow_id>/resume", methods=["POST"])
@require_auth
def resume_workflow(workflow_id):
    memory.update_workflow_status(workflow_id, "active")
    from workflow_engine import run_next_step
    run_next_step(workflow_id)
    return jsonify({"ok": True})
