# scripts/backfill_email_mining.py
"""One-time historical backfill of the Shams email archive.

Processes ~57K emails across personal/coinbits/qcc accounts in chunks of 500.
Resumable via per-account cursor stored in shams_memory.

Usage:
    # Dry-run (no Gmail mutations)
    EMAIL_MINING_DRY_RUN=true python -m scripts.backfill_email_mining [--account qcc] [--limit 1000]

    # Live
    python -m scripts.backfill_email_mining
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import requests

# Ensure Shams project root is on path when running as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")

CHUNK_SIZE = 500


def list_message_ids(account_key: str, page_token: str | None) -> tuple[list[str], str | None]:
    """List message IDs in bulk. No query → lists all mail (not just inbox)."""
    import google_client
    token = google_client._get_access_token(account_key)
    if not token:
        return [], None
    params = {"maxResults": CHUNK_SIZE, "includeSpamTrash": "false"}
    if page_token:
        params["pageToken"] = page_token
    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers={"Authorization": f"Bearer {token}"},
        params=params, timeout=30,
    )
    if not r.ok:
        logger.error(f"list error for {account_key}: {r.status_code} {r.text[:200]}")
        return [], None
    data = r.json()
    ids = [m["id"] for m in data.get("messages", [])]
    return ids, data.get("nextPageToken")


def process_chunk(account_key: str, message_ids: list[str]) -> dict:
    import email_mining
    import google_client
    import memory

    processed = 0
    errors = 0
    category_counts: dict[str, int] = {}

    for mid in message_ids:
        # Skip if already processed (idempotency).
        # (A more elaborate check would query shams_email_archive; the UNIQUE
        # constraint in insert_email_archive also protects us.)
        try:
            full = google_client.fetch_full_message(account_key, mid)
            if not full:
                errors += 1
                continue
            result = email_mining.process_email(full)
            processed += 1
            category_counts[result["category"]] = category_counts.get(result["category"], 0) + 1
        except Exception as e:
            logger.error(f"process error {account_key}:{mid}: {e}")
            errors += 1

    return {"processed": processed, "errors": errors, "categories": category_counts}


def backfill_account(account_key: str, limit: int | None) -> None:
    import memory

    total = 0
    while True:
        cursor = memory.get_backfill_cursor(account_key)
        ids, next_token = list_message_ids(account_key, cursor)
        if not ids:
            logger.info(f"{account_key}: no more messages (cursor exhausted)")
            break

        stats = process_chunk(account_key, ids)
        total += stats["processed"]
        logger.info(
            f"{account_key}: processed={stats['processed']} errors={stats['errors']} "
            f"total={total} categories={stats['categories']}"
        )

        if next_token is None:
            logger.info(f"{account_key}: reached end of mailbox")
            memory.set_backfill_cursor(account_key, "")  # sentinel for "done"
            break

        memory.set_backfill_cursor(account_key, next_token)

        if limit and total >= limit:
            logger.info(f"{account_key}: hit --limit {limit}, stopping")
            break

        time.sleep(1)  # polite pacing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", choices=["personal", "coinbits", "qcc"], default=None,
                        help="If set, only backfill this account. Otherwise all three.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max emails to process per account this run.")
    args = parser.parse_args()

    # Load .env if present.
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

    accounts = [args.account] if args.account else ["qcc", "coinbits", "personal"]

    dry = os.environ.get("EMAIL_MINING_DRY_RUN", "").lower() in ("1", "true", "yes")
    logger.info(f"Backfill start. DRY_RUN={dry} accounts={accounts} limit={args.limit}")

    for acct in accounts:
        logger.info(f"=== {acct} ===")
        backfill_account(acct, args.limit)


if __name__ == "__main__":
    main()
