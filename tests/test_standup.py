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


def test_triage_tier_parsing():
    """Test that we correctly parse the new Reply/Read/Archive tier format."""
    result_text = (
        "MESSAGE_ID: abc123\n"
        "TIER: reply\n"
        "SUMMARY: Ahmed asking about Q2 pricing\n"
        "ACTION: Draft reply confirming interest\n"
        "DRAFT: Thanks Ahmed, we're interested in the Q2 pricing.\n"
        "---\n"
        "MESSAGE_ID: def456\n"
        "TIER: read\n"
        "SUMMARY: Mercury deposit notification\n"
        "ACTION: No action needed\n"
        "DRAFT: NONE\n"
        "---\n"
        "MESSAGE_ID: ghi789\n"
        "TIER: archive\n"
        "SUMMARY: Shopify order notification\n"
        "ACTION: Auto-archive\n"
        "DRAFT: NONE\n"
    )
    results = []
    for block in result_text.split("---"):
        block = block.strip()
        if not block:
            continue
        fields = {}
        for line in block.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip().upper()] = v.strip()
        tier = fields.get("TIER", "archive")
        assert tier in ("reply", "read", "archive"), f"Bad tier: {tier}"
        results.append({"message_id": fields.get("MESSAGE_ID"), "tier": tier})

    assert len(results) == 3
    assert results[0]["tier"] == "reply"
    assert results[1]["tier"] == "read"
    assert results[2]["tier"] == "archive"


from unittest.mock import patch, MagicMock


def test_overnight_loop_structure():
    """Test that run_overnight_loop returns structured results."""
    import standup

    # Mock all external dependencies
    with patch("standup.google_client") as mock_google, \
         patch("standup.mercury_client") as mock_mercury, \
         patch("standup.rumi_client") as mock_rumi, \
         patch("standup.memory") as mock_memory, \
         patch("standup.anthropic") as mock_anthropic:

        # Setup mocks
        mock_google.get_unread_emails_for_account.return_value = []
        mock_google.get_todays_events.return_value = []
        mock_mercury.get_balances.return_value = {"entities": [], "grand_total": 0}
        mock_rumi.get_daily_pl.return_value = None
        mock_rumi.get_action_items.return_value = {"items": []}
        mock_memory.create_overnight_run.return_value = 1
        mock_memory.get_missions.return_value = []
        mock_memory.get_open_loops.return_value = []
        mock_memory.get_actions.return_value = []

        # Mock the Claude API for archive summary
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Nothing to summarize.")]
        mock_client.messages.create.return_value = mock_response

        results = standup.run_overnight_loop()

        assert "email" in results
        assert "mercury" in results
        assert "rumi" in results
        assert "calendar" in results
        assert "reminders" in results
        mock_memory.create_overnight_run.assert_called_once()
        mock_memory.update_overnight_run.assert_called_once()
