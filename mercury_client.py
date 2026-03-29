"""Multi-account Mercury Banking API client for Shams.

Accounts:
- Clifton (QCC Clifton café)
- Plainfield (QCC Plainfield café + production/roastery)
- Personal (Maher's personal banking)
"""

from __future__ import annotations

import logging
import requests
from datetime import date, timedelta
from config import (
    MERCURY_API_KEY_CLIFTON, MERCURY_API_KEY_PLAINFIELD,
    MERCURY_API_KEY_PERSONAL, MERCURY_API_KEY_COINBITS,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercury.com/api/v1"

# Registry of all Mercury accounts
ACCOUNTS = {}
if MERCURY_API_KEY_CLIFTON:
    ACCOUNTS["clifton"] = {"key": MERCURY_API_KEY_CLIFTON, "label": "QCC Clifton"}
if MERCURY_API_KEY_PLAINFIELD:
    ACCOUNTS["plainfield"] = {"key": MERCURY_API_KEY_PLAINFIELD, "label": "QCC Plainfield & Production"}
if MERCURY_API_KEY_PERSONAL:
    ACCOUNTS["personal"] = {"key": MERCURY_API_KEY_PERSONAL, "label": "Personal"}
if MERCURY_API_KEY_COINBITS:
    ACCOUNTS["coinbits"] = {"key": MERCURY_API_KEY_COINBITS, "label": "Coinbits"}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _get(api_key: str, path: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=_headers(api_key), params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Mercury API error {path}: {e}")
        return None


def _get_all_accounts_for_key(api_key: str) -> list[dict]:
    """Get all sub-accounts (checking, credit card, savings) for one API key."""
    data = _get(api_key, "/accounts")
    if not data:
        return []
    return data.get("accounts", [])


def _get_checking_id(api_key: str) -> str | None:
    for acct in _get_all_accounts_for_key(api_key):
        if acct.get("kind") == "checking":
            return acct["id"]
    accounts = _get_all_accounts_for_key(api_key)
    return accounts[0]["id"] if accounts else None


# ── Public API ───────────────────────────────────────────────────────────────

def get_balances(account_name: str | None = None) -> dict:
    """Get balances for one or all Mercury accounts.

    Args:
        account_name: 'clifton', 'plainfield', 'personal', or None for all.
    """
    targets = ACCOUNTS
    if account_name and account_name in ACCOUNTS:
        targets = {account_name: ACCOUNTS[account_name]}

    result = {"accounts": [], "total_checking": 0.0, "total_credit_card": 0.0, "grand_total": 0.0}

    for name, info in targets.items():
        sub_accounts = _get_all_accounts_for_key(info["key"])
        for acct in sub_accounts:
            bal = float(acct.get("currentBalance") or acct.get("availableBalance") or 0)
            kind = acct.get("kind", "unknown")
            acct_name = acct.get("name", kind)

            result["accounts"].append({
                "entity": info["label"],
                "account_name": acct_name,
                "kind": kind,
                "balance": bal,
            })

            if kind == "checking":
                result["total_checking"] += bal
            elif kind in ("creditCard", "credit"):
                result["total_credit_card"] += bal

    result["grand_total"] = result["total_checking"] + result["total_credit_card"]
    return result


def get_recent_transactions(account_name: str | None = None, days: int = 7) -> list[dict]:
    """Get recent transactions for one or all accounts."""
    targets = ACCOUNTS
    if account_name and account_name in ACCOUNTS:
        targets = {account_name: ACCOUNTS[account_name]}

    end = date.today()
    start = end - timedelta(days=days)
    all_txns = []

    for name, info in targets.items():
        acct_id = _get_checking_id(info["key"])
        if not acct_id:
            continue

        data = _get(info["key"], f"/account/{acct_id}/transactions", {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 100,
            "status": "sent",
        })
        if not data:
            continue

        for t in data.get("transactions", []):
            all_txns.append({
                "entity": info["label"],
                "date": t.get("postedAt", t.get("createdAt", ""))[:10],
                "amount": float(t.get("amount", 0)),
                "counterparty": t.get("counterpartyName", "Unknown"),
                "description": t.get("bankDescription", ""),
            })

    all_txns.sort(key=lambda t: t["date"], reverse=True)
    return all_txns


def get_cash_summary() -> str:
    """Formatted cash summary across all accounts for briefings."""
    if not ACCOUNTS:
        return "Mercury: not configured"

    balances = get_balances()
    lines = ["**Mercury Cash Position (All Accounts)**"]

    for acct in balances["accounts"]:
        lines.append(f"- {acct['entity']} / {acct['account_name']}: ${acct['balance']:,.2f}")

    lines.append(f"\n**Total Checking: ${balances['total_checking']:,.2f}**")
    if balances["total_credit_card"] != 0:
        lines.append(f"**Credit Cards: ${balances['total_credit_card']:,.2f}**")
    lines.append(f"**Grand Total: ${balances['grand_total']:,.2f}**")

    txns = get_recent_transactions(days=3)
    if txns:
        lines.append(f"\n**Last 3 days ({len(txns)} transactions across all accounts):**")
        for t in txns[:15]:
            sign = "+" if t["amount"] > 0 else ""
            lines.append(f"- {t['date']} [{t['entity']}] {t['counterparty']}: {sign}${t['amount']:,.2f}")

    return "\n".join(lines)
