# Shams v2 Sub-project B: Overnight Ops + Morning Standup

*Design spec — April 12, 2026*

## Overview

Shams runs an autonomous overnight loop at 3am ET that sweeps email, checks financials, reviews ops, scans the calendar, and cross-references everything against active missions and open loops to catch things MJ might be forgetting. At 7am ET, a morning standup lands in Telegram: a single overview message followed by drip-fed action items — each with one-tap buttons (Send/Edit/Skip). The goal is that MJ wakes up to a chief of staff who already did the overnight work and just needs sign-off.

## Email Triage — 3 Tiers

Replace the current P1/P2/P3/P4 system with three tiers that map to actions:

| Tier | Meaning | Overnight action | Standup action |
|------|---------|------------------|----------------|
| **Reply** | Needs a response from MJ | Shams drafts a reply | Drip-fed with Send / Edit / Skip buttons |
| **Read** | Worth seeing, no action needed | Flagged for standup | Listed in overview as "X to read" |
| **Archive** | Junk, promotional, noise | Auto-archived via Gmail API | Summarized in one line ("14 Shopify notifications, 3 newsletters, a Square receipt") |

### Schema change

Update `shams_email_triage`:
- Replace `priority VARCHAR(5)` with `tier VARCHAR(10) CHECK (tier IN ('reply', 'read', 'archive'))`
- `draft_reply` column stays — populated for `reply` tier emails
- `action` column stays — holds specific recommended action text
- `routed_to` column stays — still useful for specialist routing

### Triage prompt update

Update the classification prompt in `tools/google.py` `triage_inbox` tool:
- **Reply**: sender is a real person or business contact, email asks a question or requests something, or is time-sensitive. Draft a reply in MJ's voice — direct, concise, professional.
- **Read**: informational email from a known source (bank alerts, service notifications with useful info, industry news MJ follows). No reply needed but MJ should see it.
- **Archive**: promotional, marketing, automated notifications with no useful info, spam, newsletters MJ doesn't read. Auto-archive silently.

## Overnight Loop (3am ET)

A single APScheduler cron job (`overnight_loop()`) that runs the Shams agent through 5 sequential steps. Each step logs results to a `shams_overnight_runs` record. If any step fails, the others still run — the failure is logged and surfaced in the standup.

### Step 1: Email Sweep

1. Pull unread emails from all 3 Google accounts (up to 50 per account)
2. Classify each as Reply / Read / Archive using updated triage prompt
3. For Reply tier: draft a response in MJ's voice, save to `shams_email_triage` with `draft_reply` populated
4. For Archive tier: auto-archive via Gmail API (mark as read + archive), save triage record with `archived = true`
5. For Read tier: save triage record for standup display
6. Compose archive summary in Shams's own words (e.g., "Cleared out 14 Shopify order notifications, 3 newsletters from Specialty Coffee Association, and a Square deposit receipt")

### Step 2: Mercury Balance Check

1. Pull balances from all 4 Mercury entities (Clifton, Plainfield, Personal, Coinbits)
2. Pull recent transactions (last 24 hours)
3. Flag anomalies:
   - Any account below $5,000
   - Any single transaction above $5,000
   - Unusual patterns (significantly higher/lower than recent daily average)
4. Store balances and alerts in overnight run results

### Step 3: Rumi Ops Check

1. Pull yesterday's daily P&L from Rumi
2. Pull inventory alerts (low stock, items needing reorder)
3. Pull action items from Rumi
4. Pull cashflow forecast if available
5. Store results — revenue, COGS, margin, order count, alerts

### Step 4: Calendar Scan + Prep

1. Pull today's calendar events from all 3 Google accounts
2. For each meeting:
   - Check if there's a related active mission or open loop
   - If a meeting has a related mission with incomplete work, draft a prep brief (2-3 paragraphs: context, key points, what MJ should push for)
   - Flag any meetings that look like they need prep but have none
3. Flag calendar conflicts (overlapping events)
4. Store events, prep briefs, and flags in overnight run results

### Step 5: Forgetting Check

Cross-reference all active state to catch things MJ might be dropping:

1. **Stale missions** — active missions with no activity in 3+ days. Draft next-step recommendations.
2. **Approaching deadlines** — missions or deals with deadlines in the next 7 days. Draft status updates or action plans.
3. **Orphaned open loops** — open loops with no related mission or calendar entry. Suggest: close, create mission, or schedule time.
4. **Pending actions** — actions stuck in pending for 24+ hours. Resurface them.
5. **Unscheduled important work** — active missions with no calendar time blocked. Suggest when to work on them based on calendar gaps.

For items that need work product, Shams drafts actual deliverables:
- Meeting prep briefs
- Mission status summaries
- Next-step action plans
- Draft communications (if a mission involves reaching out to someone)

These drafts are stored in the overnight run results and delivered as action items in the standup.

## Morning Standup (7am ET)

Replaces the current morning briefing. Delivered via Telegram in two phases.

### Phase 1: Overview Message

A single Telegram message with the full picture. Sent immediately at 7am.

```
☀️ Morning Standup — Sat Apr 12

📬 3 replies drafted · 5 to read · 23 archived
💰 Total cash: $77,932 · ⚠️ Coinbits low ($3,200)
📊 Yesterday: $1,847 rev / 50% margin / 12 orders
📅 2 meetings today · ⚠️ supplier call needs prep
🔔 3 things you might be forgetting

Walking you through action items now ↓
```

Format rules:
- One line per section, emoji prefix, key numbers only
- Warning emoji (⚠️) for anything that needs attention
- Ends with a transition to the drip-feed

### Phase 2: Drip-Feed Action Items

One Telegram message per item that needs MJ's input. Sent sequentially after the overview. Each message has inline keyboard buttons.

**Order of delivery:**
1. Draft replies (most time-sensitive) — "Reply 1/3", "Reply 2/3", etc.
2. Drafted briefs/work product — meeting prep, mission next steps
3. Flags — low balances, stale missions, forgotten items

**Draft reply format:**
```
📬 Reply 1/3
From: Ahmed @ Café Imports
Re: Green coffee pricing Q2

Draft: "Thanks Ahmed. Can you send the updated pricing for the Ethiopian Yirgacheffe and the Sumatra? We're placing our Q2 order next week."

[✓ Send]  [✏️ Edit]  [Skip]
```

**Work product format:**
```
📋 Prep: Supplier call at 10:00

You're meeting with Café Imports about Q2 pricing. The Red Mountain Sumatra has been your top seller — push for volume pricing. Last order was 300 lbs at $4.80/lb. Current market is trending down.

Key points:
• Ask about the Yirgacheffe availability (was backordered in March)
• Volume discount threshold — can we get to $4.50 at 500 lbs?
• Payment terms — they offered net-30 last quarter

[👍 Looks good]  [✏️ Edit]  [Skip]
```

**Reminder format:**
```
🔔 Don't forget: Wholesale portal deploy
Been idle 3 days. The code is ready (all 296 tests passing). Want me to create a deploy mission?

[Got it]  [Snooze]  [Create mission]
```

### Edit Flow

When MJ taps "Edit" on any item:
1. Shams quotes the draft in a new message: "Here's the current draft — send me your version:"
2. MJ types their edited version as a regular Telegram message
3. Shams confirms and executes: "Got it. Sending now." / "Saved the updated brief."

This uses the existing Telegram message flow — no special UI needed. The callback handler sets a state flag so the next text message from MJ is treated as an edit rather than a new conversation.

### Wrap-Up

After all action items are handled (or 2 hours pass with no response), Shams sends a wrap-up:
```
✅ Standup done. 2 emails sent, 1 skipped, 1 brief saved, 23 archived. Have a good one.
```

## Standup State Machine

The standup is a stateful flow managed in memory. States:

```
idle → overview_sent → dripping → waiting_for_edit → dripping → complete
```

- `idle` — no standup in progress
- `overview_sent` — overview delivered, about to start dripping
- `dripping` — sending action items one at a time, waiting for button press
- `waiting_for_edit` — user tapped Edit, next text message is their edit
- `complete` — all items handled or timed out

State is stored in `shams_memory` as a key-value pair: `standup_state` → JSON with current state, current item index, overnight run ID, and edit context.

## New Database Table

```sql
CREATE TABLE shams_overnight_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      VARCHAR(20) DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    results     JSONB DEFAULT '{}',
    summary     TEXT DEFAULT ''
);
```

The `results` JSONB structure:

```json
{
  "email": {
    "reply": [{"account": "...", "message_id": "...", "from": "...", "subject": "...", "draft": "..."}],
    "read": [{"account": "...", "message_id": "...", "from": "...", "subject": "...", "snippet": "..."}],
    "archived": [{"account": "...", "message_id": "...", "from": "...", "subject": "..."}],
    "archive_summary": "Cleared out 14 Shopify order notifications, 3 newsletters..."
  },
  "mercury": {
    "balances": {"clifton": 14230, "plainfield": 8102, "personal": 52400, "coinbits": 3200},
    "alerts": [{"type": "low_balance", "account": "coinbits", "balance": 3200}],
    "recent_transactions": [...]
  },
  "rumi": {
    "revenue": 1847,
    "cogs": 923,
    "margin": 0.50,
    "orders": 12,
    "wholesale_orders": 3,
    "alerts": [],
    "action_items": []
  },
  "calendar": {
    "events": [{"time": "10:00", "title": "...", "account": "..."}],
    "prep_briefs": [{"event_title": "...", "brief": "..."}],
    "conflicts": []
  },
  "reminders": [
    {"title": "Wholesale portal deploy", "why": "Been idle 3 days, code is ready", "suggestion": "Create deploy mission", "draft": null},
    {"title": "Red House LOI response", "why": "Due Monday", "suggestion": "Review and send", "draft": "..."}
  ]
}
```

## Config Changes

Two new environment variables in `config.py`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OVERNIGHT_HOUR_UTC` | `7` | Hour (UTC) to run overnight loop. Default = 3am ET. |
| `STANDUP_HOUR_UTC` | `11` | Hour (UTC) to deliver morning standup. Default = 7am ET. |

The existing `BRIEFING_HOUR_UTC` is retired — replaced by `STANDUP_HOUR_UTC`.

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `OVERNIGHT_HOUR_UTC`, `STANDUP_HOUR_UTC`. Remove `BRIEFING_HOUR_UTC`. |
| `schema.sql` | Add `shams_overnight_runs` table. Update `shams_email_triage` — replace `priority` with `tier`. |
| `memory.py` | Add: `create_overnight_run()`, `update_overnight_run()`, `get_latest_overnight_run()`, `get_standup_state()`, `set_standup_state()`. Update email triage functions for tier field. |
| `standup.py` | New file — replaces `briefing.py`. Contains `run_overnight_loop()` (5-step autonomous loop) and `deliver_morning_standup()` (overview + drip-feed). |
| `briefing.py` | Deleted — functionality moves to `standup.py`. |
| `scheduler.py` | Replace morning briefing job with `overnight_loop` at 3am and `morning_standup` at 7am. Keep evening briefing as-is. |
| `tools/google.py` | Update `triage_inbox` tool — change classification from P1-P4 to Reply/Read/Archive tiers. |
| `telegram.py` | Add callback handlers for standup buttons: `standup_send`, `standup_edit`, `standup_skip`, `standup_gotit`, `standup_snooze`, `standup_create_mission`. Add edit state handling in `process_message()`. |
| `claude_client.py` | Update overnight hot context slot (ET < 5) to include latest overnight run results. |

## What This Does NOT Include

- **Dashboard changes** — overnight run results are viewable via activity feed (already logged). A dedicated overnight ops dashboard page is a future enhancement.
- **Trust-based auto-send** — all Reply drafts require MJ's approval. Auto-send based on trust scores is Sub-project D territory.
- **Evening briefing changes** — the evening briefing stays as-is. It could be converted to a similar standup format later.
- **Gmail send** — `google_client.py` already has `archive_email()`, `send_email()`, and other Gmail action functions with the necessary scopes. No new OAuth setup needed.
