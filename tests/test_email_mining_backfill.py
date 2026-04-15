"""Integration test: dry-run backfill against real Gmail + real Postgres.

Skipped unless GOOGLE_CLIENT_ID + DATABASE_URL are set.
Always runs in dry-run — never mutates Gmail.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


REQUIRED_ENV = ["DATABASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ANTHROPIC_API_KEY"]


@pytest.mark.skipif(
    any(not os.environ.get(k) for k in REQUIRED_ENV),
    reason="integration env missing",
)
@pytest.mark.usefixtures("setup_db")
def test_dry_run_backfill_processes_emails_without_mutating_gmail():
    env = {**os.environ, "EMAIL_MINING_DRY_RUN": "true"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backfill_email_mining",
         "--account", "qcc", "--limit", "100"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "processed=" in result.stdout or "processed=" in result.stderr

    import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # At least 50 rows inserted (classifier may error on some).
            cur.execute("SELECT COUNT(*) FROM shams_email_archive WHERE account='qcc'")
            assert cur.fetchone()[0] >= 50
            # No rows marked gmail_archived under dry-run.
            cur.execute("SELECT COUNT(*) FROM shams_email_archive WHERE account='qcc' AND gmail_archived = TRUE")
            assert cur.fetchone()[0] == 0
            # Category distribution is non-trivial (not all one category).
            cur.execute("SELECT COUNT(DISTINCT category) FROM shams_email_archive WHERE account='qcc'")
            assert cur.fetchone()[0] >= 3
