# tests/test_context.py
from __future__ import annotations

import os
import sys
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# We need to mock heavy dependencies before importing claude_client
# so it doesn't blow up without a DB or API key.

_mock_memory = MagicMock()
_mock_memory.recall_all.return_value = {"name": "Maher"}
_mock_memory.get_open_loops.return_value = [{"id": 1, "title": "Test loop", "context": "ctx"}]
_mock_memory.get_recent_decisions.return_value = [{"summary": "Decided X"}]
_mock_memory.get_actions.return_value = []
_mock_memory.get_missions.return_value = []
_mock_memory.get_activity_feed.return_value = []
_mock_memory.recall.return_value = None


@patch.dict(os.environ, {
    "DATABASE_URL": "postgresql://fake:fake@localhost/fake",
    "ANTHROPIC_API_KEY": "sk-test-fake",
})
@patch.dict(sys.modules, {"memory": _mock_memory, "anthropic": MagicMock()})
def _import_client():
    """Import claude_client with mocked dependencies."""
    # Clear if previously imported so we get fresh import
    sys.modules.pop("claude_client", None)
    sys.modules.pop("config", None)
    import claude_client
    return claude_client


_client = _import_client()


def test_build_core_prompt_is_short():
    prompt = _client._build_core_prompt()
    assert len(prompt) > 0
    assert "shams" in prompt.lower()


def test_build_hot_context_morning():
    with patch.object(_client, "_now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 11, 0, 0, tzinfo=timezone.utc)  # 7am ET
        ctx = _client._build_hot_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0


def test_build_hot_context_overnight():
    with patch.object(_client, "_now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 7, 0, 0, tzinfo=timezone.utc)  # 3am ET
        ctx = _client._build_hot_context()
        assert isinstance(ctx, str)


def test_build_hot_context_evening():
    with patch.object(_client, "_now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 23, 0, 0, tzinfo=timezone.utc)  # 7pm ET
        ctx = _client._build_hot_context()
        assert isinstance(ctx, str)


def test_build_system_combines_core_and_hot():
    system = _client._build_system()
    assert isinstance(system, str)
    assert len(system) > 0
    # Should contain the proactive memory block
    assert "Proactive Memory" in system


def test_hot_context_includes_open_loops():
    with patch.object(_client, "_now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)
        ctx = _client._build_hot_context()
        assert "Open Loops" in ctx
        assert "Test loop" in ctx


def test_hot_context_includes_memories():
    with patch.object(_client, "_now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)
        ctx = _client._build_hot_context()
        assert "Key Memories" in ctx
