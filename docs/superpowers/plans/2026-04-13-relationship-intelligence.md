# Relationship Intelligence (Server-Side) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic relationship tracking from email + calendar + deals with warmth scoring, cooling/cold detection, follow-up drafting, and standup integration — so Shams catches relationships MJ is dropping.

**Architecture:** A new `shams_contacts` table stores contacts auto-discovered from email senders, calendar attendees, and deal contacts. The overnight loop gets step 7 (`_step_relationship_scan`) which extracts contacts, recalculates warmth scores, and drafts follow-ups for cooling contacts. Results surface in the morning standup drip-feed. A bridge API (`api/bridge.py`) accepts touchpoints from external sources (iMessage/WhatsApp bridge — separate plan).

**Tech Stack:** Python 3.9+ (`from __future__ import annotations`), PostgreSQL, existing overnight loop + standup infrastructure

**Spec:** `docs/superpowers/specs/2026-04-13-relationship-intelligence-design.md`

**Note:** This is Plan A (server-side). Plan B (macOS bridge for iMessage/WhatsApp) is a separate plan that builds on top of this.

---

### File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `schema.sql` | Add `shams_contacts` + `shams_bridge_commands` tables | Modify |
| `memory.py` | Contact CRUD + warmth scoring functions | Modify |
| `api/bridge.py` | Touchpoint ingestion API endpoint | **Create** |
| `standup.py` | Add `_step_relationship_scan()` as step 7, update overview + action items + drip-feed | Modify |
| `telegram.py` | Add `su_snooze7` callback | Modify |
| `tests/test_standup.py` | Warmth calculation, contact filtering, relationship scan tests | Modify |

---

### Task 1: Schema + Contact CRUD

**Files:**
- Modify: `schema.sql` (append 2 tables)
- Modify: `memory.py` (append contact functions)
- Modify: `tests/test_standup.py` (add tests)

- [ ] **Step 1: Write tests**

Append to `tests/test_standup.py`:

```python
def test_warmth_score_calculation():
    """Test warmth score decay and boost logic."""
    from standup import _calculate_warmth
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    # Fresh contact — should be ~100
    score = _calculate_warmth(
        last_inbound=now - timedelta(hours=1),
        last_outbound=now - timedelta(hours=2),
        last_meeting=None,
        touchpoint_count=5,
        channels=["email"],
        has_active_deal=False,
    )
    assert score >= 95

    # 20 days silent — should be cooling
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=20),
        last_outbound=now - timedelta(days=22),
        last_meeting=None,
        touchpoint_count=5,
        channels=["email"],
        has_active_deal=False,
    )
    assert 25 <= score <= 50

    # 40 days silent — should be cold
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=40),
        last_outbound=None,
        last_meeting=None,
        touchpoint_count=3,
        channels=["email"],
        has_active_deal=False,
    )
    assert score < 25

    # Active deal — warmth floor of 20
    score = _calculate_warmth(
        last_inbound=now - timedelta(days=60),
        last_outbound=None,
        last_meeting=None,
        touchpoint_count=2,
        channels=["email"],
        has_active_deal=True,
    )
    assert score >= 20


def test_contact_noise_filtering():
    """Test that noise contacts are filtered out."""
    from standup import _is_noise_contact
    assert _is_noise_contact("noreply@shopify.com") is True
    assert _is_noise_contact("notifications@github.com") is True
    assert _is_noise_contact("support@squareup.com") is True
    assert _is_noise_contact("ahmed@cafeimports.com") is False
    assert _is_noise_contact("maher@qcitycoffee.com") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_warmth_score_calculation tests/test_standup.py::test_contact_noise_filtering -v`
Expected: FAIL

- [ ] **Step 3: Add tables to schema.sql**

Append to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS shams_contacts (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(50),
    whatsapp_jid    VARCHAR(100),
    source          VARCHAR(50) DEFAULT 'email',
    channels        TEXT[] DEFAULT '{}',
    last_inbound    TIMESTAMPTZ,
    last_outbound   TIMESTAMPTZ,
    last_meeting    TIMESTAMPTZ,
    touchpoint_count INTEGER DEFAULT 0,
    warmth_score    INTEGER DEFAULT 50,
    deal_id         INTEGER,
    notes           TEXT DEFAULT '',
    snoozed_until   TIMESTAMPTZ,
    auto_discovered BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email ON shams_contacts (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON shams_contacts (phone);
CREATE INDEX IF NOT EXISTS idx_contacts_warmth ON shams_contacts (warmth_score);

CREATE TABLE IF NOT EXISTS shams_bridge_commands (
    id          SERIAL PRIMARY KEY,
    channel     VARCHAR(20) NOT NULL CHECK (channel IN ('imessage', 'whatsapp', 'email')),
    recipient   VARCHAR(255) NOT NULL,
    message     TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);
```

- [ ] **Step 4: Run schema migration on Railway**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('''
CREATE TABLE IF NOT EXISTS shams_contacts (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(50),
    whatsapp_jid    VARCHAR(100),
    source          VARCHAR(50) DEFAULT 'email',
    channels        TEXT[] DEFAULT '{}',
    last_inbound    TIMESTAMPTZ,
    last_outbound   TIMESTAMPTZ,
    last_meeting    TIMESTAMPTZ,
    touchpoint_count INTEGER DEFAULT 0,
    warmth_score    INTEGER DEFAULT 50,
    deal_id         INTEGER,
    notes           TEXT DEFAULT '',
    snoozed_until   TIMESTAMPTZ,
    auto_discovered BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email ON shams_contacts (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON shams_contacts (phone);
CREATE INDEX IF NOT EXISTS idx_contacts_warmth ON shams_contacts (warmth_score);
CREATE TABLE IF NOT EXISTS shams_bridge_commands (
    id          SERIAL PRIMARY KEY,
    channel     VARCHAR(20) NOT NULL,
    recipient   VARCHAR(255) NOT NULL,
    message     TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);
''')
conn.commit()
print('Tables created')
"
```

- [ ] **Step 5: Add warmth calculation + noise filter to standup.py**

In `standup.py`, add these after the `_log_revenue` function and before `# ── Overnight Loop`:

```python
# ── Relationship intelligence ──────────────────────────────────────────────

NOISE_DOMAINS = {
    "shopify.com", "squareup.com", "klaviyo.com", "recharge.io",
    "github.com", "railway.app", "google.com", "apple.com",
    "amazonses.com", "sendgrid.net", "mailchimp.com", "stripe.com",
    "paypal.com", "intuit.com", "quickbooks.com",
}

NOISE_PREFIXES = {"noreply", "no-reply", "notifications", "support", "info", "mailer-daemon", "postmaster"}


def _is_noise_contact(email: str) -> bool:
    """Check if an email address is noise (automated sender, not a real relationship)."""
    if not email:
        return True
    email = email.lower().strip()
    local = email.split("@")[0] if "@" in email else ""
    domain = email.split("@")[1] if "@" in email else ""
    if local in NOISE_PREFIXES:
        return True
    if domain in NOISE_DOMAINS:
        return True
    return False


def _calculate_warmth(
    last_inbound: datetime | None,
    last_outbound: datetime | None,
    last_meeting: datetime | None,
    touchpoint_count: int,
    channels: list[str],
    has_active_deal: bool,
) -> int:
    """Calculate warmth score 0-100 for a contact."""
    now = datetime.now(timezone.utc)

    # Find most recent touchpoint
    timestamps = [t for t in [last_inbound, last_outbound, last_meeting] if t]
    if not timestamps:
        return 0

    for i, ts in enumerate(timestamps):
        if ts.tzinfo is None:
            timestamps[i] = ts.replace(tzinfo=timezone.utc)

    latest = max(timestamps)
    days_since = (now - latest).days

    # Decay rate: frequent contacts decay slower
    decay_rate = 1.5 if touchpoint_count > 12 else 3.0
    base = max(0, 100 - (days_since * decay_rate))

    # Direction boost: inbound more recent than outbound = they're engaging
    if last_inbound and last_outbound:
        li = last_inbound if last_inbound.tzinfo else last_inbound.replace(tzinfo=timezone.utc)
        lo = last_outbound if last_outbound.tzinfo else last_outbound.replace(tzinfo=timezone.utc)
        if li > lo:
            base = min(100, base + 5)

    # Multi-channel bonus
    if len(channels) >= 2:
        base = min(100, base + 10)

    # Deal floor
    if has_active_deal:
        base = max(20, base)

    return int(base)
```

- [ ] **Step 6: Add contact CRUD functions to memory.py**

Append to `memory.py`:

```python
# ── Contacts (Relationship Intelligence) ───────────────────────────────────

def upsert_contact(name: str, email: str | None = None, phone: str | None = None,
                   source: str = "email", channel: str = "email",
                   direction: str = "inbound", deal_id: int | None = None) -> int:
    """Create or update a contact. Returns contact ID."""
    with get_conn() as conn, conn.cursor() as cur:
        if email:
            cur.execute(f"SELECT id, channels FROM {P}contacts WHERE email = %s", (email,))
        elif phone:
            cur.execute(f"SELECT id, channels FROM {P}contacts WHERE phone = %s", (phone,))
        else:
            return 0

        row = cur.fetchone()
        now_field = "last_inbound" if direction == "inbound" else "last_outbound"

        if row:
            contact_id = row[0]
            existing_channels = row[1] or []
            if channel not in existing_channels:
                existing_channels.append(channel)
            cur.execute(
                f"UPDATE {P}contacts SET {now_field} = NOW(), touchpoint_count = touchpoint_count + 1, "
                f"channels = %s, updated_at = NOW() "
                + (f", deal_id = %s" if deal_id else "") +
                f" WHERE id = %s",
                (existing_channels, deal_id, contact_id) if deal_id else (existing_channels, contact_id),
            )
            return contact_id
        else:
            cur.execute(
                f"INSERT INTO {P}contacts (name, email, phone, source, channels, {now_field}, touchpoint_count, deal_id) "
                f"VALUES (%s, %s, %s, %s, %s, NOW(), 1, %s) RETURNING id",
                (name, email, phone, source, [channel], deal_id),
            )
            return cur.fetchone()[0]


def update_contact_meeting(email: str):
    """Update last_meeting timestamp for a contact by email."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}contacts SET last_meeting = NOW(), touchpoint_count = touchpoint_count + 1, "
            f"updated_at = NOW() WHERE email = %s",
            (email,),
        )
        if "calendar" not in (cur.description or []):
            cur.execute(
                f"UPDATE {P}contacts SET channels = array_append(channels, 'calendar') "
                f"WHERE email = %s AND NOT ('calendar' = ANY(channels))",
                (email,),
            )


def update_all_warmth_scores():
    """Recalculate warmth scores for all contacts."""
    from standup import _calculate_warmth
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {P}contacts")
        contacts = cur.fetchall()

        # Get active deal IDs
        cur.execute(f"SELECT id FROM {P}deals WHERE stage NOT IN ('closed', 'dead')")
        active_deal_ids = {r["id"] for r in cur.fetchall()}

    with get_conn() as conn, conn.cursor() as cur:
        for c in contacts:
            has_deal = c.get("deal_id") in active_deal_ids if c.get("deal_id") else False
            score = _calculate_warmth(
                last_inbound=c.get("last_inbound"),
                last_outbound=c.get("last_outbound"),
                last_meeting=c.get("last_meeting"),
                touchpoint_count=c.get("touchpoint_count", 0),
                channels=c.get("channels", []),
                has_active_deal=has_deal,
            )
            cur.execute(
                f"UPDATE {P}contacts SET warmth_score = %s, updated_at = NOW() WHERE id = %s",
                (score, c["id"]),
            )


def get_cooling_contacts(threshold: int = 49) -> list[dict]:
    """Get contacts with warmth score at or below threshold, excluding snoozed."""
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}contacts WHERE warmth_score <= %s "
            f"AND touchpoint_count >= 2 "
            f"AND (snoozed_until IS NULL OR snoozed_until < NOW()) "
            f"ORDER BY warmth_score ASC LIMIT 10",
            (threshold,),
        )
        return cur.fetchall()


def snooze_contact(contact_id: int, days: int = 7):
    """Snooze a contact from relationship alerts for N days."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}contacts SET snoozed_until = NOW() + INTERVAL '%s days', updated_at = NOW() WHERE id = %s",
            (days, contact_id),
        )


def get_contact_count() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {P}contacts WHERE touchpoint_count >= 2")
        return cur.fetchone()[0]


def queue_bridge_command(channel: str, recipient: str, message: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {P}bridge_commands (channel, recipient, message) "
            f"VALUES (%s, %s, %s) RETURNING id",
            (channel, recipient, message),
        )
        return cur.fetchone()[0]


def get_pending_bridge_commands() -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {P}bridge_commands WHERE status = 'pending' ORDER BY created_at"
        )
        return cur.fetchall()


def ack_bridge_command(command_id: int, status: str = "sent"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {P}bridge_commands SET status = %s, executed_at = NOW() WHERE id = %s",
            (status, command_id),
        )
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_warmth_score_calculation tests/test_standup.py::test_contact_noise_filtering -v`
Expected: PASS

- [ ] **Step 8: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add schema.sql memory.py standup.py tests/test_standup.py
git commit -m "feat: add contacts table + warmth scoring + contact CRUD for relationship intelligence"
```

---

### Task 2: Bridge API Endpoint

**Files:**
- Create: `api/bridge.py`
- Modify: `api/__init__.py` (register blueprint)

- [ ] **Step 1: Create `api/bridge.py`**

Create `/Users/mj/code/Shams/api/bridge.py`:

```python
"""Bridge API — receives touchpoints from local macOS bridge, serves command queue."""
from __future__ import annotations

import logging
import os
from flask import Blueprint, request, jsonify

import memory
from standup import _is_noise_contact

logger = logging.getLogger(__name__)

bp = Blueprint("bridge", __name__, url_prefix="/api")

BRIDGE_TOKEN = os.environ.get("BRIDGE_API_TOKEN", "")


def _check_bridge_auth():
    """Verify bridge API token."""
    if not BRIDGE_TOKEN:
        return False
    token = request.headers.get("X-Bridge-Token", "")
    return token == BRIDGE_TOKEN


@bp.route("/touchpoints", methods=["POST"])
def receive_touchpoints():
    """Receive touchpoint batch from local bridge."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data or "touchpoints" not in data:
        return jsonify({"error": "Missing touchpoints"}), 400

    processed = 0
    for tp in data["touchpoints"]:
        handle = tp.get("contact_handle", "")
        name = tp.get("contact_name", "") or handle
        source = tp.get("source", "unknown")
        direction = tp.get("direction", "inbound")
        phone = tp.get("contact_phone")

        # Determine email vs phone
        email = handle if "@" in handle and not handle.endswith("@s.whatsapp.net") else None
        if not email and not phone:
            phone = handle  # Assume phone number for iMessage handles

        if email and _is_noise_contact(email):
            continue

        try:
            memory.upsert_contact(
                name=name, email=email, phone=phone,
                source=source, channel=source, direction=direction,
            )
            processed += 1
        except Exception as e:
            logger.error(f"Touchpoint processing failed: {e}")

    memory.log_activity("shams", "touchpoints", f"Bridge: {processed} touchpoints processed")
    return jsonify({"processed": processed})


@bp.route("/bridge/pending", methods=["GET"])
def get_pending_commands():
    """Return pending bridge commands for the local bridge to execute."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    commands = memory.get_pending_bridge_commands()
    return jsonify({"commands": commands})


@bp.route("/bridge/ack", methods=["POST"])
def ack_command():
    """Acknowledge command execution from bridge."""
    if not _check_bridge_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    command_id = data.get("id")
    status = data.get("status", "sent")
    if command_id:
        memory.ack_bridge_command(command_id, status)
    return jsonify({"ok": True})
```

- [ ] **Step 2: Register blueprint in `api/__init__.py`**

Check the current `api/__init__.py` to see how blueprints are registered, then add `from api.bridge import bp as bridge_bp` and register it.

- [ ] **Step 3: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api/bridge.py api/__init__.py
git commit -m "feat: add bridge API — touchpoint ingestion + command queue endpoints"
```

---

### Task 3: Relationship Scan — Step 7 of Overnight Loop

**Files:**
- Modify: `standup.py` (add `_step_relationship_scan`, wire into overnight loop, update trust + P&L configs)

- [ ] **Step 1: Write test**

Append to `tests/test_standup.py`:

```python
def test_relationship_scan_structure():
    """Test that _step_relationship_scan returns structured results."""
    from unittest.mock import patch, MagicMock
    import standup

    with patch("standup.memory") as mock_memory, \
         patch("standup.google_client") as mock_google, \
         patch("standup.anthropic") as mock_anthropic:

        mock_memory.get_cooling_contacts.return_value = []
        mock_memory.get_contact_count.return_value = 0
        mock_google.get_todays_events.return_value = []

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        result = standup._step_relationship_scan()

        assert "contacts_updated" in result
        assert "new_contacts" in result
        assert "cooling" in result
        assert "cold" in result
        mock_memory.update_all_warmth_scores.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_relationship_scan_structure -v`
Expected: FAIL

- [ ] **Step 3: Add `_step_relationship_scan()` to standup.py**

Add this after `_call_scout()` and before `_build_overnight_summary()`:

```python
# ── Relationship scan ──────────────────────────────────────────────────────


def _step_relationship_scan() -> dict:
    """Scan email + calendar + deals for relationship signals, update warmth scores."""
    contacts_updated = 0
    new_contacts = 0

    # Extract contacts from today's triaged emails (already processed by email sweep)
    try:
        recent_emails = memory.get_triaged_emails(limit=50)
        for email in recent_emails:
            from_addr = email.get("from_addr", "")
            if not from_addr or _is_noise_contact(from_addr):
                continue
            # Extract name from "Name <email>" format
            if "<" in from_addr and ">" in from_addr:
                name = from_addr.split("<")[0].strip().strip('"')
                addr = from_addr.split("<")[1].split(">")[0].strip()
            else:
                name = from_addr.split("@")[0]
                addr = from_addr
            if _is_noise_contact(addr):
                continue
            cid = memory.upsert_contact(name=name, email=addr, source="email", channel="email", direction="inbound")
            if cid:
                contacts_updated += 1
    except Exception as e:
        logger.error(f"Relationship scan email extraction failed: {e}")

    # Extract contacts from today's calendar events
    try:
        events = google_client.get_todays_events()
        for event in events:
            # Calendar events don't have attendee emails in the current API response
            # but the event summary often contains names we can match
            pass  # Attendee extraction requires Calendar API attendees field — future enhancement
    except Exception as e:
        logger.error(f"Relationship scan calendar extraction failed: {e}")

    # Ensure deal contacts are tracked
    try:
        from config import DATABASE_URL
        import psycopg2, psycopg2.extras
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, contact FROM shams_deals WHERE stage NOT IN ('closed', 'dead') AND contact != ''"
            )
            deals = cur.fetchall()
        for deal in deals:
            contact_str = deal.get("contact", "")
            if not contact_str:
                continue
            # Try to extract email from contact field
            email = None
            if "@" in contact_str:
                parts = contact_str.split()
                for p in parts:
                    if "@" in p:
                        email = p.strip("<>(),")
                        break
            name = contact_str.split("<")[0].strip() if "<" in contact_str else contact_str
            if email and not _is_noise_contact(email):
                memory.upsert_contact(name=name, email=email, source="deal", channel="email", deal_id=deal["id"])
    except Exception as e:
        logger.error(f"Relationship scan deal extraction failed: {e}")

    # Recalculate warmth scores
    memory.update_all_warmth_scores()

    # Find cooling and cold contacts
    cooling = memory.get_cooling_contacts(threshold=49)
    cold = [c for c in cooling if c.get("warmth_score", 0) < 25]
    cooling_only = [c for c in cooling if c.get("warmth_score", 0) >= 25]

    # Draft follow-ups for cooling/cold contacts
    follow_ups = []
    if cooling:
        try:
            api_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            contacts_text = "\n".join(
                f"- {c['name']} ({c.get('email', c.get('phone', '?'))}) — "
                f"warmth: {c['warmth_score']}/100, "
                f"last contact: {_days_since(c)} days ago, "
                f"channels: {', '.join(c.get('channels', []))}"
                + (f", deal: #{c['deal_id']}" if c.get("deal_id") else "")
                for c in cooling[:5]
            )
            prompt = (
                f"Draft brief, natural follow-up messages for these contacts that Maher is losing touch with. "
                f"Keep it casual and genuine — Maher is direct and concise. One message per contact.\n\n"
                f"{contacts_text}\n\n"
                f"Format:\nNAME: <name>\nDRAFT: <message>\n---"
            )
            response = api_client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content[0].text.split("---"):
                block = block.strip()
                if not block:
                    continue
                name_val, draft_val = "", ""
                for line in block.split("\n"):
                    if line.startswith("NAME:"):
                        name_val = line[5:].strip()
                    elif line.startswith("DRAFT:"):
                        draft_val = line[6:].strip()
                    elif draft_val:
                        draft_val += "\n" + line
                if name_val and draft_val:
                    follow_ups.append({"name": name_val, "draft": draft_val.strip()})
        except Exception as e:
            logger.error(f"Relationship follow-up drafting failed: {e}")

    # Attach drafts to matching contacts
    cooling_with_drafts = []
    for c in cooling:
        entry = {
            "id": c["id"],
            "name": c["name"],
            "email": c.get("email"),
            "phone": c.get("phone"),
            "channels": c.get("channels", []),
            "warmth": c.get("warmth_score", 0),
            "days_silent": _days_since(c),
            "deal_id": c.get("deal_id"),
            "draft": "",
        }
        for fu in follow_ups:
            if fu["name"].lower() in c["name"].lower() or c["name"].lower() in fu["name"].lower():
                entry["draft"] = fu["draft"]
                break
        cooling_with_drafts.append(entry)

    # Log P&L revenue for relationship management
    _log_revenue("reminder", len(cooling), f"{len(cooling)} relationship follow-ups surfaced")

    total_contacts = memory.get_contact_count()

    return {
        "contacts_updated": contacts_updated,
        "new_contacts": new_contacts,
        "total_contacts": total_contacts,
        "cooling": [c for c in cooling_with_drafts if c["warmth"] >= 25],
        "cold": [c for c in cooling_with_drafts if c["warmth"] < 25],
        "follow_ups_drafted": len(follow_ups),
    }


def _days_since(contact: dict) -> int:
    """Calculate days since last interaction with a contact."""
    now = datetime.now(timezone.utc)
    timestamps = []
    for field in ("last_inbound", "last_outbound", "last_meeting"):
        ts = contact.get(field)
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamps.append(ts)
    if not timestamps:
        return 999
    latest = max(timestamps)
    return (now - latest).days
```

- [ ] **Step 4: Wire into overnight loop as step 7**

In `standup.py`, find the `run_overnight_loop()` function. In the initial `results` dict, add after the `"scout"` key:

```python
        "relationships": {"contacts_updated": 0, "new_contacts": 0, "cooling": [], "cold": [], "follow_ups_drafted": 0},
```

After the step 6 Scout block and before `# Save results`, add:

```python
    # Step 7: Relationship scan
    try:
        results["relationships"] = _step_relationship_scan()
        memory.log_activity("shams", "overnight", "Relationship scan complete", {
            "contacts_updated": results["relationships"]["contacts_updated"],
            "cooling": len(results["relationships"]["cooling"]),
            "cold": len(results["relationships"]["cold"]),
        })
    except Exception as e:
        logger.error(f"Overnight relationship scan failed: {e}", exc_info=True)
        results["relationships"] = {"contacts_updated": 0, "new_contacts": 0, "cooling": [], "cold": [], "follow_ups_drafted": 0}
        status = "partial"
```

- [ ] **Step 5: Add `relationship_followup` to TRUST_TIERS and STANDUP_TRUST_MAP**

In `standup.py`, add to `TRUST_TIERS` (in the medium risk section):

```python
    "relationship_followup": {"tier": "medium", "threshold": 15, "max_rejection_pct": 10},
```

Add to `STANDUP_TRUST_MAP`:

```python
    "relationship": "relationship_followup",
```

Add to `PL_CONFIG["time_values"]`:

```python
        "relationship_followup": 10,
```

- [ ] **Step 6: Run test**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/test_standup.py::test_relationship_scan_structure -v`
Expected: PASS

- [ ] **Step 7: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add standup.py tests/test_standup.py
git commit -m "feat: add relationship scan as step 7 of overnight loop"
```

---

### Task 4: Standup Integration — Overview + Drip-Feed for Relationships

**Files:**
- Modify: `standup.py` (update overview, action items, drip-feed rendering)
- Modify: `telegram.py` (add `su_snooze7` + channel-specific callbacks)

- [ ] **Step 1: Update `_build_overview_message` for relationships**

In `standup.py`, in `_build_overview_message()`, after the Scout section and before the daily P&L section, add:

```python
    # Relationships
    rels = results.get("relationships", {})
    cooling_count = len(rels.get("cooling", []))
    cold_count = len(rels.get("cold", []))
    if cooling_count or cold_count:
        parts_rel = []
        if cooling_count:
            parts_rel.append(f"{cooling_count} cooling")
        if cold_count:
            parts_rel.append(f"{cold_count} going cold")
        lines.append(f"🤝 {' · '.join(parts_rel)}")
```

- [ ] **Step 2: Update `_build_action_items` for relationships**

In `standup.py`, in `_build_action_items()`, after the Scout findings section and before `return items`, add:

```python
    # 5. Relationship follow-ups
    rels = results.get("relationships", {})
    for c in rels.get("cold", []) + rels.get("cooling", []):
        items.append({
            "type": "relationship",
            "contact_id": c.get("id"),
            "name": c.get("name", ""),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "channels": c.get("channels", []),
            "warmth": c.get("warmth", 0),
            "days_silent": c.get("days_silent", 0),
            "deal_id": c.get("deal_id"),
            "draft": c.get("draft", ""),
        })
```

- [ ] **Step 3: Update `_send_next_standup_item` for relationship items**

In `standup.py`, in `_send_next_standup_item()`, after the `elif item["type"] == "scout_info":` block, add:

```python
    elif item["type"] == "relationship":
        cold_label = "Going cold" if item["warmth"] < 25 else "Cooling"
        msg = (
            f"🤝 {cold_label}: {item['name']}\n"
            f"Last contact: {item['days_silent']} days ago\n"
            f"Warmth: {item['warmth']}/100"
        )
        if item.get("draft"):
            msg += f"\n\nDraft: {item['draft']}"

        buttons = []
        channels = item.get("channels", [])
        if "email" in channels and item.get("email"):
            buttons.append({"text": "📧 Email", "callback_data": f"su_email:{idx}"})
        if "imessage" in channels and item.get("phone"):
            buttons.append({"text": "💬 iMessage", "callback_data": f"su_imsg:{idx}"})
        if "whatsapp" in channels and item.get("phone"):
            buttons.append({"text": "💚 WhatsApp", "callback_data": f"su_wa:{idx}"})
        if not buttons and item.get("email"):
            buttons.append({"text": "📧 Email", "callback_data": f"su_email:{idx}"})
        buttons.append({"text": "✏️ Edit", "callback_data": f"su_edit:{idx}"})
        buttons.append({"text": "Skip", "callback_data": f"su_skip:{idx}"})
        buttons.append({"text": "😴 7d", "callback_data": f"su_snooze7:{idx}"})
        send_telegram_with_buttons(chat_id, msg, buttons)
```

- [ ] **Step 4: Update `_build_overnight_summary` for relationships**

In `standup.py`, in `_build_overnight_summary()`, after the Scout section and before `return`, add:

```python
    rels = results.get("relationships", {})
    total_cooling = len(rels.get("cooling", [])) + len(rels.get("cold", []))
    if total_cooling:
        parts.append(f"Relationships: {total_cooling} need attention")
```

- [ ] **Step 5: Add relationship callbacks to telegram.py**

In `telegram.py`, in `_handle_standup_callback()`, add these handlers. After the `su_mission` block:

```python
    elif action_type == "su_email":
        # Save draft to Gmail for relationship follow-up
        if item.get("email") and item.get("draft"):
            import google_client
            # Find which account has communicated with this contact
            account = "personal"  # default
            for acct in config.GOOGLE_ACCOUNTS:
                # Use personal as default for relationship follow-ups
                break
            result = google_client.create_draft_reply(account, "", item["draft"])
            if result:
                _ack_callback(cb_id, "Draft saved to Gmail")
                send_telegram(chat_id, f"Draft saved for {item.get('name', '')}")
                memory.log_activity("shams", "relationship_followup", f"Email draft saved for {item.get('name', '')}")
            else:
                _ack_callback(cb_id, "Draft failed")
        handled[str(idx)] = "sent"

    elif action_type == "su_imsg":
        # Queue iMessage via bridge
        if item.get("phone") and item.get("draft"):
            memory.queue_bridge_command("imessage", item["phone"], item["draft"])
            _ack_callback(cb_id, "Queued for iMessage")
            send_telegram(chat_id, f"iMessage queued for {item.get('name', '')} — bridge will send it")
            memory.log_activity("shams", "relationship_followup", f"iMessage queued for {item.get('name', '')}")
        handled[str(idx)] = "sent"

    elif action_type == "su_wa":
        # Queue WhatsApp via bridge
        if item.get("phone") and item.get("draft"):
            memory.queue_bridge_command("whatsapp", item["phone"], item["draft"])
            _ack_callback(cb_id, "Queued for WhatsApp")
            send_telegram(chat_id, f"WhatsApp queued for {item.get('name', '')} — bridge will open it")
            memory.log_activity("shams", "relationship_followup", f"WhatsApp queued for {item.get('name', '')}")
        handled[str(idx)] = "sent"

    elif action_type == "su_snooze7":
        # Snooze contact for 7 days
        if item.get("contact_id"):
            memory.snooze_contact(item["contact_id"], days=7)
            _ack_callback(cb_id, "Snoozed 7 days")
            send_telegram(chat_id, f"Snoozed {item.get('name', '')} for 7 days")
        handled[str(idx)] = "snooze"
```

- [ ] **Step 6: Run all tests**

Run: `cd /Users/mj/code/Shams && python3 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add standup.py telegram.py
git commit -m "feat: integrate relationship intelligence into standup — overview + drip-feed + channel buttons"
```

---

### Task 5: Deploy + Smoke Test

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

Wait for `SUCCESS`.

- [ ] **Step 3: Verify contacts table exists**

```bash
cd /Users/mj/code/Shams && /Users/mj/.local/bin/railway run python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM shams_contacts')
print(f'Contacts: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM shams_bridge_commands')
print(f'Bridge commands: {cur.fetchone()[0]}')
"
```

- [ ] **Step 4: Tag the release**

```bash
cd /Users/mj/code/Shams && git tag -a shams-v2-relationships -m "Shams v2: Relationship intelligence — automatic CRM with warmth scoring"
git push origin shams-v2-relationships
```
