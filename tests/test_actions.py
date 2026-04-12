# tests/test_actions.py
from __future__ import annotations
import pytest
import memory

pytestmark = pytest.mark.usefixtures("setup_db")

def test_create_action():
    action_id = memory.create_action(
        agent_name="shams",
        action_type="test",
        title="_test_action",
        description="Test action",
        payload={"key": "val"},
    )
    assert action_id is not None
    action = memory.get_action(action_id)
    assert action["title"] == "_test_action"
    assert action["status"] == "pending"

def test_approve_action():
    action_id = memory.create_action("shams", "test", "_test_approve", "", {})
    memory.update_action_status(action_id, "approved")
    action = memory.get_action(action_id)
    assert action["status"] == "approved"

def test_reject_action():
    action_id = memory.create_action("shams", "test", "_test_reject", "", {})
    memory.update_action_status(action_id, "rejected")
    action = memory.get_action(action_id)
    assert action["status"] == "rejected"

def test_get_pending_actions():
    action_id = memory.create_action("shams", "test", "_test_pending", "", {})
    actions = memory.get_actions(status="pending")
    ids = [a["id"] for a in actions]
    assert action_id in ids

def test_trust_score_lifecycle():
    memory.increment_trust("_test_agent", "total_proposed")
    memory.increment_trust("_test_agent", "total_approved")
    score = memory.get_trust_score("_test_agent")
    assert score is not None
    assert score["total_proposed"] >= 1
    assert score["total_approved"] >= 1

def test_auto_approve_toggle():
    memory.set_auto_approve("_test_agent_aa", False)
    assert not memory.should_auto_approve("_test_agent_aa")
    memory.set_auto_approve("_test_agent_aa", True)
    assert memory.should_auto_approve("_test_agent_aa")
    memory.set_auto_approve("_test_agent_aa", False)
