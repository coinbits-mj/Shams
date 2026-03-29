"""Direct Mercury Banking API client for Shams — account balances, transactions, cash flow."""

from __future__ import annotations

import logging
import requests
from datetime import date, timedelta
from config import MERCURY_API_KEY, MERCURY_ACCOUNT_ID

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercury.com/api/v1"
_headers = {"Authorization": f"Bearer {MERCURY_API_KEY}", "Content-Type": "application/json"} if MERCURY_API_KEY else {}


def _get(path: str, params: dict | None = None) -> dict | None:
    if not MERCURY_API_KEY:
        return None
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=_headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Mercury API error {path}: {e}")
        return None


def get_account_id() -> str | None:
    if MERCURY_ACCOUNT_ID:
        return MERCURY_ACCOUNT_ID
    data = _get("/accounts")
    if not data:
        return None
    for acct in data.get("accounts", []):
        if acct.get("kind") == "checking":
            return acct["id"]
    accounts = data.get("accounts", [])
    return accounts[0]["id"] if accounts else None


def get_balances() -> dict | None:
    """Get current balances across all Mercury accounts."""
    data = _get("/accounts")
    if not data:
        return None
    result = {"checking": 0.0, "credit_card": 0.0, "total": 0.0, "accounts": []}
    for acct in data.get("accounts", []):
        bal = float(acct.get("currentBalance") or acct.get("availableBalance") or 0)
        kind = acct.get("kind", "unknown")
        result["accounts"].append({
            "name": acct.get("name", kind),
            "kind": kind,
            "balance": bal,
        })
        if kind == "checking":
            result["checking"] += bal
        elif kind in ("creditCard", "credit"):
            result["credit_card"] += bal
    result["total"] = result["checking"] + result["credit_card"]
    return result


def get_recent_transactions(days: int = 7) -> list[dict] | None:
    """Get transactions from the last N days."""
    acct_id = get_account_id()
    if not acct_id:
        return None
    end = date.today()
    start = end - timedelta(days=days)
    data = _get(f"/account/{acct_id}/transactions", {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 100,
        "status": "sent",
    })
    if not data:
        return None

    txns = []
    for t in data.get("transactions", []):
        txns.append({
            "date": t.get("postedAt", t.get("createdAt", ""))[:10],
            "amount": float(t.get("amount", 0)),
            "counterparty": t.get("counterpartyName", "Unknown"),
            "description": t.get("bankDescription", ""),
            "status": t.get("status", ""),
        })
    return txns


def get_cash_summary() -> str:
    """Get a formatted cash summary for Shams briefings."""
    balances = get_balances()
    if not balances:
        return "Mercury: unavailable"

    lines = [f"**Mercury Cash Position**"]
    for acct in balances["accounts"]:
        lines.append(f"- {acct['name']}: ${acct['balance']:,.2f}")
    lines.append(f"- **Net: ${balances['total']:,.2f}**")

    txns = get_recent_transactions(3)
    if txns:
        lines.append(f"\n**Last 3 days ({len(txns)} transactions):**")
        for t in txns[:10]:
            sign = "+" if t["amount"] > 0 else ""
            lines.append(f"- {t['date']} {t['counterparty']}: {sign}${t['amount']:,.2f}")

    return "\n".join(lines)
