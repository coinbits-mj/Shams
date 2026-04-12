"""Projects — Missions + Projects + Gantt."""
from __future__ import annotations

import json
import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("projects", __name__, url_prefix="/api")


# ── Missions ─────────────────────────────────────────────────────────────────

@bp.route("/missions", methods=["GET"])
@require_auth
def get_missions():
    status = request.args.get("status")
    agent = request.args.get("agent")
    missions = memory.get_missions(status, agent)
    result = []
    for m in missions:
        d = dict(m)
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/missions", methods=["POST"])
@require_auth
def create_mission():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    mission_id = memory.create_mission(
        title, data.get("description", ""), data.get("priority", "normal"),
        data.get("assigned_agent"), data.get("tags", [])
    )
    memory.log_activity("shams", "mission_created", f"Mission #{mission_id}: {title}")
    return jsonify({"id": mission_id})


@bp.route("/missions/<int:mission_id>", methods=["GET"])
@require_auth
def get_mission(mission_id):
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM shams_missions WHERE id = %s", (mission_id,))
        mission = cur.fetchone()
        if not mission:
            return jsonify({"error": "not found"}), 404

        # Get related actions
        cur.execute("SELECT * FROM shams_actions WHERE mission_id = %s ORDER BY created_at", (mission_id,))
        actions = cur.fetchall()

        # Get linked files
        cur.execute(
            "SELECT id, filename, file_type, summary, uploaded_at FROM shams_files WHERE mission_id = %s ORDER BY uploaded_at",
            (mission_id,)
        )
        files = cur.fetchall()

        # Get related activity feed entries (matching mission ID in content)
        cur.execute(
            "SELECT * FROM shams_activity_feed WHERE content LIKE %s ORDER BY timestamp",
            (f"%Mission #{mission_id}%",)
        )
        activity = cur.fetchall()

    d = dict(mission)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()

    d["actions"] = []
    for a in actions:
        ad = dict(a)
        for k in ("created_at", "resolved_at"):
            if ad.get(k):
                ad[k] = ad[k].isoformat()
        if ad.get("payload") and isinstance(ad["payload"], str):
            ad["payload"] = json.loads(ad["payload"])
        d["actions"].append(ad)

    d["files"] = []
    for fi in files:
        fid = dict(fi)
        if fid.get("uploaded_at"):
            fid["uploaded_at"] = fid["uploaded_at"].isoformat()
        d["files"].append(fid)

    d["activity"] = []
    for f in activity:
        fd = dict(f)
        if fd.get("timestamp"):
            fd["timestamp"] = fd["timestamp"].isoformat()
        if fd.get("metadata") and isinstance(fd["metadata"], str):
            fd["metadata"] = json.loads(fd["metadata"])
        d["activity"].append(fd)

    return jsonify(d)


@bp.route("/missions/<int:mission_id>", methods=["PATCH"])
@require_auth
def update_mission(mission_id):
    data = request.get_json(silent=True) or {}
    memory.update_mission(mission_id, **data)
    if data.get("status"):
        memory.log_activity("shams", "mission_update", f"Mission #{mission_id} → {data['status']}")
    return jsonify({"ok": True})


# ── Projects (Gantt) ────────────────────────────────────────────────────────

@bp.route("/projects", methods=["GET"])
@require_auth
def get_projects():
    status = request.args.get("status")
    projects = memory.get_projects(status)
    result = []
    for p in projects:
        d = dict(p)
        for k in ("created_at", "updated_at", "start_date", "target_date"):
            if d.get(k):
                d[k] = d[k].isoformat() if hasattr(d[k], 'isoformat') else str(d[k])
        result.append(d)
    return jsonify(result)


@bp.route("/projects/<int:project_id>", methods=["GET"])
@require_auth
def get_project(project_id):
    proj = memory.get_project_with_missions(project_id)
    if not proj:
        return jsonify({"error": "not found"}), 404
    for k in ("created_at", "updated_at", "start_date", "target_date"):
        if proj.get(k):
            proj[k] = proj[k].isoformat() if hasattr(proj[k], 'isoformat') else str(proj[k])
    for m in proj.get("missions", []):
        for k in ("created_at", "updated_at", "start_date", "end_date"):
            if m.get(k):
                m[k] = m[k].isoformat() if hasattr(m[k], 'isoformat') else str(m[k])
    return jsonify(proj)


@bp.route("/projects", methods=["POST"])
@require_auth
def create_project():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    pid = memory.create_project(
        title=title, brief=data.get("brief", ""),
        start_date=data.get("start_date"), target_date=data.get("target_date"),
        color=data.get("color", "#38bdf8"),
    )
    return jsonify({"id": pid})


@bp.route("/projects/<int:project_id>", methods=["PATCH"])
@require_auth
def update_project(project_id):
    data = request.get_json(silent=True) or {}
    memory.update_project(project_id, **data)
    return jsonify({"ok": True})


@bp.route("/projects/<int:project_id>/gantt", methods=["GET"])
@require_auth
def get_project_gantt(project_id):
    """Get project with missions formatted for Gantt rendering."""
    proj = memory.get_project_with_missions(project_id)
    if not proj:
        return jsonify({"error": "not found"}), 404

    # Build Gantt data
    gantt = {
        "id": proj["id"],
        "title": proj["title"],
        "brief": proj.get("brief", ""),
        "color": proj.get("color", "#38bdf8"),
        "start_date": str(proj["start_date"]) if proj.get("start_date") else None,
        "target_date": str(proj["target_date"]) if proj.get("target_date") else None,
        "status": proj["status"],
        "tasks": [],
    }
    for m in proj.get("missions", []):
        gantt["tasks"].append({
            "id": m["id"],
            "title": m["title"],
            "status": m["status"],
            "priority": m["priority"],
            "assigned_agent": m.get("assigned_agent"),
            "start_date": str(m["start_date"]) if m.get("start_date") else None,
            "end_date": str(m["end_date"]) if m.get("end_date") else None,
            "depends_on": m.get("depends_on") or [],
        })
    return jsonify(gantt)


@bp.route("/gantt", methods=["GET"])
@require_auth
def get_all_gantt():
    """Get all active projects with their missions for the full Gantt view."""
    projects = memory.get_projects("active")
    result = []
    for p in projects:
        proj = memory.get_project_with_missions(p["id"])
        if not proj:
            continue
        gantt = {
            "id": proj["id"],
            "title": proj["title"],
            "brief": proj.get("brief", ""),
            "color": proj.get("color", "#38bdf8"),
            "start_date": str(proj["start_date"]) if proj.get("start_date") else None,
            "target_date": str(proj["target_date"]) if proj.get("target_date") else None,
            "status": proj["status"],
            "tasks": [],
        }
        for m in proj.get("missions", []):
            gantt["tasks"].append({
                "id": m["id"],
                "title": m["title"],
                "status": m["status"],
                "priority": m["priority"],
                "assigned_agent": m.get("assigned_agent"),
                "start_date": str(m["start_date"]) if m.get("start_date") else None,
                "end_date": str(m["end_date"]) if m.get("end_date") else None,
                "depends_on": m.get("depends_on") or [],
                "file_count": m.get("file_count", 0),
            })
        result.append(gantt)
    return jsonify(result)
