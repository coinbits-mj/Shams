"""Mercury — bank balances and transactions."""
from __future__ import annotations

from flask import Blueprint, request, jsonify

import mercury_client
from api.auth import require_auth

bp = Blueprint("mercury", __name__, url_prefix="/api")


@bp.route("/mercury/balances", methods=["GET"])
@require_auth
def mercury_balances():
    account = request.args.get("account")
    result = mercury_client.get_balances(account)
    return jsonify(result)


@bp.route("/mercury/transactions", methods=["GET"])
@require_auth
def mercury_transactions():
    account = request.args.get("account")
    days = request.args.get("days", 7, type=int)
    result = mercury_client.get_recent_transactions(account, days)
    return jsonify(result or [])
