# Trust System — Per-Action-Type Autonomous Approval

*Design spec — April 13, 2026*

## Overview

Each action type (email_archive, email_draft, deal_create, scout_outreach, etc.) has its own independent trust track. As MJ approves actions through the standup drip-feed, trust builds per type. Once a type crosses its threshold, those actions auto-approve — they execute silently, log to the activity feed, but skip the standup drip-feed. If MJ rejects 2 actions of the same type within 7 days, auto-approve revokes for that type.

## Trust Tiers

Three risk tiers with different thresholds:

| Tier | Action types | Threshold | Rejection tolerance |
|------|-------------|-----------|---------------------|
| **Low risk** | `email_archive`, `mission_create`, `loop_close`, `reminder_ack` | 5 approvals | <20% rejection rate |
| **Medium risk** | `email_draft`, `deal_create`, `deal_update`, `prep_brief` | 15 approvals | <10% rejection rate |
| **High risk** | `scout_outreach`, `email_send`, `action_execute` | 30 approvals | <5% rejection rate |

### Tier assignment

Each action type has a hardcoded tier mapping in the code:

```python
TRUST_TIERS = {
    # Low risk — 5 approvals, <20% rejection
    "email_archive": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "mission_create": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "loop_close": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    "reminder_ack": {"tier": "low", "threshold": 5, "max_rejection_pct": 20},
    # Medium risk — 15 approvals, <10% rejection
    "email_draft": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "deal_create": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "deal_update": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    "prep_brief": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
    # High risk — 30 approvals, <5% rejection
    "scout_outreach": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
    "email_send": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
    "action_execute": {"tier": "high", "threshold": 30, "max_rejection_pct": 5},
}
```

Unknown action types default to medium risk.

## Database Table

New table `shams_trust_actions` (the existing `shams_trust_scores` table is per-agent and stays as-is):

```sql
CREATE TABLE IF NOT EXISTS shams_trust_actions (
    id              SERIAL PRIMARY KEY,
    action_type     VARCHAR(50) NOT NULL UNIQUE,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Note: The rejection window (2 rejections in 7 days) is computed dynamically from the activity feed — we don't need to store `last_rejection` or `rejection_count_7d` in the table. The activity feed already logs every approval and rejection with timestamps.

## Trust Logic

### On approval (standup callback: su_send, su_ok)

1. Map the standup item type to an action type:
   - `reply` → `email_draft`
   - `prep` → `prep_brief`
   - `reminder` → `reminder_ack`
   - `scout_outreach` → `scout_outreach`
   - `scout_info` → `deal_create`

2. Call `increment_trust_approval(action_type)`:
   - Upsert `shams_trust_actions` row, increment `total_approved`
   - Look up tier config from `TRUST_TIERS`
   - If `total_approved >= threshold` AND rejection rate < max_rejection_pct → set `auto_approve = true`
   - Log activity: `"Trust unlocked for {action_type}"` (only on first unlock)

### On rejection (standup callback: su_skip is neutral, explicit reject or consecutive skips are not rejection)

Only actual rejections count — which in the current standup flow means:
- The existing action `approve`/`reject` callback system (non-standup actions via `handle_callback`)
- A future explicit "Reject" button if added

For now, `su_skip` is neutral. The trust system tracks approvals to build trust. Rejections come from the existing action approval system in `telegram.py` (the `approve`/`reject` callbacks on `shams_actions`).

When a rejection happens:
1. Call `increment_trust_rejection(action_type)`:
   - Increment `total_rejected`
   - Count rejections in last 7 days from activity feed
   - If count >= 2 AND `auto_approve = true` → set `auto_approve = false`
   - Log activity: `"Trust revoked for {action_type}"`

### Auto-approve check

`should_auto_approve_action(action_type) -> bool`:
- Look up row in `shams_trust_actions`
- Return `auto_approve` column value (default `false` if no row)

## Standup Integration

### During `_build_action_items()`

Before adding each item to the drip-feed list, check `should_auto_approve_action(action_type)`. If auto-approved:
- Execute the action silently (e.g., save Gmail draft, log deal creation)
- Add to an `auto_approved` list instead of the `items` list
- Don't include in the drip-feed

### During `deliver_morning_standup()`

After building action items, if there are auto-approved items, add a summary line to the overview message:

```
✅ 3 auto-approved (2 email drafts saved, 1 deal created)
```

If ALL items are auto-approved, send a short standup instead of the drip-feed:

```
✅ Standup done. Everything auto-approved today. 3 drafts saved, 2 deals created, 15 archived. Have a good one.
```

### Action type mapping for standup items

| Standup item type | Trust action type |
|-------------------|-------------------|
| `reply` | `email_draft` |
| `prep` | `prep_brief` |
| `reminder` | `reminder_ack` |
| `scout_outreach` | `scout_outreach` |
| `scout_info` | `deal_create` |

## Memory Layer Functions

Add to `memory.py`:

- `get_trust_for_action(action_type) -> dict | None` — Get trust record for an action type
- `increment_trust_approval(action_type) -> bool` — Increment approval count, check threshold, return whether auto_approve was newly unlocked
- `increment_trust_rejection(action_type)` — Increment rejection count, check 7-day window, revoke if needed
- `should_auto_approve_action(action_type) -> bool` — Check if an action type is auto-approved
- `get_trust_summary() -> list[dict]` — Get all trust records (for future Settings page)

## Files Changed

| File | Change |
|------|--------|
| `schema.sql` | Add `shams_trust_actions` table |
| `memory.py` | Add trust action CRUD functions (5 functions) |
| `standup.py` | Add `TRUST_TIERS` config. Update `_build_action_items()` to filter auto-approved. Update `deliver_morning_standup()` for auto-approve summary. Add `_execute_auto_approved()` helper. |
| `telegram.py` | Update standup callbacks (su_send, su_ok) to call `increment_trust_approval()`. Update action reject callback to call `increment_trust_rejection()`. |
| `tests/test_standup.py` | Tests for trust thresholds, auto-approve logic, rejection window, tier mapping |

## What This Does NOT Include

- No Settings page UI — trust is managed automatically via thresholds. Dashboard Settings page is a separate sub-project.
- No per-agent trust changes — the existing `shams_trust_scores` table stays as-is
- No "undo auto-approve" in Telegram — revocation happens via the strike system (2 rejections in 7 days) or eventually via Settings page
- `su_skip` is neutral — does not count as approval or rejection
- No notification when trust unlocks — just an activity feed log entry (could add Telegram notification later)
