# tests/test_db.py
from __future__ import annotations

import pytest
import db

pytestmark = pytest.mark.usefixtures("setup_db")

def test_get_conn_returns_connection():
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1

def test_get_conn_commits_on_success():
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO shams_memory (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("_test_pool_commit", "yes"),
        )
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM shams_memory WHERE key = %s", ("_test_pool_commit",))
        assert cur.fetchone()[0] == "yes"
        cur.execute("DELETE FROM shams_memory WHERE key = %s", ("_test_pool_commit",))

def test_get_conn_rollback_on_error():
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO shams_memory (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                ("_test_pool_rollback", "should_not_persist"),
            )
            raise ValueError("Simulated error")
    except ValueError:
        pass
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM shams_memory WHERE key = %s", ("_test_pool_rollback",))
        assert cur.fetchone() is None
