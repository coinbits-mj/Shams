"""Actions — approve/reject/execute, trust scores."""
from __future__ import annotations

import json
import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("actions", __name__, url_prefix="/api")


def _auto_advance_mission(action: dict):
    """If an action is linked to a mission, check if all actions are done and advance."""
    mission_id = action.get("mission_id")
    if not mission_id:
        return
    actions = memory.get_actions_for_mission(mission_id)
    all_done = all(a["status"] in ("completed", "rejected") for a in actions)
    if all_done:
        memory.update_mission(mission_id, status="review")
        memory.log_activity(action["agent_name"], "mission_update", f"Mission #{mission_id} → review (all actions complete)")
        memory.create_notification("mission_updated", f"Mission #{mission_id} ready for review", "", "mission", mission_id)


@bp.route("/actions", methods=["GET"])
@require_auth
def get_actions():
    status = request.args.get("status")
    agent = request.args.get("agent")
    limit = request.args.get("limit", 50, type=int)
    actions = memory.get_actions(status, agent, limit)
    result = []
    for a in actions:
        d = dict(a)
        for k in ("created_at", "resolved_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if d.get("payload") and isinstance(d["payload"], str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return jsonify(result)


@bp.route("/actions/<int:action_id>", methods=["GET"])
@require_auth
def get_action(action_id):
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    d = dict(a)
    for k in ("created_at", "resolved_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    if d.get("payload") and isinstance(d["payload"], str):
        d["payload"] = json.loads(d["payload"])
    return jsonify(d)


@bp.route("/actions/<int:action_id>/approve", methods=["POST"])
@require_auth
def approve_action(action_id):
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "pending":
        return jsonify({"error": f"Action is already {a['status']}"}), 400
    memory.update_action_status(action_id, "approved")
    memory.increment_trust(a["agent_name"], "total_approved")
    memory.log_activity(a["agent_name"], "action_approved", f"Action #{action_id} approved: {a['title']}")

    # Check if this is a workflow step — resume workflow
    payload = a.get("payload", {})
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    if payload.get("workflow_id"):
        try:
            from workflow_engine import resume_after_approval
            resume_after_approval(action_id)
        except Exception as e:
            logger.error(f"Workflow resume failed: {e}")

    return jsonify({"ok": True})


@bp.route("/actions/<int:action_id>/reject", methods=["POST"])
@require_auth
def reject_action(action_id):
    data = request.get_json(silent=True) or {}
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "pending":
        return jsonify({"error": f"Action is already {a['status']}"}), 400
    memory.update_action_status(action_id, "rejected", data.get("reason", ""))
    memory.increment_trust(a["agent_name"], "total_rejected")
    memory.log_activity(a["agent_name"], "action_rejected", f"Action #{action_id} rejected: {a['title']}")
    return jsonify({"ok": True})


@bp.route("/actions/<int:action_id>/execute", methods=["POST"])
@require_auth
def execute_action(action_id):
    """Execute an approved action."""
    a = memory.get_action(action_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    if a["status"] != "approved":
        return jsonify({"error": f"Action must be approved first (currently {a['status']})"}), 400

    memory.update_action_status(action_id, "executing")
    payload = a["payload"] if isinstance(a["payload"], dict) else json.loads(a["payload"] or "{}")

    try:
        if a["action_type"] == "create_pr":
            import github_client
            import re
            # Generate a branch name from the title
            branch = "shams/" + re.sub(r'[^a-z0-9]+', '-', payload.get("title", "change").lower())[:50].strip('-')
            pr = github_client.create_pr_with_files(
                repo_key=payload["repo"],
                branch_name=branch,
                title=payload["title"],
                description=payload.get("description", ""),
                files=payload.get("files", []),
            )
            result = f"PR #{pr['number']} created: {pr['url']}"
            memory.update_action_status(action_id, "completed", result)
            memory.log_activity("builder", "action_completed", f"Action #{action_id}: {result}")
            memory.create_notification("action_completed", f"PR created: {payload['title']}", result, "action", action_id)
            _auto_advance_mission(a)
            return jsonify({"ok": True, "result": result, "pr": pr})
        else:
            # Generic actions — mark completed, no auto-execution
            memory.update_action_status(action_id, "completed", "Executed manually")
            memory.log_activity(a["agent_name"], "action_completed", f"Action #{action_id} executed")
            memory.create_notification("action_completed", a["title"], "", "action", action_id)
            _auto_advance_mission(a)
            return jsonify({"ok": True, "result": "Action marked as executed"})

    except Exception as e:
        error_msg = str(e)
        memory.update_action_status(action_id, "failed", error_msg)
        memory.log_activity(a["agent_name"], "error", f"Action #{action_id} failed: {error_msg}")
        logger.error(f"Action execution error: {e}", exc_info=True)
        return jsonify({"error": error_msg}), 500


@bp.route("/actions/batch-approve", methods=["POST"])
@require_auth
def batch_approve_actions():
    data = request.get_json(silent=True) or {}
    action_ids = data.get("ids", [])
    approved = 0
    for aid in action_ids:
        a = memory.get_action(aid)
        if a and a["status"] == "pending":
            memory.update_action_status(aid, "approved")
            memory.log_activity(a["agent_name"], "action_approved", f"Action #{aid} approved: {a['title']}")
            approved += 1
    return jsonify({"ok": True, "approved": approved})


# ── Trust Scores ────────────────────────────────────────────────────────────

@bp.route("/trust", methods=["GET"])
@require_auth
def get_trust():
    scores = memory.get_all_trust_scores()
    result = []
    for s in scores:
        d = dict(s)
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        # Calculate approval rate
        total = d.get("total_approved", 0) + d.get("total_rejected", 0)
        d["approval_rate"] = round(d["total_approved"] / total * 100, 1) if total > 0 else 0
        d["eligible_for_auto"] = d["total_proposed"] >= 10 and d["approval_rate"] >= 90
        result.append(d)
    return jsonify(result)


@bp.route("/trust/<agent_name>/auto-approve", methods=["POST"])
@require_auth
def toggle_auto_approve(agent_name):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", False)
    memory.set_auto_approve(agent_name, enabled)
    memory.log_activity("shams", "trust_update",
        f"Auto-approve {'enabled' if enabled else 'disabled'} for {agent_name}")
    return jsonify({"ok": True})
