# tools/registry.py
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Callable

log = logging.getLogger(__name__)

_registry: dict[str, dict[str, Any]] = {}


def tool(
    name: str,
    description: str,
    schema: dict,
    agent: str | None = None,
) -> Callable:
    """Decorator to register a tool handler."""
    def decorator(fn: Callable) -> Callable:
        _registry[name] = {
            "name": name,
            "description": description,
            "agent": agent,
            "schema": schema,
            "handler": fn,
        }
        return fn
    return decorator


def get_tool_definitions(agent: str | None = None) -> list[dict]:
    """Return Claude-API-compatible tool definitions, optionally scoped by agent.

    If agent is None, returns ALL tools (for Shams).
    If agent is specified, returns tools tagged for that agent + unscoped tools.
    """
    defs = []
    for entry in _registry.values():
        if agent is None or entry["agent"] is None or entry["agent"] == agent:
            defs.append({
                "name": entry["name"],
                "description": entry["description"],
                "input_schema": {
                    "type": "object",
                    **entry["schema"],
                },
            })
    return defs


def execute(name: str, params: dict) -> Any:
    """Dispatch a tool call by name."""
    entry = _registry.get(name)
    if entry is None:
        log.warning("Unknown tool: %s", name)
        return {"error": f"Unknown tool: {name}"}
    try:
        return entry["handler"](**params)
    except Exception as e:
        log.exception("Tool %s failed", name)
        return {"error": f"Tool {name} failed: {e}"}


def discover_tools() -> None:
    """Import all tools/*.py modules to trigger @tool decorations."""
    import tools as tools_pkg
    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname == "registry":
            continue
        importlib.import_module(f"tools.{modname}")
    log.info("Discovered %d tools from tools/ package", len(_registry))


def get_tools() -> dict[str, dict]:
    """Return the raw registry (for introspection/testing)."""
    return _registry
