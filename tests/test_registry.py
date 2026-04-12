# tests/test_registry.py
from __future__ import annotations

from tools.registry import tool, get_tool_definitions, execute, _registry


def setup_function():
    """Clear registry before each test."""
    _registry.clear()


def test_tool_decorator_registers():
    @tool(
        name="test_tool",
        description="A test tool",
        agent="ops",
        schema={"properties": {"x": {"type": "integer"}}, "required": ["x"]},
    )
    def test_tool(x: int) -> dict:
        return {"result": x * 2}

    assert "test_tool" in _registry
    assert _registry["test_tool"]["agent"] == "ops"
    assert _registry["test_tool"]["handler"] is test_tool


def test_get_tools_returns_all():
    @tool(name="tool_a", description="A", schema={})
    def tool_a() -> dict:
        return {}

    @tool(name="tool_b", description="B", agent="ops", schema={})
    def tool_b() -> dict:
        return {}

    defs = get_tool_definitions()
    names = {d["name"] for d in defs}
    assert names == {"tool_a", "tool_b"}


def test_get_tools_scoped_by_agent():
    @tool(name="tool_a", description="A", agent="ops", schema={})
    def tool_a() -> dict:
        return {}

    @tool(name="tool_b", description="B", agent="wakil", schema={})
    def tool_b() -> dict:
        return {}

    @tool(name="tool_c", description="C", schema={})
    def tool_c() -> dict:
        return {}

    ops_defs = get_tool_definitions(agent="ops")
    ops_names = {d["name"] for d in ops_defs}
    assert ops_names == {"tool_a", "tool_c"}


def test_execute_dispatches():
    @tool(name="multiply", description="Multiply", schema={"properties": {"x": {"type": "integer"}}})
    def multiply(x: int) -> dict:
        return {"result": x * 3}

    result = execute("multiply", {"x": 5})
    assert result == {"result": 15}


def test_execute_unknown_tool():
    result = execute("nonexistent", {})
    assert "error" in result
