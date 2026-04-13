# Shams P&L Attribution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-tracking P&L engine that logs Claude API costs per call, attributes revenue from time saved at $250/hr, and delivers daily + weekly ROI reports via standup and Telegram digest.

**Architecture:** A new `shams_pl_entries` table stores revenue and cost entries. Token costs are logged after every `messages.create()` call in `claude_client.py` and `agents/registry.py`. Revenue is logged in each overnight loop step. Daily P&L appears in the standup overview; weekly digest fires Sunday night.

**Tech Stack:** Python 3.9+ (`from __future__ import annotations`), PostgreSQL, Anthropic API response.usage, APScheduler

**Spec:** `docs/superpowers/specs/2026-04-13-pl-attribution-design.md`

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `schema.sql` | Add `shams_pl_entries` table | Modify |
| `memory.py` | P&L CRUD functions (6 functions) | Modify |
| `standup.py` | `PL_CONFIG`, revenue logging in overnight steps + auto-approve, daily P&L in overview | Modify |
| `claude_client.py` | Log token costs after API calls | Modify |
| `agents/registry.py` | Log token costs after agent API calls | Modify |
| `scheduler.py` | Weekly P&L digest job + daily hosting cost job | Modify |
| `tools/deals.py` | Deal-advance bonus logging | Modify |
| `tests/test_standup.py` | P&L tests | Modify |

---

### Task 1: Schema + Memory Layer — P&L CRUD

**Files:**
- Modify: `schema.sql` (append table)
- Modify: `memory.py` (append 6 functions)
- Modify: `standup.py` (add PL_CONFIG near top)
- Modify: `tests/test_standup.py` (add tests)

- [ ] **Step 1: Write tests**

Append to `tests/test_standup.py`:

```python
def test_pl_config_exists():
    """Test that PL_CONFIG exists with expected structure."""
    from standup import PL_CONFIG
    assert PL_CONFIG["hourly_rate"] == 250
    assert "email_triage" in PL_CONFIG["time_values"]
    assert "input_per_million" in PL_CONFIG["token_pricing"]
    assert PL_CONFIG["token_pricing"]["input_per_million"] == 3.00


def test_pl_revenue_calculation():
    """Test revenue calculation from time values."""
    from standup import PL_CONFIG
    hourly = PL_CONFIG["hourly_rate"]
    # 5 min draft at $250/hr = $20.83
    draft_value = (5 / 60) * hourly
    assert round(draft_value, 2) == 20.83
    # 0.5 min email triage at $250/hr = $2.08
    triage_value = (0.5 / 60) * hourly
    assert round(triage_value, 2) == 2.08


def test_pl_cost_calculation():
    """Test cost calculation from token counts."""
    from standup import PL_CONFIG
    pricing = PL_CONFIG["token_pricing"]
    # 100K input tokens + 20K output tokens
    cost = (100_000 / 1_000_000 * pricing["input_per_million"]) + \
           (20_000 / 1_000_000 * pricing["output_per_million"])
    assert round(cost, 4) == 0.6  # $0.30 input + $0.30 output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_pl_config_exists tests/test_standup.py::test_pl_revenue_calculation tests/test_standup.py::test_pl_cost_calculation -v`
Expected: FAIL — `ImportError: cannot import name 'PL_CONFIG'`

- [ ] **Step 3: Add `shams_pl_entries` table to schema.sql**

Append to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS shams_pl_entries (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,
    entry_type  VARCHAR(20) NOT NULL CHECK (entry_type IN ('revenue', 'cost')),
    category    VARCHAR(50) NOT NULL,
    description TEXT DEFAULT '',
    amount      NUMERIC(10,4) NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pl_entries_date ON shams_pl_entries (date DESC);
CREATE INDEX IF NOT EXISTS idx_pl_entries_type ON shams_pl_entries (entry_type, date DESC);
```

- [ ] **Step 4: Run schema migration on Railway**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "
CREATE TABLE IF NOT EXISTS shams_pl_entries (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,
    entry_type  VARCHAR(20) NOT NULL CHECK (entry_type IN ('revenue', 'cost')),
    category    VARCHAR(50) NOT NULL,
    description TEXT DEFAULT '',
    amount      NUMERIC(10,4) NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pl_entries_date ON shams_pl_entries (date DESC);
CREATE INDEX IF NOT EXISTS idx_pl_entries_type ON shams_pl_entries (entry_type, date DESC);
"
```

- [ ] **Step 5: Add PL_CONFIG to standup.py**

In `standup.py`, add this after `STANDUP_TRUST_MAP` (the trust map dict that was added previously):

```python
# ── P&L configuration ─────────────────────────────────────────────────────

PL_CONFIG = {
    "hourly_rate": 250,
    "time_values": {  # minutes saved per action
        "email_triage": 0.5,
        "draft_reply": 5,
        "prep_brief": 15,
        "reminder": 10,
        "auto_approve": 2,
        "scout_finding": 20,
    },
    "deal_advance_bonus": 500,
    "token_pricing": {
        "input_per_million": 3.00,
        "output_per_million": 15.00,
    },
    "railway_monthly": 75,
}
```

- [ ] **Step 6: Add 6 P&L functions to memory.py**

Append to `memory.py`:

```python
# ── P&L Entries ────────────────────────────────────────────────────────────

def log_pl_revenue(category: str, amount: float, description: str = "",
                   metadata: dict | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}pl_entries (entry_type, category, amount, description, metadata) "
            f"VALUES ('revenue', %s, %s, %s, %s)",
            (category, amount, description, json.dumps(metadata or {})),
        )


def log_pl_cost(input_tokens: int = 0, output_tokens: int = 0, context: str = ""):
    from standup import PL_CONFIG
    pricing = PL_CONFIG["token_pricing"]
    cost = (input_tokens / 1_000_000 * pricing["input_per_million"]) + \
           (output_tokens / 1_000_000 * pricing["output_per_million"])
    if cost <= 0:
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}pl_entries (entry_type, category, amount, description, metadata) "
            f"VALUES ('cost', 'claude_api', %s, %s, %s)",
            (cost, context, json.dumps({"input_tokens": input_tokens, "output_tokens": output_tokens})),
        )


def log_pl_hosting_cost():
    from standup import PL_CONFIG
    daily_cost = PL_CONFIG["railway_monthly"] / 30
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}pl_entries (entry_type, category, amount, description) "
            f"VALUES ('cost', 'railway_hosting', %s, 'Daily Railway hosting')",
            (daily_cost,),
        )


def get_pl_daily(date: str | None = None) -> dict:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if date:
            cur.execute(
                f"SELECT entry_type, category, SUM(amount) as total FROM {P}pl_entries "
                f"WHERE date = %s GROUP BY entry_type, category", (date,)
            )
        else:
            cur.execute(
                f"SELECT entry_type, category, SUM(amount) as total FROM {P}pl_entries "
                f"WHERE date = CURRENT_DATE - INTERVAL '1 day' GROUP BY entry_type, category"
            )
        rows = cur.fetchall()

    revenue = sum(float(r["total"]) for r in rows if r["entry_type"] == "revenue")
    costs = sum(float(r["total"]) for r in rows if r["entry_type"] == "cost")
    return {
        "revenue": round(revenue, 2),
        "costs": round(costs, 2),
        "net": round(revenue - costs, 2),
        "entries": rows,
    }


def get_pl_weekly(weeks_ago: int = 0) -> dict:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT entry_type, category, SUM(amount) as total, "
            f"COUNT(*) as count FROM {P}pl_entries "
            f"WHERE date >= CURRENT_DATE - INTERVAL '%s weeks' - INTERVAL '6 days' "
            f"AND date <= CURRENT_DATE - INTERVAL '%s weeks' "
            f"GROUP BY entry_type, category ORDER BY entry_type, total DESC",
            (weeks_ago, weeks_ago),
        )
        rows = cur.fetchall()

        # Get token totals for the week
        cur.execute(
            f"SELECT SUM((metadata->>'input_tokens')::bigint) as input_tokens, "
            f"SUM((metadata->>'output_tokens')::bigint) as output_tokens "
            f"FROM {P}pl_entries "
            f"WHERE category = 'claude_api' "
            f"AND date >= CURRENT_DATE - INTERVAL '%s weeks' - INTERVAL '6 days' "
            f"AND date <= CURRENT_DATE - INTERVAL '%s weeks'",
            (weeks_ago, weeks_ago),
        )
        token_row = cur.fetchone()

    revenue_entries = [r for r in rows if r["entry_type"] == "revenue"]
    cost_entries = [r for r in rows if r["entry_type"] == "cost"]
    revenue = sum(float(r["total"]) for r in revenue_entries)
    costs = sum(float(r["total"]) for r in cost_entries)

    return {
        "revenue": round(revenue, 2),
        "costs": round(costs, 2),
        "net": round(revenue - costs, 2),
        "revenue_breakdown": {r["category"]: {"total": round(float(r["total"]), 2), "count": r["count"]} for r in revenue_entries},
        "cost_breakdown": {r["category"]: round(float(r["total"]), 2) for r in cost_entries},
        "tokens": {
            "input": int(token_row["input_tokens"] or 0) if token_row else 0,
            "output": int(token_row["output_tokens"] or 0) if token_row else 0,
        },
    }


def get_pl_running_total() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT entry_type, SUM(amount) as total FROM {P}pl_entries "
            f"GROUP BY entry_type"
        )
        rows = {r[0]: float(r[1]) for r in cur.fetchall()}

    revenue = round(rows.get("revenue", 0), 2)
    costs = round(rows.get("cost", 0), 2)
    return {"revenue": revenue, "costs": costs, "net": round(revenue - costs, 2)}
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_pl_config_exists tests/test_standup.py::test_pl_revenue_calculation tests/test_standup.py::test_pl_cost_calculation -v`
Expected: PASS

- [ ] **Step 8: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add schema.sql memory.py standup.py tests/test_standup.py
git commit -m "feat: add P&L entries table + CRUD functions + PL_CONFIG"
```

---

### Task 2: Token Cost Tracking — Log API Costs

**Files:**
- Modify: `claude_client.py` (log costs after both `messages.create` calls)
- Modify: `agents/registry.py` (log costs after agent `messages.create` call)

- [ ] **Step 1: Add cost logging to `claude_client.py` chat loop**

In `claude_client.py`, find the `chat()` function. There are two places where `response = client.messages.create(...)` is called.

**First call (line ~192, inside the for loop):** After the `response = client.messages.create(...)` line, add:

```python
        # Log API cost
        if hasattr(response, 'usage') and response.usage:
            memory.log_pl_cost(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                context="chat",
            )
```

**Second call (in `generate_briefing()`, line ~250):** After the `response = client.messages.create(...)` line, add:

```python
        # Log API cost
        if hasattr(response, 'usage') and response.usage:
            memory.log_pl_cost(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                context=f"briefing:{briefing_type}",
            )
```

- [ ] **Step 2: Add cost logging to `agents/registry.py`**

In `agents/registry.py`, find `call_agent()`. After the `response = client.messages.create(**kwargs)` line (inside the try block), add:

```python
            # Log API cost
            if hasattr(response, 'usage') and response.usage:
                import memory
                memory.log_pl_cost(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    context=f"agent:{agent_name}",
                )
```

- [ ] **Step 3: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add claude_client.py agents/registry.py
git commit -m "feat: log Claude API token costs after every messages.create call"
```

---

### Task 3: Revenue Logging — Track Value in Overnight Loop + Auto-Approve

**Files:**
- Modify: `standup.py` (add revenue logging in overnight steps + auto-approve)

- [ ] **Step 1: Write test**

Append to `tests/test_standup.py`:

```python
def test_pl_revenue_amount_for_emails():
    """Test revenue calculation for email triage."""
    from standup import PL_CONFIG
    hourly = PL_CONFIG["hourly_rate"]
    # 10 emails triaged at 0.5 min each = 5 min = $20.83
    count = 10
    minutes = count * PL_CONFIG["time_values"]["email_triage"]
    amount = round((minutes / 60) * hourly, 4)
    assert amount == 20.8333
```

- [ ] **Step 2: Run test**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_pl_revenue_amount_for_emails -v`
Expected: PASS

- [ ] **Step 3: Add a helper function for revenue calculation to standup.py**

Add this right after `PL_CONFIG`:

```python
def _log_revenue(category: str, count: int, description: str = ""):
    """Log P&L revenue for a batch of actions."""
    if count <= 0:
        return
    minutes = count * PL_CONFIG["time_values"].get(category, 0)
    if minutes <= 0:
        return
    amount = round((minutes / 60) * PL_CONFIG["hourly_rate"], 4)
    memory.log_pl_revenue(category, amount, description, {"count": count, "minutes": minutes})
```

- [ ] **Step 4: Add revenue logging to `_step_email_sweep()` return path**

In `standup.py`, find `_step_email_sweep()`. At the very end of the function, just before the `return` statement, add:

```python
    # Log P&L revenue
    total_triaged = len(reply_list) + len(read_list) + len(archived_list)
    _log_revenue("email_triage", total_triaged, f"{total_triaged} emails triaged")
    _log_revenue("draft_reply", len(reply_list), f"{len(reply_list)} draft replies written")
```

- [ ] **Step 5: Add revenue logging to `_step_calendar_scan()` return path**

In `standup.py`, find `_step_calendar_scan()`. At the very end, just before the `return` statement, add:

```python
    # Log P&L revenue
    _log_revenue("prep_brief", len(prep_briefs), f"{len(prep_briefs)} prep briefs drafted")
```

- [ ] **Step 6: Add revenue logging to `_step_forgetting_check()` return path**

In `standup.py`, find `_step_forgetting_check()`. At the very end, just before the `return reminders` statement, add:

```python
    # Log P&L revenue
    _log_revenue("reminder", len(reminders), f"{len(reminders)} reminders caught")
```

- [ ] **Step 7: Add revenue logging to `_step_scout_sweep()` return path**

In `standup.py`, find `_step_scout_sweep()`. The function just calls `_call_scout()` and returns. Replace it with:

```python
def _step_scout_sweep() -> dict:
    """Run Scout's daily research sweep across all 6 domains."""
    result = _call_scout()
    # Log P&L revenue
    findings_count = len(result.get("findings", []))
    _log_revenue("scout_finding", findings_count, f"{findings_count} Scout findings")
    return result
```

- [ ] **Step 8: Add revenue logging to `_execute_auto_approved()`**

In `standup.py`, find `_execute_auto_approved()`. At the end of the function (after the for loop), add:

```python
    # Log P&L revenue for auto-approved items
    _log_revenue("auto_approve", len(items), f"{len(items)} actions auto-approved")
```

- [ ] **Step 9: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: log P&L revenue in overnight loop steps + auto-approve"
```

---

### Task 4: Daily P&L in Standup + Deal Advance Bonus

**Files:**
- Modify: `standup.py` (add daily P&L line to overview message)
- Modify: `tools/deals.py` (add deal-advance bonus)

- [ ] **Step 1: Add daily P&L line to `_build_overview_message()`**

In `standup.py`, find `_build_overview_message()`. After the Scout section (after the `lines.append(f"🔍 {' · '.join(parts)}")` block) and before the `lines.append("\nWalking you through action items now ↓")` line, add:

```python
    # Daily P&L
    try:
        pl = memory.get_pl_daily()
        if pl["revenue"] > 0 or pl["costs"] > 0:
            roi = f"{pl['revenue'] / pl['costs']:.0f}x" if pl["costs"] > 0 else "∞"
            lines.append(f"💎 Yesterday: earned ${pl['revenue']:,.2f}, cost ${pl['costs']:,.2f} — ROI: {roi}")
    except Exception:
        pass  # Skip P&L line if no data yet
```

- [ ] **Step 2: Add deal-advance bonus to `tools/deals.py`**

In `tools/deals.py`, find the `update_deal()` function. After the line `memory.update_deal(deal_id, **kwargs)`, add:

```python
    # Log P&L bonus if a Scout-created deal advances past evaluating
    if stage and stage in ("loi", "due_diligence", "closing", "closed"):
        try:
            deal = memory.get_deal(deal_id)
            if deal and "scout" in (deal.get("source", "") or "").lower():
                # Check we haven't already logged a bonus for this deal
                from standup import PL_CONFIG
                existing = memory.get_pl_entries_by_metadata("deal_id", deal_id)
                if not existing:
                    memory.log_pl_revenue(
                        "deal_advanced",
                        PL_CONFIG["deal_advance_bonus"],
                        f"Deal #{deal_id} advanced to {stage}: {deal.get('title', '')}",
                        {"deal_id": deal_id, "stage": stage},
                    )
        except Exception:
            pass  # Don't break deal updates if P&L logging fails
```

- [ ] **Step 3: Add helper functions to memory.py for deal bonus dedup**

Append to `memory.py`:

```python
def get_deal(deal_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}deals WHERE id = %s", (deal_id,))
        return cur.fetchone()


def get_pl_entries_by_metadata(key: str, value) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}pl_entries WHERE metadata->>%s = %s",
            (key, str(value)),
        )
        return cur.fetchall()
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add standup.py tools/deals.py memory.py
git commit -m "feat: add daily P&L line to standup + deal-advance bonus logging"
```

---

### Task 5: Weekly P&L Digest + Hosting Cost Job

**Files:**
- Modify: `scheduler.py` (add weekly digest + daily hosting cost jobs)

- [ ] **Step 1: Add `send_weekly_pl_digest()` function to scheduler.py**

Add this after `deliver_standup()`:

```python
def send_weekly_pl_digest():
    """Send weekly P&L digest via Telegram. Scheduled Sunday 9pm ET (1am UTC Monday)."""
    try:
        pl = memory.get_pl_weekly()
        running = memory.get_pl_running_total()

        lines = ["📊 Shams Weekly P&L\n"]

        lines.append(f"Revenue: ${pl['revenue']:,.2f}")
        for cat, data in pl.get("revenue_breakdown", {}).items():
            label = cat.replace("_", " ").title()
            lines.append(f"  {label}: {data['count']}x (${data['total']:,.2f})")

        lines.append(f"\nCosts: ${pl['costs']:,.2f}")
        for cat, total in pl.get("cost_breakdown", {}).items():
            label = cat.replace("_", " ").title()
            if cat == "claude_api":
                tokens = pl.get("tokens", {})
                input_k = tokens.get("input", 0) // 1000
                output_k = tokens.get("output", 0) // 1000
                lines.append(f"  {label}: ${total:,.2f} ({input_k}K input / {output_k}K output)")
            else:
                lines.append(f"  {label}: ${total:,.2f}")

        net = pl["net"]
        roi = f"{pl['revenue'] / pl['costs']:.1f}x" if pl["costs"] > 0 else "∞"
        lines.append(f"\nNet: ${net:,.2f}")
        lines.append(f"ROI: {roi}")
        lines.append(f"\nRunning total: ${running['net']:,.2f}")

        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, "\n".join(lines))
        memory.log_activity("shams", "pl_digest", f"Weekly P&L: ${net:,.2f} net, {roi} ROI")
        logger.info("Weekly P&L digest sent")
    except Exception as e:
        logger.error(f"Weekly P&L digest failed: {e}", exc_info=True)


def log_daily_hosting():
    """Log daily Railway hosting cost. Scheduled at midnight UTC."""
    try:
        memory.log_pl_hosting_cost()
    except Exception as e:
        logger.error(f"Hosting cost logging failed: {e}")
```

- [ ] **Step 2: Wire new jobs into `init_scheduler()`**

In `scheduler.py`, in `init_scheduler()`, add these two lines after the `smart_alerts_check` job (before `scheduler.start()`):

```python
    scheduler.add_job(send_weekly_pl_digest, "cron", day_of_week="sun", hour=1, minute=0, id="weekly_pl")  # Sunday 9pm ET = 1am UTC Mon
    scheduler.add_job(log_daily_hosting, "cron", hour=0, minute=5, id="daily_hosting")  # 12:05am UTC daily
```

- [ ] **Step 3: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scheduler.py
git commit -m "feat: add weekly P&L digest (Sunday 9pm) + daily hosting cost job"
```

---

### Task 6: Deploy + Smoke Test

**Files:**
- None (deployment only)

- [ ] **Step 1: Push to GitHub**

```bash
cd /Users/mj/code/Shams && git push origin main
```

- [ ] **Step 2: Wait for Railway deploy**

```bash
/Users/mj/.local/bin/railway service status --all
```

Wait for `shams` → `SUCCESS`.

- [ ] **Step 3: Verify P&L table exists**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "SELECT * FROM shams_pl_entries LIMIT 5;"
```

Expected: Empty table.

- [ ] **Step 4: Test that API calls log costs**

Send a message to Shams via Telegram. Then check:

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "SELECT * FROM shams_pl_entries WHERE category = 'claude_api' ORDER BY created_at DESC LIMIT 3;"
```

Expected: At least one cost entry with input/output tokens in metadata.

- [ ] **Step 5: Tag the release**

```bash
cd /Users/mj/code/Shams && git tag -a shams-v2-pl -m "Shams v2: P&L attribution — self-tracking ROI engine"
git push origin shams-v2-pl
```
