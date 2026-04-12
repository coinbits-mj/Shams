# Shams v2 — Sub-project A: Codebase Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Shams monolithic codebase into focused modules — tool registry with decorator-based dispatch, 4-agent system (down from 6), slimmed system prompt with hot context, connection pooling, split API/Telegram/scheduler, and a test harness covering core paths.

**Architecture:** Split three monoliths (`claude_client.py` 1,217 / `dashboard_api.py` 2,053 / `app.py` 914) into ~30 focused files. Replace the 41-tool if/elif dispatch with a decorator registry. Collapse 6 agents to 4 (Shams, Ops, Wakil, Leo) with Shams as the only user-facing agent that routes to specialists internally. Add `psycopg2.pool.ThreadedConnectionPool`. Delete `group_chat.py` entirely.

**Tech Stack:** Python 3.9+ (Railway uses 3.11) / Flask 3.0 / psycopg2 / APScheduler / Anthropic SDK / pytest

**Spec reference:** `docs/superpowers/specs/2026-04-12-shams-v2-codebase-overhaul-design.md`

**Repo:** `/Users/mj/code/Shams`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `db.py` | ThreadedConnectionPool, `get_conn()` context manager |
| `tools/__init__.py` | Package init |
| `tools/registry.py` | `@tool` decorator, auto-discovery, `get_tools()`, `execute()` |
| `tools/web.py` | `web_search`, `fetch_url` |
| `tools/mercury.py` | 5 Mercury banking tools |
| `tools/rumi.py` | 7 Rumi/QCC ops tools |
| `tools/leo.py` | 2 Leo health tools |
| `tools/google.py` | `triage_inbox`, `search_email`, `read_email` |
| `tools/github.py` | 4 codebase tools + `propose_code_change` |
| `tools/docuseal.py` | `send_for_signature`, `check_signatures` |
| `tools/media.py` | `add_media` |
| `tools/memory_tools.py` | `remember`, `add_open_loop`, `close_open_loop`, `log_decision` |
| `tools/missions.py` | `create_mission`, `update_mission`, `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`, `create_workflow` |
| `tools/actions.py` | `propose_action`, `route_to_specialist` (renamed from `route_to_agent`) |
| `tools/deals.py` | `create_deal`, `update_deal` |
| `tools/legal.py` | `draft_legal_document`, `assign_research` |
| `telegram.py` | Message handling, callbacks, voice/photo/doc processing |
| `scheduler.py` | APScheduler setup, job registration, dynamic task loading |
| `api/__init__.py` | Blueprint registration helper |
| `api/auth.py` | Login, magic link, sessions, `require_auth` decorator |
| `api/chat.py` | Chat, conversations |
| `api/projects.py` | Projects, missions, kanban, timeline, gantt |
| `api/agents.py` | Agent status, activity feed |
| `api/mercury.py` | Mercury banking endpoints |
| `api/integrations.py` | Google OAuth, connected accounts |
| `api/actions.py` | Actions approve/reject/execute, trust scores |
| `api/inbox.py` | Email scan, archive, star, draft, batch |
| `api/files.py` | Folders, files, search |
| `api/briefings.py` | Briefings, loops, decisions, memory |
| `api/settings.py` | Alert rules, scheduled tasks, workflows, notifications, delegations |
| `api/deals.py` | Deal CRUD endpoints |
| `api/signatures.py` | DocuSeal endpoints |
| `api/money.py` | Rumi + today/money dashboard aggregates |
| `context/ops.md` | Ops agent persona (consolidates Rumi + Scout + Builder) |
| `tests/conftest.py` | pytest fixtures — test DB, mock Claude |
| `tests/test_registry.py` | Tool registry tests |
| `tests/test_routing.py` | Agent routing tests |
| `tests/test_context.py` | Hot context assembly tests |
| `tests/test_actions.py` | Action lifecycle tests |
| `tests/test_memory.py` | Memory CRUD tests |
| `tests/test_db.py` | Connection pool tests |

### Modified files

| File | Changes |
|------|---------|
| `claude_client.py` | Gutted from 1,217 → ~200 lines. Chat loop + prompt assembly only. Tools moved out. |
| `app.py` | Gutted from 914 → ~150 lines. Flask init + startup only. Telegram/scheduler moved out. |
| `memory.py` | Reduced from 859 → ~300 lines. Uses `db.get_conn()` instead of `_conn()`. |
| `agents/registry.py` | Rewritten. 4 agents, on-demand persona loading, `route_to_specialist()`. |
| `config.py` | No changes needed. |
| `schema.sql` | No changes needed. |

### Deleted files

| File | Reason |
|------|--------|
| `group_chat.py` | War Room removed. Shams routes internally. |
| `agents/codebase.py` | Folded into `tools/github.py`. |

---

## Task 1: Database connection pool (`db.py`)

**Files:**
- Create: `db.py`
- Create: `tests/test_db.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

Everything else depends on this module. Build it first, test it, then migrate `memory.py` to use it.

- [ ] **Step 1: Write test for connection pool**

Create `tests/__init__.py` (empty) and `tests/conftest.py`:

```python
# tests/conftest.py
from __future__ import annotations

import os
import pytest

# Use test database if available, otherwise use main DB
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", os.environ.get("DATABASE_URL", ""))


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Ensure tables exist before running tests."""
    if not TEST_DATABASE_URL:
        pytest.skip("No DATABASE_URL set")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import db
    db.init_pool()
    import memory
    memory.ensure_tables()
    yield
    db.close_pool()
```

Create `tests/test_db.py`:

```python
# tests/test_db.py
from __future__ import annotations

import db


def test_get_conn_returns_connection():
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_get_conn_commits_on_success():
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO shams_memory (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("_test_pool_commit", "yes"),
        )
    # Read back in a new connection to verify commit
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM shams_memory WHERE key = %s", ("_test_pool_commit",))
        assert cur.fetchone()[0] == "yes"
        cur.execute("DELETE FROM shams_memory WHERE key = %s", ("_test_pool_commit",))


def test_get_conn_rollback_on_error():
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO shams_memory (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                ("_test_pool_rollback", "should_not_persist"),
            )
            raise ValueError("Simulated error")
    except ValueError:
        pass
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM shams_memory WHERE key = %s", ("_test_pool_rollback",))
        assert cur.fetchone() is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_db.py -v
```

Expected: ModuleNotFoundError for `db`

- [ ] **Step 3: Implement `db.py`**

```python
# db.py
from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from config import DATABASE_URL

log = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def init_pool(minconn: int = 2, maxconn: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(minconn=minconn, maxconn=maxconn, dsn=DATABASE_URL)
    log.info("Connection pool initialized (min=%d, max=%d)", minconn, maxconn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn():
    """Acquire a connection from the pool, commit on success, rollback on error."""
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_db.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add db.py tests/__init__.py tests/conftest.py tests/test_db.py
git commit -m "feat: add db.py connection pool with ThreadedConnectionPool"
```

---

## Task 2: Tool registry with decorator-based dispatch

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write tests for tool registry**

```python
# tests/test_registry.py
from __future__ import annotations

from tools.registry import tool, get_tools, get_tool_definitions, execute, _registry


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
    # ops gets its own tools + unscoped tools
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_registry.py -v
```

Expected: ModuleNotFoundError for `tools.registry`

- [ ] **Step 3: Implement tool registry**

Create `tools/__init__.py` (empty file).

Create `tools/registry.py`:

```python
# tools/registry.py
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Callable

log = logging.getLogger(__name__)

# {tool_name: {"name", "description", "agent", "schema", "handler"}}
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
    """Import all tools/*.py modules to trigger @tool decorrations."""
    import tools as tools_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname == "registry":
            continue
        importlib.import_module(f"tools.{modname}")
    log.info("Discovered %d tools from %d modules", len(_registry), len(list(pkgutil.iter_modules(tools_pkg.__path__))) - 1)


def get_tools() -> dict[str, dict]:
    """Return the raw registry (for introspection/testing)."""
    return _registry
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_registry.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/registry.py tests/test_registry.py
git commit -m "feat: add decorator-based tool registry with auto-discovery"
```

---

## Task 3: Migrate all 41 tools into domain files

**Files:**
- Create: `tools/web.py`, `tools/mercury.py`, `tools/rumi.py`, `tools/leo.py`, `tools/google.py`, `tools/github.py`, `tools/docuseal.py`, `tools/media.py`, `tools/memory_tools.py`, `tools/missions.py`, `tools/actions.py`, `tools/deals.py`, `tools/legal.py`

This is the largest task — move every tool from `claude_client.py` into its domain file using the `@tool` decorator. Each tool's definition comes from the TOOLS list (lines 42-555 of `claude_client.py`) and its handler from `_execute_tool()` (lines 560-1036).

**IMPORTANT:** Read `claude_client.py` lines 42-555 for each tool's name, description, and input_schema. Read lines 560-1036 for each tool's handler logic. Preserve the exact behavior — this is a mechanical move, not a rewrite.

- [ ] **Step 1: Create `tools/web.py`**

Move tools: `web_search`, `fetch_url` (definitions at lines 43-64, handlers at lines 562-589).

```python
# tools/web.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="web_search",
    description="Search the web using Tavily. Returns relevant results with snippets.",
    schema={
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> dict:
    from web_search import search
    return search(query)


@tool(
    name="fetch_url",
    description="Fetch and extract readable content from a URL.",
    schema={
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    },
)
def fetch_url(url: str) -> dict:
    from web_search import fetch
    return fetch(url)
```

- [ ] **Step 2: Create `tools/mercury.py`**

Move tools: `get_mercury_balances`, `get_mercury_transactions`, `get_mercury_cash_summary` (definitions at lines 65-93, handlers at lines 591-618).

```python
# tools/mercury.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_mercury_balances",
    description="Get current balances for Mercury bank accounts.",
    agent="ops",
    schema={
        "properties": {
            "accounts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Account names to check. Options: clifton, plainfield, personal, coinbits. Omit for all.",
            },
        },
    },
)
def get_mercury_balances(accounts: list[str] | None = None) -> dict:
    from mercury_client import get_balances
    return get_balances(accounts)


@tool(
    name="get_mercury_transactions",
    description="Get recent transactions from a Mercury account.",
    agent="ops",
    schema={
        "properties": {
            "account": {"type": "string", "description": "Account name: clifton, plainfield, personal, or coinbits"},
            "limit": {"type": "integer", "description": "Number of transactions (default 10)"},
        },
        "required": ["account"],
    },
)
def get_mercury_transactions(account: str, limit: int = 10) -> dict:
    from mercury_client import get_transactions
    return get_transactions(account, limit)


@tool(
    name="get_mercury_cash_summary",
    description="Get a summary of cash across all Mercury accounts with totals.",
    agent="ops",
    schema={"properties": {}},
)
def get_mercury_cash_summary() -> dict:
    from mercury_client import get_cash_summary
    return get_cash_summary()
```

- [ ] **Step 3: Create `tools/rumi.py`**

Move tools: `get_rumi_daily_pl`, `get_rumi_monthly_pl`, `get_rumi_scorecard`, `get_rumi_action_items`, `get_rumi_cashflow_forecast`, `get_rumi_labor`, `get_rumi_inventory_alerts` (definitions at lines 94-151, handlers at lines 620-655).

```python
# tools/rumi.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_rumi_daily_pl",
    description="Get today's P&L from QCC operations via Rumi.",
    agent="ops",
    schema={
        "properties": {
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format. Defaults to today."},
        },
    },
)
def get_rumi_daily_pl(date: str | None = None) -> dict:
    from rumi_client import call_rumi
    params = {"date": date} if date else {}
    return call_rumi("/api/wholesale/daily-pl", params)


@tool(
    name="get_rumi_monthly_pl",
    description="Get monthly P&L summary from QCC.",
    agent="ops",
    schema={
        "properties": {
            "month": {"type": "string", "description": "Month in YYYY-MM format. Defaults to current month."},
        },
    },
)
def get_rumi_monthly_pl(month: str | None = None) -> dict:
    from rumi_client import call_rumi
    params = {"month": month} if month else {}
    return call_rumi("/api/wholesale/monthly-pl", params)


@tool(
    name="get_rumi_scorecard",
    description="Get QCC operational scorecard — key metrics at a glance.",
    agent="ops",
    schema={"properties": {}},
)
def get_rumi_scorecard() -> dict:
    from rumi_client import call_rumi
    return call_rumi("/api/wholesale/scorecard")


@tool(
    name="get_rumi_action_items",
    description="Get current QCC action items and tasks from Rumi.",
    agent="ops",
    schema={"properties": {}},
)
def get_rumi_action_items() -> dict:
    from rumi_client import call_rumi
    return call_rumi("/api/wholesale/action-items")


@tool(
    name="get_rumi_cashflow_forecast",
    description="Get QCC cashflow forecast from Rumi.",
    agent="ops",
    schema={"properties": {}},
)
def get_rumi_cashflow_forecast() -> dict:
    from rumi_client import call_rumi
    return call_rumi("/api/wholesale/cashflow-forecast")


@tool(
    name="get_rumi_labor",
    description="Get QCC labor report — hours, costs, efficiency.",
    agent="ops",
    schema={"properties": {}},
)
def get_rumi_labor() -> dict:
    from rumi_client import call_rumi
    return call_rumi("/api/wholesale/labor")


@tool(
    name="get_rumi_inventory_alerts",
    description="Get QCC inventory alerts — low stock, expiring items.",
    agent="ops",
    schema={"properties": {}},
)
def get_rumi_inventory_alerts() -> dict:
    from rumi_client import call_rumi
    return call_rumi("/api/wholesale/inventory-alerts")
```

- [ ] **Step 4: Create `tools/leo.py`**

Move tools: `get_leo_health_summary`, `get_leo_trends` (definitions at lines 152-167, handlers at lines 657-668).

```python
# tools/leo.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="get_leo_health_summary",
    description="Get MJ's health summary from Leo — recent logs, streaks, recommendations.",
    agent="leo",
    schema={"properties": {}},
)
def get_leo_health_summary() -> dict:
    from leo_client import get_health_summary
    return get_health_summary()


@tool(
    name="get_leo_trends",
    description="Get MJ's health trends from Leo — weight, sleep, activity over time.",
    agent="leo",
    schema={
        "properties": {
            "days": {"type": "integer", "description": "Number of days to look back (default 30)"},
        },
    },
)
def get_leo_trends(days: int = 30) -> dict:
    from leo_client import get_trends
    return get_trends(days)
```

- [ ] **Step 5: Create `tools/google.py`**

Move tools: `triage_inbox`, `search_email`, `read_email` (definitions at lines 168-201, handlers at lines 670-720).

**IMPORTANT:** The `triage_inbox` handler (line 621 in the original) spawns a nested Claude API call with `inbox_persona.md`. Preserve this behavior exactly.

```python
# tools/google.py
from __future__ import annotations

import json
import logging

from tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="triage_inbox",
    description="Triage unread emails across Gmail accounts. Categorizes by priority (P1-P4), suggests actions, drafts replies for urgent items.",
    schema={
        "properties": {
            "account": {
                "type": "string",
                "description": "Gmail account to triage: personal, coinbits, or qcc. Omit for all accounts.",
            },
            "max_emails": {"type": "integer", "description": "Max emails to triage per account (default 10)"},
        },
    },
)
def triage_inbox(account: str | None = None, max_emails: int = 10) -> dict:
    from google_client import get_unread_emails, get_google_accounts
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from pathlib import Path

    accounts = [account] if account else list(get_google_accounts().keys())
    results = []
    inbox_prompt = Path(__file__).parent.parent / "context" / "inbox_persona.md"
    system = inbox_prompt.read_text() if inbox_prompt.exists() else "You are an email triage assistant."

    for acct in accounts:
        emails = get_unread_emails(acct, max_emails)
        if not emails:
            continue
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Triage these emails from {acct}:\n\n{json.dumps(emails, indent=2)}",
            }],
        )
        results.append({"account": acct, "triage": msg.content[0].text, "count": len(emails)})

    return {"results": results} if results else {"message": "No unread emails found"}


@tool(
    name="search_email",
    description="Search emails across Gmail accounts.",
    schema={
        "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "account": {"type": "string", "description": "Account: personal, coinbits, or qcc. Omit for all."},
            "max_results": {"type": "integer", "description": "Max results (default 10)"},
        },
        "required": ["query"],
    },
)
def search_email(query: str, account: str | None = None, max_results: int = 10) -> dict:
    from google_client import search_emails
    return search_emails(query, account, max_results)


@tool(
    name="read_email",
    description="Read the full content of a specific email by ID.",
    schema={
        "properties": {
            "account": {"type": "string", "description": "Account the email belongs to"},
            "message_id": {"type": "string", "description": "Gmail message ID"},
        },
        "required": ["account", "message_id"],
    },
)
def read_email(account: str, message_id: str) -> dict:
    from google_client import get_email_content
    return get_email_content(account, message_id)
```

- [ ] **Step 6: Create `tools/github.py`**

Move tools: `read_codebase`, `search_codebase`, `list_codebase_files`, `get_repo_structure`, `propose_code_change` (definitions at lines 202-354, handlers at lines 722-770 and 955-983).

```python
# tools/github.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="read_codebase",
    description="Read a file from a GitHub repo.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Repo name: shams, rumi, or leo"},
            "path": {"type": "string", "description": "File path within the repo"},
        },
        "required": ["repo", "path"],
    },
)
def read_codebase(repo: str, path: str) -> dict:
    from agents.codebase import read_file
    return read_file(repo, path)


@tool(
    name="search_codebase",
    description="Search for text across files in a GitHub repo.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Repo name: shams, rumi, or leo"},
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["repo", "query"],
    },
)
def search_codebase(repo: str, query: str) -> dict:
    from agents.codebase import search_code
    return search_code(repo, query)


@tool(
    name="list_codebase_files",
    description="List files in a directory of a GitHub repo.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Repo name: shams, rumi, or leo"},
            "path": {"type": "string", "description": "Directory path (default: root)"},
        },
        "required": ["repo"],
    },
)
def list_codebase_files(repo: str, path: str = "") -> dict:
    from agents.codebase import list_files
    return list_files(repo, path)


@tool(
    name="get_repo_structure",
    description="Get the full directory tree of a GitHub repo.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Repo name: shams, rumi, or leo"},
        },
        "required": ["repo"],
    },
)
def get_repo_structure(repo: str) -> dict:
    from agents.codebase import get_tree
    return get_tree(repo)


@tool(
    name="propose_code_change",
    description="Propose a code change to a repo. Creates a GitHub PR for Maher to review.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "enum": ["shams", "rumi", "leo"]},
            "description": {"type": "string", "description": "What this change does and why"},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["repo", "description", "files"],
    },
)
def propose_code_change(repo: str, description: str, files: list[dict]) -> dict:
    from github_client import create_pr
    return create_pr(repo, description, files)
```

- [ ] **Step 7: Create `tools/docuseal.py`**

Move tools: `send_for_signature`, `check_signatures` (definitions at lines 390-424, handlers at lines 880-920).

```python
# tools/docuseal.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="send_for_signature",
    description="Send a document for e-signature via DocuSeal.",
    agent="wakil",
    schema={
        "properties": {
            "template_id": {"type": "integer", "description": "DocuSeal template ID"},
            "signer_email": {"type": "string", "description": "Email of the signer"},
            "signer_name": {"type": "string", "description": "Name of the signer"},
            "prefill_fields": {
                "type": "object",
                "description": "Fields to prefill in the document",
            },
        },
        "required": ["template_id", "signer_email", "signer_name"],
    },
)
def send_for_signature(
    template_id: int, signer_email: str, signer_name: str, prefill_fields: dict | None = None
) -> dict:
    from docuseal_client import send_for_signing
    return send_for_signing(template_id, signer_email, signer_name, prefill_fields or {})


@tool(
    name="check_signatures",
    description="Check status of signature requests.",
    agent="wakil",
    schema={
        "properties": {
            "submission_id": {"type": "integer", "description": "Specific submission ID to check. Omit for recent."},
        },
    },
)
def check_signatures(submission_id: int | None = None) -> dict:
    from docuseal_client import check_status
    return check_status(submission_id)
```

- [ ] **Step 8: Create `tools/media.py`**

Move tool: `add_media` (definition at lines 540-555, handler at lines 1020-1030).

```python
# tools/media.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="add_media",
    description="Request a movie or TV show to be downloaded via the media bridge (Radarr/Sonarr).",
    schema={
        "properties": {
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "Type of media"},
            "title": {"type": "string", "description": "Title of the movie or TV show"},
            "quality": {"type": "string", "description": "Quality profile (e.g., 1080p, 4k). Default: 1080p"},
        },
        "required": ["media_type", "title"],
    },
)
def add_media(media_type: str, title: str, quality: str = "1080p") -> dict:
    from media_client import add_movie, add_tv
    if media_type == "movie":
        return add_movie(title, quality)
    else:
        return add_tv(title, quality)
```

- [ ] **Step 9: Create `tools/memory_tools.py`**

Move tools: `remember`, `add_open_loop`, `close_open_loop`, `log_decision` (definitions at lines 491-539, handlers at lines 1000-1018).

```python
# tools/memory_tools.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="remember",
    description="Save an important fact or piece of information to long-term memory.",
    schema={
        "properties": {
            "key": {"type": "string", "description": "Short descriptive key (e.g., 'mj_coffee_preference')"},
            "value": {"type": "string", "description": "The information to remember"},
        },
        "required": ["key", "value"],
    },
)
def remember(key: str, value: str) -> dict:
    import memory
    memory.remember(key, value)
    return {"status": "saved", "key": key}


@tool(
    name="add_open_loop",
    description="Track something that needs follow-up — a pending task, waiting-for, or unresolved item.",
    schema={
        "properties": {
            "title": {"type": "string", "description": "What needs follow-up"},
            "context": {"type": "string", "description": "Additional context or details"},
        },
        "required": ["title"],
    },
)
def add_open_loop(title: str, context: str = "") -> dict:
    import memory
    loop_id = memory.add_open_loop(title, context)
    return {"status": "created", "id": loop_id}


@tool(
    name="close_open_loop",
    description="Close a resolved open loop.",
    schema={
        "properties": {
            "loop_id": {"type": "integer", "description": "ID of the loop to close"},
            "status": {"type": "string", "enum": ["done", "dropped"], "description": "How it was resolved"},
        },
        "required": ["loop_id", "status"],
    },
)
def close_open_loop(loop_id: int, status: str = "done") -> dict:
    import memory
    memory.close_loop(loop_id, status)
    return {"status": "closed", "id": loop_id}


@tool(
    name="log_decision",
    description="Record a decision made by Maher — what was decided, the reasoning, and expected outcome.",
    schema={
        "properties": {
            "summary": {"type": "string", "description": "What was decided"},
            "reasoning": {"type": "string", "description": "Why this decision was made"},
            "outcome": {"type": "string", "description": "Expected outcome or next steps"},
        },
        "required": ["summary"],
    },
)
def log_decision(summary: str, reasoning: str = "", outcome: str = "") -> dict:
    import memory
    dec_id = memory.log_decision(summary, reasoning, outcome)
    return {"status": "logged", "id": dec_id}
```

- [ ] **Step 10: Create `tools/missions.py`**

Move tools: `create_mission`, `update_mission`, `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`, `create_workflow` (definitions at lines 249-477, handlers at lines 772-824 and 922-965).

```python
# tools/missions.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="create_mission",
    description="Create a new mission (task) and optionally assign to an agent.",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Mission title"},
            "description": {"type": "string", "description": "What needs to be done"},
            "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"], "description": "Priority level"},
            "assigned_agent": {"type": "string", "description": "Agent to assign: shams, ops, wakil, leo"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
        },
        "required": ["title"],
    },
)
def create_mission(
    title: str,
    description: str = "",
    priority: str = "P3",
    assigned_agent: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    import memory
    mission_id = memory.create_mission(title, description, priority, assigned_agent, tags or [])
    return {"status": "created", "id": mission_id, "title": title}


@tool(
    name="update_mission",
    description="Update a mission's status, priority, or assignment.",
    schema={
        "properties": {
            "mission_id": {"type": "integer", "description": "Mission ID"},
            "status": {"type": "string", "enum": ["backlog", "active", "review", "done", "blocked"]},
            "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
            "result": {"type": "string", "description": "Result or output when completing"},
        },
        "required": ["mission_id"],
    },
)
def update_mission(
    mission_id: int,
    status: str | None = None,
    priority: str | None = None,
    result: str | None = None,
) -> dict:
    import memory
    kwargs = {}
    if status:
        kwargs["status"] = status
    if priority:
        kwargs["priority"] = priority
    if result:
        kwargs["result"] = result
    memory.update_mission(mission_id, **kwargs)
    return {"status": "updated", "id": mission_id}


@tool(
    name="schedule_task",
    description="Schedule a recurring task with a cron expression.",
    schema={
        "properties": {
            "name": {"type": "string", "description": "Task name"},
            "cron_expression": {"type": "string", "description": "Cron expression (e.g., '0 7 * * *' for daily at 7am)"},
            "prompt": {"type": "string", "description": "What to do when the task fires"},
            "agent_name": {"type": "string", "description": "Agent to run the task"},
        },
        "required": ["name", "cron_expression", "prompt"],
    },
)
def schedule_task(name: str, cron_expression: str, prompt: str, agent_name: str = "shams") -> dict:
    import memory
    task_id = memory.create_scheduled_task(name, cron_expression, prompt, agent_name)
    return {"status": "scheduled", "id": task_id, "name": name}


@tool(
    name="list_scheduled_tasks",
    description="List all scheduled recurring tasks.",
    schema={"properties": {}},
)
def list_scheduled_tasks() -> dict:
    import memory
    tasks = memory.get_scheduled_tasks()
    return {"tasks": tasks}


@tool(
    name="cancel_scheduled_task",
    description="Cancel a scheduled task.",
    schema={
        "properties": {
            "task_id": {"type": "integer", "description": "Task ID to cancel"},
        },
        "required": ["task_id"],
    },
)
def cancel_scheduled_task(task_id: int) -> dict:
    import memory
    memory.delete_scheduled_task(task_id)
    return {"status": "cancelled", "id": task_id}


@tool(
    name="create_workflow",
    description="Create a multi-step workflow with agent assignments and approval gates.",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Workflow title"},
            "description": {"type": "string", "description": "What this workflow accomplishes"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string"},
                        "instruction": {"type": "string"},
                        "requires_approval": {"type": "boolean"},
                    },
                    "required": ["agent_name", "instruction"],
                },
            },
            "mission_id": {"type": "integer", "description": "Link to a mission (optional)"},
        },
        "required": ["title", "steps"],
    },
)
def create_workflow(
    title: str,
    steps: list[dict],
    description: str = "",
    mission_id: int | None = None,
) -> dict:
    import memory
    from workflow_engine import run_next_step
    wf_id = memory.create_workflow(title, description, steps, mission_id)
    run_next_step(wf_id)
    return {"status": "created", "id": wf_id, "title": title}
```

- [ ] **Step 11: Create `tools/actions.py`**

Move tools: `propose_action`, `route_to_agent` → renamed `route_to_specialist` (definitions at lines 276-296 and 478-490, handlers at lines 824-878 and 986-998).

**IMPORTANT:** The `propose_action` handler checks auto-approve via trust scores and sends Telegram inline buttons. Preserve this behavior exactly by reading the original handler at lines 824-878.

```python
# tools/actions.py
from __future__ import annotations

import json
import logging

from tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="propose_action",
    description="Propose an action for Maher's approval. Use this for any action that modifies external systems.",
    schema={
        "properties": {
            "action_type": {
                "type": "string",
                "description": "Type: archive_email, send_email, create_pr, research, draft_document, other",
            },
            "title": {"type": "string", "description": "Short description of the action"},
            "description": {"type": "string", "description": "Detailed description of what will happen"},
            "payload": {"type": "object", "description": "Action-specific data"},
            "mission_id": {"type": "integer", "description": "Link to a mission (optional)"},
        },
        "required": ["action_type", "title"],
    },
)
def propose_action(
    action_type: str,
    title: str,
    description: str = "",
    payload: dict | None = None,
    mission_id: int | None = None,
) -> dict:
    import memory
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    import requests

    # Check auto-approve
    agent_name = "shams"
    if memory.should_auto_approve(agent_name):
        action_id = memory.create_action(agent_name, action_type, title, description, payload or {}, mission_id)
        memory.update_action_status(action_id, "approved")
        memory.increment_trust(agent_name, "total_approved")
        return {"status": "auto_approved", "id": action_id}

    action_id = memory.create_action(agent_name, action_type, title, description, payload or {}, mission_id)
    memory.increment_trust(agent_name, "total_proposed")

    # Send Telegram approval request with inline buttons
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        keyboard = {
            "inline_keyboard": [[
                {"text": "Approve", "callback_data": f"approve:{action_id}"},
                {"text": "Reject", "callback_data": f"reject:{action_id}"},
            ]]
        }
        text = f"Action proposed:\n\n{title}\n\n{description}" if description else f"Action proposed:\n\n{title}"
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "reply_markup": keyboard,
                },
                timeout=10,
            )
        except Exception as e:
            log.warning("Failed to send Telegram approval: %s", e)

    return {"status": "pending_approval", "id": action_id}


@tool(
    name="route_to_specialist",
    description="Route a query to a specialist agent (Ops, Wakil, or Leo) for domain-specific handling.",
    schema={
        "properties": {
            "agent": {"type": "string", "enum": ["ops", "wakil", "leo"], "description": "Specialist to consult"},
            "query": {"type": "string", "description": "What to ask the specialist"},
        },
        "required": ["agent", "query"],
    },
)
def route_to_specialist(agent: str, query: str) -> dict:
    from agents.registry import call_agent
    response = call_agent(agent, query)
    return {"agent": agent, "response": response}
```

- [ ] **Step 12: Create `tools/deals.py`**

Move tools: `create_deal`, `update_deal` (definitions at lines 355-389, handlers at lines 922-953).

```python
# tools/deals.py
from __future__ import annotations

from tools.registry import tool


@tool(
    name="create_deal",
    description="Create a new acquisition or partnership deal in the pipeline.",
    agent="wakil",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Deal title (e.g., 'Blue Mountain Roasters acquisition')"},
            "deal_type": {"type": "string", "enum": ["acquisition", "partnership", "lease", "other"]},
            "stage": {"type": "string", "enum": ["lead", "outreach", "negotiation", "due_diligence", "closing", "closed", "dead"]},
            "value": {"type": "number", "description": "Deal value in dollars"},
            "contact": {"type": "string", "description": "Primary contact name/email"},
            "source": {"type": "string", "description": "How the deal was sourced"},
            "location": {"type": "string", "description": "Location of the business"},
            "notes": {"type": "string", "description": "Additional notes"},
        },
        "required": ["title", "deal_type"],
    },
)
def create_deal(
    title: str,
    deal_type: str,
    stage: str = "lead",
    value: float | None = None,
    contact: str = "",
    source: str = "",
    location: str = "",
    notes: str = "",
) -> dict:
    import memory
    deal_id = memory.create_deal(title, deal_type, stage=stage, value=value, contact=contact, source=source, location=location, notes=notes)
    return {"status": "created", "id": deal_id, "title": title}


@tool(
    name="update_deal",
    description="Update a deal's stage, value, or notes.",
    agent="wakil",
    schema={
        "properties": {
            "deal_id": {"type": "integer", "description": "Deal ID"},
            "stage": {"type": "string", "enum": ["lead", "outreach", "negotiation", "due_diligence", "closing", "closed", "dead"]},
            "value": {"type": "number", "description": "Updated deal value"},
            "next_action": {"type": "string", "description": "Next action to take"},
            "notes": {"type": "string", "description": "Additional notes"},
        },
        "required": ["deal_id"],
    },
)
def update_deal(deal_id: int, **kwargs) -> dict:
    import memory
    memory.update_deal(deal_id, **kwargs)
    return {"status": "updated", "id": deal_id}
```

- [ ] **Step 13: Create `tools/legal.py`**

Move tools: `draft_legal_document`, `assign_research` (definitions at lines 297-329, handlers at lines 722-770 and 809-822).

**IMPORTANT:** The `draft_legal_document` handler spawns a nested Claude API call with Wakil's persona. Preserve this behavior exactly.

```python
# tools/legal.py
from __future__ import annotations

import json
import logging

from tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="draft_legal_document",
    description="Draft a legal document using Wakil (legal specialist). Types: LOI, NDA, term_sheet, memo, contract_review.",
    agent="wakil",
    schema={
        "properties": {
            "doc_type": {
                "type": "string",
                "enum": ["loi", "nda", "term_sheet", "memo", "contract_review", "other"],
            },
            "context": {"type": "string", "description": "All relevant details for the document"},
            "parties": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names of parties involved",
            },
        },
        "required": ["doc_type", "context"],
    },
)
def draft_legal_document(doc_type: str, context: str, parties: list[str] | None = None) -> dict:
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from agents.registry import build_agent_system_prompt

    system = build_agent_system_prompt("wakil", extra_context=f"Document type: {doc_type}\nParties: {parties or []}")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": f"Draft this {doc_type}:\n\n{context}"}],
    )
    draft = msg.content[0].text

    import memory
    file_id = memory.save_file(
        filename=f"{doc_type}_{parties[0] if parties else 'draft'}.md".replace(" ", "_"),
        file_type="legal_draft",
        content=draft,
    )
    return {"draft": draft, "file_id": file_id, "doc_type": doc_type}


@tool(
    name="assign_research",
    description="Assign a research task. Searches the web, compiles findings, and reports back.",
    agent="ops",
    schema={
        "properties": {
            "query": {"type": "string", "description": "What to research"},
            "depth": {"type": "string", "enum": ["quick", "deep"], "description": "Quick (1-2 searches) or deep (5+ searches)"},
        },
        "required": ["query"],
    },
)
def assign_research(query: str, depth: str = "quick") -> dict:
    from web_search import search
    results = search(query)
    return {"query": query, "depth": depth, "results": results}
```

- [ ] **Step 14: Verify all tools load via auto-discovery**

```bash
cd /Users/mj/code/Shams && python3 -c "
from tools.registry import discover_tools, get_tool_definitions
discover_tools()
defs = get_tool_definitions()
print(f'Total tools registered: {len(defs)}')
for d in sorted(defs, key=lambda x: x['name']):
    print(f'  {d[\"name\"]}')
"
```

Expected: 41 tools listed. If any import fails, fix the failing tool file.

- [ ] **Step 15: Commit all tool files**

```bash
git add tools/
git commit -m "feat: migrate all 41 tools to domain files with @tool decorator"
```

---

## Task 4: Rewrite agent system (4 agents, internal routing)

**Files:**
- Modify: `agents/registry.py`
- Create: `context/ops.md`
- Create: `tests/test_routing.py`

- [ ] **Step 1: Create Ops persona file**

Read `context/rumi_persona.md`, `context/scout_persona.md`, and `context/builder_persona.md` to understand what each covers. Then create a consolidated Ops persona.

```markdown
# Ops — QCC Operations & Intelligence

You are Ops, the operational intelligence specialist for Queen City Coffee Roasters. You handle:

## QCC Operations (via Rumi API)
- P&L analysis (daily, monthly)
- Inventory monitoring and stockout prediction
- Labor and production metrics
- Cashflow forecasting
- Action items and operational alerts

## Research & Market Intelligence
- Web research for acquisition targets, competitors, real estate
- Market analysis and deal sourcing
- Competitive intelligence gathering

## Technical Operations
- Codebase reading and search across repos (Shams, Rumi, Leo)
- Code change proposals via GitHub PRs
- System health monitoring

## Style
- Data-first: lead with numbers, then interpretation
- Concise: bullet points over paragraphs
- Proactive: flag anomalies before asked
- Operational: focus on what needs doing, not theory
```

- [ ] **Step 2: Write agent routing tests**

```python
# tests/test_routing.py
from __future__ import annotations

from agents.registry import AGENTS, build_agent_system_prompt, get_agent_tools


def test_four_agents_defined():
    assert set(AGENTS.keys()) == {"shams", "ops", "wakil", "leo"}


def test_shams_gets_all_tools():
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    shams_tools = get_tool_definitions(agent=None)
    all_tools = get_tool_definitions()
    assert len(shams_tools) == len(all_tools)


def test_ops_gets_scoped_tools():
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    ops_tools = get_tool_definitions(agent="ops")
    ops_names = {t["name"] for t in ops_tools}
    # Ops should have rumi tools + research + github + unscoped tools
    assert "get_rumi_daily_pl" in ops_names
    assert "web_search" in ops_names  # unscoped
    # Ops should NOT have wakil-only tools
    assert "draft_legal_document" not in ops_names


def test_wakil_gets_scoped_tools():
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    wakil_tools = get_tool_definitions(agent="wakil")
    wakil_names = {t["name"] for t in wakil_tools}
    assert "draft_legal_document" in wakil_names
    assert "create_deal" in wakil_names
    assert "get_rumi_daily_pl" not in wakil_names


def test_leo_gets_scoped_tools():
    from tools.registry import discover_tools, get_tool_definitions
    discover_tools()
    leo_tools = get_tool_definitions(agent="leo")
    leo_names = {t["name"] for t in leo_tools}
    assert "get_leo_health_summary" in leo_names
    assert "get_rumi_daily_pl" not in leo_names


def test_build_agent_system_prompt_loads_persona():
    prompt = build_agent_system_prompt("ops")
    assert "Operations" in prompt or "Ops" in prompt


def test_build_agent_system_prompt_with_extra_context():
    prompt = build_agent_system_prompt("ops", extra_context="Today is Monday.")
    assert "Today is Monday" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_routing.py -v
```

Expected: Failures because `AGENTS` still has 6 agents

- [ ] **Step 4: Rewrite `agents/registry.py`**

Replace the entire file:

```python
# agents/registry.py
from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

log = logging.getLogger(__name__)

CONTEXT_DIR = Path(__file__).parent.parent / "context"

AGENTS = {
    "shams": {
        "role": "Chief of Staff & Orchestrator",
        "persona_file": "shams_system_prompt.md",
        "knowledge_files": [
            "shams_knowledge_qcc_overview.md",
            "shams_knowledge_active_deals.md",
            "shams_knowledge_personal.md",
        ],
        "color": "#6366f1",
    },
    "ops": {
        "role": "QCC Operations & Intelligence",
        "persona_file": "ops.md",
        "knowledge_files": ["shams_knowledge_qcc_overview.md"],
        "color": "#f59e0b",
    },
    "wakil": {
        "role": "Legal Strategist & Counsel",
        "persona_file": "wakil_persona.md",
        "knowledge_files": [
            "shams_knowledge_active_deals.md",
        ],
        "color": "#ef4444",
    },
    "leo": {
        "role": "Health & Performance Coach",
        "persona_file": "leo_persona.md",
        "knowledge_files": [],
        "color": "#10b981",
    },
}


def build_agent_system_prompt(agent_name: str, extra_context: str = "") -> str:
    """Build system prompt for an agent by loading persona + knowledge on demand."""
    agent = AGENTS.get(agent_name)
    if not agent:
        return f"You are {agent_name}."

    parts = []

    # Load persona
    persona_path = CONTEXT_DIR / agent["persona_file"]
    if persona_path.exists():
        parts.append(persona_path.read_text().strip())

    # Load knowledge files
    for kf in agent["knowledge_files"]:
        kf_path = CONTEXT_DIR / kf
        if kf_path.exists():
            parts.append(kf_path.read_text().strip())

    if extra_context:
        parts.append(f"# Current Context\n{extra_context}")

    return "\n\n---\n\n".join(parts)


def call_agent(agent_name: str, message: str, history: list | None = None, extra_context: str = "") -> str:
    """Call a specialist agent with its scoped tools. Returns text response."""
    from tools.registry import get_tool_definitions, execute

    system = build_agent_system_prompt(agent_name, extra_context)
    tools = get_tool_definitions(agent=agent_name)

    messages = list(history or [])
    messages.append({"role": "user", "content": message})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for _ in range(5):  # max tool-use iterations
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_blocks)

        # Handle tool use
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result) if not isinstance(result, str) else result,
                })
        messages.append({"role": "user", "content": tool_results})

    return "Agent reached maximum iterations."


def list_agents() -> list[dict]:
    """Return agent info for dashboard display."""
    return [
        {"name": name, "role": agent["role"], "color": agent["color"]}
        for name, agent in AGENTS.items()
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_routing.py -v
```

Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add agents/registry.py context/ops.md tests/test_routing.py
git commit -m "feat: rewrite agent system — 4 agents (Shams, Ops, Wakil, Leo) with scoped tools"
```

---

## Task 5: Rewrite `claude_client.py` — chat loop + prompt assembly

**Files:**
- Modify: `claude_client.py` (1,217 → ~200 lines)
- Create: `tests/test_context.py`

This is the core rewrite. The new `claude_client.py` does ONLY: build system prompt with hot context, run the tool-use chat loop via the registry, and save to conversation history.

- [ ] **Step 1: Write tests for hot context assembly**

```python
# tests/test_context.py
from __future__ import annotations

from unittest.mock import patch
from datetime import datetime


def test_build_core_prompt_is_short():
    from claude_client import _build_core_prompt
    prompt = _build_core_prompt()
    # Core prompt should be under 2000 chars (~500 tokens)
    assert len(prompt) < 2000
    assert "Shams" in prompt


def test_build_hot_context_morning():
    from claude_client import _build_hot_context
    with patch("claude_client._now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 11, 0, 0)  # 7am ET = 11 UTC
        ctx = _build_hot_context()
        assert isinstance(ctx, str)
        # Morning context should mention calendar/actions
        assert len(ctx) > 0


def test_build_hot_context_overnight():
    from claude_client import _build_hot_context
    with patch("claude_client._now") as mock_now:
        mock_now.return_value = datetime(2026, 4, 12, 7, 0, 0)  # 3am ET = 7 UTC
        ctx = _build_hot_context()
        assert isinstance(ctx, str)


def test_build_system_combines_core_and_hot():
    from claude_client import _build_system
    system = _build_system()
    assert isinstance(system, str)
    assert "Shams" in system
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_context.py -v
```

Expected: ImportError because functions don't exist yet

- [ ] **Step 3: Rewrite `claude_client.py`**

Replace the entire file. Read the original first to preserve `chat()` and `generate_briefing()` behavior.

```python
# claude_client.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import memory
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from tools.registry import discover_tools, get_tool_definitions, execute

log = logging.getLogger(__name__)

CONTEXT_DIR = Path(__file__).parent / "context"
CORE_PROMPT_FILE = CONTEXT_DIR / "shams_system_prompt.md"

# Discover tools at import time
discover_tools()


def _now() -> datetime:
    """Current UTC time. Mockable for tests."""
    return datetime.now(timezone.utc)


def _build_core_prompt() -> str:
    """Static identity + instructions (~500 tokens). Loaded once."""
    if CORE_PROMPT_FILE.exists():
        return CORE_PROMPT_FILE.read_text().strip()
    return "You are Shams, MJ's AI chief of staff."


def _build_hot_context() -> str:
    """Rotating context block based on time of day and recent activity."""
    now = _now()
    et_hour = (now.hour - 4) % 24  # rough ET offset

    parts = []
    parts.append(f"Current time: {now.strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        # Always include open loops (lightweight)
        loops = memory.get_open_loops()
        if loops:
            parts.append(f"Open loops ({len(loops)}): " + "; ".join(l["title"] for l in loops[:5]))
    except Exception:
        pass

    try:
        if et_hour < 5:
            # Overnight (3am loop): cash + deadlines + recent emails
            parts.append("# Overnight Context")
            decisions = memory.get_recent_decisions(3)
            if decisions:
                parts.append("Recent decisions: " + "; ".join(d["summary"] for d in decisions))

        elif et_hour < 10:
            # Morning standup: overnight results + today's actions
            parts.append("# Morning Context")
            actions = memory.get_actions(status="pending", limit=5)
            if actions:
                parts.append(f"Pending actions ({len(actions)}): " + "; ".join(a["title"] for a in actions))

        elif et_hour < 18:
            # Daytime: recent activity + active missions
            parts.append("# Daytime Context")
            missions = memory.get_missions(status="active")
            if missions:
                parts.append(f"Active missions ({len(missions)}): " + "; ".join(m["title"] for m in missions[:5]))

        else:
            # Evening: day summary
            parts.append("# Evening Context")
            decisions = memory.get_recent_decisions(5)
            if decisions:
                parts.append("Today's decisions: " + "; ".join(d["summary"] for d in decisions))

    except Exception as e:
        log.warning("Error building hot context: %s", e)

    # Always include key memories
    try:
        all_mem = memory.recall_all()
        if all_mem:
            mem_strs = [f"{k}: {v}" for k, v in list(all_mem.items())[:10]]
            parts.append("Key memories: " + "; ".join(mem_strs))
    except Exception:
        pass

    return "\n".join(parts)


def _build_system() -> str:
    """Assemble full system prompt: core + hot context."""
    core = _build_core_prompt()
    hot = _build_hot_context()
    return f"{core}\n\n---\n\n{hot}"


def chat(user_message: str, images: list[dict] | None = None) -> str:
    """Main chat interface. Runs tool-use loop, saves to conversation history."""
    memory.save_message("user", user_message)

    # Build messages from recent history
    recent = memory.get_recent_messages(limit=30)
    messages = []
    for msg in recent:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # If images, replace last message with multimodal content
    if images and messages:
        content_blocks = []
        for img in images:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/jpeg"),
                    "data": img["data"],
                },
            })
        content_blocks.append({"type": "text", "text": user_message})
        messages[-1] = {"role": "user", "content": content_blocks}

    system = _build_system()
    tools = get_tool_definitions()  # All tools for Shams
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for iteration in range(5):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            reply = "\n".join(text_blocks)
            memory.save_message("assistant", reply)
            return reply

        # Tool use
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:200])
                result = execute(block.name, block.input)
                result_str = json.dumps(result) if not isinstance(result, str) else result

                # Log to activity feed
                try:
                    memory.log_activity(
                        agent_name="shams",
                        event_type="tool_call",
                        content=f"{block.name}: {result_str[:200]}",
                        metadata={"tool": block.name, "input": block.input},
                    )
                except Exception:
                    pass

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })
        messages.append({"role": "user", "content": tool_results})

    reply = "I hit my iteration limit. Let me know if you'd like me to continue."
    memory.save_message("assistant", reply)
    return reply


def generate_briefing(briefing_type: str = "morning") -> str:
    """Generate a briefing without saving to conversation history."""
    system = _build_system()
    tools = get_tool_definitions()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if briefing_type == "morning":
        prompt = (
            "Generate the morning briefing. Check: Mercury balances, Rumi scorecard, "
            "open loops, pending actions, today's calendar. Be concise and actionable."
        )
    else:
        prompt = (
            "Generate the evening briefing. Summarize: what happened today, decisions made, "
            "actions completed, open items for tomorrow. Be concise."
        )

    messages = [{"role": "user", "content": prompt}]

    for _ in range(5):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            briefing = "\n".join(text_blocks)
            memory.save_briefing(briefing_type, briefing, "telegram")
            return briefing

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute(block.name, block.input)
                result_str = json.dumps(result) if not isinstance(result, str) else result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })
        messages.append({"role": "user", "content": tool_results})

    return "Briefing generation hit iteration limit."
```

- [ ] **Step 4: Run context tests**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_context.py -v
```

Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add claude_client.py tests/test_context.py
git commit -m "feat: rewrite claude_client.py — slim prompt, hot context, registry-based dispatch"
```

---

## Task 6: Migrate `memory.py` to connection pool

**Files:**
- Modify: `memory.py`
- Create: `tests/test_memory.py`

Switch all ~55 functions from `_conn()` to `db.get_conn()`. This is a mechanical find-and-replace of the connection pattern.

- [ ] **Step 1: Write memory tests**

```python
# tests/test_memory.py
from __future__ import annotations

import memory


def test_save_and_recall():
    memory.remember("_test_key", "test_value")
    result = memory.recall("_test_key")
    assert result == "test_value"
    # Cleanup
    memory.remember("_test_key", "")


def test_recall_all():
    memory.remember("_test_all_1", "val1")
    memory.remember("_test_all_2", "val2")
    all_mem = memory.recall_all()
    assert "_test_all_1" in all_mem
    assert all_mem["_test_all_1"] == "val1"
    # Cleanup
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
    dec_id = memory.log_decision("_test_decision", "because test", "should pass")
    assert dec_id is not None
    decisions = memory.get_recent_decisions(limit=1)
    assert len(decisions) >= 1


def test_activity_feed():
    memory.log_activity("shams", "test_event", "_test_activity", {"key": "val"})
    feed = memory.get_activity_feed(limit=1)
    assert len(feed) >= 1
```

- [ ] **Step 2: Run tests to verify current memory.py works**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_memory.py -v
```

Expected: Should pass (testing current implementation before migration)

- [ ] **Step 3: Migrate memory.py to use connection pool**

Replace the `_conn()` function and all its usages. The pattern change for every function:

**Before:**
```python
def remember(key, value):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO ... ON CONFLICT ...", (key, value))
        conn.commit()
    finally:
        conn.close()
```

**After:**
```python
def remember(key, value):
    from db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO ... ON CONFLICT ...", (key, value))
```

Read the full `memory.py` file. For every function:
1. Remove the `conn = _conn()` / `try` / `finally: conn.close()` pattern
2. Replace with `from db import get_conn` (import at top of file) + `with get_conn() as conn:`
3. Remove `conn.commit()` calls (handled by context manager)
4. Remove `conn.close()` calls (handled by context manager)

Delete the `_conn()` function entirely. Add `from db import get_conn` at the top of the file.

Also update `ensure_tables()` to use the pool:

```python
def ensure_tables():
    schema_path = Path(__file__).parent / "schema.sql"
    if schema_path.exists():
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(schema_path.read_text())
```

- [ ] **Step 4: Run tests to verify migration didn't break anything**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_memory.py -v
```

Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add memory.py tests/test_memory.py
git commit -m "feat: migrate memory.py to connection pool — replace _conn() with db.get_conn()"
```

---

## Task 7: Split `app.py` → `telegram.py` + `scheduler.py`

**Files:**
- Modify: `app.py` (914 → ~150 lines)
- Create: `telegram.py`
- Create: `scheduler.py`

- [ ] **Step 1: Create `telegram.py`**

Move from `app.py`: `process_message()` (lines 146-284), `telegram_polling()` (lines 289-346), `_handle_callback()` (lines 502-561), `_handle_email_action()` (lines 447-500), `telegram_webhook()` (lines 362-392), and all Telegram helpers (send_message, send_typing_action, download_file, etc.).

```python
# telegram.py
from __future__ import annotations

import base64
import json
import logging
import tempfile
import threading

import requests

import claude_client
import memory
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY

log = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(chat_id: str | int, text: str, reply_markup: dict | None = None) -> None:
    """Send a Telegram message, splitting if > 4096 chars."""
    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            send_message(chat_id, text[i:i + 4096], reply_markup if i + 4096 >= len(text) else None)
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)
    except Exception as e:
        log.error("Failed to send Telegram message: %s", e)


def send_typing_action(chat_id: str | int) -> None:
    try:
        requests.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass


def process_message(message: dict) -> None:
    """Process an incoming Telegram message."""
    chat_id = message.get("chat", {}).get("id")
    if str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    send_typing_action(chat_id)

    # Text messages
    if "text" in message:
        text = message["text"]

        # Slash commands
        if text.startswith("/start"):
            send_message(chat_id, "Shams online. How can I help?")
            return

        if text.startswith("/movie "):
            title = text[7:].strip()
            quality = "1080p"
            parts = title.rsplit(" ", 1)
            if len(parts) == 2 and parts[1] in ("720p", "1080p", "4k", "2160p"):
                title, quality = parts
            from tools.registry import execute
            result = execute("add_media", {"media_type": "movie", "title": title, "quality": quality})
            send_message(chat_id, json.dumps(result, indent=2) if isinstance(result, dict) else str(result))
            return

        if text.startswith("/tv "):
            title = text[4:].strip()
            from tools.registry import execute
            result = execute("add_media", {"media_type": "tv", "title": title})
            send_message(chat_id, json.dumps(result, indent=2) if isinstance(result, dict) else str(result))
            return

        reply = claude_client.chat(text)
        send_message(chat_id, reply)
        return

    # Photo messages
    if "photo" in message:
        photo = message["photo"][-1]  # highest resolution
        file_info = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": photo["file_id"]}, timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}", timeout=30).content
        b64 = base64.b64encode(file_data).decode()
        caption = message.get("caption", "What do you see in this image?")
        images = [{"data": b64, "media_type": "image/jpeg"}]
        reply = claude_client.chat(caption, images=images)
        send_message(chat_id, reply)
        return

    # Voice messages
    if "voice" in message or "audio" in message:
        voice = message.get("voice") or message.get("audio")
        file_info = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": voice["file_id"]}, timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}", timeout=30).content

        # Transcribe with Whisper
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as f:
            f.write(file_data)
            f.flush()
            with open(f.name, "rb") as audio:
                transcript = client.audio.transcriptions.create(model="whisper-1", file=audio)
        text = transcript.text
        send_message(chat_id, f"Heard: {text}")
        reply = claude_client.chat(text)
        send_message(chat_id, reply)
        return

    # Document messages
    if "document" in message:
        doc = message["document"]
        file_info = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": doc["file_id"]}, timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}", timeout=30).content

        mime = doc.get("mime_type", "")
        if "pdf" in mime:
            import io
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(file_data))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception:
                text = "(Could not extract PDF text)"
        else:
            text = file_data.decode("utf-8", errors="replace")

        caption = message.get("caption", f"Here's a document ({doc.get('file_name', 'file')}). Please review it.")
        reply = claude_client.chat(f"{caption}\n\nDocument content:\n{text[:10000]}")
        send_message(chat_id, reply)
        return

    send_message(chat_id, "I can handle text, photos, voice notes, and documents.")


def handle_callback(callback_query: dict) -> None:
    """Handle inline button presses (approve/reject actions, email actions)."""
    data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]

    # Acknowledge the callback
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": callback_query["id"]},
        timeout=5,
    )

    if data.startswith("approve:"):
        action_id = int(data.split(":")[1])
        memory.update_action_status(action_id, "approved")
        memory.increment_trust("shams", "total_approved")
        send_message(chat_id, f"Action {action_id} approved.")
        # Check if part of a workflow
        action = memory.get_action(action_id)
        if action and action.get("payload", {}).get("workflow_id"):
            from workflow_engine import run_next_step
            run_next_step(action["payload"]["workflow_id"])
        return

    if data.startswith("reject:"):
        action_id = int(data.split(":")[1])
        memory.update_action_status(action_id, "rejected")
        memory.increment_trust("shams", "total_rejected")
        send_message(chat_id, f"Action {action_id} rejected.")
        return

    # Email actions (earchive, estar, etc.)
    if data.startswith("e"):
        _handle_email_action(data, chat_id)
        return


def _handle_email_action(data: str, chat_id: str | int) -> None:
    """Handle email triage inline button actions."""
    parts = data.split(":")
    if len(parts) < 2:
        return
    action_type = parts[0]
    triage_id = int(parts[1])

    if action_type == "earchive":
        memory.mark_email_archived(triage_id)
        send_message(chat_id, "Email archived.")
    elif action_type == "estar":
        send_message(chat_id, "Email starred.")
    elif action_type == "esnooze":
        send_message(chat_id, "Email snoozed.")
    elif action_type == "edraft":
        send_message(chat_id, "Draft reply coming...")
    elif action_type == "edelegate":
        send_message(chat_id, "Delegating...")


def setup_webhook(app_url: str) -> bool:
    """Register Telegram webhook."""
    webhook_url = f"{app_url}/telegram/webhook"
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
            timeout=10,
        )
        result = resp.json()
        if result.get("ok"):
            log.info("Telegram webhook set: %s", webhook_url)
            return True
        log.error("Webhook setup failed: %s", result)
        return False
    except Exception as e:
        log.error("Webhook setup error: %s", e)
        return False
```

- [ ] **Step 2: Create `scheduler.py`**

Move from `app.py`: all APScheduler setup, job functions (`send_morning_briefing`, `send_evening_briefing`, `scheduled_inbox_triage`, `agent_health_check`, `mission_stale_check`, `smart_alerts_check`), and dynamic task loading.

```python
# scheduler.py
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

import claude_client
import memory
from config import BRIEFING_HOUR_UTC, EVENING_HOUR_UTC, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)

scheduler: BackgroundScheduler | None = None


def send_morning_briefing() -> None:
    from telegram import send_message
    try:
        briefing = claude_client.generate_briefing("morning")
        send_message(TELEGRAM_CHAT_ID, briefing)
    except Exception as e:
        log.error("Morning briefing failed: %s", e)


def send_evening_briefing() -> None:
    from telegram import send_message
    try:
        briefing = claude_client.generate_briefing("evening")
        send_message(TELEGRAM_CHAT_ID, briefing)
    except Exception as e:
        log.error("Evening briefing failed: %s", e)


def scheduled_inbox_triage() -> None:
    from tools.registry import execute
    try:
        result = execute("triage_inbox", {"max_emails": 10})
        if result.get("results"):
            from telegram import send_message
            count = sum(r.get("count", 0) for r in result["results"])
            if count > 0:
                send_message(TELEGRAM_CHAT_ID, f"Inbox triage: processed {count} emails.")
    except Exception as e:
        log.error("Scheduled inbox triage failed: %s", e)


def agent_health_check() -> None:
    import requests
    agents = memory.get_agents()
    for agent in agents:
        url = agent.get("health_url")
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=5)
            status = "online" if resp.status_code == 200 else "degraded"
        except Exception:
            status = "offline"
        memory.update_agent_status(agent["name"], status)


def mission_stale_check() -> None:
    try:
        missions = memory.get_missions(status="active")
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        stale = []
        for m in missions:
            created = m.get("created_at")
            if created and (now - created).total_seconds() > 48 * 3600:
                stale.append(m)
        if stale:
            from telegram import send_message
            titles = ", ".join(m["title"] for m in stale[:5])
            send_message(TELEGRAM_CHAT_ID, f"Stale missions (>48h active): {titles}")
    except Exception as e:
        log.error("Mission stale check failed: %s", e)


def smart_alerts_check() -> None:
    try:
        rules = memory.get_alert_rules(enabled_only=True)
        for rule in rules:
            # Evaluate each rule — this is a placeholder for actual metric evaluation
            # Each rule has: metric, condition, threshold, message_template
            pass
    except Exception as e:
        log.error("Smart alerts check failed: %s", e)


def _load_dynamic_tasks() -> None:
    """Load user-created scheduled tasks from DB."""
    try:
        tasks = memory.get_scheduled_tasks(enabled_only=True)
        for task in tasks:
            cron_parts = task["cron_expression"].split()
            if len(cron_parts) == 5:
                scheduler.add_job(
                    _run_dynamic_task,
                    "cron",
                    minute=cron_parts[0],
                    hour=cron_parts[1],
                    day=cron_parts[2],
                    month=cron_parts[3],
                    day_of_week=cron_parts[4],
                    args=[task["id"], task["prompt"], task.get("agent_name", "shams")],
                    id=f"dynamic_{task['id']}",
                    replace_existing=True,
                )
    except Exception as e:
        log.error("Failed to load dynamic tasks: %s", e)


def _run_dynamic_task(task_id: int, prompt: str, agent_name: str) -> None:
    try:
        reply = claude_client.chat(prompt)
        memory.mark_task_run(task_id, reply[:500])
    except Exception as e:
        log.error("Dynamic task %d failed: %s", task_id, e)
        memory.mark_task_run(task_id, f"Error: {e}")


def init_scheduler() -> BackgroundScheduler:
    """Initialize and start the scheduler with all jobs."""
    global scheduler
    scheduler = BackgroundScheduler()

    scheduler.add_job(send_morning_briefing, "cron", hour=BRIEFING_HOUR_UTC, minute=0, id="morning_briefing")
    scheduler.add_job(send_evening_briefing, "cron", hour=EVENING_HOUR_UTC, minute=0, id="evening_briefing")
    scheduler.add_job(scheduled_inbox_triage, "interval", minutes=30, id="inbox_triage")
    scheduler.add_job(agent_health_check, "interval", minutes=5, id="health_check")
    scheduler.add_job(mission_stale_check, "cron", hour=12, minute=0, id="stale_check")
    scheduler.add_job(smart_alerts_check, "interval", hours=1, id="smart_alerts")

    _load_dynamic_tasks()
    scheduler.start()
    log.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler
```

- [ ] **Step 3: Rewrite `app.py`**

Slim down to Flask init + startup only:

```python
# app.py
from __future__ import annotations

import logging
import os

from flask import Flask, request, jsonify, send_from_directory

import db
import memory
import claude_client
from config import FLASK_SECRET_KEY, FLASK_PORT

log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend/dist")
app.secret_key = FLASK_SECRET_KEY or "dev-secret"


# --- Health ---
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# --- Telegram webhook ---
@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    from telegram import process_message, handle_callback
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": True})

    if "message" in data:
        process_message(data["message"])
    elif "callback_query" in data:
        handle_callback(data["callback_query"])

    return jsonify({"ok": True})


# --- Chat (HTTP fallback) ---
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")
    reply = claude_client.chat(message)
    return jsonify({"reply": reply})


# --- Dashboard API ---
from api import register_blueprints
register_blueprints(app)


# --- Frontend SPA ---
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    static = app.static_folder
    if path and os.path.exists(os.path.join(static, path)):
        return send_from_directory(static, path)
    return send_from_directory(static, "index.html")


# --- Startup ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Init database
    db.init_pool()
    memory.ensure_tables()

    # Init scheduler
    from scheduler import init_scheduler
    init_scheduler()

    # Setup Telegram webhook
    app_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if app_url:
        from telegram import setup_webhook
        setup_webhook(f"https://{app_url}")

    app.run(host="0.0.0.0", port=FLASK_PORT)
```

- [ ] **Step 4: Verify the app starts locally**

```bash
cd /Users/mj/code/Shams && python3 -c "from app import app; print('App created successfully')"
```

Expected: "App created successfully" (just tests import chain, not full startup)

- [ ] **Step 5: Commit**

```bash
git add app.py telegram.py scheduler.py
git commit -m "feat: split app.py into telegram.py + scheduler.py — app.py now ~80 lines"
```

---

## Task 8: Split `dashboard_api.py` into `api/` modules

**Files:**
- Create: `api/__init__.py`, `api/auth.py`, `api/chat.py`, `api/projects.py`, `api/agents.py`, `api/mercury.py`, `api/integrations.py`, `api/actions.py`, `api/inbox.py`, `api/files.py`, `api/briefings.py`, `api/settings.py`, `api/deals.py`, `api/signatures.py`, `api/money.py`
- Delete: `dashboard_api.py` (after migration)

This is a large mechanical task. Each API module creates its own Blueprint and the `__init__.py` registers them all.

- [ ] **Step 1: Create `api/__init__.py`**

```python
# api/__init__.py
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """Register all API blueprints."""
    from api.auth import bp as auth_bp
    from api.chat import bp as chat_bp
    from api.projects import bp as projects_bp
    from api.agents import bp as agents_bp
    from api.mercury import bp as mercury_bp
    from api.integrations import bp as integrations_bp
    from api.actions import bp as actions_bp
    from api.inbox import bp as inbox_bp
    from api.files import bp as files_bp
    from api.briefings import bp as briefings_bp
    from api.settings import bp as settings_bp
    from api.deals import bp as deals_bp
    from api.signatures import bp as signatures_bp
    from api.money import bp as money_bp

    for blueprint in [
        auth_bp, chat_bp, projects_bp, agents_bp, mercury_bp,
        integrations_bp, actions_bp, inbox_bp, files_bp, briefings_bp,
        settings_bp, deals_bp, signatures_bp, money_bp,
    ]:
        app.register_blueprint(blueprint)
```

- [ ] **Step 2: Create `api/auth.py`**

Move the `require_auth` decorator and auth routes from `dashboard_api.py` lines 29-132. This is the shared auth decorator that all other modules import.

```python
# api/auth.py
from __future__ import annotations

import functools
import secrets

from flask import Blueprint, request, jsonify, g

import memory
from config import RESEND_API_KEY, RESEND_FROM_EMAIL

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def require_auth(f):
    """Decorator to require authentication via session cookie or Bearer token."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("shams_session")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if not token:
            return jsonify({"error": "Not authenticated"}), 401
        session = memory.validate_session(token)
        if not session:
            return jsonify({"error": "Invalid session"}), 401
        g.email = session["email"]
        return f(*args, **kwargs)
    return decorated


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400

    token = secrets.token_urlsafe(32)
    memory.create_magic_link(email, token)

    # Send magic link via Resend
    if RESEND_API_KEY:
        import requests as req
        req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": RESEND_FROM_EMAIL,
                "to": email,
                "subject": "Shams Login Link",
                "html": f'<a href="https://app.myshams.ai/auth/verify?token={token}">Click to login</a>',
            },
            timeout=10,
        )

    return jsonify({"status": "sent"})


@bp.route("/verify")
def verify():
    token = request.args.get("token", "")
    result = memory.validate_magic_link(token)
    if not result:
        return jsonify({"error": "Invalid or expired link"}), 401

    session_token = secrets.token_urlsafe(32)
    memory.create_session(result["email"], session_token)

    resp = jsonify({"status": "ok", "email": result["email"]})
    resp.set_cookie("shams_session", session_token, httponly=True, samesite="Lax", max_age=7 * 24 * 3600)
    return resp


@bp.route("/me")
@require_auth
def me():
    return jsonify({"email": g.email})


@bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    token = request.cookies.get("shams_session")
    if token:
        memory.delete_session(token)
    resp = jsonify({"status": "ok"})
    resp.delete_cookie("shams_session")
    return resp
```

- [ ] **Step 3: Create remaining API modules**

For each module below, read the corresponding section of `dashboard_api.py` and move the routes. Every module follows the same pattern:

```python
from flask import Blueprint, request, jsonify
from api.auth import require_auth
import memory
```

Create these files by reading the original `dashboard_api.py` and moving routes grouped by domain. Each file creates a `bp = Blueprint("name", __name__, url_prefix="/api")`.

**Files to create (read original routes at the line numbers noted):**

- `api/chat.py` — lines 370-430: `/api/chat` POST, `/api/group-chat` POST (modified to route through Shams instead of group_chat.py), `/api/group-chat/history` GET, `/api/conversations` GET
- `api/projects.py` — lines 902-1128: missions CRUD + projects CRUD + gantt endpoints
- `api/agents.py` — lines 794-897: agents list, detail, status update, activity feed (lines 317-338 in memory)
- `api/mercury.py` — lines 632-646: balances, transactions
- `api/integrations.py` — lines 672-789: integration status, Google OAuth flow
- `api/actions.py` — lines from shams_actions: actions list/approve/reject/execute + trust scores
- `api/inbox.py` — lines 1534+: inbox scan + email triage endpoints
- `api/files.py` — lines 561-627 + 1297-1323: folders, files, search, recent, mission files (lines 1204-1226)
- `api/briefings.py` — lines 435-556: memory KV, open loops, decisions, briefings
- `api/settings.py` — lines 1350-1529: alert rules, delegations, notifications, scheduled tasks, workflows
- `api/deals.py` — lines 1462-1498: deals CRUD
- `api/signatures.py` — lines 1133-1199: DocuSeal templates, send, submissions, status
- `api/money.py` — lines 137-319 + 651-667: today dashboard, money view, rumi daily/monthly/scorecard

**Each route handler is a direct copy from `dashboard_api.py` with these changes:**
1. `@api.route(...)` becomes `@bp.route(...)`
2. `@require_auth` import changes to `from api.auth import require_auth`
3. All `memory.*` calls stay the same

- [ ] **Step 4: Modify `api/chat.py` to remove group_chat dependency**

The `/api/group-chat` POST endpoint currently calls `group_chat.send_group_message()`. Replace this with routing through Shams:

```python
@bp.route("/group-chat", methods=["POST"])
@require_auth
def group_chat_send():
    data = request.get_json()
    message = data.get("message", "")
    # Route through Shams instead of parallel agent dispatch
    reply = claude_client.chat(message)
    memory.save_group_message("shams", reply)
    return jsonify({"responses": [{"agent": "shams", "content": reply}]})
```

- [ ] **Step 5: Delete `dashboard_api.py`**

After all routes are migrated and verified:

```bash
git rm dashboard_api.py
```

- [ ] **Step 6: Delete `group_chat.py`**

```bash
git rm group_chat.py
```

- [ ] **Step 7: Verify all API routes are accessible**

```bash
cd /Users/mj/code/Shams && python3 -c "
from app import app
rules = sorted([r.rule for r in app.url_map.iter_rules() if r.rule.startswith('/api')])
print(f'Total API routes: {len(rules)}')
for r in rules:
    print(f'  {r}')
"
```

Expected: All ~55 routes listed under `/api/`

- [ ] **Step 8: Commit**

```bash
git add api/ && git rm dashboard_api.py group_chat.py
git commit -m "feat: split dashboard_api.py into 14 api/ modules, delete group_chat.py"
```

---

## Task 9: Action lifecycle tests

**Files:**
- Create: `tests/test_actions.py`

- [ ] **Step 1: Write action lifecycle tests**

```python
# tests/test_actions.py
from __future__ import annotations

import memory


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
    # Reset for test
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
    # Reset
    memory.set_auto_approve("_test_agent_aa", False)
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/test_actions.py -v
```

Expected: All passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_actions.py
git commit -m "test: add action lifecycle + trust score tests"
```

---

## Task 10: Full test suite + cleanup + verification

**Files:**
- Modify: `agents/codebase.py` — keep for now (still imported by `tools/github.py`)
- Remove any unused imports across all files

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/mj/code/Shams && python3 -m pytest tests/ -v
```

Expected: All tests passing (~30-40 tests across 6 test files)

- [ ] **Step 2: Verify import chain**

```bash
cd /Users/mj/code/Shams && python3 -c "
import db
import memory
from tools.registry import discover_tools, get_tool_definitions, execute
discover_tools()
print(f'Tools: {len(get_tool_definitions())}')
from agents.registry import AGENTS, list_agents
print(f'Agents: {list(AGENTS.keys())}')
import claude_client
print('claude_client OK')
import telegram
print('telegram OK')
import scheduler
print('scheduler OK')
from api import register_blueprints
print('api OK')
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if r.rule.startswith('/api')]
print(f'API routes: {len(rules)}')
print('All imports successful!')
"
```

Expected: All imports succeed, 41 tools, 4 agents, ~55 API routes

- [ ] **Step 3: Verify line counts improved**

```bash
cd /Users/mj/code/Shams && echo "=== Before ===" && echo "claude_client.py: 1217" && echo "dashboard_api.py: 2053" && echo "app.py: 914" && echo "memory.py: 859" && echo "" && echo "=== After ===" && wc -l claude_client.py app.py memory.py db.py telegram.py scheduler.py tools/*.py api/*.py agents/registry.py 2>/dev/null | tail -1
```

- [ ] **Step 4: Clean up any remaining references to old code**

Search for any imports of the deleted files:

```bash
cd /Users/mj/code/Shams && grep -r "from dashboard_api\|import dashboard_api\|from group_chat\|import group_chat" --include="*.py" .
```

Fix any remaining references found.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: cleanup — remove stale imports, verify all modules load"
```

- [ ] **Step 6: Tag the overhaul**

```bash
git tag -a shams-v2-overhaul -m "Shams v2 Sub-project A: codebase overhaul — tool registry, 4 agents, connection pool, split monoliths, tests"
```

---

## Route summary (unchanged — all routes preserved)

All ~55 existing API routes are preserved across the 14 `api/` modules. The only behavioral change is `/api/group-chat` POST, which now routes through Shams instead of parallel agent dispatch.

## What's next

After this overhaul deploys and stabilizes:
- **Sub-project B:** Overnight ops + morning standup (3am loop, 7am interactive Telegram)
- **Sub-project C:** Revenue engines (deal flow, inventory, pricing, winback)
- **Sub-project D:** P&L attribution layer
