# Shams v2 — Sub-project A: Codebase Overhaul Design

> Prerequisite for all Shams v2 work. Restructure the monolithic codebase into focused modules, add a tool registry, simplify the agent system, slim the prompt, add connection pooling, and establish a test harness.

## Context

Shams is MJ's AI chief of staff — a Flask/Python app on Railway with Telegram as the primary interface and a React dashboard. The codebase has grown to 7,320 lines across 18 Python files, with three monoliths (`dashboard_api.py` 2,053 / `claude_client.py` 1,217 / `app.py` 914) that are tangled and hard to extend.

Shams v2 will transform from a reactive chatbot into an autonomous revenue engine. This overhaul creates the clean foundation for:
- **Sub-project B:** Overnight ops + morning standup
- **Sub-project C:** Revenue engines (deal flow, inventory, pricing, winback)
- **Sub-project D:** P&L attribution layer

### Current State

- 44 Claude tools in a single if/elif dispatch chain
- 88 dashboard API endpoints in one flat file
- 6 agents (Shams, Rumi, Leo, Wakil, Scout, Builder) with parallel War Room dispatch
- ~60 memory functions with no connection pooling (new psycopg2.connect() per call)
- System prompt ~4,000 tokens, loaded at import time with 3 baked-in knowledge files
- Zero tests

---

## 1. File Structure

Split the 3 monoliths into focused modules. Every file should have one clear purpose.

### app.py (914 lines) splits into:

| New file | Responsibility | Approximate size |
|----------|---------------|-----------------|
| `app.py` | Flask init, static serving, `/health`, startup | ~150 lines |
| `telegram.py` | Message handling, callback queries, voice/photo/doc processing | ~400 lines |
| `scheduler.py` | APScheduler setup, job registration, dynamic task loading | ~200 lines |

### claude_client.py (1,217 lines) splits into:

| New file | Responsibility |
|----------|---------------|
| `claude_client.py` | Chat loop, prompt assembly, hot context injection, agent routing | ~200 lines |
| `tools/registry.py` | Tool decorator, auto-discovery, scoped tool lists, dispatch | ~100 lines |
| `tools/web.py` | web_search, fetch_url |
| `tools/mercury.py` | 5 Mercury banking tools |
| `tools/rumi.py` | 7 Rumi/QCC ops tools |
| `tools/leo.py` | Leo health tools |
| `tools/google.py` | Email triage, search, read, calendar |
| `tools/github.py` | Codebase read, propose_code_change |
| `tools/docuseal.py` | Signature tools |
| `tools/media.py` | add_media (Radarr/Sonarr bridge) |
| `tools/memory_tools.py` | remember, add/close_open_loop, log_decision |
| `tools/missions.py` | Mission CRUD, workflows, schedule_task |
| `tools/actions.py` | propose_action, route_to_agent |
| `tools/deals.py` | Deal CRUD |

All 44 tools preserved, just reorganized by domain.

### dashboard_api.py (2,053 lines) splits into:

| New file | Responsibility |
|----------|---------------|
| `api/__init__.py` | Blueprint registration |
| `api/auth.py` | Login, magic link, sessions |
| `api/chat.py` | Chat, conversations |
| `api/projects.py` | Projects, missions, kanban, timeline |
| `api/agents.py` | Agent status, activity feed |
| `api/mercury.py` | Mercury banking endpoints |
| `api/integrations.py` | Google OAuth, connected accounts |
| `api/actions.py` | Actions approve/reject/execute |
| `api/inbox.py` | Email scan, archive, star, draft, batch |
| `api/files.py` | Folders, files, search |
| `api/briefings.py` | Briefings, loops, decisions, memory |
| `api/settings.py` | Trust scores, alert rules, scheduled tasks, notifications |

### memory.py (859 lines) splits into:

| New file | Responsibility |
|----------|---------------|
| `db.py` | Connection pool, context manager, query helpers |
| `memory.py` | Conversations, memories, open loops, decisions (~200 lines) |

The ~60 functions stay grouped by table, all switching to the pooled connection from `db.py`. Further splits into `models/` can happen as Sub-projects B-D add tables.

---

## 2. Agent System

### 4 agents (down from 6)

| Agent | Role | Absorbs |
|-------|------|---------|
| **Shams** | Chief of staff, orchestrator, daily driver | — |
| **Ops** | QCC operations, research, code | Rumi (persona), Scout, Builder |
| **Wakil** | Legal, deals, contracts, document drafting | — |
| **Leo** | Health coaching, food intake accountability | — |

### Routing model

Shams is the only agent the user talks to. No more War Room parallel dispatch.

```
User message → Shams (always)
  ├── needs QCC data? → loads Ops tools + context, calls Rumi API
  ├── needs legal?    → loads Wakil persona + context
  ├── needs health?   → loads Leo persona + context
  └── otherwise       → handles directly
```

Routing is a tool: `route_to_specialist(agent, query)`. Shams decides when to invoke it based on message content. When invoked, a separate Claude API call is made with the specialist's persona + scoped tools. The specialist's response is returned to Shams as a tool result, and Shams synthesizes it into its own voice before replying to the user. This keeps specialist reasoning isolated while maintaining one coherent voice.

### Agent registry

```python
AGENTS = {
    "shams": {"persona": "context/shams.md", "tools": ["*"]},
    "ops":   {"persona": "context/ops.md",   "tools": ["rumi", "research", "github", "inventory"]},
    "wakil": {"persona": "context/wakil.md", "tools": ["docuseal", "deals", "legal_draft"]},
    "leo":   {"persona": "context/leo.md",   "tools": ["health_log", "food_tracking"]},
}
```

Each agent has a slim persona file (~200 tokens) and knowledge files, loaded on demand (not at import time).

### What gets deleted

- `group_chat.py` — removed entirely
- War Room parallel dispatch — gone
- `agents/codebase.py` — folded into `tools/github.py`
- Individual persona files for Scout, Builder, Rumi — consolidated into Ops persona

---

## 3. System Prompt + Context Injection

### Core prompt (~500 tokens)

Identity, tone, available tools, routing instructions. Static, never changes.

### Hot context block (~500-1,000 tokens, rotates by time of day)

| Time window | Hot context |
|-------------|------------|
| Overnight (3am loop) | Cash balances, pending deadlines, open loops, overnight emails |
| Morning standup (7am) | Overnight results, today's calendar, pending actions, P&L snapshot |
| Daytime (on-demand) | Recent conversation summary, active missions, last few actions |
| Evening briefing | Day's P&L, completed actions, tomorrow's calendar, open items |

### Lazy-load via tool

`recall_context(query)` — fetches relevant memories, knowledge, and history on demand. No more baking 3 knowledge files into every call.

### Token budget per call

| Component | Tokens |
|-----------|--------|
| Core prompt | ~500 |
| Hot context | ~500-1,000 |
| Conversation history | ~2,000 |
| Tool results | variable |
| **Total base** | **~3,000-3,500** (down from ~8,000+) |

---

## 4. Tool Registry

### Decorator-based registration

```python
# tools/mercury.py
from tools.registry import tool

@tool(
    name="check_mercury_balance",
    description="Check balance across Mercury bank accounts",
    agent="ops",
    schema={
        "properties": {
            "account": {
                "type": "string",
                "enum": ["clifton", "plainfield", "personal", "coinbits"]
            }
        }
    }
)
def check_mercury_balance(account: str) -> dict:
    return mercury_client.get_balance(account)
```

### Registry API

- `registry.get_tools(agent=None)` — returns tool definitions. No agent = all tools (for Shams). With agent = scoped subset.
- `registry.execute(name, params)` — dispatches to the decorated handler. Replaces the 44-branch if/elif chain.
- Auto-discovery at startup: imports all `tools/*.py` modules, collects decorated functions.

### Tool count

All 44 current tools preserved, reorganized into ~13 domain files. No pruning in this sub-project.

---

## 5. Database + Connection Pooling

### New: db.py

```python
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

pool = ThreadedConnectionPool(minconn=2, maxconn=10, dsn=DATABASE_URL)

@contextmanager
def get_conn():
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
```

### Migration path

All ~60 memory functions switch from `_conn()` (new connection per call) to `with get_conn() as conn:`. Schema stays the same — 20 existing tables unchanged. New tables come in Sub-projects B-D.

---

## 6. Tests

### Scope: core paths only

| Area | What's tested |
|------|--------------|
| Tool registry | Tools register via decorator, auto-discover, dispatch correctly |
| Agent routing | Shams routes to correct specialist based on message content |
| Context assembly | Hot context block builds correctly per time slot |
| Action lifecycle | propose → approve → execute → log |
| Memory CRUD | Read/write for conversations, memories, loops, decisions |
| Connection pool | Acquire, release, rollback on error |

### Not tested (yet)

Individual tool implementations that hit external services (Mercury API, Rumi API, Gmail, etc.) — those are integration tests for later.

### Setup

- pytest with fixtures for test database and mock Claude responses
- Target: ~40-50 tests covering structural wiring
- No coverage targets — just confidence the overhaul didn't break things

---

## 7. What Doesn't Change

- **Flask framework** — stays
- **psycopg2** — stays (with pooling added)
- **Telegram as primary interface** — stays
- **Dashboard** — stays as-is, revisited later after Telegram UX is nailed
- **All 44 tools** — preserved, just reorganized
- **All 20 database tables** — untouched
- **All external integrations** — Mercury, Rumi, Leo, Google, GitHub, DocuSeal, media bridge
- **Deploy model** — git push → Railway auto-deploy

---

## 8. Shams v2 Full Roadmap (for reference)

| Sub-project | Scope | Depends on |
|-------------|-------|-----------|
| **A: Codebase Overhaul** (this spec) | Split monoliths, tool registry, agent system, prompt slim, pooling, tests | — |
| **B: Overnight Ops + Morning Standup** | 3am autonomous loop, 7am interactive Telegram standup with one-tap actions | A |
| **C: Revenue Engines** | Deal flow, inventory intelligence, competitive pricing, customer winback | A, B |
| **D: P&L Attribution Layer** | Dollar-value tagging on every action, weekly self-review, ROI tracking | A, B, C |
