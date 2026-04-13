# Trust System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-action-type trust tracking that auto-approves low-risk standup items after enough approvals, with a strike system that revokes trust after 2 rejections in 7 days.

**Architecture:** A new `shams_trust_actions` table tracks approval/rejection counts per action type. Trust tier config (`TRUST_TIERS`) defines thresholds. During standup delivery, auto-approved items execute silently and skip the drip-feed. Telegram callbacks increment trust on approval. The existing per-agent trust system stays untouched.

**Tech Stack:** Python 3.9+ (`from __future__ import annotations`), PostgreSQL, existing standup + Telegram callback infrastructure

**Spec:** `docs/superpowers/specs/2026-04-13-trust-system-design.md`

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `schema.sql` | Add `shams_trust_actions` table | Modify |
| `memory.py` | Trust action CRUD (5 functions) | Modify |
| `standup.py` | `TRUST_TIERS` config, auto-approve filtering in action items, silent execution | Modify |
| `telegram.py` | Increment trust on standup approvals | Modify |
| `tests/test_standup.py` | Trust threshold + auto-approve tests | Modify |

---

### Task 1: Schema + Memory Layer — Trust Action CRUD

**Files:**
- Modify: `schema.sql` (append table)
- Modify: `memory.py` (append 5 functions)
- Modify: `tests/test_standup.py` (add tests)

- [ ] **Step 1: Write tests**

Append to `tests/test_standup.py`:

```python
def test_trust_tier_config():
    """Test that TRUST_TIERS config exists and has expected structure."""
    from standup import TRUST_TIERS
    assert "email_draft" in TRUST_TIERS
    assert "scout_outreach" in TRUST_TIERS
    assert TRUST_TIERS["email_draft"]["threshold"] == 15
    assert TRUST_TIERS["scout_outreach"]["threshold"] == 30
    assert TRUST_TIERS["email_archive"]["threshold"] == 5


def test_should_auto_approve_action_default_false():
    """Test that unknown action types are not auto-approved."""
    import memory
    result = memory.should_auto_approve_action("nonexistent_action_type_xyz")
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_trust_tier_config tests/test_standup.py::test_should_auto_approve_action_default_false -v`
Expected: FAIL

- [ ] **Step 3: Add `shams_trust_actions` table to schema.sql**

Append to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS shams_trust_actions (
    id              SERIAL PRIMARY KEY,
    action_type     VARCHAR(50) NOT NULL UNIQUE,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trust_actions_type ON shams_trust_actions (action_type);
```

- [ ] **Step 4: Run schema migration on Railway**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "
CREATE TABLE IF NOT EXISTS shams_trust_actions (
    id              SERIAL PRIMARY KEY,
    action_type     VARCHAR(50) NOT NULL UNIQUE,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trust_actions_type ON shams_trust_actions (action_type);
"
```

- [ ] **Step 5: Add TRUST_TIERS config to standup.py**

Add this near the top of `standup.py`, after the `logger = logging.getLogger(__name__)` line:

```python
# ── Trust tier configuration ───────────────────────────────────────────────

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

# Map standup item types to trust action types
STANDUP_TRUST_MAP = {
    "reply": "email_draft",
    "prep": "prep_brief",
    "reminder": "reminder_ack",
    "scout_outreach": "scout_outreach",
    "scout_info": "deal_create",
}
```

- [ ] **Step 6: Add 5 trust functions to memory.py**

Append to `memory.py`:

```python
# ── Trust Actions (per-action-type) ────────────────────────────────────────

def get_trust_for_action(action_type: str) -> dict | None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}trust_actions WHERE action_type = %s", (action_type,))
        return cur.fetchone()


def increment_trust_approval(action_type: str) -> bool:
    """Increment approval count. Returns True if auto_approve was newly unlocked."""
    from standup import TRUST_TIERS
    tier_config = TRUST_TIERS.get(action_type, {"threshold": 15, "max_rejection_pct": 10})

    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"INSERT INTO {P}trust_actions (action_type, total_approved) VALUES (%s, 1) "
            f"ON CONFLICT (action_type) DO UPDATE SET total_approved = {P}trust_actions.total_approved + 1, "
            f"updated_at = NOW() RETURNING *",
            (action_type,),
        )
        row = cur.fetchone()

    if not row or row["auto_approve"]:
        return False  # Already auto-approved or error

    total = row["total_approved"] + row["total_rejected"]
    rejection_pct = (row["total_rejected"] / total * 100) if total > 0 else 0

    if row["total_approved"] >= tier_config["threshold"] and rejection_pct < tier_config["max_rejection_pct"]:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {P}trust_actions SET auto_approve = TRUE, updated_at = NOW() "
                f"WHERE action_type = %s AND auto_approve = FALSE",
                (action_type,),
            )
        log_activity("shams", "trust_unlocked", f"Auto-approve unlocked for {action_type}")
        return True

    return False


def increment_trust_rejection(action_type: str):
    """Increment rejection count. Revokes auto-approve if 2+ rejections in 7 days."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}trust_actions (action_type, total_rejected) VALUES (%s, 1) "
            f"ON CONFLICT (action_type) DO UPDATE SET total_rejected = {P}trust_actions.total_rejected + 1, "
            f"updated_at = NOW()",
            (action_type,),
        )

    # Check 7-day rejection window from activity feed
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {P}activity_feed WHERE event_type = 'trust_rejection' "
            f"AND content LIKE %s AND timestamp > NOW() - INTERVAL '7 days'",
            (f"%{action_type}%",),
        )
        recent_rejections = cur.fetchone()[0] + 1  # +1 for this rejection

    log_activity("shams", "trust_rejection", f"Rejection recorded for {action_type}")

    if recent_rejections >= 2:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {P}trust_actions SET auto_approve = FALSE, updated_at = NOW() "
                f"WHERE action_type = %s AND auto_approve = TRUE",
                (action_type,),
            )
            if cur.rowcount > 0:
                log_activity("shams", "trust_revoked", f"Auto-approve revoked for {action_type} (2+ rejections in 7 days)")


def should_auto_approve_action(action_type: str) -> bool:
    """Check if an action type is auto-approved."""
    row = get_trust_for_action(action_type)
    if not row:
        return False
    return row["auto_approve"]


def get_trust_summary() -> list[dict]:
    """Get all trust records for dashboard/settings."""
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}trust_actions ORDER BY action_type")
        return cur.fetchall()
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_trust_tier_config tests/test_standup.py::test_should_auto_approve_action_default_false -v`
Expected: PASS

- [ ] **Step 8: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add schema.sql memory.py standup.py tests/test_standup.py
git commit -m "feat: add trust actions table + CRUD + tier config for per-action-type trust"
```

---

### Task 2: Standup Auto-Approve Filtering + Silent Execution

**Files:**
- Modify: `standup.py` (update `deliver_morning_standup`, `_build_action_items`, `_build_overview_message`)

- [ ] **Step 1: Write test**

Append to `tests/test_standup.py`:

```python
def test_auto_approved_items_filtered_from_drip_feed():
    """Test that auto-approved items don't appear in the drip-feed."""
    from unittest.mock import patch
    import standup

    results = {
        "email": {
            "reply": [
                {"from": "ahmed@test.com", "subject": "Pricing", "draft": "Thanks", "triage_id": 1, "account": "qcc", "message_id": "abc"},
            ],
            "read": [], "archived": [], "archive_summary": "",
        },
        "mercury": {"balances": {}, "grand_total": 0, "alerts": []},
        "rumi": {},
        "calendar": {"events": [], "prep_briefs": []},
        "reminders": [{"title": "Test reminder", "why": "testing", "suggestion": "", "draft": "", "mission_id": None, "loop_id": None, "action_id": None}],
        "scout": {"findings": [], "searches_run": 0, "new_deals": 0, "updated_deals": 0},
    }

    # With no trust, both items should appear
    with patch("standup.memory") as mock_mem:
        mock_mem.should_auto_approve_action.return_value = False
        items, auto = standup._build_action_items_with_trust(results)
        assert len(items) == 2  # reply + reminder
        assert len(auto) == 0

    # With email_draft auto-approved, only reminder should appear
    with patch("standup.memory") as mock_mem:
        def side_effect(action_type):
            return action_type == "email_draft"
        mock_mem.should_auto_approve_action.side_effect = side_effect
        items, auto = standup._build_action_items_with_trust(results)
        assert len(items) == 1  # only reminder
        assert items[0]["type"] == "reminder"
        assert len(auto) == 1
        assert auto[0]["type"] == "reply"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_auto_approved_items_filtered_from_drip_feed -v`
Expected: FAIL — `AttributeError: module 'standup' has no attribute '_build_action_items_with_trust'`

- [ ] **Step 3: Add `_build_action_items_with_trust()` to standup.py**

Add this function right after `_build_action_items()`:

```python
def _build_action_items_with_trust(results: dict) -> tuple[list[dict], list[dict]]:
    """Build action items, separating auto-approved from manual.

    Returns (manual_items, auto_approved_items).
    """
    all_items = _build_action_items(results)
    manual = []
    auto_approved = []

    for item in all_items:
        action_type = STANDUP_TRUST_MAP.get(item["type"])
        if action_type and memory.should_auto_approve_action(action_type):
            auto_approved.append(item)
        else:
            manual.append(item)

    return manual, auto_approved
```

- [ ] **Step 4: Update `deliver_morning_standup()` to use trust filtering**

In `standup.py`, find `deliver_morning_standup()`. Replace the section that builds action items and checks if empty. Find these lines:

```python
    # Phase 2: Build action items list and start dripping
    action_items = _build_action_items(results)

    if not action_items:
        if config.TELEGRAM_CHAT_ID:
            send_telegram(config.TELEGRAM_CHAT_ID, "Nothing needs your input today. Have a good one.")
        return
```

Replace with:

```python
    # Phase 2: Build action items, filtering auto-approved
    action_items, auto_approved = _build_action_items_with_trust(results)

    # Execute auto-approved items silently
    if auto_approved:
        _execute_auto_approved(auto_approved)

    if not action_items:
        # Everything was auto-approved or nothing needed input
        auto_summary = _build_auto_approve_summary(auto_approved)
        if config.TELEGRAM_CHAT_ID:
            if auto_approved:
                send_telegram(config.TELEGRAM_CHAT_ID,
                              f"✅ Standup done. Everything auto-approved today. {auto_summary}. Have a good one.")
            else:
                send_telegram(config.TELEGRAM_CHAT_ID, "Nothing needs your input today. Have a good one.")
        return
```

- [ ] **Step 5: Add `_execute_auto_approved()` and `_build_auto_approve_summary()` to standup.py**

Add these after `_build_action_items_with_trust()`:

```python
def _execute_auto_approved(items: list[dict]):
    """Execute auto-approved standup items silently."""
    import google_client

    for item in items:
        try:
            if item["type"] == "reply":
                # Save draft to Gmail
                if item.get("message_id") and item.get("draft"):
                    google_client.create_draft_reply(item["account"], item["message_id"], item["draft"])
                    memory.log_activity("shams", "auto_approved", f"Draft auto-saved: {item.get('subject', '')}")
            elif item["type"] == "prep":
                memory.log_activity("shams", "auto_approved", f"Prep brief auto-approved: {item.get('event', '')}")
            elif item["type"] == "reminder":
                memory.log_activity("shams", "auto_approved", f"Reminder auto-acked: {item.get('title', '')}")
            elif item["type"] == "scout_outreach":
                memory.log_activity("shams", "auto_approved", f"Scout outreach auto-approved: {item.get('title', '')}")
            elif item["type"] == "scout_info":
                memory.log_activity("shams", "auto_approved", f"Scout finding auto-acked: {item.get('title', '')}")
        except Exception as e:
            logger.error(f"Auto-approve execution failed for {item.get('type')}: {e}")


def _build_auto_approve_summary(items: list[dict]) -> str:
    """Build a short summary of what was auto-approved."""
    counts = {}
    for item in items:
        label = {
            "reply": "email draft",
            "prep": "prep brief",
            "reminder": "reminder",
            "scout_outreach": "scout outreach",
            "scout_info": "scout finding",
        }.get(item["type"], item["type"])
        counts[label] = counts.get(label, 0) + 1

    parts = []
    for label, count in counts.items():
        parts.append(f"{count} {label}{'s' if count != 1 else ''}")
    return ", ".join(parts) if parts else "0 items"
```

- [ ] **Step 6: Update `_build_overview_message()` to include auto-approve line**

In `standup.py`, find `_build_overview_message()`. The function currently receives `results` only. We need to also pass auto-approved count. The simplest approach: add the auto-approve line in `deliver_morning_standup()` instead of modifying the function signature.

In `deliver_morning_standup()`, after the overview is sent and auto_approved items are available, insert the auto-approve notification. Find the line:

```python
    if config.TELEGRAM_CHAT_ID:
        send_telegram(config.TELEGRAM_CHAT_ID, overview)
```

Replace with:

```python
    if config.TELEGRAM_CHAT_ID:
        if auto_approved:
            auto_summary = _build_auto_approve_summary(auto_approved)
            overview += f"\n✅ {len(auto_approved)} auto-approved ({auto_summary})"
        send_telegram(config.TELEGRAM_CHAT_ID, overview)
```

- [ ] **Step 7: Run test**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_auto_approved_items_filtered_from_drip_feed -v`
Expected: PASS

- [ ] **Step 8: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: auto-approve trusted action types in standup — filter + silent execution"
```

---

### Task 3: Telegram Callbacks — Trust Tracking on Approve

**Files:**
- Modify: `telegram.py` (update standup callback handler)

- [ ] **Step 1: Write test**

Append to `tests/test_standup.py`:

```python
def test_standup_trust_map_covers_all_item_types():
    """Test that STANDUP_TRUST_MAP covers all standup item types."""
    from standup import STANDUP_TRUST_MAP
    expected_types = ["reply", "prep", "reminder", "scout_outreach", "scout_info"]
    for t in expected_types:
        assert t in STANDUP_TRUST_MAP, f"Missing trust mapping for standup type: {t}"
```

- [ ] **Step 2: Run test**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_standup_trust_map_covers_all_item_types -v`
Expected: PASS (already implemented in Task 1)

- [ ] **Step 3: Update `_handle_standup_callback` in telegram.py to track trust**

In `telegram.py`, find the `_handle_standup_callback` function. We need to add trust tracking when MJ approves (su_send, su_ok) or when future rejection logic is added.

After the line `handled[str(idx)] = "sent"` in the `su_send` block, add:

```python
        # Track trust
        from standup import STANDUP_TRUST_MAP
        trust_type = STANDUP_TRUST_MAP.get(item.get("type", ""))
        if trust_type:
            memory.increment_trust_approval(trust_type)
```

After the line `handled[str(idx)] = "ok"` in the `su_ok` block (but before the prep brief log), add:

```python
        # Track trust
        from standup import STANDUP_TRUST_MAP
        trust_type = STANDUP_TRUST_MAP.get(item.get("type", ""))
        if trust_type:
            memory.increment_trust_approval(trust_type)
```

After the line `handled[str(idx)] = "mission"` in the `su_mission` block, add:

```python
        # Track trust (creating a mission counts as approval)
        from standup import STANDUP_TRUST_MAP
        trust_type = STANDUP_TRUST_MAP.get(item.get("type", ""))
        if trust_type:
            memory.increment_trust_approval(trust_type)
```

Note: `su_skip` and `su_snooze` are intentionally NOT tracked — they're neutral.

- [ ] **Step 4: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telegram.py tests/test_standup.py
git commit -m "feat: track trust approvals on standup callbacks (su_send, su_ok, su_mission)"
```

---

### Task 4: Deploy + Smoke Test

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

Wait for `shams` status to show `SUCCESS`.

- [ ] **Step 3: Verify trust table exists**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run psql '$DATABASE_URL' -c "SELECT * FROM shams_trust_actions;"
```

Expected: Empty table (no rows yet — trust builds through usage).

- [ ] **Step 4: Tag the release**

```bash
cd /Users/mj/code/Shams && git tag -a shams-v2-trust -m "Shams v2: Per-action-type trust system"
git push origin shams-v2-trust
```
