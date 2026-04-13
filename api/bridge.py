"""Bridge API — receives touchpoints from local macOS bridge, serves command queue."""
from __future__ import annotations

import logging
import os
from flask import Blueprint, request, jsonify

import memory
from standup import _is_noise_contact

logger = logging.getLogger(__name__)

bp = Blueprint("bridge", __name__, url_prefix="/api")

BRIDGE_TOKEN = os.environ.get("BRIDGE_API_TOKEN", "")


def _check_bridge_auth():
    """Verify bridge API token."""
    if not BRIDGE_TOKEN:
        return False
    token = request.headers.get("X-Bridge-Token", "")
    return token == BRIDGE_TOKEN


@bp.route("/touchpoints", methods=["POST"])
def receive_touchpoints():
    """Receive touchpoint batch from local bridge."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data or "touchpoints" not in data:
        return jsonify({"error": "Missing touchpoints"}), 400

    processed = 0
    for tp in data["touchpoints"]:
        handle = tp.get("contact_handle", "")
        name = tp.get("contact_name", "") or handle
        source = tp.get("source", "unknown")
        direction = tp.get("direction", "inbound")
        phone = tp.get("contact_phone")

        # Determine email vs phone
        email = handle if "@" in handle and not handle.endswith("@s.whatsapp.net") else None
        if not email and not phone:
            phone = handle  # Assume phone number for iMessage handles

        if email and _is_noise_contact(email):
            continue

        try:
            memory.upsert_contact(
                name=name, email=email, phone=phone,
                source=source, channel=source, direction=direction,
            )
            processed += 1
        except Exception as e:
            logger.error(f"Touchpoint processing failed: {e}")

    memory.log_activity("shams", "touchpoints", f"Bridge: {processed} touchpoints processed")
    return jsonify({"processed": processed})


@bp.route("/bridge/pending", methods=["GET"])
def get_pending_commands():
    """Return pending bridge commands for the local bridge to execute."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    commands = memory.get_pending_bridge_commands()
    return jsonify({"commands": commands})


@bp.route("/bridge/ack", methods=["POST"])
def ack_command():
    """Acknowledge command execution from bridge."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    command_id = data.get("id")
    status = data.get("status", "sent")
    if command_id:
        memory.ack_bridge_command(command_id, status)
    return jsonify({"ok": True})
