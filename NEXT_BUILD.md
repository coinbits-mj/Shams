# Shams Next Build Plan
*Written March 31, 2026 — pick up from here in a fresh Claude Code session*

## CONTEXT

Read these files first:
- `SHAMS_CONTEXT.md` — original build context
- `context/shams_platform_spec.md` — full technical spec
- All files in `context/` — agent personas and knowledge base
- `agents/registry.py` — agent framework
- `agents/codebase.py` — codebase tools
- `dashboard_api.py` — all API endpoints
- `claude_client.py` — 24 tools, tool use loop
- `group_chat.py` — War Room (parallel agent responses)
- `app.py` — Flask + Telegram + scheduler

## WHAT'S BUILT AND WORKING

- Shams on Telegram (@myshams_bot) + Railway (24/7)
- Web dashboard at shams-production.up.railway.app (app.myshams.ai pending)
- 6 agents: Shams, Rumi, Leo, Wakil, Scout, Builder
- War Room group chat (all agents respond in parallel)
- 24 Claude tools (web search, Mercury x4, Rumi, Leo, memory, codebase read)
- Google OAuth connected (3 accounts: personal, coinbits, qcc)
- Email triage (Inbox as Shams skill) with agent routing
- Mission queue (kanban) — UI built but missions are manual only
- Activity feed — exists but not populated by agent actions
- Magic link auth via Resend (shams@myshams.ai)
- 12 Postgres tables on shared Railway instance

## WHAT NEEDS BUILDING

### 1. AGENT ACTION FRAMEWORK (highest priority — everything depends on this)

Every agent action must go through a pipeline:

```
Agent proposes action → saved to shams_actions table →
  status: "pending_approval" → shown in dashboard →
  Maher approves/rejects → agent executes →
  result saved → status: "completed"
```

**New table: `shams_actions`**
```sql
CREATE TABLE shams_actions (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL,
    action_type     VARCHAR(50) NOT NULL,  -- 'archive_email', 'create_pr', 'send_message', 'research', 'draft_document'
    title           VARCHAR(500) NOT NULL,
    description     TEXT DEFAULT '',
    payload         JSONB DEFAULT '{}',     -- action-specific data (email IDs, code diff, etc.)
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'executing', 'completed', 'failed')),
    result          TEXT DEFAULT '',
    mission_id      INTEGER REFERENCES shams_missions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
```

**Dashboard: Actions page**
- List of pending actions grouped by agent
- One-click approve/reject
- Batch approve ("approve all P4 archives")
- Completed actions log
- Trust level indicator per agent (how many actions approved vs rejected)

**Claude tool: `propose_action`**
- Every agent gets this tool
- Instead of executing directly, they propose and wait for approval
- For trusted actions (based on history), auto-approve

### 2. AGENTS CREATE AND MANAGE MISSIONS AUTONOMOUSLY

Right now missions are created manually. Agents need to:

**a) Auto-create missions from conversations**
- When Shams detects a task in Telegram/War Room chat, create a mission
- Assign to the right agent based on domain
- Log to activity feed

**b) Agents update their own mission status**
- When an agent starts working on something → status: "active"
- When blocked or needs input → status: "review"
- When done → status: "done" with result

**c) Mission lifecycle in dashboard**
- Real-time updates (poll every 10 seconds)
- Click a mission to see full history: who created it, what actions were taken, result
- Filter by agent, priority, status

**Implementation:**
- Add `create_mission` and `update_mission` tools to every agent in `claude_client.py`
- Modify `group_chat.py` so agents can create missions from War Room conversations
- Add mission detail view in frontend

### 3. LIVE AGENT ACTIVITY IN DASHBOARD

The activity feed exists but is barely populated. Every agent action needs to log:

**What to log:**
- Tool calls (Shams searched web, Rumi pulled P&L)
- Mission status changes
- Action proposals (pending approval)
- Action completions
- Errors
- Inbox triage results
- Briefing deliveries

**Where to log:**
- `memory.log_activity(agent_name, event_type, content, metadata)`
- Already exists — just need to call it from every tool execution in `claude_client.py`

**Dashboard updates:**
- Activity feed on Mission Control page already shows this
- Add filtering by agent, by event type
- Add sound/visual notification for P1 items
- Auto-scroll to latest

### 4. INBOX DEEP SCAN + ONGOING TRIAGE

**Phase 1: Deep scan (one-time)**
Build a `/api/inbox/scan` endpoint that:
1. Pulls up to 50 unread from each of the 3 accounts (150 total)
2. Runs Inbox triage on all of them
3. Saves results to a new `shams_email_triage` table:
   ```sql
   CREATE TABLE shams_email_triage (
       id              SERIAL PRIMARY KEY,
       account         VARCHAR(50) NOT NULL,
       message_id      VARCHAR(200) NOT NULL UNIQUE,
       from_addr       TEXT,
       subject         TEXT,
       snippet         TEXT,
       priority        VARCHAR(5),  -- P1, P2, P3, P4
       routed_to       TEXT[],      -- ['shams', 'wakil']
       action          TEXT,        -- recommended action
       draft_reply     TEXT,
       archived        BOOLEAN DEFAULT FALSE,
       triaged_at      TIMESTAMPTZ DEFAULT NOW()
   );
   ```
4. Shows results in dashboard: Inbox page with P1/P2/P3/P4 tabs
5. Batch archive button for P4
6. "Send draft" button for P1/P2 (proposes action, needs approval)

**Phase 2: Auto-archive with approval**
- P4 emails → Inbox proposes "Archive 47 promotional emails" as an action
- Maher approves → Gmail API marks as read/archives
- Need to add Gmail modify scope to OAuth

**Phase 3: Scheduled triage**
- Add APScheduler job: every 30 min, scan for new unread
- P1 → send Telegram notification immediately
- P2 → queue for next briefing
- P3/P4 → auto-archive (once trust is established)

### 5. BUILDER: GITHUB PR CREATION (Phase 2 from original plan)

**Add GitHub tools to Builder agent:**
- `create_github_branch` — create a branch from main
- `write_file_to_github` — commit a file change
- `create_pull_request` — open a PR with title + description

**Implementation:**
- Use `gh` CLI or GitHub REST API via requests
- Every code change goes through the action framework (propose PR → approve → create)
- PR link shown in dashboard

**Add to `claude_client.py` tools:**
```python
{
    "name": "propose_code_change",
    "description": "Propose a code change to a repo. Creates a GitHub PR for Maher to review.",
    "input_schema": {
        "properties": {
            "repo": {"type": "string", "enum": ["shams", "rumi", "leo"]},
            "description": {"type": "string"},
            "files": {"type": "array", "items": {"type": "object", "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            }}}
        }
    }
}
```

**GitHub token:** Need a `GITHUB_TOKEN` env var with repo scope. MJ needs to create a Personal Access Token at github.com/settings/tokens.

### 6. SCOUT: AUTONOMOUS RESEARCH (finish Phase 3)

Scout currently has a persona but no tools in the War Room. Add:

**a) Give Scout web search in group chat**
- Modify `group_chat.py` to give Scout access to web_search and fetch_url tools
- When someone asks a market question, Scout actually searches instead of guessing

**b) Scheduled research missions**
- Add to APScheduler: daily at 7am, Scout runs a research sweep
- Queries: "specialty coffee roasters restructuring NJ", "commercial real estate Somerville NJ", "coffee industry M&A 2026"
- Results saved as missions with findings
- P1 findings → Telegram notification

**c) Research tool in claude_client.py**
```python
{
    "name": "assign_research",
    "description": "Assign a research task to Scout. Scout will search the web, compile findings, and report back.",
    "input_schema": {
        "properties": {
            "query": {"type": "string"},
            "depth": {"type": "string", "enum": ["quick", "deep"]},
            "deadline": {"type": "string"}
        }
    }
}
```

### 7. WAKIL DOCUMENT DRAFTING

Wakil can advise but can't draft documents. Add:

**a) Document generation tool**
- `draft_legal_document` tool — generates LOI, counter-proposal, legal memo, NDA
- Output saved to `shams_files` table with type "legal_draft"
- Shown in Files page under a "Legal Drafts" folder

**b) Pre-built templates**
- LOI template (based on Red House structure)
- NDA template
- Revenue-based financing term sheet
- Employment offer/restructuring letter

**c) Contract review tool**
- Upload a PDF via Telegram or dashboard
- Wakil reviews, flags risks, suggests changes
- Already works via document upload — just needs Wakil-specific prompting

### 8. TRUST SYSTEM

The automation unlock. Track per-agent trust:

```sql
CREATE TABLE shams_trust_scores (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL,
    total_proposed  INTEGER DEFAULT 0,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

**Logic:**
- < 10 actions: everything needs approval
- 10+ actions with > 90% approval rate: suggest auto-approve
- Maher toggles auto-approve per agent in Settings
- Auto-approved actions still logged and visible
- Any rejection resets trust for that action type

### 9. DASHBOARD IMPROVEMENTS

**a) Settings page**
- Trust levels per agent (toggle auto-approve)
- Briefing schedule (change morning/evening times)
- Notification preferences (which P levels trigger Telegram)
- Connected accounts overview

**b) Mission detail view**
- Click a mission → see full timeline: created → assigned → active → review → done
- All actions taken, all activity feed entries
- Result/output

**c) Agent detail view**
- Click an agent → see their missions, actions, trust score, recent activity
- Health check status
- Configuration

**d) Inbox page (new)**
- Triaged emails grouped by priority
- Filter by account, by routed agent
- Batch actions (archive, snooze, delegate)
- Draft reply editor

### 10. SCHEDULED AUTOMATION

Add these APScheduler jobs:

| Job | Schedule | What it does |
|-----|----------|-------------|
| `inbox_triage` | Every 30 min | Scan for new unread, triage, notify P1 |
| `scout_daily_sweep` | 7:00 AM ET | Research acquisition targets, real estate, competitors |
| `agent_health_check` | Every 5 min | Ping Rumi + Leo health endpoints, update agent status |
| `trust_score_update` | Daily | Recalculate trust scores from action history |
| `mission_stale_check` | Daily | Flag missions stuck in "active" for > 48 hours |

## BUILD ORDER (recommended)

1. **Agent action framework + table** — everything depends on this
2. **Log all tool calls to activity feed** — makes dashboard come alive
3. **Auto-mission creation from conversations** — agents manage their own work
4. **Inbox deep scan + email triage table** — first real autonomous workflow
5. **GitHub PR creation for Builder** — code changes with approval
6. **Scout web search in War Room** — research becomes real
7. **Trust system** — path to automation
8. **Wakil document drafting** — legal deliverables
9. **Scheduled automation jobs** — agents work while Maher sleeps
10. **Dashboard improvements** — Settings, Inbox page, detail views

## ENVIRONMENT NOTES

- Railway project: aware-strength (Shams + Rumi + Postgres)
- Leo is separate Railway project: leo-health-coach
- Railway CLI: `/Users/mj/.local/bin/railway`
- Logged in as: maher@coinbits.app
- GitHub: coinbits-mj (repos: Shams, coffee-pl-bot, leo-health-coach)
- Frontend: React + Vite + Tailwind, build with `cd frontend && npm run build`
- Deploy: push to GitHub → Railway auto-deploys
- Python 3.9 locally (use `from __future__ import annotations`)
- Dockerfile uses Python 3.11 on Railway

## KEY DESIGN PRINCIPLES

1. **Approval before action** — agents propose, Maher approves. Always.
2. **Everything visible** — every tool call, every action, every mission update shows in the dashboard
3. **Trust compounds** — approval history unlocks automation gradually
4. **No duplicate work** — Inbox triages once, routes to specialists
5. **Agents stay in their lane** — Wakil does legal, Rumi does ops, no overlap
6. **Human-readable** — every agent output is written for Maher, not for machines
