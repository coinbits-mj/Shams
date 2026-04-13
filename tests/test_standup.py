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
        mock_memory.get_latest_overnight_run.return_value = None  # No previous run — lock check passes
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


def test_overview_message_includes_scout():
    """Test that overview message includes Scout findings."""
    import standup

    results = {
        "email": {"reply": [], "read": [], "archived": [], "archive_summary": ""},
        "mercury": {"balances": {}, "grand_total": 0, "alerts": []},
        "rumi": {},
        "calendar": {"events": [], "prep_briefs": []},
        "reminders": [],
        "scout": {
            "findings": [
                {"title": "Test Lead", "score": 8, "type": "acquisition"},
                {"title": "Updated Deal", "score": 6, "type": "real_estate"},
            ],
            "searches_run": 5,
            "new_deals": 2,
            "updated_deals": 1,
        },
    }

    msg = standup._build_overview_message(results)
    assert "2 new leads" in msg or "2 leads" in msg
    assert "1 deal updated" in msg or "1 updated" in msg


def test_trust_tier_config():
    """Test that TRUST_TIERS config exists and has expected structure."""
    from standup import TRUST_TIERS
    assert "email_draft" in TRUST_TIERS
    assert "scout_outreach" in TRUST_TIERS
    assert TRUST_TIERS["email_draft"]["threshold"] == 15
    assert TRUST_TIERS["scout_outreach"]["threshold"] == 30
    assert TRUST_TIERS["email_archive"]["threshold"] == 5


def test_should_auto_approve_action_default_false():
    """Test that unknown action types are not auto-approved."""
    import memory
    result = memory.should_auto_approve_action("nonexistent_action_type_xyz")
    assert result is False


def test_auto_approved_items_filtered_from_drip_feed():
    """Test that auto-approved items don't appear in the drip-feed."""
    from unittest.mock import patch
    import standup

    results = {
        "email": {
            "reply": [
                {"from": "ahmed@test.com", "subject": "Pricing", "draft": "Thanks", "triage_id": 1, "account": "qcc", "message_id": "abc"},
            ],
            "read": [], "archived": [], "archive_summary": "",
        },
        "mercury": {"balances": {}, "grand_total": 0, "alerts": []},
        "rumi": {},
        "calendar": {"events": [], "prep_briefs": []},
        "reminders": [{"title": "Test reminder", "why": "testing", "suggestion": "", "draft": "", "mission_id": None, "loop_id": None, "action_id": None}],
        "scout": {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0},
    }

    # With no trust, both items should appear
    with patch("standup.memory") as mock_mem:
        mock_mem.should_auto_approve_action.return_value = False
        items, auto = standup._build_action_items_with_trust(results)
        assert len(items) == 2  # reply + reminder
        assert len(auto) == 0

    # With email_draft auto-approved, only reminder should appear
    with patch("standup.memory") as mock_mem:
        def side_effect(action_type):
            return action_type == "email_draft"
        mock_mem.should_auto_approve_action.side_effect = side_effect
        items, auto = standup._build_action_items_with_trust(results)
        assert len(items) == 1  # only reminder
        assert items[0]["type"] == "reminder"
        assert len(auto) == 1
        assert auto[0]["type"] == "reply"


def test_standup_trust_map_covers_all_item_types():
    """Test that STANDUP_TRUST_MAP covers all standup item types."""
    from standup import STANDUP_TRUST_MAP
    expected_types = ["reply", "prep", "reminder", "scout_outreach", "scout_info"]
    for t in expected_types:
        assert t in STANDUP_TRUST_MAP, f"Missing trust mapping for standup type: {t}"


def test_pl_config_exists():
    """Test that PL_CONFIG exists with expected structure."""
    from standup import PL_CONFIG
    assert PL_CONFIG["hourly_rate"] == 250
    assert "email_triage" in PL_CONFIG["time_values"]
    assert "input_per_million" in PL_CONFIG["token_pricing"]
    assert PL_CONFIG["token_pricing"]["input_per_million"] == 3.00


def test_pl_revenue_calculation():
    """Test revenue calculation from time values."""
    from standup import PL_CONFIG
    hourly = PL_CONFIG["hourly_rate"]
    draft_value = (5 / 60) * hourly
    assert round(draft_value, 2) == 20.83
    triage_value = (0.5 / 60) * hourly
    assert round(triage_value, 2) == 2.08


def test_pl_cost_calculation():
    """Test cost calculation from token counts."""
    from standup import PL_CONFIG
    pricing = PL_CONFIG["token_pricing"]
    cost = (100_000 / 1_000_000 * pricing["input_per_million"]) + \
           (20_000 / 1_000_000 * pricing["output_per_million"])
    assert round(cost, 4) == 0.6


def test_pl_revenue_amount_for_emails():
    """Test revenue calculation for email triage."""
    from standup import PL_CONFIG
    hourly = PL_CONFIG["hourly_rate"]
    count = 10
    minutes = count * PL_CONFIG["time_values"]["email_triage"]
    amount = round((minutes / 60) * hourly, 4)
    assert amount == 20.8333


def test_warmth_score_calculation():
    """Test warmth score decay and boost logic."""
    from standup import _calculate_warmth
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    # Fresh contact — should be ~100
    score = _calculate_warmth(
        last_inbound=now - timedelta(hours=1),
        last_outbound=now - timedelta(hours=2),
        last_meeting=None,
        touchpoint_count=5,
        channels=["email"],
        has_active_deal=False,
    )
    assert score >= 95

    # 20 days silent — should be cooling
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=20),
        last_outbound=now - timedelta(days=22),
        last_meeting=None,
        touchpoint_count=5,
        channels=["email"],
        has_active_deal=False,
    )
    assert 25 <= score <= 50

    # 40 days silent — should be cold
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=40),
        last_outbound=None,
        last_meeting=None,
        touchpoint_count=3,
        channels=["email"],
        has_active_deal=False,
    )
    assert score < 25

    # Active deal — warmth floor of 20
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=60),
        last_outbound=None,
        last_meeting=None,
        touchpoint_count=2,
        channels=["email"],
        has_active_deal=True,
    )
    assert score >= 20


def test_contact_noise_filtering():
    """Test that noise contacts are filtered out."""
    from standup import _is_noise_contact
    assert _is_noise_contact("noreply@shopify.com") is True
    assert _is_noise_contact("notifications@github.com") is True
    assert _is_noise_contact("support@squareup.com") is True
    assert _is_noise_contact("ahmed@cafeimports.com") is False
    assert _is_noise_contact("maher@qcitycoffee.com") is False


def test_relationship_scan_structure():
    """Test that _step_relationship_scan returns structured results."""
    from unittest.mock import patch, MagicMock
    import standup

    with patch("standup.memory") as mock_memory, \
         patch("standup.google_client") as mock_google, \
         patch("standup.anthropic") as mock_anthropic:

        mock_memory.get_cooling_contacts.return_value = []
        mock_memory.get_contact_count.return_value = 0
        mock_memory.get_triaged_emails.return_value = []
        mock_google.get_todays_events.return_value = []

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        result = standup._step_relationship_scan()

        assert "contacts_updated" in result
        assert "new_contacts" in result
        assert "cooling" in result
        assert "cold" in result
        mock_memory.update_all_warmth_scores.assert_called_once()
