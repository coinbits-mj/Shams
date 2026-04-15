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
    """List message IDs in bulk. Defaults to inbox-only via EMAIL_MINING_QUERY env var
    (default 'in:inbox'). Set EMAIL_MINING_QUERY='' to iterate all mail."""
    import google_client
    token = google_client._get_access_token(account_key)
    if not token:
        return [], None
    params = {"maxResults": CHUNK_SIZE, "includeSpamTrash": "false"}
    query = os.environ.get("EMAIL_MINING_QUERY", "in:inbox")
    if query:
        params["q"] = query
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


def _already_processed_ids(account_key: str, message_ids: list[str]) -> dict:
    """Return {message_id: (category, priority)} for message_ids already in shams_email_archive.
    Used to skip Anthropic re-classification when re-processing the same emails."""
    import db
    if not message_ids:
        return {}
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gmail_message_id, category, priority FROM shams_email_archive "
                "WHERE account = %s AND gmail_message_id = ANY(%s)",
                (account_key, message_ids),
            )
            return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def process_chunk(account_key: str, message_ids: list[str]) -> dict:
    import email_mining
    import google_client
    import db

    processed = 0
    skipped = 0
    archived_only = 0
    errors = 0
    category_counts: dict[str, int] = {}

    # Bulk look up which IDs are already classified — skip the classifier for those,
    # just retroactively archive in Gmail (cheap, no Anthropic spend).
    cached = _already_processed_ids(account_key, message_ids)

    for mid in message_ids:
        try:
            if mid in cached:
                cat, prio = cached[mid]
                # Already classified — just retry the Gmail archive (no-op if already archived).
                ok = email_mining.archive_in_gmail(account_key, mid, cat, priority=prio)
                if ok:
                    with db.get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE shams_email_archive SET gmail_archived = TRUE "
                                "WHERE account = %s AND gmail_message_id = %s",
                                (account_key, mid),
                            )
                    archived_only += 1
                skipped += 1
                continue

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

    return {
        "processed": processed,
        "skipped_cached": skipped,
        "archived_only": archived_only,
        "errors": errors,
        "categories": category_counts,
    }


def _with_retry(fn, *args, attempts: int = 6, base_delay: float = 2.0, **kwargs):
    """Retry a callable with exponential backoff on transient errors (DNS, connection, etc)."""
    import time
    last_exc = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            delay = base_delay * (2 ** i)
            logger.warning(f"transient error (attempt {i+1}/{attempts}): {type(e).__name__}: {e}. sleeping {delay}s")
            time.sleep(delay)
    raise last_exc


def backfill_account(account_key: str, limit: int | None) -> None:
    import memory
    import time as _time

    total = 0
    while True:
        try:
            cursor = _with_retry(memory.get_backfill_cursor, account_key)
            ids, next_token = _with_retry(list_message_ids, account_key, cursor)
        except Exception as e:
            logger.error(f"{account_key}: persistent error getting cursor/ids after retries: {e}")
            logger.error(f"{account_key}: sleeping 60s then trying again")
            _time.sleep(60)
            continue

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
            try:
                _with_retry(memory.set_backfill_cursor, account_key, "")
            except Exception:
                pass
            break

        try:
            _with_retry(memory.set_backfill_cursor, account_key, next_token)
        except Exception as e:
            logger.error(f"{account_key}: failed to persist cursor after retries: {e}. continuing anyway")

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
