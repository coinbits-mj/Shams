# Shams P&L — Self-Tracking ROI Engine

*Design spec — April 13, 2026*

## Overview

Shams runs a P&L like a business unit. Every API call logs its token cost. Every action logs its time-saved value at $250/hr. A daily summary appears in the morning standup overview, and a weekly detailed P&L digest drops Sunday night via Telegram.

## Revenue (Value Produced)

Shams calculates revenue from time saved at $250/hr:

| Action | Time value | How tracked |
|--------|-----------|-------------|
| Email triaged (reply/read/archive) | 30 sec each | Count from overnight email sweep |
| Draft reply written | 5 min each | Count from overnight + standup |
| Prep brief drafted | 15 min each | Count from calendar scan |
| Reminder caught (forgetting check) | 10 min each | Count from forgetting check |
| Action auto-approved | 2 min each | Count from trust system |
| Scout finding surfaced | 20 min each | Count from Scout sweep |
| Deal advanced past evaluating | $500 flat bonus | When a Scout-created deal moves to `loi` or beyond |

Time values are deliberately conservative so the P&L is credible. Conversion: `(minutes / 60) * 250 = dollar value`.

## Costs

| Cost | Source | How tracked |
|------|--------|-------------|
| Claude API (input tokens) | `response.usage.input_tokens` | Logged per call, priced at model rate |
| Claude API (output tokens) | `response.usage.output_tokens` | Logged per call, priced at model rate |
| Railway hosting | Fixed monthly | Hardcoded, divided by 30 for daily cost |

## Config

```python
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
    "deal_advance_bonus": 500,  # flat dollar bonus
    "token_pricing": {
        "input_per_million": 3.00,
        "output_per_million": 15.00,
    },
    "railway_monthly": 75,
}
```

## Database Table

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

Revenue categories: `email_triage`, `draft_reply`, `prep_brief`, `reminder`, `auto_approve`, `scout_finding`, `deal_advanced`.

Cost categories: `claude_api`, `railway_hosting`.

## Token Cost Tracking

In `claude_client.py`, after every `client.messages.create()` call, log token usage:

```python
if response.usage:
    memory.log_pl_cost(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        context="chat",
    )
```

Same pattern in `agents/registry.py` `call_agent()` with `context=f"agent:{agent_name}"`.

The `log_pl_cost()` function:
1. Calculates dollar cost: `(input_tokens / 1_000_000 * input_rate) + (output_tokens / 1_000_000 * output_rate)`
2. Inserts a `shams_pl_entries` row with `entry_type='cost'`, `category='claude_api'`
3. Stores token counts in `metadata` for the weekly digest breakdown

## Revenue Tracking

Revenue is logged at the point of action:

- **`_step_email_sweep()`** — after completing, log revenue for: `email_triage` (count of all triaged * 0.5 min) + `draft_reply` (count of reply tier * 5 min)
- **`_step_calendar_scan()`** — after completing, log revenue for `prep_brief` (count of briefs * 15 min)
- **`_step_forgetting_check()`** — after completing, log revenue for `reminder` (count of reminders * 10 min)
- **`_step_scout_sweep()`** — after completing, log revenue for `scout_finding` (count of findings * 20 min)
- **`_execute_auto_approved()`** — log revenue for `auto_approve` (count of items * 2 min)
- **`update_deal` tool** — when a deal with `source` containing "scout" advances to `loi`, `due_diligence`, `closing`, or `closed`, log `deal_advanced` ($500 bonus). Only log once per deal (check metadata for `deal_id`).

Revenue amount formula: `(minutes * hourly_rate) / 60`

## Daily Standup Line

Add to `_build_overview_message()` after the Scout line:

```
💎 Yesterday: Shams earned $187, cost $4.20 — ROI: 44x
```

Calculated from `get_pl_daily(yesterday)`. If no data yet (first day), skip the line.

## Weekly Digest

New scheduled job `send_weekly_pl_digest()` runs Sunday at 1:00 UTC (9pm ET Saturday). Sends:

```
📊 Shams Weekly P&L — Apr 7-13

Revenue: $1,247.00
  Emails: 312 triaged ($650.00)
  Drafts: 18 written ($375.00)
  Prep briefs: 4 ($250.00)
  Reminders: 7 ($291.67)
  Scout findings: 3 ($250.00)
  Auto-approved: 12 ($100.00)

Costs: $31.40
  Claude API: $28.90 (412K input / 89K output tokens)
  Railway: $2.50

Net: $1,215.60
ROI: 39.7x

Running total (since Apr 13): $1,215.60
```

## Memory Layer Functions

- `log_pl_revenue(category, amount, description="", metadata=None)` — insert revenue entry for today
- `log_pl_cost(input_tokens=0, output_tokens=0, context="")` — calculate cost from tokens using PL_CONFIG pricing, insert cost entry
- `log_pl_hosting_cost()` — insert daily Railway hosting cost (`railway_monthly / 30`)
- `get_pl_daily(date=None)` — returns `{"revenue": float, "costs": float, "net": float, "entries": list}` for a date (defaults to yesterday)
- `get_pl_weekly(weeks_ago=0)` — returns current (or past) week's P&L with category breakdowns
- `get_pl_running_total()` — returns all-time `{"revenue": float, "costs": float, "net": float}`

## Files Changed

| File | Change |
|------|--------|
| `schema.sql` | Add `shams_pl_entries` table |
| `memory.py` | Add 6 P&L functions |
| `standup.py` | Add `PL_CONFIG`, log revenue in each overnight step + auto-approve, add daily P&L line to overview |
| `claude_client.py` | Log token costs after every `messages.create()` call |
| `agents/registry.py` | Log token costs after agent `messages.create()` calls |
| `scheduler.py` | Add weekly P&L digest job + `log_pl_hosting_cost` daily job |
| `tools/deals.py` | Log deal-advance bonus in `update_deal` when Scout deal passes evaluating |
| `tests/test_standup.py` | Tests for P&L revenue calculation, cost calculation, daily summary |

## What This Does NOT Include

- No dashboard P&L page — that's Dashboard Improvements
- No cost tracking for OpenAI Whisper (voice transcription) — minor and infrequent
- No cost tracking for web search API — add later if significant
- No retroactive P&L — starts tracking from deployment date forward
- No P&L for Rumi or Leo API calls — only Shams's own Claude API usage
