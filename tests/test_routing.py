# tests/test_routing.py
"""Tests for the 4-agent routing system."""
from __future__ import annotations

import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.registry import AGENTS, build_agent_system_prompt, list_agents
from tools.registry import get_tool_definitions, discover_tools, _registry


def setup_module():
    """Discover all tools once before tests run."""
    if not _registry:
        discover_tools()


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------


def test_five_agents_defined():
    assert set(AGENTS.keys()) == {"shams", "ops", "wakil", "leo", "scout"}


def test_each_agent_has_required_fields():
    for name, agent in AGENTS.items():
        assert "role" in agent, f"{name} missing role"
        assert "persona_file" in agent, f"{name} missing persona_file"
        assert "knowledge_files" in agent, f"{name} missing knowledge_files"
        assert "color" in agent, f"{name} missing color"


# ---------------------------------------------------------------------------
# Tool scoping
# ---------------------------------------------------------------------------


def test_shams_gets_all_tools():
    """Shams (agent=None) gets every registered tool."""
    all_tools = get_tool_definitions(agent=None)
    all_names = {t["name"] for t in all_tools}
    # Should include tools from every agent scope
    assert len(all_tools) == len(_registry)
    for entry in _registry.values():
        assert entry["name"] in all_names


def test_ops_gets_scoped_tools():
    """Ops gets ops-tagged tools + unscoped tools, not wakil/leo-only."""
    ops_tools = get_tool_definitions(agent="ops")
    ops_names = {t["name"] for t in ops_tools}

    # Should include all ops-tagged and unscoped tools
    for entry in _registry.values():
        if entry["agent"] == "ops" or entry["agent"] is None:
            assert entry["name"] in ops_names, f"ops missing {entry['name']}"

    # Should NOT include wakil-only or leo-only tools
    for entry in _registry.values():
        if entry["agent"] == "wakil":
            assert entry["name"] not in ops_names, f"ops has wakil tool {entry['name']}"
        if entry["agent"] == "leo":
            assert entry["name"] not in ops_names, f"ops has leo tool {entry['name']}"


def test_wakil_gets_scoped_tools():
    """Wakil gets wakil-tagged tools + unscoped, not ops/leo-only."""
    wakil_tools = get_tool_definitions(agent="wakil")
    wakil_names = {t["name"] for t in wakil_tools}

    for entry in _registry.values():
        if entry["agent"] == "wakil" or entry["agent"] is None:
            assert entry["name"] in wakil_names, f"wakil missing {entry['name']}"

    for entry in _registry.values():
        if entry["agent"] == "ops":
            assert entry["name"] not in wakil_names, f"wakil has ops tool {entry['name']}"


def test_leo_gets_scoped_tools():
    """Leo gets leo-tagged tools + unscoped, not ops/wakil-only."""
    leo_tools = get_tool_definitions(agent="leo")
    leo_names = {t["name"] for t in leo_tools}

    for entry in _registry.values():
        if entry["agent"] == "leo" or entry["agent"] is None:
            assert entry["name"] in leo_names, f"leo missing {entry['name']}"

    for entry in _registry.values():
        if entry["agent"] == "ops":
            assert entry["name"] not in leo_names, f"leo has ops tool {entry['name']}"
        if entry["agent"] == "wakil":
            assert entry["name"] not in leo_names, f"leo has wakil tool {entry['name']}"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def test_build_agent_system_prompt_loads_persona():
    prompt = build_agent_system_prompt("ops")
    assert "Operations" in prompt or "Ops" in prompt


def test_build_agent_system_prompt_with_extra_context():
    extra = "Today's revenue: $4,200"
    prompt = build_agent_system_prompt("ops", extra_context=extra)
    assert extra in prompt


def test_build_agent_system_prompt_unknown_agent():
    prompt = build_agent_system_prompt("nonexistent")
    assert "nonexistent" in prompt


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


def test_list_agents_returns_five():
    agents = list_agents()
    assert len(agents) == 5
    names = {a["name"] for a in agents}
    assert names == {"shams", "ops", "wakil", "leo", "scout"}
    for a in agents:
        assert "role" in a
        assert "color" in a
