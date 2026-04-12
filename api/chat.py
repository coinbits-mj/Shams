"""Chat — direct chat + group chat (now routed through Shams)."""
from __future__ import annotations

import json
import logging
from flask import Blueprint, request, jsonify

import memory
import claude_client
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("chat", __name__, url_prefix="/api")


def _process_uploaded_files(req) -> tuple:
    """Extract message and file data from a multipart or JSON request.
    Returns (message, images_list, doc_text).
    """
    import base64

    images = []
    doc_text = ""

    # Multipart form
    if req.content_type and "multipart" in req.content_type:
        message = req.form.get("message", "").strip()
        files = req.files.getlist("files")
        for f in files:
            file_bytes = f.read()
            mime = f.content_type or ""
            fname = f.filename or "upload"

            if mime.startswith("image/"):
                img_b64 = base64.b64encode(file_bytes).decode("utf-8")
                images.append({"data": img_b64, "media_type": mime})
                # Save to files table
                memory.save_file(fname, "photo", mime, len(file_bytes),
                                 summary=f"Uploaded via dashboard: {fname}")
            elif mime == "application/pdf":
                from telegram import extract_document_text
                text = extract_document_text(file_bytes, fname)
                doc_text += f"\n\n[Document: {fname}]\n{text}"
                memory.save_file(fname, "pdf", mime, len(file_bytes),
                                 transcript=text[:2000],
                                 summary=f"Uploaded via dashboard: {fname}")
            else:
                # Try text extraction for other docs
                from telegram import extract_document_text
                text = extract_document_text(file_bytes, fname)
                doc_text += f"\n\n[Document: {fname}]\n{text}"
                memory.save_file(fname, "document", mime, len(file_bytes),
                                 transcript=text[:2000],
                                 summary=f"Uploaded via dashboard: {fname}")
    else:
        data = req.get_json(silent=True) or {}
        message = data.get("message", "").strip()

    return message, images, doc_text


@bp.route("/chat", methods=["POST"])
@require_auth
def chat():
    message, images, doc_text = _process_uploaded_files(request)

    if doc_text:
        message = (message + doc_text) if message else doc_text.strip()
    if not message and not images:
        return jsonify({"error": "message or file required"}), 400

    reply = claude_client.chat(message or "What's in this file?", images=images if images else None)
    return jsonify({"reply": reply})


@bp.route("/group-chat", methods=["POST"])
@require_auth
def group_chat_send():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not message:
        return jsonify({"error": "message required"}), 400

    reply = claude_client.chat(message)
    memory.save_group_message("shams", reply)
    return jsonify({"responses": [{"agent": "shams", "content": reply}]})


@bp.route("/group-chat/history", methods=["GET"])
@require_auth
def group_chat_history():
    limit = request.args.get("limit", 50, type=int)
    messages = memory.get_group_messages(limit)
    result = []
    for m in messages:
        d = dict(m)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)


@bp.route("/conversations", methods=["GET"])
@require_auth
def conversations():
    limit = request.args.get("limit", 100, type=int)
    messages = memory.get_recent_messages(limit)
    result = []
    for m in messages:
        d = dict(m)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return jsonify(result)
