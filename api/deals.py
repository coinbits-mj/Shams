"""Deals — CRUD for deal pipeline."""
from __future__ import annotations

from flask import Blueprint, request, jsonify

import memory
from api.auth import require_auth

bp = Blueprint("deals", __name__, url_prefix="/api")


@bp.route("/deals", methods=["GET"])
@require_auth
def get_deals():
    stage = request.args.get("stage")
    deals = memory.get_deals(stage)
    result = []
    for d in deals:
        dd = dict(d)
        for k in ("created_at", "updated_at", "deadline"):
            if dd.get(k):
                dd[k] = dd[k].isoformat() if hasattr(dd[k], 'isoformat') else str(dd[k])
        if dd.get("value"):
            dd["value"] = float(dd["value"])
        result.append(dd)
    return jsonify(result)


@bp.route("/deals", methods=["POST"])
@require_auth
def create_deal():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    deal_id = memory.create_deal(title=title, **{k: v for k, v in data.items() if k != "title"})
    memory.log_activity("shams", "deal_created", f"Deal #{deal_id}: {title}")
    return jsonify({"id": deal_id})


@bp.route("/deals/<int:deal_id>", methods=["PATCH"])
@require_auth
def update_deal(deal_id):
    data = request.get_json(silent=True) or {}
    memory.update_deal(deal_id, **data)
    if data.get("stage"):
        memory.log_activity("shams", "deal_updated", f"Deal #{deal_id} → {data['stage']}")
    return jsonify({"ok": True})
