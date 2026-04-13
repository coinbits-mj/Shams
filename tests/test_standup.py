"""Tests for overnight ops + morning standup."""
from __future__ import annotations


def test_config_has_overnight_and_standup_hours():
    import config
    assert hasattr(config, "OVERNIGHT_HOUR_UTC")
    assert hasattr(config, "STANDUP_HOUR_UTC")
    assert isinstance(config.OVERNIGHT_HOUR_UTC, int)
    assert isinstance(config.STANDUP_HOUR_UTC, int)


import json
import pytest


@pytest.fixture
def db_conn():
    """Get a test database connection. Skip if no DATABASE_URL."""
    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set — skipping DB tests")
    import psycopg2
    conn = psycopg2.connect(db_url)
    yield conn
    conn.rollback()
    conn.close()


def test_create_overnight_run(db_conn):
    import memory
    run_id = memory.create_overnight_run()
    assert isinstance(run_id, int)
    assert run_id > 0


def test_update_overnight_run(db_conn):
    import memory
    run_id = memory.create_overnight_run()
    results = {"email": {"archived": 5}, "mercury": {"balances": {}}}
    memory.update_overnight_run(run_id, status="completed", results=results, summary="Test run")
    run = memory.get_latest_overnight_run()
    assert run is not None
    assert run["id"] == run_id
    assert run["status"] == "completed"
    assert run["results"]["email"]["archived"] == 5
    assert run["summary"] == "Test run"


def test_standup_state(db_conn):
    import memory
    # Initially no state
    state = memory.get_standup_state()
    # Set state
    memory.set_standup_state({
        "phase": "dripping",
        "current_index": 2,
        "run_id": 42,
    })
    state = memory.get_standup_state()
    assert state["phase"] == "dripping"
    assert state["current_index"] == 2
    assert state["run_id"] == 42
    # Clear state
    memory.clear_standup_state()
    state = memory.get_standup_state()
    assert state is None
