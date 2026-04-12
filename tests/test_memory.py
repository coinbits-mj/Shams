from __future__ import annotations

import pytest
import memory

pytestmark = pytest.mark.usefixtures("setup_db")


def test_save_and_recall():
    memory.remember("_test_key", "test_value")
    result = memory.recall("_test_key")
    assert result == "test_value"
    memory.remember("_test_key", "")


def test_recall_all():
    memory.remember("_test_all_1", "val1")
    memory.remember("_test_all_2", "val2")
    all_mem = memory.recall_all()
    assert "_test_all_1" in all_mem
    assert all_mem["_test_all_1"] == "val1"
    memory.remember("_test_all_1", "")
    memory.remember("_test_all_2", "")


def test_save_and_get_message():
    memory.save_message("user", "_test_message_content")
    recent = memory.get_recent_messages(limit=1)
    assert len(recent) >= 1
    assert recent[-1]["content"] == "_test_message_content"


def test_open_loop_lifecycle():
    loop_id = memory.add_open_loop("_test_loop", "test context")
    assert loop_id is not None
    loops = memory.get_open_loops()
    titles = [l["title"] for l in loops]
    assert "_test_loop" in titles
    memory.close_loop(loop_id, "done")
    loops = memory.get_open_loops()
    titles = [l["title"] for l in loops]
    assert "_test_loop" not in titles


def test_decision_lifecycle():
    memory.log_decision("_test_decision", "because test", "should pass")
    decisions = memory.get_recent_decisions(limit=1)
    assert len(decisions) >= 1


def test_activity_feed():
    memory.log_activity("shams", "test_event", "_test_activity", {"key": "val"})
    feed = memory.get_activity_feed(limit=1)
    assert len(feed) >= 1
