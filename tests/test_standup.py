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


def test_build_overview_message():
    """Test that overview message formats correctly."""
    import standup

    results = {
        "email": {
            "reply": [{"subject": "Test"}] * 3,
            "read": [{"subject": "FYI"}] * 5,
            "archived": [{"subject": "Spam"}] * 23,
            "archive_summary": "Mostly Shopify notifications and newsletters",
        },
        "mercury": {
            "balances": {"clifton": 14230, "plainfield": 8102, "personal": 52400, "coinbits": 3200},
            "grand_total": 77932,
            "alerts": [{"type": "low_balance", "account": "coinbits", "balance": 3200}],
        },
        "rumi": {"revenue": 1847, "cogs": 923, "margin": 0.50, "orders": 12, "wholesale_orders": 3},
        "calendar": {
            "events": [{"summary": "Supplier call", "start": "10:00 AM"}, {"summary": "Roasting", "start": "2:00 PM"}],
            "prep_briefs": [{"event": "Supplier call", "brief": "Push for volume pricing"}],
        },
        "reminders": [
            {"title": "Wholesale deploy", "type": "stale_mission"},
            {"title": "Red House LOI", "type": "deadline"},
            {"title": "Recharge migration", "type": "orphaned_loop"},
        ],
    }

    msg = standup._build_overview_message(results)
    assert "3 replies drafted" in msg
    assert "5 to read" in msg
    assert "23 archived" in msg
    assert "$77,932" in msg
    assert "Coinbits" in msg or "coinbits" in msg
    assert "$1,847" in msg
    assert "3 things" in msg or "3 item" in msg


def test_standup_callback_routing():
    """Test that standup callback data is parsed correctly."""
    test_cases = [
        ("su_send:0", "su_send", 0),
        ("su_edit:2", "su_edit", 2),
        ("su_skip:1", "su_skip", 1),
        ("su_ok:3", "su_ok", 3),
        ("su_snooze:0", "su_snooze", 0),
        ("su_mission:1", "su_mission", 1),
    ]
    for cb_data, expected_action, expected_idx in test_cases:
        parts = cb_data.split(":")
        assert len(parts) == 2
        action_type = parts[0]
        idx = int(parts[1])
        assert action_type == expected_action
        assert idx == expected_idx


def test_scout_agent_registered():
    """Test that Scout is registered as an agent."""
    from agents.registry import AGENTS, build_agent_system_prompt
    assert "scout" in AGENTS
    assert AGENTS["scout"]["role"] == "Market Intelligence & Research Agent"
    prompt = build_agent_system_prompt("scout")
    assert "Scout" in prompt


def test_list_deals_tool_exists():
    """Test that list_deals tool is registered."""
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    all_tools = get_tool_definitions()
    tool_names = [t["name"] for t in all_tools]
    assert "list_deals" in tool_names


def test_deal_tools_available_to_scout():
    """Test that deal tools are available to scout agent."""
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    scout_tools = get_tool_definitions(agent="scout")
    tool_names = [t["name"] for t in scout_tools]
    assert "create_deal" in tool_names
    assert "update_deal" in tool_names
    assert "list_deals" in tool_names
    assert "web_search" in tool_names
    assert "fetch_url" in tool_names


def test_scout_sweep_structure():
    """Test that _step_scout_sweep returns structured results."""
    from unittest.mock import patch, MagicMock
    import standup

    with patch("standup.memory") as mock_memory, \
         patch("standup._call_scout") as mock_call:

        mock_memory.get_deals.return_value = []
        mock_call.return_value = {
            "findings": [],
            "searches_run": 5,
            "new_deals": 0,
            "updated_deals": 0,
        }

        result = standup._step_scout_sweep()

        assert "findings" in result
        assert "searches_run" in result
        assert "new_deals" in result
        assert "updated_deals" in result
        mock_call.assert_called_once()
