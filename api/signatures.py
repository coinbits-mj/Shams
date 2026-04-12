"""Signatures — DocuSeal template + signing endpoints."""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("signatures", __name__, url_prefix="/api")


@bp.route("/signatures/templates", methods=["GET"])
@require_auth
def get_signature_templates():
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify({"error": "DocuSeal not configured"}), 400
    return jsonify(docuseal_client.list_templates())


@bp.route("/signatures/templates", methods=["POST"])
@require_auth
def upload_signature_template():
    """Upload a PDF to create a signing template."""
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify({"error": "DocuSeal not configured"}), 400

    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400

    f = request.files["file"]
    name = request.form.get("name", f.filename or "Document")
    pdf_bytes = f.read()

    result = docuseal_client.create_template_from_pdf(name, pdf_bytes)
    if result:
        memory.log_activity("shams", "template_created", f"Signing template created: {name}")
        return jsonify(result)
    return jsonify({"error": "Failed to create template"}), 500


@bp.route("/signatures/send", methods=["POST"])
@require_auth
def send_signature():
    """Send a template for signing."""
    import docuseal_client
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    signers = data.get("signers", [])
    message = data.get("message", "")

    if not template_id or not signers:
        return jsonify({"error": "template_id and signers required"}), 400

    submitters = [{"email": s["email"], "name": s.get("name", ""), "role": "First Party"} for s in signers]
    result = docuseal_client.send_for_signature(template_id, submitters, send_email=True, message=message)
    if result:
        memory.log_activity("shams", "signature_sent",
            f"Sent template #{template_id} to {', '.join(s['email'] for s in signers)}")
        return jsonify(result)
    return jsonify({"error": "Failed to send"}), 500


@bp.route("/signatures/submissions", methods=["GET"])
@require_auth
def get_submissions():
    import docuseal_client
    if not docuseal_client.is_configured():
        return jsonify([])
    return jsonify(docuseal_client.list_submissions(limit=20))


@bp.route("/signatures/status", methods=["GET"])
@require_auth
def signatures_status():
    import docuseal_client
    return jsonify({"configured": docuseal_client.is_configured()})
