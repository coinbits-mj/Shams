"""Files — folders, files, search, recent, mission files."""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, g

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("files", __name__, url_prefix="/api")


@bp.route("/folders", methods=["GET"])
@require_auth
def get_folders():
    parent_id = request.args.get("parent_id", None, type=int)
    folders = memory.get_folders(parent_id)
    result = []
    for f in folders:
        d = dict(f)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/folders", methods=["POST"])
@require_auth
def create_folder():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    folder_id = memory.create_folder(name, data.get("parent_id"))
    return jsonify({"id": folder_id})


@bp.route("/files", methods=["GET"])
@require_auth
def get_files():
    folder_id = request.args.get("folder_id", None, type=int)
    file_type = request.args.get("type")
    limit = request.args.get("limit", 50, type=int)
    files = memory.get_files(folder_id, file_type, limit)
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        # Don't send full transcript in list view
        if d.get("transcript"):
            d["transcript_preview"] = d["transcript"][:200]
            del d["transcript"]
        result.append(d)
    return jsonify(result)


@bp.route("/files/<int:file_id>", methods=["GET"])
@require_auth
def get_file(file_id):
    f = memory.get_file(file_id)
    if not f:
        return jsonify({"error": "not found"}), 404
    d = dict(f)
    if d.get("uploaded_at"):
        d["uploaded_at"] = d["uploaded_at"].isoformat()
    return jsonify(d)


@bp.route("/files/<int:file_id>/move", methods=["POST"])
@require_auth
def move_file(file_id):
    data = request.get_json(silent=True) or {}
    folder_id = data.get("folder_id")
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("UPDATE shams_files SET folder_id = %s WHERE id = %s", (folder_id, file_id))
    return jsonify({"ok": True})


# ── Mission File Room ───────────────────────────────────────────────────────

@bp.route("/missions/<int:mission_id>/files", methods=["GET"])
@require_auth
def get_mission_files(mission_id):
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, filename, file_type, mime_type, file_size, summary, file_category, "
            "version, uploaded_by, uploaded_at FROM shams_files "
            "WHERE mission_id = %s ORDER BY uploaded_at DESC",
            (mission_id,)
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/missions/<int:mission_id>/files", methods=["POST"])
@require_auth
def upload_mission_file(mission_id):
    """Upload a file to a mission's file room."""
    import base64

    if not request.content_type or "multipart" not in request.content_type:
        return jsonify({"error": "multipart form required"}), 400

    files = request.files.getlist("files")
    category = request.form.get("category", "")
    description = request.form.get("description", "")

    uploaded = []
    for f in files:
        file_bytes = f.read()
        mime = f.content_type or ""
        fname = f.filename or "upload"

        # Extract text for searchability
        transcript = ""
        if mime == "application/pdf":
            try:
                from telegram import extract_document_text
                transcript = extract_document_text(file_bytes, fname)
            except Exception:
                pass
        elif mime.startswith("text/") or fname.endswith(('.txt', '.md', '.csv', '.json')):
            try:
                transcript = file_bytes.decode("utf-8")[:10000]
            except Exception:
                pass

        # Check for existing version
        from config import DATABASE_URL
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(version) FROM shams_files WHERE mission_id = %s AND filename = %s",
                (mission_id, fname)
            )
            max_ver = cur.fetchone()[0]
        version = (max_ver or 0) + 1

        file_id = memory.save_file(
            filename=fname,
            file_type=category or ("pdf" if mime == "application/pdf" else "document"),
            mime_type=mime,
            file_size=len(file_bytes),
            summary=description or f"Uploaded to mission #{mission_id}",
            transcript=transcript[:5000] if transcript else "",
            mission_id=mission_id,
        )

        # Update category, version, uploaded_by
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE shams_files SET file_category = %s, version = %s, uploaded_by = %s WHERE id = %s",
                (category, version, g.email or "maher", file_id)
            )

        memory.log_activity("shams", "file_uploaded",
            f"File uploaded to mission #{mission_id}: {fname} (v{version})",
            {"file_id": file_id, "mission_id": mission_id})
        memory.create_notification("file_uploaded", f"New file: {fname}", f"Mission #{mission_id}", "file", file_id)

        uploaded.append({"id": file_id, "filename": fname, "version": version})

    return jsonify({"ok": True, "files": uploaded})


@bp.route("/files/search", methods=["GET"])
@require_auth
def search_files():
    """Search across all files by name or content."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, filename, file_type, summary, mission_id, uploaded_at "
            "FROM shams_files WHERE filename ILIKE %s OR summary ILIKE %s OR transcript ILIKE %s "
            "ORDER BY uploaded_at DESC LIMIT 20",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)


@bp.route("/files/recent", methods=["GET"])
@require_auth
def recent_files():
    """Get most recent files across all missions."""
    limit = request.args.get("limit", 10, type=int)
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT f.id, f.filename, f.file_type, f.summary, f.mission_id, f.file_category, "
            "f.version, f.uploaded_by, f.uploaded_at, m.title as mission_title "
            "FROM shams_files f LEFT JOIN shams_missions m ON f.mission_id = m.id "
            "ORDER BY f.uploaded_at DESC LIMIT %s",
            (limit,)
        )
        files = cur.fetchall()
    result = []
    for f in files:
        d = dict(f)
        if d.get("uploaded_at"):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return jsonify(result)
