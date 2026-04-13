# Shams v2 Sub-project B: Overnight Ops + Morning Standup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 3am autonomous overnight loop that sweeps email, checks financials/ops, scans calendar, and catches forgotten items — then delivers a 7am interactive morning standup via Telegram with drip-fed action items and one-tap buttons.

**Architecture:** A new `standup.py` module replaces `briefing.py` with two main functions: `run_overnight_loop()` (data gathering + autonomous actions at 3am) and `deliver_morning_standup()` (Telegram delivery at 7am). Overnight results are stored in a new `shams_overnight_runs` table as structured JSONB. The standup is a stateful flow tracked via `shams_memory` key-value store. Email triage is simplified from P1-P4 to Reply/Read/Archive tiers.

**Tech Stack:** Python 3.9+ (use `from __future__ import annotations`), PostgreSQL, APScheduler, Anthropic Claude API, Telegram Bot API, Gmail API (modify scope)

**Spec:** `docs/superpowers/specs/2026-04-12-shams-v2-overnight-ops-standup-design.md`

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `standup.py` | Overnight loop (5 steps) + morning standup delivery (overview + drip-feed) | **Create** |
| `config.py` | Add `OVERNIGHT_HOUR_UTC`, `STANDUP_HOUR_UTC` | Modify |
| `schema.sql` | Add `shams_overnight_runs` table, migrate email triage to tier | Modify |
| `memory.py` | Add overnight run CRUD + standup state helpers | Modify |
| `tools/google.py` | Update triage to Reply/Read/Archive tiers | Modify |
| `scheduler.py` | Wire overnight + standup jobs, retire morning briefing | Modify |
| `telegram.py` | Add standup callback handlers + edit state | Modify |
| `claude_client.py` | Enrich overnight hot context slot | Modify |
| `tests/test_standup.py` | Tests for standup state machine, overnight run CRUD, tier classification | **Create** |

---

### Task 1: Config + Schema — Add overnight/standup config and DB table

**Files:**
- Modify: `config.py:67-69`
- Modify: `schema.sql:160-176` (email triage table)
- Modify: `schema.sql` (end of file — add overnight_runs table)

- [ ] **Step 1: Write the test for config values**

Create `tests/test_standup.py`:

```python
"""Tests for overnight ops + morning standup."""
from __future__ import annotations


def test_config_has_overnight_and_standup_hours():
    import config
    assert hasattr(config, "OVERNIGHT_HOUR_UTC")
    assert hasattr(config, "STANDUP_HOUR_UTC")
    assert isinstance(config.OVERNIGHT_HOUR_UTC, int)
    assert isinstance(config.STANDUP_HOUR_UTC, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_config_has_overnight_and_standup_hours -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'OVERNIGHT_HOUR_UTC'`

- [ ] **Step 3: Add config values**

In `config.py`, replace lines 67-69:

```python
# Scheduling
BRIEFING_HOUR_UTC = int(os.environ.get("BRIEFING_HOUR_UTC", "11"))  # 6am ET
EVENING_HOUR_UTC = int(os.environ.get("EVENING_HOUR_UTC", "1"))     # 8pm ET
```

With:

```python
# Scheduling
BRIEFING_HOUR_UTC = int(os.environ.get("BRIEFING_HOUR_UTC", "11"))  # 6am ET — legacy, used by evening briefing
EVENING_HOUR_UTC = int(os.environ.get("EVENING_HOUR_UTC", "1"))     # 8pm ET
OVERNIGHT_HOUR_UTC = int(os.environ.get("OVERNIGHT_HOUR_UTC", "7"))  # 3am ET
STANDUP_HOUR_UTC = int(os.environ.get("STANDUP_HOUR_UTC", "11"))     # 7am ET
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_config_has_overnight_and_standup_hours -v`
Expected: PASS

- [ ] **Step 5: Add overnight_runs table to schema.sql**

Append to `schema.sql` (after the `shams_group_chat` index):

```sql
CREATE TABLE IF NOT EXISTS shams_overnight_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      VARCHAR(20) DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    results     JSONB DEFAULT '{}',
    summary     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_overnight_runs_started ON shams_overnight_runs (started_at DESC);
```

- [ ] **Step 6: Add email triage tier migration to schema.sql**

Append to `schema.sql`:

```sql
-- Migrate email triage from P1-P4 priority to Reply/Read/Archive tiers
DO $$ BEGIN
    ALTER TABLE shams_email_triage ADD COLUMN tier VARCHAR(10) DEFAULT 'archive'
        CHECK (tier IN ('reply', 'read', 'archive'));
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_email_triage_tier ON shams_email_triage (tier);
```

Note: We keep the `priority` column for backward compatibility with existing data. New code writes to `tier`, old data retains `priority`. The `get_notification_counts()` function in `memory.py` references `priority` — we'll update it in Task 3.

- [ ] **Step 7: Commit**

```bash
git add config.py schema.sql tests/test_standup.py
git commit -m "feat: add overnight/standup config + overnight_runs table + email tier column"
```

---

### Task 2: Memory Layer — Overnight run CRUD + standup state

**Files:**
- Modify: `memory.py` (append new functions at end)
- Modify: `tests/test_standup.py` (add tests)

- [ ] **Step 1: Write tests for overnight run CRUD and standup state**

Append to `tests/test_standup.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py -v -k "overnight or standup_state"`
Expected: FAIL — `AttributeError: module 'memory' has no attribute 'create_overnight_run'`

- [ ] **Step 3: Add overnight run CRUD and standup state functions to memory.py**

Append to the end of `memory.py`:

```python
# ── Overnight Runs ─────────────────────────────────────────────────────────

def create_overnight_run() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}overnight_runs (status) VALUES ('running') RETURNING id"
        )
        return cur.fetchone()[0]


def update_overnight_run(run_id: int, status: str = "completed",
                         results: dict | None = None, summary: str = ""):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}overnight_runs SET status = %s, results = %s, summary = %s, "
            f"finished_at = NOW() WHERE id = %s",
            (status, json.dumps(results or {}), summary, run_id),
        )


def get_latest_overnight_run() -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}overnight_runs ORDER BY started_at DESC LIMIT 1"
        )
        return cur.fetchone()


# ── Standup State ──────────────────────────────────────────────────────────

def get_standup_state() -> dict | None:
    raw = recall("standup_state")
    if not raw:
        return None
    return json.loads(raw)


def set_standup_state(state: dict):
    remember("standup_state", json.dumps(state))


def clear_standup_state():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {P}memory WHERE key = 'standup_state'")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py -v -k "overnight or standup_state"`
Expected: PASS (or skip if no DATABASE_URL)

- [ ] **Step 5: Commit**

```bash
git add memory.py tests/test_standup.py
git commit -m "feat: add overnight run CRUD + standup state to memory layer"
```

---

### Task 3: Update memory.py notification counts for tier

**Files:**
- Modify: `memory.py:366-380` (`get_notification_counts`)
- Modify: `memory.py:385-401` (`save_triage_result`)
- Modify: `memory.py:403-423` (`get_triaged_emails`)

- [ ] **Step 1: Update `get_notification_counts` to use tier instead of priority**

In `memory.py`, replace this line inside `get_notification_counts()`:

```python
        cur.execute(
            f"SELECT COUNT(*) FROM {P}email_triage WHERE priority IN ('P1','P2') AND archived = FALSE"
        )
        inbox_urgent = cur.fetchone()[0]
```

With:

```python
        cur.execute(
            f"SELECT COUNT(*) FROM {P}email_triage WHERE tier = 'reply' AND archived = FALSE"
        )
        inbox_urgent = cur.fetchone()[0]
```

- [ ] **Step 2: Update `save_triage_result` to accept tier**

In `memory.py`, replace the `save_triage_result` function:

```python
def save_triage_result(account: str, message_id: str, from_addr: str, subject: str,
                       snippet: str, tier: str = "archive", priority: str = "",
                       routed_to: list | None = None,
                       action: str = "", draft_reply: str = "") -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}email_triage (account, message_id, from_addr, subject, snippet, "
            f"tier, priority, routed_to, action, draft_reply) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT (message_id) DO UPDATE SET "
            f"tier = EXCLUDED.tier, priority = EXCLUDED.priority, routed_to = EXCLUDED.routed_to, "
            f"action = EXCLUDED.action, draft_reply = EXCLUDED.draft_reply, triaged_at = NOW() "
            f"RETURNING id",
            (account, message_id, from_addr, subject, snippet, tier, priority,
             routed_to or [], action, draft_reply),
        )
        return cur.fetchone()[0]
```

- [ ] **Step 3: Update `get_triaged_emails` to support tier filtering**

In `memory.py`, replace the `get_triaged_emails` function:

```python
def get_triaged_emails(tier: str | None = None, priority: str | None = None,
                       account: str | None = None,
                       archived: bool | None = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        conditions, params = [], []
        if tier:
            conditions.append("tier = %s")
            params.append(tier)
        if priority:
            conditions.append("priority = %s")
            params.append(priority)
        if account:
            conditions.append("account = %s")
            params.append(account)
        if archived is not None:
            conditions.append("archived = %s")
            params.append(archived)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        cur.execute(
            f"SELECT * FROM {P}email_triage {where} "
            f"ORDER BY CASE tier WHEN 'reply' THEN 0 WHEN 'read' THEN 1 ELSE 2 END, "
            f"triaged_at DESC LIMIT %s", params
        )
        return cur.fetchall()
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add memory.py
git commit -m "feat: update email triage functions for Reply/Read/Archive tier system"
```

---

### Task 4: Update email triage tool for Reply/Read/Archive tiers

**Files:**
- Modify: `tools/google.py:7-52` (triage_inbox tool)
- Modify: `scheduler.py:117-226` (scheduled_inbox_triage)

- [ ] **Step 1: Write test for tier classification**

Append to `tests/test_standup.py`:

```python
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
    # Parse blocks the same way scheduled_inbox_triage does
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
```

- [ ] **Step 2: Run test to verify it passes (it's a parsing test)**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_triage_tier_parsing -v`
Expected: PASS

- [ ] **Step 3: Update `tools/google.py` triage_inbox tool**

Replace the entire `triage_inbox` function in `tools/google.py`:

```python
@tool(
    name="triage_inbox",
    description="Triage Maher's email inbox. Fetches unread emails, classifies as Reply (needs response — draft included), Read (FYI, no action), or Archive (auto-archived). Use when Maher asks about email, inbox, or 'what needs my attention'.",
    schema={
        "properties": {
            "max_emails": {"type": "integer", "description": "How many unread emails to process (default 10)", "default": 10}
        },
    },
)
def triage_inbox(max_emails: int = 10) -> str:
    import pathlib
    import anthropic
    import google_client
    import memory
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

    emails = google_client.get_unread_emails(max_emails)
    if not emails:
        return "No unread emails (or Gmail not connected — check Integrations page)."

    context_dir = pathlib.Path(__file__).parent.parent / "context"
    inbox_persona_path = context_dir / "inbox_persona.md"
    inbox_persona = inbox_persona_path.read_text() if inbox_persona_path.exists() else ""

    email_text = "\n\n".join(
        f"Account: {e.get('account', 'unknown')} ({e.get('account_email', '')})\nFrom: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
        for e in emails
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    triage_prompt = (
        f"Triage these {len(emails)} emails into three tiers:\n\n"
        f"REPLY — Sender is a real person or business contact, email asks a question or "
        f"requests something, or is time-sensitive. Draft a reply in Maher's voice (direct, concise, professional).\n"
        f"READ — Informational from a known source (bank alerts, service notifications with useful info). "
        f"No reply needed but Maher should see it.\n"
        f"ARCHIVE — Promotional, marketing, automated notifications with no useful info, spam, "
        f"newsletters Maher doesn't read.\n\n"
        f"For EACH email, respond in this exact format:\n"
        f"MESSAGE_ID: <id>\nTIER: reply|read|archive\nSUMMARY: one-line\nACTION: recommended action\nDRAFT: reply text or NONE\n---\n\n"
        f"Emails:\n\n{email_text}"
    )

    triage_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=inbox_persona if inbox_persona else "Triage emails by tier: Reply, Read, or Archive.",
        messages=[{"role": "user", "content": triage_prompt}],
    )
    result = triage_response.content[0].text

    # Route triaged emails to agent queues in memory
    for agent in ["wakil", "rumi", "leo", "scout"]:
        if agent in result.lower():
            lines = [l for l in result.split("\n") if agent in l.lower()]
            if lines:
                memory.remember(f"inbox_{agent}_queue", "\n".join(lines[:5]))

    return result
```

- [ ] **Step 4: Update `scheduled_inbox_triage` in `scheduler.py`**

Replace the triage prompt and parsing section in `scheduled_inbox_triage()` (lines 152-205 in `scheduler.py`). Replace from `email_text = "\n\n---\n\n".join(` through the end of the `for block in result_text.split("---"):` loop (ending before the `# P1 -> immediate Telegram notification` comment):

```python
        email_text = "\n\n---\n\n".join(
            f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
            f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
            for e in new_emails[:20]
        )
        prompt = (
            f"Triage these {min(len(new_emails), 20)} emails into three tiers:\n\n"
            f"REPLY — Sender is a real person/contact, asks a question or is time-sensitive. Draft a reply.\n"
            f"READ — Informational from a known source. No reply needed but worth seeing.\n"
            f"ARCHIVE — Promotional, spam, automated notifications with no useful info.\n\n"
            f"For EACH email:\n"
            f"MESSAGE_ID: <id>\nTIER: reply|read|archive\nSUMMARY: one-line\nACTION: recommended action\nDRAFT: reply or NONE\n---\n\n"
            f"Emails:\n\n{email_text}"
        )

        response = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=4096,
            system=inbox_persona, messages=[{"role": "user", "content": prompt}],
        )
        result_text = response.content[0].text
        email_lookup = {e["message_id"]: e for e in new_emails}

        reply_emails = []
        for block in result_text.split("---"):
            block = block.strip()
            if not block:
                continue
            fields = {}
            for line in block.split("\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    fields[k.strip().upper()] = v.strip()

            msg_id = fields.get("MESSAGE_ID", "")
            email = email_lookup.get(msg_id)
            if not email:
                continue

            tier = fields.get("TIER", "archive").lower()
            if tier not in ("reply", "read", "archive"):
                tier = "archive"
            route_str = fields.get("ROUTE", "shams")
            routed_to = [r.strip() for r in route_str.split(",") if r.strip()]
            action = fields.get("ACTION", "")
            draft = fields.get("DRAFT", "")
            if draft.upper() == "NONE":
                draft = ""

            triage_id = memory.save_triage_result(
                account=email["account"], message_id=msg_id,
                from_addr=email["from"], subject=email["subject"],
                snippet=email["snippet"], tier=tier,
                routed_to=routed_to, action=action, draft_reply=draft,
            )

            if tier == "reply":
                reply_emails.append((triage_id, email, action, draft))

        # Reply tier -> immediate Telegram notification with action buttons
        if reply_emails and config.TELEGRAM_CHAT_ID:
            for triage_id, email, action, draft in reply_emails:
                msg = (
                    f"📬 REPLY NEEDED\n\n"
                    f"From: {email['from']}\n"
                    f"[{email['account']}] {email['subject']}\n\n"
                    f"Action: {action}"
                )
                buttons = [
                    {"text": "Archive", "callback_data": f"earchive:{triage_id}"},
                    {"text": "Star", "callback_data": f"estar:{triage_id}"},
                    {"text": "Snooze", "callback_data": f"esnooze:{triage_id}"},
                ]
                if draft:
                    buttons.insert(0, {"text": "Draft Reply", "callback_data": f"edraft:{triage_id}"})
                send_telegram_with_buttons(config.TELEGRAM_CHAT_ID, msg, buttons)
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/google.py scheduler.py tests/test_standup.py
git commit -m "feat: update email triage to Reply/Read/Archive tier system"
```

---

### Task 5: Create standup.py — Overnight Loop

**Files:**
- Create: `standup.py`

This is the core module. It replaces `briefing.py` and contains the overnight loop logic. The morning standup delivery (Task 6) and Telegram callbacks (Task 7) are separate tasks.

- [ ] **Step 1: Write test for overnight loop data gathering**

Append to `tests/test_standup.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_overnight_loop_structure -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'standup'`

- [ ] **Step 3: Create `standup.py` with overnight loop**

Create `standup.py`:

```python
"""Overnight ops loop + morning standup delivery.

Replaces briefing.py. Two entry points:
- run_overnight_loop(): 3am ET — autonomous data gathering + actions
- deliver_morning_standup(): 7am ET — Telegram delivery with drip-feed
"""
from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone

import anthropic

import config
import memory
import google_client
import mercury_client
import rumi_client
from telegram import send_telegram, send_telegram_with_buttons

logger = logging.getLogger(__name__)


# ── Overnight Loop ─────────────────────────────────────────────────────────


def run_overnight_loop() -> dict:
    """Run the full overnight ops loop. Called at 3am ET by scheduler.

    Steps:
    1. Email sweep — triage all accounts, auto-archive, draft replies
    2. Mercury balance check — pull balances, flag anomalies
    3. Rumi ops check — yesterday's P&L, inventory alerts
    4. Calendar scan — today's events, cross-ref missions, draft prep
    5. Forgetting check — stale missions, approaching deadlines, orphaned loops

    Returns structured results dict. Also saves to shams_overnight_runs.
    """
    run_id = memory.create_overnight_run()
    results = {
        "email": {"reply": [], "read": [], "archived": [], "archive_summary": ""},
        "mercury": {"balances": {}, "alerts": [], "recent_transactions": []},
        "rumi": {"revenue": 0, "cogs": 0, "margin": 0, "orders": 0, "alerts": [], "action_items": []},
        "calendar": {"events": [], "prep_briefs": [], "conflicts": []},
        "reminders": [],
    }
    status = "completed"

    # Step 1: Email sweep
    try:
        results["email"] = _step_email_sweep()
        memory.log_activity("shams", "overnight", "Email sweep complete", {
            "reply": len(results["email"]["reply"]),
            "read": len(results["email"]["read"]),
            "archived": len(results["email"]["archived"]),
        })
    except Exception as e:
        logger.error(f"Overnight email sweep failed: {e}", exc_info=True)
        results["email"]["error"] = str(e)
        status = "partial"

    # Step 2: Mercury balance check
    try:
        results["mercury"] = _step_mercury_check()
        memory.log_activity("shams", "overnight", "Mercury check complete", {
            "alerts": len(results["mercury"]["alerts"]),
        })
    except Exception as e:
        logger.error(f"Overnight Mercury check failed: {e}", exc_info=True)
        results["mercury"]["error"] = str(e)
        status = "partial"

    # Step 3: Rumi ops check
    try:
        results["rumi"] = _step_rumi_check()
        memory.log_activity("shams", "overnight", "Rumi ops check complete")
    except Exception as e:
        logger.error(f"Overnight Rumi check failed: {e}", exc_info=True)
        results["rumi"]["error"] = str(e)
        status = "partial"

    # Step 4: Calendar scan
    try:
        results["calendar"] = _step_calendar_scan()
        memory.log_activity("shams", "overnight", "Calendar scan complete", {
            "events": len(results["calendar"]["events"]),
            "prep_briefs": len(results["calendar"]["prep_briefs"]),
        })
    except Exception as e:
        logger.error(f"Overnight calendar scan failed: {e}", exc_info=True)
        results["calendar"]["error"] = str(e)
        status = "partial"

    # Step 5: Forgetting check
    try:
        results["reminders"] = _step_forgetting_check()
        memory.log_activity("shams", "overnight", "Forgetting check complete", {
            "reminders": len(results["reminders"]),
        })
    except Exception as e:
        logger.error(f"Overnight forgetting check failed: {e}", exc_info=True)
        status = "partial"

    # Save results
    summary = _build_overnight_summary(results)
    memory.update_overnight_run(run_id, status=status, results=results, summary=summary)
    memory.log_activity("shams", "overnight", f"Overnight loop {status}", {"run_id": run_id})

    return results


# ── Step implementations ───────────────────────────────────────────────────


def _step_email_sweep() -> dict:
    """Triage all accounts, auto-archive junk, draft replies."""
    all_emails = []
    for account_key in config.GOOGLE_ACCOUNTS:
        try:
            emails = google_client.get_unread_emails_for_account(account_key, 50)
            all_emails.extend(emails)
        except Exception as e:
            logger.error(f"Email fetch failed for {account_key}: {e}")

    if not all_emails:
        return {"reply": [], "read": [], "archived": [], "archive_summary": "No unread emails."}

    # Check which we've already triaged
    from config import DATABASE_URL
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        msg_ids = [e["message_id"] for e in all_emails]
        cur.execute("SELECT message_id FROM shams_email_triage WHERE message_id = ANY(%s)", (msg_ids,))
        already_triaged = {r[0] for r in cur.fetchall()}

    new_emails = [e for e in all_emails if e["message_id"] not in already_triaged]
    if not new_emails:
        return {"reply": [], "read": [], "archived": [], "archive_summary": "No new emails since last triage."}

    # Classify with Claude
    persona_path = pathlib.Path(__file__).parent / "context" / "inbox_persona.md"
    inbox_persona = persona_path.read_text() if persona_path.exists() else "Triage emails by tier."
    api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    email_text = "\n\n---\n\n".join(
        f"MESSAGE_ID: {e['message_id']}\nACCOUNT: {e['account']}\n"
        f"From: {e['from']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}\nDate: {e['date']}"
        for e in new_emails[:30]
    )
    prompt = (
        f"Triage these {min(len(new_emails), 30)} emails into three tiers:\n\n"
        f"REPLY — Sender is a real person/contact, asks a question or is time-sensitive. "
        f"Draft a reply in Maher's voice (direct, concise, professional).\n"
        f"READ — Informational from a known source. No reply needed but worth seeing.\n"
        f"ARCHIVE — Promotional, spam, automated notifications with no useful info.\n\n"
        f"For EACH email:\n"
        f"MESSAGE_ID: <id>\nTIER: reply|read|archive\nSUMMARY: one-line\nACTION: recommended action\nDRAFT: reply or NONE\n---\n\n"
        f"Emails:\n\n{email_text}"
    )

    response = api_client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=4096,
        system=inbox_persona, messages=[{"role": "user", "content": prompt}],
    )
    result_text = response.content[0].text
    email_lookup = {e["message_id"]: e for e in new_emails}

    reply_list, read_list, archived_list = [], [], []

    for block in result_text.split("---"):
        block = block.strip()
        if not block:
            continue
        fields = {}
        for line in block.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip().upper()] = v.strip()

        msg_id = fields.get("MESSAGE_ID", "")
        email = email_lookup.get(msg_id)
        if not email:
            continue

        tier = fields.get("TIER", "archive").lower()
        if tier not in ("reply", "read", "archive"):
            tier = "archive"
        action_text = fields.get("ACTION", "")
        draft = fields.get("DRAFT", "")
        summary_text = fields.get("SUMMARY", "")
        if draft.upper() == "NONE":
            draft = ""

        triage_id = memory.save_triage_result(
            account=email["account"], message_id=msg_id,
            from_addr=email["from"], subject=email["subject"],
            snippet=email["snippet"], tier=tier,
            routed_to=[], action=action_text, draft_reply=draft,
        )

        entry = {
            "triage_id": triage_id, "account": email["account"],
            "message_id": msg_id, "from": email["from"],
            "subject": email["subject"], "summary": summary_text,
            "draft": draft,
        }

        if tier == "reply":
            reply_list.append(entry)
        elif tier == "read":
            read_list.append(entry)
        else:
            # Auto-archive
            try:
                google_client.archive_email(email["account"], msg_id)
                google_client.mark_read(email["account"], msg_id)
                memory.mark_email_archived(triage_id)
            except Exception as e:
                logger.error(f"Auto-archive failed for {msg_id}: {e}")
            archived_list.append(entry)

    # Generate archive summary in Shams's words
    archive_summary = ""
    if archived_list:
        subjects = [a["subject"] for a in archived_list[:20]]
        summary_prompt = (
            f"Summarize what was auto-archived in one casual sentence. "
            f"Group by type (e.g., 'Shopify notifications', 'newsletters'). "
            f"Be specific about the sources.\n\nArchived subjects:\n"
            + "\n".join(f"- {s}" for s in subjects)
        )
        summary_resp = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=200,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        archive_summary = summary_resp.content[0].text

    return {
        "reply": reply_list,
        "read": read_list,
        "archived": archived_list,
        "archive_summary": archive_summary,
    }


def _step_mercury_check() -> dict:
    """Pull Mercury balances and flag anomalies."""
    balances_data = mercury_client.get_balances()
    if not balances_data:
        return {"balances": {}, "alerts": [], "recent_transactions": []}

    balances = {}
    alerts = []
    entities = balances_data.get("entities", [])
    for entity in entities:
        name = entity.get("name", "unknown").lower()
        balance = entity.get("balance", 0)
        balances[name] = balance
        if balance < 5000:
            alerts.append({
                "type": "low_balance",
                "account": name,
                "balance": balance,
                "message": f"{name} balance is ${balance:,.0f} (below $5,000)",
            })

    # Check recent transactions for large amounts
    recent = []
    try:
        txns = mercury_client.get_recent_transactions()
        if txns:
            for txn in txns[:10]:
                amount = abs(txn.get("amount", 0))
                if amount >= 5000:
                    alerts.append({
                        "type": "large_transaction",
                        "account": txn.get("account", ""),
                        "amount": txn.get("amount", 0),
                        "description": txn.get("description", ""),
                        "message": f"Large transaction: ${amount:,.0f} — {txn.get('description', '')}",
                    })
                recent.append(txn)
    except Exception as e:
        logger.error(f"Mercury transactions fetch failed: {e}")

    return {
        "balances": balances,
        "grand_total": balances_data.get("grand_total", sum(balances.values())),
        "alerts": alerts,
        "recent_transactions": recent,
    }


def _step_rumi_check() -> dict:
    """Pull yesterday's P&L, inventory alerts, action items from Rumi."""
    result = {
        "revenue": 0, "cogs": 0, "margin": 0, "orders": 0,
        "wholesale_orders": 0, "alerts": [], "action_items": [],
    }

    pl = rumi_client.get_daily_pl("yesterday")
    if pl:
        result["revenue"] = pl.get("revenue", 0)
        result["cogs"] = pl.get("cogs", 0)
        margin = pl.get("net_margin_pct", 0)
        result["margin"] = margin
        result["orders"] = pl.get("order_count", 0)
        result["wholesale_orders"] = pl.get("wholesale_count", 0)

    try:
        action_items = rumi_client.get_action_items()
        if action_items and action_items.get("items"):
            result["action_items"] = action_items["items"][:5]
    except Exception:
        pass

    try:
        inventory = rumi_client.get_inventory_alerts()
        if inventory:
            result["alerts"] = inventory if isinstance(inventory, list) else [inventory]
    except Exception:
        pass

    return result


def _step_calendar_scan() -> dict:
    """Pull today's events, cross-reference with missions, draft prep briefs."""
    events = google_client.get_todays_events()
    if not events:
        return {"events": [], "prep_briefs": [], "conflicts": []}

    formatted_events = []
    for e in events:
        start = e.get("start", "")
        # Extract time from ISO datetime
        if "T" in start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                start_display = dt.strftime("%-I:%M %p")
            except Exception:
                start_display = start
        else:
            start_display = start
        formatted_events.append({
            "summary": e.get("summary", ""),
            "start": start_display,
            "start_raw": e.get("start", ""),
            "end_raw": e.get("end", ""),
            "location": e.get("location", ""),
        })

    # Cross-reference with active missions and open loops
    missions = memory.get_missions(status="active")
    open_loops = memory.get_open_loops()

    prep_briefs = []
    if formatted_events and (missions or open_loops):
        api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        events_text = "\n".join(f"- {e['start']}: {e['summary']}" for e in formatted_events)
        missions_text = "\n".join(f"- [{m['id']}] {m['title']}: {m.get('description', '')[:100]}" for m in missions[:10])
        loops_text = "\n".join(f"- [{l['id']}] {l['title']}: {l.get('context', '')[:100]}" for l in open_loops[:10])

        prompt = (
            f"Today's calendar:\n{events_text}\n\n"
            f"Active missions:\n{missions_text or 'None'}\n\n"
            f"Open loops:\n{loops_text or 'None'}\n\n"
            f"For each meeting that relates to a mission or open loop, write a brief prep doc "
            f"(2-3 paragraphs: context, key points to discuss, what Maher should push for). "
            f"Also flag if any meeting needs prep that isn't covered by a mission.\n\n"
            f"Respond in this format for each meeting that needs prep:\n"
            f"EVENT: <event summary>\nBRIEF: <prep text>\n---"
        )
        response = api_client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content[0].text.split("---"):
            block = block.strip()
            if not block:
                continue
            fields = {}
            current_key = None
            for line in block.split("\n"):
                if line.startswith("EVENT:"):
                    fields["event"] = line[6:].strip()
                    current_key = "event"
                elif line.startswith("BRIEF:"):
                    fields["brief"] = line[6:].strip()
                    current_key = "brief"
                elif current_key == "brief":
                    fields["brief"] = fields.get("brief", "") + "\n" + line
            if fields.get("event") and fields.get("brief"):
                prep_briefs.append(fields)

    return {
        "events": formatted_events,
        "prep_briefs": prep_briefs,
        "conflicts": [],
    }


def _step_forgetting_check() -> list[dict]:
    """Scan active state for things MJ might be forgetting."""
    reminders = []

    # Stale missions (active for 3+ days with no update)
    from config import DATABASE_URL
    import psycopg2, psycopg2.extras
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, title, description, assigned_agent, updated_at FROM shams_missions "
            "WHERE status = 'active' AND updated_at < NOW() - INTERVAL '3 days'"
        )
        stale_missions = cur.fetchall()

        # Approaching deadlines (next 7 days)
        cur.execute(
            "SELECT id, title, description, end_date FROM shams_missions "
            "WHERE status IN ('active', 'assigned', 'inbox') AND end_date IS NOT NULL "
            "AND end_date <= CURRENT_DATE + INTERVAL '7 days' AND end_date >= CURRENT_DATE"
        )
        deadline_missions = cur.fetchall()

        cur.execute(
            "SELECT id, title, deadline FROM shams_deals "
            "WHERE stage NOT IN ('closed', 'dead') AND deadline IS NOT NULL "
            "AND deadline <= CURRENT_DATE + INTERVAL '7 days' AND deadline >= CURRENT_DATE"
        )
        deadline_deals = cur.fetchall()

    for m in stale_missions:
        reminders.append({
            "type": "stale_mission",
            "title": m["title"],
            "why": f"Active but no updates since {m['updated_at'].strftime('%b %d') if m.get('updated_at') else 'unknown'}",
            "mission_id": m["id"],
            "suggestion": "Review and update status, or create next steps",
        })

    for m in deadline_missions:
        reminders.append({
            "type": "deadline",
            "title": m["title"],
            "why": f"Due {m['end_date'].strftime('%b %d') if m.get('end_date') else 'soon'}",
            "mission_id": m["id"],
            "suggestion": "Check progress and prioritize",
        })

    for d in deadline_deals:
        reminders.append({
            "type": "deal_deadline",
            "title": d["title"],
            "why": f"Deadline {d['deadline'].strftime('%b %d') if d.get('deadline') else 'soon'}",
            "suggestion": "Review and take action",
        })

    # Orphaned open loops — open loops with no recent activity
    loops = memory.get_open_loops()
    for loop in loops:
        age_days = (datetime.now(timezone.utc) - loop["created_at"].replace(tzinfo=timezone.utc)).days if loop.get("created_at") else 0
        if age_days > 7:
            reminders.append({
                "type": "orphaned_loop",
                "title": loop["title"],
                "why": f"Open for {age_days} days with no resolution",
                "loop_id": loop["id"],
                "suggestion": "Close, create a mission, or schedule time",
            })

    # Pending actions stuck for 24+ hours
    pending = memory.get_actions(status="pending")
    for a in pending:
        if a.get("created_at"):
            age_hours = (datetime.now(timezone.utc) - a["created_at"].replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age_hours > 24:
                reminders.append({
                    "type": "stale_action",
                    "title": a["title"],
                    "why": f"Pending for {int(age_hours)} hours",
                    "action_id": a["id"],
                    "suggestion": "Approve, reject, or review",
                })

    # If there are reminders that could use work product, draft next steps
    if reminders and any(r["type"] in ("stale_mission", "deadline") for r in reminders):
        _draft_reminder_work_product(reminders)

    return reminders


def _draft_reminder_work_product(reminders: list[dict]):
    """Use Claude to draft next-step recommendations for stale/deadline items."""
    items_needing_drafts = [r for r in reminders if r["type"] in ("stale_mission", "deadline")]
    if not items_needing_drafts:
        return

    api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    items_text = "\n".join(
        f"- {r['title']} ({r['type']}): {r['why']}"
        for r in items_needing_drafts[:5]
    )
    prompt = (
        f"For each of these items Maher might be forgetting, draft a short next-step "
        f"recommendation (2-3 sentences). Be specific and actionable.\n\n{items_text}\n\n"
        f"Format:\nITEM: <title>\nDRAFT: <recommendation>\n---"
    )
    response = api_client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    drafts = {}
    for block in response.content[0].text.split("---"):
        block = block.strip()
        if not block:
            continue
        item_title, draft_text = "", ""
        for line in block.split("\n"):
            if line.startswith("ITEM:"):
                item_title = line[5:].strip()
            elif line.startswith("DRAFT:"):
                draft_text = line[6:].strip()
        if item_title:
            drafts[item_title.lower()] = draft_text

    # Attach drafts to matching reminders
    for r in reminders:
        draft = drafts.get(r["title"].lower(), "")
        if draft:
            r["draft"] = draft


# ── Summary builder ────────────────────────────────────────────────────────


def _build_overnight_summary(results: dict) -> str:
    """Build a human-readable summary of overnight results for logging."""
    parts = []
    email = results.get("email", {})
    parts.append(f"Email: {len(email.get('reply', []))} reply, {len(email.get('read', []))} read, {len(email.get('archived', []))} archived")

    mercury = results.get("mercury", {})
    total = mercury.get("grand_total", 0)
    if total:
        parts.append(f"Cash: ${total:,.0f}")
    if mercury.get("alerts"):
        parts.append(f"Mercury alerts: {len(mercury['alerts'])}")

    rumi = results.get("rumi", {})
    if rumi.get("revenue"):
        parts.append(f"Yesterday: ${rumi['revenue']:,.0f} rev / {rumi.get('margin', 0):.0%} margin")

    calendar = results.get("calendar", {})
    parts.append(f"Calendar: {len(calendar.get('events', []))} events, {len(calendar.get('prep_briefs', []))} prep briefs")

    reminders = results.get("reminders", [])
    if reminders:
        parts.append(f"Reminders: {len(reminders)} items")

    return " | ".join(parts)
```

- [ ] **Step 4: Run the test**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_overnight_loop_structure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: create standup.py with overnight loop (5 steps)"
```

---

### Task 6: Morning Standup Delivery — Overview + Drip-Feed

**Files:**
- Modify: `standup.py` (append morning standup functions)

- [ ] **Step 1: Write test for standup overview message**

Append to `tests/test_standup.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_build_overview_message -v`
Expected: FAIL — `AttributeError: module 'standup' has no attribute '_build_overview_message'`

- [ ] **Step 3: Add morning standup delivery to standup.py**

Append to `standup.py`:

```python
# ── Morning Standup Delivery ───────────────────────────────────────────────


def deliver_morning_standup():
    """Deliver the morning standup via Telegram. Called at 7am ET by scheduler.

    Phase 1: Send overview message
    Phase 2: Drip-feed action items (reply drafts, prep briefs, reminders)
    """
    run = memory.get_latest_overnight_run()
    if not run or run.get("status") == "failed":
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID,
                          "Overnight loop didn't run or failed. Check the logs.")
        return

    results = run.get("results", {})
    if isinstance(results, str):
        results = json.loads(results)

    # Phase 1: Overview
    overview = _build_overview_message(results)
    if config.TELEGRAM_CHAT_ID:
        send_telegram(config.TELEGRAM_CHAT_ID, overview)

    # Phase 2: Build action items list and start dripping
    action_items = _build_action_items(results)

    if not action_items:
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, "Nothing needs your input today. Have a good one.")
        return

    # Save standup state and send first item
    memory.set_standup_state({
        "phase": "dripping",
        "run_id": run["id"],
        "items": action_items,
        "current_index": 0,
        "sent_count": 0,
        "handled": {},
    })

    _send_next_standup_item()


def _build_overview_message(results: dict) -> str:
    """Build the single overview Telegram message."""
    from datetime import date
    today = date.today().strftime("%a %b %-d")
    lines = [f"☀️ Morning Standup — {today}\n"]

    # Email
    email = results.get("email", {})
    reply_count = len(email.get("reply", []))
    read_count = len(email.get("read", []))
    archived_count = len(email.get("archived", []))
    lines.append(f"📬 {reply_count} replies drafted · {read_count} to read · {archived_count} archived")
    archive_summary = email.get("archive_summary", "")
    if archive_summary:
        lines.append(f"   {archive_summary}")

    # Mercury
    mercury = results.get("mercury", {})
    total = mercury.get("grand_total", 0)
    if total:
        alert_text = ""
        for alert in mercury.get("alerts", []):
            if alert.get("type") == "low_balance":
                acct = alert.get("account", "").title()
                bal = alert.get("balance", 0)
                alert_text = f" · ⚠️ {acct} low (${bal:,.0f})"
                break
        lines.append(f"💰 Total cash: ${total:,.0f}{alert_text}")

    # Rumi
    rumi = results.get("rumi", {})
    if rumi.get("revenue"):
        margin_pct = rumi.get("margin", 0)
        if isinstance(margin_pct, float) and margin_pct < 1:
            margin_display = f"{margin_pct:.0%}"
        else:
            margin_display = f"{margin_pct:.1f}%"
        orders = rumi.get("orders", 0)
        lines.append(f"📊 Yesterday: ${rumi['revenue']:,.0f} rev / {margin_display} margin / {orders} orders")

    # Calendar
    calendar = results.get("calendar", {})
    events = calendar.get("events", [])
    prep_briefs = calendar.get("prep_briefs", [])
    if events:
        prep_note = f" · ⚠️ {len(prep_briefs)} need prep" if prep_briefs else ""
        lines.append(f"📅 {len(events)} meetings today{prep_note}")

    # Reminders
    reminders = results.get("reminders", [])
    if reminders:
        lines.append(f"🔔 {len(reminders)} things you might be forgetting")

    lines.append("\nWalking you through action items now ↓")

    return "\n".join(lines)


def _build_action_items(results: dict) -> list[dict]:
    """Build ordered list of action items for drip-feed."""
    items = []

    # 1. Reply drafts (most time-sensitive)
    email = results.get("email", {})
    reply_emails = email.get("reply", [])
    for i, r in enumerate(reply_emails):
        items.append({
            "type": "reply",
            "index_label": f"Reply {i+1}/{len(reply_emails)}",
            "from": r.get("from", ""),
            "subject": r.get("subject", ""),
            "draft": r.get("draft", ""),
            "triage_id": r.get("triage_id"),
            "account": r.get("account", ""),
            "message_id": r.get("message_id", ""),
        })

    # 2. Prep briefs
    calendar = results.get("calendar", {})
    for brief in calendar.get("prep_briefs", []):
        items.append({
            "type": "prep",
            "event": brief.get("event", ""),
            "brief": brief.get("brief", ""),
        })

    # 3. Reminders
    for r in results.get("reminders", []):
        items.append({
            "type": "reminder",
            "title": r.get("title", ""),
            "why": r.get("why", ""),
            "suggestion": r.get("suggestion", ""),
            "draft": r.get("draft", ""),
            "mission_id": r.get("mission_id"),
            "loop_id": r.get("loop_id"),
            "action_id": r.get("action_id"),
        })

    return items


def _send_next_standup_item():
    """Send the next action item in the standup drip-feed."""
    state = memory.get_standup_state()
    if not state or state.get("phase") != "dripping":
        return

    items = state.get("items", [])
    idx = state.get("current_index", 0)

    if idx >= len(items):
        _finish_standup(state)
        return

    item = items[idx]
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    if item["type"] == "reply":
        msg = (
            f"📬 {item['index_label']}\n"
            f"From: {item['from']}\n"
            f"Re: {item['subject']}\n\n"
            f"Draft: {item['draft']}"
        )
        buttons = [
            {"text": "✓ Send", "callback_data": f"su_send:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "prep":
        msg = (
            f"📋 Prep: {item['event']}\n\n"
            f"{item['brief']}"
        )
        buttons = [
            {"text": "👍 Looks good", "callback_data": f"su_ok:{idx}"},
            {"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"},
            {"text": "Skip", "callback_data": f"su_skip:{idx}"},
        ]
        send_telegram_with_buttons(chat_id, msg, buttons)

    elif item["type"] == "reminder":
        msg = (
            f"🔔 Don't forget: {item['title']}\n"
            f"{item['why']}"
        )
        if item.get("draft"):
            msg += f"\n\nSuggested next steps: {item['draft']}"

        buttons = [
            {"text": "Got it", "callback_data": f"su_ok:{idx}"},
            {"text": "Snooze", "callback_data": f"su_snooze:{idx}"},
        ]
        if item.get("mission_id"):
            pass  # Already a mission
        else:
            buttons.append({"text": "Create mission", "callback_data": f"su_mission:{idx}"})
        send_telegram_with_buttons(chat_id, msg, buttons)


def _finish_standup(state: dict):
    """Send wrap-up message and clear state."""
    handled = state.get("handled", {})
    sent = sum(1 for v in handled.values() if v == "sent")
    skipped = sum(1 for v in handled.values() if v == "skip")
    items = state.get("items", [])
    email_count = sum(1 for i in items if i["type"] == "reply")

    parts = []
    if sent:
        parts.append(f"{sent} email draft{'s' if sent != 1 else ''} saved to Gmail")
    if skipped:
        parts.append(f"{skipped} skipped")

    # Get archived count from overnight run
    run = memory.get_latest_overnight_run()
    if run:
        results = run.get("results", {})
        if isinstance(results, str):
            results = json.loads(results)
        archived = len(results.get("email", {}).get("archived", []))
        if archived:
            parts.append(f"{archived} archived")

    summary = ", ".join(parts) if parts else "All done"

    if config.TELEGRAM_CHAT_ID:
        send_telegram(config.TELEGRAM_CHAT_ID, f"✅ Standup done. {summary}. Have a good one.")

    memory.clear_standup_state()
```

- [ ] **Step 4: Run the test**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_build_overview_message -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: add morning standup delivery — overview + drip-feed action items"
```

---

### Task 7: Telegram Callbacks — Standup Button Handlers

**Files:**
- Modify: `telegram.py:330-389` (handle_callback function)
- Modify: `telegram.py:126-171` (process_message — edit state handling)

- [ ] **Step 1: Write test for standup callback routing**

Append to `tests/test_standup.py`:

```python
def test_standup_callback_routing():
    """Test that standup callback data is parsed correctly."""
    # Verify our callback format works with existing handler pattern
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
```

- [ ] **Step 2: Run test to verify it passes (parsing test)**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/test_standup.py::test_standup_callback_routing -v`
Expected: PASS

- [ ] **Step 3: Add standup callback handlers to telegram.py**

In `telegram.py`, add this function before `handle_callback()` (before line 330):

```python
def _handle_standup_callback(action_type: str, idx: int, cb_id: str, chat_id: str):
    """Handle standup drip-feed button presses."""
    import standup

    state = memory.get_standup_state()
    if not state or state.get("phase") not in ("dripping", "waiting_for_edit"):
        _ack_callback(cb_id, "Standup expired")
        return

    items = state.get("items", [])
    if idx >= len(items):
        _ack_callback(cb_id, "Item not found")
        return

    item = items[idx]
    handled = state.get("handled", {})

    if action_type == "su_send":
        # Create draft in Gmail (we have gmail.modify, not gmail.send)
        import google_client
        if item.get("message_id") and item.get("draft"):
            result = google_client.create_draft_reply(
                item["account"], item["message_id"], item["draft"]
            )
            if result:
                memory.log_activity("shams", "standup_send", f"Draft saved: {item.get('subject', '')}")
                _ack_callback(cb_id, "Draft saved to Gmail")
                send_telegram(chat_id, f"Draft saved in Gmail for: {item.get('subject', '')}")
            else:
                _ack_callback(cb_id, "Failed to save draft")
                send_telegram(chat_id, "Failed to save draft — check Gmail connection.")
        handled[str(idx)] = "sent"

    elif action_type == "su_edit":
        # Enter edit mode — next text message from MJ is the edited version
        state["phase"] = "waiting_for_edit"
        state["edit_index"] = idx
        memory.set_standup_state(state)
        _ack_callback(cb_id, "Send your edit")

        if item["type"] == "reply":
            send_telegram(chat_id, f"Here's the current draft — send me your version:\n\n{item.get('draft', '')}")
        elif item["type"] == "prep":
            send_telegram(chat_id, f"Here's the current brief — send me your version:\n\n{item.get('brief', '')}")
        return  # Don't advance to next item

    elif action_type == "su_skip":
        handled[str(idx)] = "skip"
        _ack_callback(cb_id, "Skipped")

    elif action_type == "su_ok":
        handled[str(idx)] = "ok"
        _ack_callback(cb_id, "Got it")

        # If it's a prep brief, save it
        if item["type"] == "prep":
            memory.log_activity("shams", "standup_prep", f"Prep brief approved: {item.get('event', '')}")

    elif action_type == "su_snooze":
        handled[str(idx)] = "snooze"
        _ack_callback(cb_id, "Snoozed")

    elif action_type == "su_mission":
        # Create a mission from the reminder
        mission_id = memory.create_mission(
            title=item.get("title", "Untitled"),
            description=item.get("why", "") + "\n" + item.get("draft", ""),
            priority="normal",
        )
        handled[str(idx)] = "mission"
        _ack_callback(cb_id, f"Mission #{mission_id} created")
        send_telegram(chat_id, f"Created mission #{mission_id}: {item.get('title', '')}")

    # Advance to next item
    state["handled"] = handled
    state["current_index"] = idx + 1
    state["phase"] = "dripping"
    memory.set_standup_state(state)

    standup._send_next_standup_item()
```

- [ ] **Step 4: Update `handle_callback` to route standup callbacks**

In `telegram.py`, in the `handle_callback()` function, add standup routing after the email action check (after line 348 `return`):

```python
    # Standup callbacks (su_send, su_edit, su_skip, su_ok, su_snooze, su_mission)
    if action_type.startswith("su_"):
        _handle_standup_callback(action_type, action_id, cb_id, chat_id)
        return
```

- [ ] **Step 5: Add edit state handling in `process_message`**

In `telegram.py`, in the `process_message()` function, add edit state handling right after the text check at line 130 (`if msg.get("text"):`), before the `/start` command check:

```python
    if msg.get("text"):
        text = msg["text"].strip()

        # Check if we're in standup edit mode
        standup_state = memory.get_standup_state()
        if standup_state and standup_state.get("phase") == "waiting_for_edit":
            import standup as standup_mod
            edit_idx = standup_state.get("edit_index", 0)
            items = standup_state.get("items", [])
            if edit_idx < len(items):
                item = items[edit_idx]
                handled = standup_state.get("handled", {})

                if item["type"] == "reply":
                    # Save edited draft to Gmail
                    import google_client
                    if item.get("message_id"):
                        result = google_client.create_draft_reply(item["account"], item["message_id"], text)
                        if result:
                            send_telegram(chat_id, "Got it. Draft saved to Gmail with your edit.")
                            memory.log_activity("shams", "standup_edit", f"Edited draft saved: {item.get('subject', '')}")
                        else:
                            send_telegram(chat_id, "Failed to save draft — check Gmail connection.")
                    handled[str(edit_idx)] = "sent"
                elif item["type"] == "prep":
                    send_telegram(chat_id, "Got it. Updated brief saved.")
                    memory.log_activity("shams", "standup_edit", f"Edited prep brief: {item.get('event', '')}")
                    handled[str(edit_idx)] = "ok"

                standup_state["handled"] = handled
                standup_state["current_index"] = edit_idx + 1
                standup_state["phase"] = "dripping"
                memory.set_standup_state(standup_state)
                standup_mod._send_next_standup_item()
            return

        if text == "/start":
```

Note: The existing code after `/start` stays as-is. The only change is inserting the standup edit check between `if msg.get("text"):` and `if text == "/start":`.

- [ ] **Step 6: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add telegram.py tests/test_standup.py
git commit -m "feat: add standup Telegram callback handlers + edit flow"
```

---

### Task 8: Wire Up Scheduler — Replace Morning Briefing

**Files:**
- Modify: `scheduler.py:18-31` (replace send_morning_briefing)
- Modify: `scheduler.py:341-355` (init_scheduler — wire new jobs)

- [ ] **Step 1: Replace morning briefing with overnight loop + standup in scheduler.py**

Replace `send_morning_briefing()` (lines 20-31):

```python
def send_morning_briefing():
    """Run overnight ops loop. Scheduled at 3am ET."""
    import standup
    try:
        results = standup.run_overnight_loop()
        memory.log_activity("shams", "overnight", "Overnight loop completed", {
            "email_reply": len(results.get("email", {}).get("reply", [])),
            "email_archived": len(results.get("email", {}).get("archived", [])),
            "reminders": len(results.get("reminders", [])),
        })
        logger.info("Overnight loop completed")
    except Exception as e:
        memory.log_activity("shams", "error", f"Overnight loop failed: {e}")
        logger.error(f"Overnight loop failed: {e}")
```

- [ ] **Step 2: Add standup delivery function to scheduler.py**

Add after `send_evening_briefing()` (after line 45):

```python

def deliver_standup():
    """Deliver morning standup via Telegram. Scheduled at 7am ET."""
    import standup
    try:
        standup.deliver_morning_standup()
        memory.log_activity("shams", "standup", "Morning standup delivered")
        logger.info("Morning standup delivered")
    except Exception as e:
        memory.log_activity("shams", "error", f"Morning standup delivery failed: {e}")
        logger.error(f"Morning standup delivery failed: {e}")
```

- [ ] **Step 3: Update `init_scheduler` to wire new jobs**

Replace line 347 (`scheduler.add_job(send_morning_briefing, ...)`):

```python
    scheduler.add_job(send_morning_briefing, "cron", hour=config.OVERNIGHT_HOUR_UTC, minute=0, id="overnight_loop")
    scheduler.add_job(deliver_standup, "cron", hour=config.STANDUP_HOUR_UTC, minute=0, id="morning_standup")
```

And update the logger line (line 354):

```python
    logger.info(f"Scheduler started — overnight @ {config.OVERNIGHT_HOUR_UTC}:00 UTC, standup @ {config.STANDUP_HOUR_UTC}:00 UTC, evening @ {config.EVENING_HOUR_UTC}:00 UTC")
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scheduler.py
git commit -m "feat: wire overnight loop (3am) + standup (7am) into scheduler"
```

---

### Task 9: Update Hot Context — Overnight Results in Morning Slot

**Files:**
- Modify: `claude_client.py:52-66` (morning hot context slot)

- [ ] **Step 1: Update morning hot context to include overnight results**

In `claude_client.py`, replace the morning slot (lines 59-65):

```python
        elif et_hour < 10:
            # Morning: pending actions, overnight results
            actions = memory.get_actions(status="pending")
            if actions:
                parts.append("\n## Pending Actions")
                for a in actions[:5]:
                    parts.append(f"- [{a.get('id','')}] {a.get('title','')}")
```

With:

```python
        elif et_hour < 10:
            # Morning: overnight results + pending actions
            overnight = memory.get_latest_overnight_run()
            if overnight and overnight.get("summary"):
                parts.append(f"\n## Overnight Summary\n{overnight['summary']}")
            actions = memory.get_actions(status="pending")
            if actions:
                parts.append("\n## Pending Actions")
                for a in actions[:5]:
                    parts.append(f"- [{a.get('id','')}] {a.get('title','')}")
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add claude_client.py
git commit -m "feat: inject overnight run summary into morning hot context"
```

---

### Task 10: Delete briefing.py + Final Integration

**Files:**
- Delete: `briefing.py`
- Modify: `scheduler.py:34-45` (update evening briefing to use standup.py)

- [ ] **Step 1: Move evening briefing logic to standup.py**

Append to `standup.py` (before the closing section):

```python
# ── Evening Briefing (kept from briefing.py) ───────────────────────────────


def generate_evening_briefing() -> str:
    """Generate an evening wrap-up briefing."""
    import claude_client
    import leo_client

    parts = []

    # Tomorrow's calendar
    events = google_client.get_upcoming_events(1)
    if events:
        parts.append("## Tomorrow's Calendar")
        for e in events:
            parts.append(f"- {e['start']} — {e['summary']}")

    # MTD P&L
    mtd = rumi_client.get_monthly_pl()
    if mtd:
        parts.append(f"\n## MTD P&L")
        parts.append(f"- Revenue: ${mtd.get('revenue', 0):,.0f}")
        parts.append(f"- Net margin: {mtd.get('net_margin_pct', 0):.1f}%")

    # Open loops
    loops = memory.get_open_loops()
    if loops:
        parts.append("\n## Open Loops (still open)")
        for loop in loops:
            parts.append(f"- [{loop['id']}] {loop['title']}")

    context = "\n".join(parts)
    return claude_client.generate_briefing("evening", context)
```

- [ ] **Step 2: Update evening briefing in scheduler.py to use standup module**

In `scheduler.py`, replace `send_evening_briefing()` (lines 34-45):

```python
def send_evening_briefing():
    import standup
    try:
        text = standup.generate_evening_briefing()
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, text)
        memory.save_briefing("evening", text)
        memory.log_activity("shams", "briefing", "Evening briefing delivered", {"type": "evening", "channel": "telegram"})
        logger.info("Evening briefing sent")
    except Exception as e:
        memory.log_activity("shams", "error", f"Evening briefing failed: {e}")
        logger.error(f"Evening briefing failed: {e}")
```

- [ ] **Step 3: Delete briefing.py**

```bash
rm /Users/mj/code/Shams/briefing.py
```

- [ ] **Step 4: Check for any remaining imports of briefing module**

Run: `grep -r "import briefing" /Users/mj/code/Shams/ --include="*.py" -l`

If any files still import `briefing`, update them to import `standup` instead. The scheduler.py references in `send_morning_briefing` and `send_evening_briefing` were already updated in Steps 1-2 of this task and Task 8.

- [ ] **Step 5: Run all tests**

Run: `cd /Users/mj/code/Shams && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add standup.py scheduler.py
git rm briefing.py
git commit -m "feat: delete briefing.py — evening briefing moved to standup.py"
```

---

### Task 11: Run Schema Migration on Railway

**Files:**
- None (database operation only)

- [ ] **Step 1: Run the schema migration on Railway Postgres**

The new table and column need to be created on the production database:

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -f schema.sql
```

Or if that fails, run just the new additions:

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "
CREATE TABLE IF NOT EXISTS shams_overnight_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      VARCHAR(20) DEFAULT 'running' CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    results     JSONB DEFAULT '{}',
    summary     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_overnight_runs_started ON shams_overnight_runs (started_at DESC);
DO \$\$ BEGIN
    ALTER TABLE shams_email_triage ADD COLUMN tier VARCHAR(10) DEFAULT 'archive' CHECK (tier IN ('reply', 'read', 'archive'));
EXCEPTION WHEN duplicate_column THEN NULL;
END \$\$;
CREATE INDEX IF NOT EXISTS idx_email_triage_tier ON shams_email_triage (tier);
"
```

- [ ] **Step 2: Verify tables exist**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "\dt shams_overnight*"
```

Expected: `shams_overnight_runs` table listed.

- [ ] **Step 3: Commit** (nothing to commit — DB-only change)

Mark as done.

---

### Task 12: Deploy + Smoke Test

**Files:**
- None (deployment only)

- [ ] **Step 1: Push to GitHub to trigger Railway auto-deploy**

```bash
cd /Users/mj/code/Shams && git push origin main
```

- [ ] **Step 2: Monitor Railway deploy logs**

Watch the deploy at Railway dashboard or via:
```bash
/Users/mj/.local/bin/railway logs --follow
```

Confirm:
- No import errors
- Scheduler starts with overnight/standup jobs logged
- "Scheduler started — overnight @ 7:00 UTC, standup @ 11:00 UTC, evening @ 1:00 UTC"

- [ ] **Step 3: Manually trigger overnight loop for smoke test**

Send a message to Shams via Telegram asking it to run the overnight loop, or trigger it via:

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run python -c "
import standup
results = standup.run_overnight_loop()
print('Email:', len(results['email']['reply']), 'reply,', len(results['email']['archived']), 'archived')
print('Mercury alerts:', len(results['mercury']['alerts']))
print('Reminders:', len(results['reminders']))
"
```

- [ ] **Step 4: Manually trigger standup delivery**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run python -c "
import standup
standup.deliver_morning_standup()
print('Standup delivered')
"
```

Check Telegram for:
1. Overview message with correct format
2. First drip-feed action item with buttons
3. Tap Send/Edit/Skip and verify it advances to the next item
4. Verify wrap-up message after all items handled

- [ ] **Step 5: Done — tag the release**

```bash
cd /Users/mj/code/Shams && git tag -a shams-v2-overnight-ops -m "Shams v2 Sub-project B: Overnight Ops + Morning Standup"
git push origin shams-v2-overnight-ops
```
