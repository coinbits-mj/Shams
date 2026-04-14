# Email Mining Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Shams's email mining pipeline: classify every email across all 3 Gmail accounts with Sonnet 4.6, extract structured entities, route invoices/complaints/deals into dedicated tables, auto-archive noise, escalate 4 priority topic areas via Telegram on new threads. Includes one-time historical backfill for ~57K emails.

**Architecture:** Single-email pipeline (`fetch → classify → extract → route → archive`) shared between the nightly overnight job (`standup._step_email_mining`) and the one-time backfill script. All writes to Postgres via existing `memory.py` / `db.py` helpers. Sonnet 4.6 via existing `claude_client` abstraction. Four priority categories (Coinbits legal, Prime Trust lawsuit, investor relations, Somerville purchase) never auto-archive and fire a Telegram ping only on new threads.

**Tech Stack:** Python 3, Flask, Postgres (Railway), anthropic SDK (Sonnet 4.6), Gmail REST API, pytest.

**Spec:** `docs/superpowers/specs/2026-04-13-email-mining-pipeline-design.md`

---

## File Structure

### New files
- `migrations/2026-04-13-email-mining-tables.sql` — schema additions
- `email_mining.py` — core pipeline: classify, extract, route, archive, process_email
- `scripts/backfill_email_mining.py` — one-time historical sweep
- `tests/test_email_mining.py` — unit tests for classifier + entity extraction + routing + safety net
- `tests/test_email_mining_backfill.py` — integration test for dry-run backfill

### Modified files
- `schema.sql` — add same tables as migration (source of truth)
- `standup.py` — replace `_step_email_sweep` body with call to `email_mining.run_overnight_sweep`
- `memory.py` — add helpers: `insert_email_archive`, `insert_ap_invoice`, `insert_cx_complaint`, `thread_already_escalated`, `record_thread_escalation`, `get_backfill_cursor`, `set_backfill_cursor`
- `tools/email_tools.py` (new file inside existing `tools/` dir) — three new `@tool`-decorated Claude tools: `search_email_archive`, `get_ap_summary`, `get_cx_summary`
- `tests/conftest.py` — add `EMAIL_MINING_DRY_RUN` env-var fixture

---

## Task 1: Create migration SQL for new tables

**Files:**
- Create: `migrations/2026-04-13-email-mining-tables.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- migrations/2026-04-13-email-mining-tables.sql

-- One row per email across all Shams-connected Gmail accounts.
CREATE TABLE IF NOT EXISTS shams_email_archive (
    id                BIGSERIAL PRIMARY KEY,
    account           TEXT NOT NULL,
    gmail_message_id  TEXT NOT NULL UNIQUE,
    gmail_thread_id   TEXT NOT NULL,
    from_addr         TEXT,
    from_name         TEXT,
    to_addrs          TEXT[],
    subject           TEXT,
    date              TIMESTAMPTZ,
    snippet           TEXT,
    body              TEXT,
    category          TEXT NOT NULL,
    priority          TEXT NOT NULL,
    entities          JSONB NOT NULL DEFAULT '{}'::jsonb,
    gmail_archived    BOOLEAN NOT NULL DEFAULT FALSE,
    processed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_model   TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_archive_account_date
    ON shams_email_archive(account, date DESC);
CREATE INDEX IF NOT EXISTS idx_email_archive_category
    ON shams_email_archive(category);
CREATE INDEX IF NOT EXISTS idx_email_archive_from
    ON shams_email_archive(from_addr);
CREATE INDEX IF NOT EXISTS idx_email_archive_thread
    ON shams_email_archive(gmail_thread_id);
CREATE INDEX IF NOT EXISTS idx_email_archive_entities_gin
    ON shams_email_archive USING GIN (entities);
CREATE INDEX IF NOT EXISTS idx_email_archive_body_fts
    ON shams_email_archive USING GIN (to_tsvector('english', coalesce(body,'')));

-- Invoices routed from category='invoice'.
CREATE TABLE IF NOT EXISTS shams_ap_queue (
    id              BIGSERIAL PRIMARY KEY,
    archive_id      BIGINT NOT NULL REFERENCES shams_email_archive(id) ON DELETE CASCADE,
    vendor          TEXT,
    amount_cents    BIGINT,
    currency        TEXT DEFAULT 'USD',
    invoice_number  TEXT,
    due_date        DATE,
    status          TEXT NOT NULL DEFAULT 'unpaid',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ap_queue_status_due
    ON shams_ap_queue(status, due_date);
CREATE INDEX IF NOT EXISTS idx_ap_queue_vendor
    ON shams_ap_queue(vendor);

-- Customer complaints routed from category='customer_complaint'.
CREATE TABLE IF NOT EXISTS shams_cx_log (
    id                BIGSERIAL PRIMARY KEY,
    archive_id        BIGINT NOT NULL REFERENCES shams_email_archive(id) ON DELETE CASCADE,
    customer_email    TEXT,
    customer_name     TEXT,
    issue_summary     TEXT,
    severity          TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    resolution_notes  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cx_log_status_severity
    ON shams_cx_log(status, severity);

-- Tracks which priority threads have already fired a Telegram ping.
CREATE TABLE IF NOT EXISTS shams_priority_threads (
    gmail_thread_id   TEXT PRIMARY KEY,
    category          TEXT NOT NULL,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_email_id     BIGINT REFERENCES shams_email_archive(id) ON DELETE SET NULL
);
```

- [ ] **Step 2: Commit**

```bash
git add migrations/2026-04-13-email-mining-tables.sql
git commit -m "Email mining: add migration for archive, ap_queue, cx_log, priority_threads"
```

---

## Task 2: Apply migration to Railway Postgres

**Files:**
- (no file changes — executes SQL against Railway DB)

- [ ] **Step 1: Apply the migration**

```bash
cd /Users/mj/code/Shams
psql "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" -f migrations/2026-04-13-email-mining-tables.sql
```

Expected: `CREATE TABLE` × 4, `CREATE INDEX` × 8 (or `NOTICE: relation already exists, skipping` if re-running).

- [ ] **Step 2: Verify tables exist**

```bash
psql "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" -c "\dt shams_email_archive shams_ap_queue shams_cx_log shams_priority_threads"
```

Expected: all four tables listed.

---

## Task 3: Update `schema.sql` source of truth

**Files:**
- Modify: `schema.sql` — append the same CREATE TABLE statements

- [ ] **Step 1: Append new tables to `schema.sql`**

Open `schema.sql`, go to the end of the file, and append the full contents of `migrations/2026-04-13-email-mining-tables.sql` (identical DDL).

- [ ] **Step 2: Commit**

```bash
git add schema.sql
git commit -m "Email mining: sync schema.sql with migration"
```

---

## Task 4: Add memory helpers for new tables

**Files:**
- Modify: `memory.py` — add helper functions at end of file

- [ ] **Step 1: Write failing test for `insert_email_archive`**

Create `tests/test_email_mining.py`:

```python
# tests/test_email_mining.py
from __future__ import annotations

import pytest


@pytest.mark.usefixtures("setup_db")
class TestMemoryHelpers:
    def test_insert_email_archive_returns_id_and_is_idempotent(self):
        import memory

        email = {
            "account": "personal",
            "gmail_message_id": "test_msg_001",
            "gmail_thread_id": "test_thread_001",
            "from_addr": "a@b.com",
            "from_name": "A B",
            "to_addrs": ["me@me.com"],
            "subject": "Test",
            "date": "2026-04-13T00:00:00Z",
            "snippet": "hi",
            "body": "hello world",
            "category": "other",
            "priority": "P3",
            "entities": {"action_needed": False},
            "processed_model": "claude-sonnet-4-6",
        }

        id1 = memory.insert_email_archive(email)
        assert id1 is not None

        # Re-insert same message — should return existing id, not duplicate.
        id2 = memory.insert_email_archive(email)
        assert id2 == id1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/mj/code/Shams
pytest tests/test_email_mining.py::TestMemoryHelpers::test_insert_email_archive_returns_id_and_is_idempotent -v
```

Expected: FAIL with `AttributeError: module 'memory' has no attribute 'insert_email_archive'`.

- [ ] **Step 3: Implement `insert_email_archive` in `memory.py`**

Append to `memory.py`:

```python
# ── Email mining helpers ─────────────────────────────────────────────────────

def insert_email_archive(email: dict) -> int | None:
    """Insert a row into shams_email_archive, idempotent on gmail_message_id.

    Returns the archive row id (new or existing). Returns None on DB error.
    """
    import json
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shams_email_archive
                    (account, gmail_message_id, gmail_thread_id, from_addr, from_name,
                     to_addrs, subject, date, snippet, body, category, priority,
                     entities, gmail_archived, processed_model)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (gmail_message_id) DO NOTHING
                RETURNING id
                """,
                (
                    email.get("account"),
                    email["gmail_message_id"],
                    email.get("gmail_thread_id", ""),
                    email.get("from_addr"),
                    email.get("from_name"),
                    email.get("to_addrs") or [],
                    email.get("subject"),
                    email.get("date"),
                    email.get("snippet"),
                    email.get("body"),
                    email["category"],
                    email["priority"],
                    json.dumps(email.get("entities") or {}),
                    email.get("gmail_archived", False),
                    email.get("processed_model"),
                ),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return row[0]
            # Conflict path — fetch existing id.
            cur.execute(
                "SELECT id FROM shams_email_archive WHERE gmail_message_id = %s",
                (email["gmail_message_id"],),
            )
            existing = cur.fetchone()
            conn.commit()
            return existing[0] if existing else None
    except Exception:
        conn.rollback()
        raise
    finally:
        db.put_conn(conn)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_email_mining.py::TestMemoryHelpers::test_insert_email_archive_returns_id_and_is_idempotent -v
```

Expected: PASS.

- [ ] **Step 5: Add failing tests for the remaining helpers**

Append to `tests/test_email_mining.py` inside the `TestMemoryHelpers` class:

```python
    def test_insert_ap_invoice(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_ap_001",
            "gmail_thread_id": "t1",
            "subject": "Invoice",
            "category": "invoice",
            "priority": "P2",
            "entities": {},
        })
        inv_id = memory.insert_ap_invoice({
            "archive_id": archive_id,
            "vendor": "Sysco",
            "amount_cents": 124000,
            "currency": "USD",
            "invoice_number": "INV-001",
            "due_date": "2026-04-25",
            "notes": None,
        })
        assert inv_id is not None

    def test_insert_cx_complaint(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_cx_001",
            "gmail_thread_id": "t2",
            "subject": "Problem",
            "category": "customer_complaint",
            "priority": "P2",
            "entities": {},
        })
        cx_id = memory.insert_cx_complaint({
            "archive_id": archive_id,
            "customer_email": "c@c.com",
            "customer_name": "C",
            "issue_summary": "stale coffee",
            "severity": "med",
        })
        assert cx_id is not None

    def test_thread_escalation_tracking(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "coinbits",
            "gmail_message_id": "msg_legal_001",
            "gmail_thread_id": "thread_legal_xyz",
            "subject": "Legal",
            "category": "coinbits_legal",
            "priority": "P1",
            "entities": {},
        })
        assert memory.thread_already_escalated("thread_legal_xyz") is False
        memory.record_thread_escalation("thread_legal_xyz", "coinbits_legal", archive_id)
        assert memory.thread_already_escalated("thread_legal_xyz") is True

    def test_backfill_cursor(self):
        import memory

        assert memory.get_backfill_cursor("personal") is None
        memory.set_backfill_cursor("personal", "page_token_abc")
        assert memory.get_backfill_cursor("personal") == "page_token_abc"
        memory.set_backfill_cursor("personal", "page_token_def")
        assert memory.get_backfill_cursor("personal") == "page_token_def"
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestMemoryHelpers -v
```

Expected: 4 FAILED (insert_ap_invoice, insert_cx_complaint, thread tracking, cursor).

- [ ] **Step 7: Implement the four helpers in `memory.py`**

Append to `memory.py`:

```python
def insert_ap_invoice(invoice: dict) -> int | None:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shams_ap_queue
                    (archive_id, vendor, amount_cents, currency, invoice_number, due_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    invoice["archive_id"],
                    invoice.get("vendor"),
                    invoice.get("amount_cents"),
                    invoice.get("currency", "USD"),
                    invoice.get("invoice_number"),
                    invoice.get("due_date"),
                    invoice.get("notes"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        db.put_conn(conn)


def insert_cx_complaint(complaint: dict) -> int | None:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shams_cx_log
                    (archive_id, customer_email, customer_name, issue_summary, severity)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    complaint["archive_id"],
                    complaint.get("customer_email"),
                    complaint.get("customer_name"),
                    complaint.get("issue_summary"),
                    complaint.get("severity"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        db.put_conn(conn)


def thread_already_escalated(gmail_thread_id: str) -> bool:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM shams_priority_threads WHERE gmail_thread_id = %s",
                (gmail_thread_id,),
            )
            return cur.fetchone() is not None
    finally:
        db.put_conn(conn)


def record_thread_escalation(gmail_thread_id: str, category: str, last_email_id: int) -> None:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shams_priority_threads (gmail_thread_id, category, last_email_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (gmail_thread_id) DO UPDATE
                    SET last_email_id = EXCLUDED.last_email_id
                """,
                (gmail_thread_id, category, last_email_id),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db.put_conn(conn)


def get_backfill_cursor(account_key: str) -> str | None:
    return recall(f"email_mining_backfill_cursor_{account_key}")


def set_backfill_cursor(account_key: str, page_token: str) -> None:
    remember(f"email_mining_backfill_cursor_{account_key}", page_token)
```

- [ ] **Step 8: Run all memory helper tests**

```bash
pytest tests/test_email_mining.py::TestMemoryHelpers -v
```

Expected: 5 PASSED.

- [ ] **Step 9: Commit**

```bash
git add memory.py tests/test_email_mining.py
git commit -m "Email mining: memory helpers for archive, ap_queue, cx_log, priority_threads, backfill cursor"
```

---

## Task 5: Build the classifier + extractor

**Files:**
- Create: `email_mining.py` (classifier portion)
- Modify: `tests/test_email_mining.py` (add `TestClassifier` class)

- [ ] **Step 1: Write failing test for classifier output shape**

Append to `tests/test_email_mining.py`:

```python
class TestClassifier:
    """Tests classifier output shape and category coverage.

    Uses mocked anthropic client; no real API calls.
    """

    def test_classify_returns_expected_shape(self, monkeypatch):
        import email_mining

        # Mock the anthropic call to return a known classification.
        def fake_call(messages, system):
            return '{"category":"invoice","priority":"P2","entities":{"vendor":"Sysco","amount_cents":124000,"currency":"USD","invoice_number":"INV-001","due_date":"2026-04-25"}}'

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)

        result = email_mining.classify_and_extract({
            "from_addr": "billing@sysco.com",
            "subject": "Invoice INV-001",
            "snippet": "Your invoice for $1,240.00 is attached.",
            "body": "Dear customer, please find attached invoice INV-001 for $1,240.00 due 2026-04-25.",
        })

        assert result["category"] == "invoice"
        assert result["priority"] == "P2"
        assert result["entities"]["vendor"] == "Sysco"
        assert result["entities"]["amount_cents"] == 124000

    def test_classify_unknown_category_falls_back_to_other(self, monkeypatch):
        import email_mining

        def fake_call(messages, system):
            return '{"category":"not_a_real_category","priority":"P3","entities":{}}'

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)
        result = email_mining.classify_and_extract({
            "from_addr": "x@y.com", "subject": "hi", "snippet": "hi", "body": "hi"
        })
        assert result["category"] == "other"
        assert result["priority"] == "P3"

    def test_classify_malformed_json_returns_error_category(self, monkeypatch):
        import email_mining

        def fake_call(messages, system):
            return "this is not json at all"

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)
        result = email_mining.classify_and_extract({
            "from_addr": "x@y.com", "subject": "hi", "snippet": "hi", "body": "hi"
        })
        assert result["category"] == "_error"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestClassifier -v
```

Expected: 3 FAILED (ImportError: No module named 'email_mining').

- [ ] **Step 3: Create `email_mining.py` with classifier**

Create `email_mining.py`:

```python
"""Email mining pipeline — classify, extract, route, archive.

Spec: docs/superpowers/specs/2026-04-13-email-mining-pipeline-design.md
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

# ── Category taxonomy ────────────────────────────────────────────────────────

PRIORITY_CATEGORIES = {
    "coinbits_legal",
    "prime_trust_lawsuit",
    "investor_relations",
    "somerville_purchase",
}

ACTIONABLE_CATEGORIES = {
    "invoice",
    "customer_complaint",
    "deal_pitch",
    "personal",
}

NOISE_CATEGORIES = {
    "newsletter",
    "automated_notification",
    "transactional_receipt",
    "spam_adjacent",
    "other",
}

ALL_CATEGORIES = PRIORITY_CATEGORIES | ACTIONABLE_CATEGORIES | NOISE_CATEGORIES

# Categories that should NEVER have Gmail INBOX label removed automatically.
# Priority categories always stay in inbox. 'personal' stays in inbox (human domain).
NEVER_ARCHIVE = PRIORITY_CATEGORIES | {"personal"}

DEFAULT_MODEL = os.environ.get("EMAIL_MINING_MODEL", "claude-sonnet-4-6")

# ── Classifier ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are Shams's email triage classifier. You read one email at a time and output a single JSON object classifying it.

CATEGORIES (choose exactly one):

Priority (P1 — always escalate, never auto-archive):
- coinbits_legal: Counsel emails for Coinbits wind-down (Cooley LLP, named attorneys), distribution schedules, regulatory comms related to the Coinbits shutdown.
- prime_trust_lawsuit: Counsel correspondence, settlement offers, court filings, discovery requests, or anything referencing the Prime Trust litigation.
- investor_relations: Actual humans — current or prospective investors, partners — reaching out. NOT automated investor update newsletters (those are 'newsletter').
- somerville_purchase: Real estate counsel, purchase docs, title/escrow, seller correspondence for the Somerville property purchase.

Actionable (P2 — routed + auto-archived except 'personal'):
- invoice: A bill/invoice requesting payment.
- customer_complaint: A QCC customer complaining about product, shipping, subscription, etc.
- deal_pitch: An unsolicited pitch for an acquisition, partnership, or investment opportunity.
- personal: Friends, family, non-business personal correspondence.

Noise (P3/P4 — archived):
- newsletter: Marketing/newsletter content, investor update blasts, industry digests.
- automated_notification: Mercury, Shopify, Stripe, GitHub, LinkedIn alerts, platform notifications.
- transactional_receipt: Order confirmations, shipping updates, auto-generated receipts.
- spam_adjacent: Low-quality outreach, generic sales spam.
- other: Doesn't fit above — use sparingly.

ENTITIES (JSON object, schema varies by category):
- invoice: {vendor, amount_cents, currency, invoice_number, due_date (YYYY-MM-DD or null)}
- customer_complaint: {customer_email, customer_name, order_id, issue_summary, severity ('low'|'med'|'high')}
- priority categories: {people:[...], firms:[...], action_needed:bool, deadline:YYYY-MM-DD|null, tldr:'...'}
- everything else: {action_needed: false}

OUTPUT (STRICT JSON, no prose, no markdown fences):
{"category": "<one_of_above>", "priority": "P1"|"P2"|"P3"|"P4", "entities": {...}}"""


def _call_sonnet(messages: list[dict], system: str) -> str:
    """Invoke Sonnet 4.6. Returns the raw text. Raises on API error."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return resp.content[0].text


def classify_and_extract(email: dict) -> dict:
    """Classify one email and extract entities.

    Returns {"category": str, "priority": str, "entities": dict}.
    On parser error, returns {"category": "_error", "priority": "P4", "entities": {"error": ...}}.
    """
    user_msg = (
        f"From: {email.get('from_addr','')}\n"
        f"Subject: {email.get('subject','')}\n\n"
        f"Snippet: {email.get('snippet','')}\n\n"
        f"Body (truncated):\n{(email.get('body') or '')[:8000]}"
    )

    try:
        raw = _call_sonnet(
            messages=[{"role": "user", "content": user_msg}],
            system=_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error(f"Classifier API error: {e}")
        return {"category": "_error", "priority": "P4", "entities": {"error": str(e)}}

    try:
        # Strip any accidental markdown fences.
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        parsed = json.loads(stripped)
    except Exception as e:
        logger.error(f"Classifier JSON parse error: {e}; raw={raw[:500]}")
        return {"category": "_error", "priority": "P4", "entities": {"error": "parse_failed", "raw": raw[:500]}}

    category = parsed.get("category", "other")
    if category not in ALL_CATEGORIES:
        logger.warning(f"Classifier returned unknown category '{category}'; falling back to 'other'")
        category = "other"

    priority = parsed.get("priority", "P3")
    if priority not in {"P1", "P2", "P3", "P4"}:
        priority = "P3"

    entities = parsed.get("entities", {}) or {}

    return {"category": category, "priority": priority, "entities": entities}
```

- [ ] **Step 4: Run classifier tests**

```bash
pytest tests/test_email_mining.py::TestClassifier -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_mining.py tests/test_email_mining.py
git commit -m "Email mining: classifier + extractor with category taxonomy"
```

---

## Task 6: Add router — send extracted data to AP queue / CX log / Scout

**Files:**
- Modify: `email_mining.py` — add `route_extracted()`
- Modify: `tests/test_email_mining.py` — add `TestRouter` class

- [ ] **Step 1: Write failing tests for the router**

Append to `tests/test_email_mining.py`:

```python
@pytest.mark.usefixtures("setup_db")
class TestRouter:
    def test_route_invoice_creates_ap_queue_row(self):
        import email_mining, memory, db

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_route_inv_001",
            "gmail_thread_id": "t_inv",
            "subject": "Invoice",
            "category": "invoice",
            "priority": "P2",
            "entities": {},
        })
        email_mining.route_extracted(
            archive_id=archive_id,
            category="invoice",
            entities={"vendor": "Odeko", "amount_cents": 85000, "currency": "USD",
                      "invoice_number": "ODK-42", "due_date": "2026-05-01"},
        )
        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT vendor, amount_cents, invoice_number FROM shams_ap_queue WHERE archive_id = %s", (archive_id,))
                row = cur.fetchone()
        finally:
            db.put_conn(conn)
        assert row == ("Odeko", 85000, "ODK-42")

    def test_route_customer_complaint_creates_cx_row(self):
        import email_mining, memory, db

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_route_cx_001",
            "gmail_thread_id": "t_cx",
            "subject": "stale",
            "category": "customer_complaint",
            "priority": "P2",
            "entities": {},
        })
        email_mining.route_extracted(
            archive_id=archive_id,
            category="customer_complaint",
            entities={"customer_email": "c@c.com", "customer_name": "C",
                      "issue_summary": "stale beans", "severity": "high"},
        )
        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT customer_email, severity FROM shams_cx_log WHERE archive_id = %s", (archive_id,))
                row = cur.fetchone()
        finally:
            db.put_conn(conn)
        assert row == ("c@c.com", "high")

    def test_route_deal_pitch_calls_create_deal(self, monkeypatch):
        import email_mining

        captured = {}
        def fake_create_deal(**kwargs):
            captured.update(kwargs)
            return 42
        monkeypatch.setattr("memory.create_deal", fake_create_deal)

        email_mining.route_extracted(
            archive_id=1,
            category="deal_pitch",
            entities={"title": "Red House Roasters buyout",
                      "deal_type": "acquisition",
                      "contact": "broker@x.com"},
            source_subject="Possible sale",
        )
        assert captured["title"] == "Red House Roasters buyout"
        assert captured["deal_type"] == "acquisition"

    def test_route_noise_does_nothing(self):
        import email_mining
        # Should not raise, no side effects.
        email_mining.route_extracted(archive_id=None, category="newsletter", entities={})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestRouter -v
```

Expected: 4 FAILED (`AttributeError: module 'email_mining' has no attribute 'route_extracted'`).

- [ ] **Step 3: Implement `route_extracted` in `email_mining.py`**

Append to `email_mining.py`:

```python
# ── Router ───────────────────────────────────────────────────────────────────

def route_extracted(
    archive_id: int | None,
    category: str,
    entities: dict,
    source_subject: str = "",
) -> None:
    """Route extracted data to the right downstream table based on category.

    No-op for categories that don't route (priority categories, noise, errors).
    """
    import memory

    if archive_id is None:
        return

    if category == "invoice":
        memory.insert_ap_invoice({
            "archive_id": archive_id,
            "vendor": entities.get("vendor"),
            "amount_cents": entities.get("amount_cents"),
            "currency": entities.get("currency", "USD"),
            "invoice_number": entities.get("invoice_number"),
            "due_date": entities.get("due_date"),
            "notes": None,
        })
        return

    if category == "customer_complaint":
        memory.insert_cx_complaint({
            "archive_id": archive_id,
            "customer_email": entities.get("customer_email"),
            "customer_name": entities.get("customer_name"),
            "issue_summary": entities.get("issue_summary"),
            "severity": entities.get("severity"),
        })
        return

    if category == "deal_pitch":
        title = entities.get("title") or source_subject or "Untitled deal"
        memory.create_deal(
            title=title,
            deal_type=entities.get("deal_type", "other"),
            value=float(entities.get("value", 0) or 0),
            contact=entities.get("contact", ""),
            source="email_mining",
            location=entities.get("location", ""),
            next_action=entities.get("next_action", ""),
            score=int(entities.get("score", 0) or 0),
            notes=entities.get("notes", ""),
        )
        return

    # Priority categories, noise, personal, _error — no routing.
    return
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_email_mining.py::TestRouter -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_mining.py tests/test_email_mining.py
git commit -m "Email mining: router to AP queue, CX log, Scout pipeline"
```

---

## Task 7: Add Gmail-side archiver with priority safety net

**Files:**
- Modify: `email_mining.py` — add `archive_in_gmail()`
- Modify: `tests/test_email_mining.py` — add `TestArchiver` class

- [ ] **Step 1: Write failing tests**

Append to `tests/test_email_mining.py`:

```python
class TestArchiver:
    def test_archive_skips_priority_categories(self, monkeypatch):
        import email_mining

        called = {"archive": False, "mark_read": False}
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: called.update({"archive": True}) or True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: called.update({"mark_read": True}) or True)

        for cat in email_mining.PRIORITY_CATEGORIES:
            called["archive"] = False
            called["mark_read"] = False
            result = email_mining.archive_in_gmail("personal", "msg1", category=cat)
            assert result is False, f"priority category {cat} should NOT archive"
            assert called["archive"] is False
            assert called["mark_read"] is False

    def test_archive_skips_personal(self, monkeypatch):
        import email_mining
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: True)
        assert email_mining.archive_in_gmail("personal", "msg1", category="personal") is False

    def test_archive_skips_error(self, monkeypatch):
        import email_mining
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: True)
        assert email_mining.archive_in_gmail("personal", "msg1", category="_error") is False

    def test_archive_noise_calls_gmail(self, monkeypatch):
        import email_mining

        calls = []
        monkeypatch.setattr("google_client.archive_email", lambda acct, mid: calls.append(("archive", acct, mid)) or True)
        monkeypatch.setattr("google_client.mark_read", lambda acct, mid: calls.append(("mark_read", acct, mid)) or True)

        result = email_mining.archive_in_gmail("coinbits", "msgXYZ", category="newsletter")
        assert result is True
        assert ("archive", "coinbits", "msgXYZ") in calls
        assert ("mark_read", "coinbits", "msgXYZ") in calls

    def test_archive_respects_dry_run(self, monkeypatch):
        import email_mining

        monkeypatch.setenv("EMAIL_MINING_DRY_RUN", "true")
        calls = []
        monkeypatch.setattr("google_client.archive_email", lambda *a: calls.append("archive") or True)
        monkeypatch.setattr("google_client.mark_read", lambda *a: calls.append("mark_read") or True)

        result = email_mining.archive_in_gmail("coinbits", "msgXYZ", category="newsletter")
        assert result is False, "dry-run should not touch Gmail"
        assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestArchiver -v
```

Expected: 5 FAILED.

- [ ] **Step 3: Implement `archive_in_gmail`**

Append to `email_mining.py`:

```python
# ── Gmail-side archiver with safety net ──────────────────────────────────────

def _dry_run_enabled() -> bool:
    return os.environ.get("EMAIL_MINING_DRY_RUN", "").lower() in ("1", "true", "yes")


def archive_in_gmail(account_key: str, gmail_message_id: str, category: str) -> bool:
    """Archive an email in Gmail (remove INBOX + UNREAD labels), subject to safety rules.

    Returns True if Gmail was actually mutated, False if skipped.
    Hard guards:
      - Never archives priority categories.
      - Never archives 'personal' (stays in inbox for human review).
      - Never archives '_error' rows.
      - No-op under EMAIL_MINING_DRY_RUN.
    """
    if category in NEVER_ARCHIVE:
        return False
    if category == "_error":
        return False
    if category not in ALL_CATEGORIES:
        logger.warning(f"archive_in_gmail: unknown category '{category}', refusing to archive")
        return False
    if _dry_run_enabled():
        logger.info(f"[DRY RUN] would archive {account_key}:{gmail_message_id} ({category})")
        return False

    import google_client
    ok_archive = google_client.archive_email(account_key, gmail_message_id)
    ok_read = google_client.mark_read(account_key, gmail_message_id)
    return ok_archive and ok_read
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_email_mining.py::TestArchiver -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_mining.py tests/test_email_mining.py
git commit -m "Email mining: Gmail archiver with priority safety net + dry-run support"
```

---

## Task 8: Add Telegram escalator for new priority threads

**Files:**
- Modify: `email_mining.py` — add `maybe_escalate()`
- Modify: `tests/test_email_mining.py` — add `TestEscalator` class

- [ ] **Step 1: Write failing tests**

Append to `tests/test_email_mining.py`:

```python
@pytest.mark.usefixtures("setup_db")
class TestEscalator:
    def test_new_thread_fires_telegram(self, monkeypatch):
        import email_mining, memory

        sent = []
        monkeypatch.setattr("telegram.send_message", lambda text, **kw: sent.append(text) or True)

        archive_id = memory.insert_email_archive({
            "account": "coinbits",
            "gmail_message_id": "msg_esc_new_001",
            "gmail_thread_id": "thread_esc_new_001",
            "from_addr": "counsel@cooley.com",
            "from_name": "Sarah Goldstein",
            "subject": "Re: Final distribution",
            "snippet": "Per our call yesterday...",
            "category": "coinbits_legal",
            "priority": "P1",
            "entities": {},
        })
        email_mining.maybe_escalate(archive_id=archive_id,
                                    category="coinbits_legal",
                                    gmail_thread_id="thread_esc_new_001",
                                    from_name="Sarah Goldstein",
                                    from_addr="counsel@cooley.com",
                                    subject="Re: Final distribution",
                                    snippet="Per our call yesterday...")
        assert len(sent) == 1
        assert "coinbits_legal" in sent[0].lower() or "coinbits" in sent[0].lower()
        assert "Sarah" in sent[0]

    def test_reply_on_existing_thread_does_not_fire(self, monkeypatch):
        import email_mining, memory

        sent = []
        monkeypatch.setattr("telegram.send_message", lambda text, **kw: sent.append(text) or True)

        archive_id = memory.insert_email_archive({
            "account": "coinbits",
            "gmail_message_id": "msg_esc_existing_001",
            "gmail_thread_id": "thread_esc_existing_001",
            "category": "coinbits_legal",
            "priority": "P1",
            "entities": {},
        })
        memory.record_thread_escalation("thread_esc_existing_001", "coinbits_legal", archive_id)

        email_mining.maybe_escalate(archive_id=archive_id,
                                    category="coinbits_legal",
                                    gmail_thread_id="thread_esc_existing_001",
                                    from_name="X", from_addr="x@y.com",
                                    subject="Re:", snippet="...")
        assert sent == []

    def test_non_priority_does_not_fire(self, monkeypatch):
        import email_mining
        sent = []
        monkeypatch.setattr("telegram.send_message", lambda text, **kw: sent.append(text) or True)

        email_mining.maybe_escalate(archive_id=999, category="invoice",
                                    gmail_thread_id="whatever",
                                    from_name="V", from_addr="v@v.com",
                                    subject="inv", snippet="...")
        assert sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestEscalator -v
```

Expected: 3 FAILED.

- [ ] **Step 3: Implement `maybe_escalate`**

Append to `email_mining.py`:

```python
# ── Telegram escalator ───────────────────────────────────────────────────────

_CATEGORY_EMOJI = {
    "coinbits_legal": "⚖️",
    "prime_trust_lawsuit": "🏛️",
    "investor_relations": "💼",
    "somerville_purchase": "🏠",
}

_CATEGORY_LABEL = {
    "coinbits_legal": "Coinbits Legal",
    "prime_trust_lawsuit": "Prime Trust Lawsuit",
    "investor_relations": "Investor Relations",
    "somerville_purchase": "Somerville Purchase",
}


def maybe_escalate(
    archive_id: int,
    category: str,
    gmail_thread_id: str,
    from_name: str,
    from_addr: str,
    subject: str,
    snippet: str,
) -> bool:
    """Fire a Telegram ping if this is a new priority thread.

    Returns True if a ping was sent.
    """
    import memory
    import telegram

    if category not in PRIORITY_CATEGORIES:
        return False
    if memory.thread_already_escalated(gmail_thread_id):
        return False

    emoji = _CATEGORY_EMOJI.get(category, "🚨")
    label = _CATEGORY_LABEL.get(category, category)
    display_from = f"{from_name} <{from_addr}>" if from_name else from_addr

    text = (
        f"🚨 {emoji} *{label}* — new thread\n"
        f"From: {display_from}\n"
        f"Subject: {subject}\n"
        f"{(snippet or '')[:200]}\n"
        f"→ https://app.myshams.ai/inbox/{archive_id}"
    )

    try:
        telegram.send_message(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Telegram escalation failed: {e}")
        return False

    memory.record_thread_escalation(gmail_thread_id, category, archive_id)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_email_mining.py::TestEscalator -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_mining.py tests/test_email_mining.py
git commit -m "Email mining: Telegram escalator for new priority threads only"
```

---

## Task 9: Build `process_email` orchestrator

**Files:**
- Modify: `email_mining.py` — add `process_email()`
- Modify: `tests/test_email_mining.py` — add `TestProcessEmail` class

- [ ] **Step 1: Write failing tests**

Append to `tests/test_email_mining.py`:

```python
@pytest.mark.usefixtures("setup_db")
class TestProcessEmail:
    def test_process_invoice_end_to_end(self, monkeypatch):
        """Invoice flows through classifier → archive row → AP queue → Gmail archive."""
        import email_mining, memory, db

        monkeypatch.setattr(email_mining, "_call_sonnet",
            lambda m, s: '{"category":"invoice","priority":"P2","entities":{"vendor":"Sysco","amount_cents":124000,"currency":"USD","invoice_number":"INV-E2E-001","due_date":"2026-05-01"}}')
        gmail_calls = []
        monkeypatch.setattr("google_client.archive_email",
            lambda acct, mid: gmail_calls.append(("archive", acct, mid)) or True)
        monkeypatch.setattr("google_client.mark_read",
            lambda acct, mid: gmail_calls.append(("mark_read", acct, mid)) or True)

        email = {
            "account": "qcc",
            "gmail_message_id": "msg_e2e_inv_001",
            "gmail_thread_id": "thread_e2e_inv_001",
            "from_addr": "billing@sysco.com",
            "from_name": "Sysco Billing",
            "to_addrs": ["maher@qcitycoffee.com"],
            "subject": "Invoice INV-E2E-001",
            "date": "2026-04-13T00:00:00Z",
            "snippet": "Your invoice is attached",
            "body": "Please find attached invoice INV-E2E-001 for $1,240.00 due 2026-05-01",
        }
        result = email_mining.process_email(email)
        assert result["archive_id"] is not None
        assert result["category"] == "invoice"
        assert result["gmail_archived"] is True

        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT invoice_number FROM shams_ap_queue WHERE archive_id = %s",
                            (result["archive_id"],))
                assert cur.fetchone() == ("INV-E2E-001",)
        finally:
            db.put_conn(conn)
        assert ("archive", "qcc", "msg_e2e_inv_001") in gmail_calls

    def test_process_priority_does_not_archive_and_fires_telegram(self, monkeypatch):
        """Priority email stays in inbox, fires Telegram on first thread occurrence."""
        import email_mining

        monkeypatch.setattr(email_mining, "_call_sonnet",
            lambda m, s: '{"category":"coinbits_legal","priority":"P1","entities":{"tldr":"review settlement draft"}}')
        gmail_calls = []
        monkeypatch.setattr("google_client.archive_email",
            lambda *a: gmail_calls.append("archive") or True)
        sent = []
        monkeypatch.setattr("telegram.send_message", lambda t, **kw: sent.append(t) or True)

        email = {
            "account": "coinbits",
            "gmail_message_id": "msg_e2e_legal_001",
            "gmail_thread_id": "thread_e2e_legal_001",
            "from_addr": "sgoldstein@cooley.com",
            "from_name": "Sarah Goldstein",
            "to_addrs": ["maher@coinbits.app"],
            "subject": "Re: distribution",
            "date": "2026-04-13T00:00:00Z",
            "snippet": "Please review the attached draft",
            "body": "Per our discussion...",
        }
        result = email_mining.process_email(email)
        assert result["category"] == "coinbits_legal"
        assert result["gmail_archived"] is False
        assert result["escalated"] is True
        assert gmail_calls == []
        assert len(sent) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_email_mining.py::TestProcessEmail -v
```

Expected: 2 FAILED (`AttributeError: module 'email_mining' has no attribute 'process_email'`).

- [ ] **Step 3: Implement `process_email`**

Append to `email_mining.py`:

```python
# ── Orchestrator ─────────────────────────────────────────────────────────────

def process_email(email: dict) -> dict:
    """Run the full classify → extract → route → archive pipeline on one email.

    `email` must contain at least: account, gmail_message_id, gmail_thread_id.
    Other fields (from_addr, subject, body, etc.) should be present for good classification.

    Returns: {archive_id, category, priority, gmail_archived, escalated}
    """
    import memory

    # 1. Classify + extract.
    classification = classify_and_extract(email)
    category = classification["category"]
    priority = classification["priority"]
    entities = classification["entities"]

    # 2. Write archive row (idempotent).
    archive_id = memory.insert_email_archive({
        **email,
        "category": category,
        "priority": priority,
        "entities": entities,
        "processed_model": DEFAULT_MODEL,
    })

    # 3. Route extracted data to destination tables.
    route_extracted(
        archive_id=archive_id,
        category=category,
        entities=entities,
        source_subject=email.get("subject", ""),
    )

    # 4. Archive in Gmail (with safety net).
    gmail_archived = archive_in_gmail(
        account_key=email["account"],
        gmail_message_id=email["gmail_message_id"],
        category=category,
    )
    if gmail_archived and archive_id is not None:
        # Persist the archived flag.
        import db
        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE shams_email_archive SET gmail_archived = TRUE WHERE id = %s",
                    (archive_id,),
                )
                conn.commit()
        finally:
            db.put_conn(conn)

    # 5. Escalate via Telegram if priority + new thread.
    escalated = False
    if archive_id is not None and category in PRIORITY_CATEGORIES:
        escalated = maybe_escalate(
            archive_id=archive_id,
            category=category,
            gmail_thread_id=email.get("gmail_thread_id", ""),
            from_name=email.get("from_name", ""),
            from_addr=email.get("from_addr", ""),
            subject=email.get("subject", ""),
            snippet=email.get("snippet", ""),
        )

    return {
        "archive_id": archive_id,
        "category": category,
        "priority": priority,
        "gmail_archived": gmail_archived,
        "escalated": escalated,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_email_mining.py::TestProcessEmail -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Run all email mining tests**

```bash
pytest tests/test_email_mining.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add email_mining.py tests/test_email_mining.py
git commit -m "Email mining: process_email orchestrator end-to-end"
```

---

## Task 10: Add `fetch_gmail_message_full` helper to `google_client.py`

**Files:**
- Modify: `google_client.py` — add full-message fetch
- (uses existing `get_email_body` + direct API call for metadata + body in one shot)

- [ ] **Step 1: Add helper**

Append to `google_client.py`:

```python
def fetch_full_message(account_key: str, message_id: str) -> dict | None:
    """Fetch full headers + plain-text body for a message. Returns a dict suitable
    for email_mining.process_email(), or None on failure.
    """
    import base64
    token = _get_access_token(account_key)
    if not token:
        return None
    email_addr = GOOGLE_ACCOUNTS.get(account_key, account_key)
    r = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        headers=_gmail_headers(token),
        params={"format": "full"},
        timeout=20,
    )
    if not r.ok:
        logger.error(f"fetch_full_message error {r.status_code} for {account_key}:{message_id}")
        return None
    data = r.json()
    payload = data.get("payload", {})
    hdrs = {h["name"]: h["value"] for h in payload.get("headers", [])}

    def _extract_text(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            text = _extract_text(sub)
            if text:
                return text
        return ""

    body = _extract_text(payload)[:50000]

    from_hdr = hdrs.get("From", "")
    from_name, from_addr = from_hdr, from_hdr
    if "<" in from_hdr and ">" in from_hdr:
        from_name = from_hdr.split("<")[0].strip().strip('"')
        from_addr = from_hdr.split("<")[1].split(">")[0].strip()

    return {
        "account": account_key,
        "account_email": email_addr,
        "gmail_message_id": message_id,
        "gmail_thread_id": data.get("threadId", ""),
        "from_addr": from_addr,
        "from_name": from_name,
        "to_addrs": [a.strip() for a in hdrs.get("To", "").split(",") if a.strip()],
        "subject": hdrs.get("Subject", ""),
        "date": hdrs.get("Date", ""),
        "snippet": data.get("snippet", ""),
        "body": body,
    }
```

- [ ] **Step 2: Manual smoke test**

```bash
cd /Users/mj/code/Shams
python3 -c "
import os
for line in open('.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1); os.environ[k] = v
os.environ.setdefault('GOOGLE_CLIENT_ID', '$(railway variables --json | python3 -c \"import sys,json;print(json.load(sys.stdin)['GOOGLE_CLIENT_ID'])\")')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', '$(railway variables --json | python3 -c \"import sys,json;print(json.load(sys.stdin)['GOOGLE_CLIENT_SECRET'])\")')
import importlib, config; importlib.reload(config)
from google_client import get_unread_emails_for_account, fetch_full_message
emails = get_unread_emails_for_account('qcc', max_results=1)
if emails:
    full = fetch_full_message('qcc', emails[0]['message_id'])
    print('SUBJECT:', full['subject'])
    print('FROM:', full['from_name'], '<'+full['from_addr']+'>')
    print('BODY (first 200 chars):', (full['body'] or '')[:200])
"
```

Expected: prints a real subject, from, and body snippet.

- [ ] **Step 3: Commit**

```bash
git add google_client.py
git commit -m "Email mining: add fetch_full_message helper to google_client"
```

---

## Task 11: Build backfill script with chunking + resumable cursor

**Files:**
- Create: `scripts/backfill_email_mining.py`

- [ ] **Step 1: Create script**

```python
# scripts/backfill_email_mining.py
"""One-time historical backfill of the Shams email archive.

Processes ~57K emails across personal/coinbits/qcc accounts in chunks of 500.
Resumable via per-account cursor stored in shams_memory.

Usage:
    # Dry-run (no Gmail mutations)
    EMAIL_MINING_DRY_RUN=true python -m scripts.backfill_email_mining [--account qcc] [--limit 1000]

    # Live
    python -m scripts.backfill_email_mining
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import requests

# Ensure Shams project root is on path when running as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")

CHUNK_SIZE = 500


def list_message_ids(account_key: str, page_token: str | None) -> tuple[list[str], str | None]:
    """List message IDs in bulk. No query → lists all mail (not just inbox)."""
    import google_client
    token = google_client._get_access_token(account_key)
    if not token:
        return [], None
    params = {"maxResults": CHUNK_SIZE, "includeSpamTrash": "false"}
    if page_token:
        params["pageToken"] = page_token
    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers={"Authorization": f"Bearer {token}"},
        params=params, timeout=30,
    )
    if not r.ok:
        logger.error(f"list error for {account_key}: {r.status_code} {r.text[:200]}")
        return [], None
    data = r.json()
    ids = [m["id"] for m in data.get("messages", [])]
    return ids, data.get("nextPageToken")


def process_chunk(account_key: str, message_ids: list[str]) -> dict:
    import email_mining
    import google_client
    import memory

    processed = 0
    errors = 0
    category_counts: dict[str, int] = {}

    for mid in message_ids:
        # Skip if already processed (idempotency).
        # (A more elaborate check would query shams_email_archive; the UNIQUE
        # constraint in insert_email_archive also protects us.)
        try:
            full = google_client.fetch_full_message(account_key, mid)
            if not full:
                errors += 1
                continue
            result = email_mining.process_email(full)
            processed += 1
            category_counts[result["category"]] = category_counts.get(result["category"], 0) + 1
        except Exception as e:
            logger.error(f"process error {account_key}:{mid}: {e}")
            errors += 1

    return {"processed": processed, "errors": errors, "categories": category_counts}


def backfill_account(account_key: str, limit: int | None) -> None:
    import memory

    total = 0
    while True:
        cursor = memory.get_backfill_cursor(account_key)
        ids, next_token = list_message_ids(account_key, cursor)
        if not ids:
            logger.info(f"{account_key}: no more messages (cursor exhausted)")
            break

        stats = process_chunk(account_key, ids)
        total += stats["processed"]
        logger.info(
            f"{account_key}: processed={stats['processed']} errors={stats['errors']} "
            f"total={total} categories={stats['categories']}"
        )

        if next_token is None:
            logger.info(f"{account_key}: reached end of mailbox")
            memory.set_backfill_cursor(account_key, "")  # sentinel for "done"
            break

        memory.set_backfill_cursor(account_key, next_token)

        if limit and total >= limit:
            logger.info(f"{account_key}: hit --limit {limit}, stopping")
            break

        time.sleep(1)  # polite pacing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", choices=["personal", "coinbits", "qcc"], default=None,
                        help="If set, only backfill this account. Otherwise all three.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max emails to process per account this run.")
    args = parser.parse_args()

    # Load .env if present.
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

    accounts = [args.account] if args.account else ["qcc", "coinbits", "personal"]

    dry = os.environ.get("EMAIL_MINING_DRY_RUN", "").lower() in ("1", "true", "yes")
    logger.info(f"Backfill start. DRY_RUN={dry} accounts={accounts} limit={args.limit}")

    for acct in accounts:
        logger.info(f"=== {acct} ===")
        backfill_account(acct, args.limit)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test in dry-run mode with small limit**

```bash
cd /Users/mj/code/Shams
EMAIL_MINING_DRY_RUN=true GOOGLE_CLIENT_ID="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_ID"])')" GOOGLE_CLIENT_SECRET="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_SECRET"])')" python3 -m scripts.backfill_email_mining --account qcc --limit 20
```

Expected: logs show `processed=20 errors=0 total=20 categories={...}`. No Gmail label changes (check by looking at the QCC inbox in Gmail — unread count unchanged).

- [ ] **Step 3: Verify DB rows**

```bash
psql "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" -c "SELECT category, COUNT(*) FROM shams_email_archive WHERE account='qcc' GROUP BY category ORDER BY 2 DESC;"
```

Expected: category counts across ~20 rows with a spread across categories.

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_email_mining.py
git commit -m "Email mining: resumable historical backfill script"
```

---

## Task 12: Replace overnight sweep in `standup.py`

**Files:**
- Modify: `standup.py` — swap `_step_email_sweep` body for a call into `email_mining`

- [ ] **Step 1: Read the current implementation**

```bash
cd /Users/mj/code/Shams
sed -n '285,340p' standup.py
```

Expected: see the current `_step_email_sweep` function body. Read it to understand its return shape (so you don't break standup reporting).

- [ ] **Step 2: Replace the body of `_step_email_sweep`**

Open `standup.py`. Find `def _step_email_sweep() -> dict:` and replace its body with:

```python
def _step_email_sweep() -> dict:
    """Nightly email mining — replaces the old triage job.

    Fetches unread messages across all three accounts, runs each through
    email_mining.process_email(), and returns a summary for the standup digest.
    """
    import email_mining
    import google_client

    stats = {
        "per_account": {},
        "categories": {},
        "escalated": 0,
        "archived": 0,
        "errors": 0,
    }

    for account_key in ("qcc", "coinbits", "personal"):
        acct_stats = {"processed": 0, "errors": 0}
        try:
            # Pull up to 100 unread per account per night.
            message_stubs = google_client.get_unread_emails_for_account(account_key, max_results=100)
        except Exception as e:
            log.error(f"nightly sweep list error {account_key}: {e}")
            stats["errors"] += 1
            stats["per_account"][account_key] = {"error": str(e)}
            continue

        for stub in message_stubs:
            try:
                full = google_client.fetch_full_message(account_key, stub["message_id"])
                if not full:
                    acct_stats["errors"] += 1
                    continue
                result = email_mining.process_email(full)
                acct_stats["processed"] += 1
                stats["categories"][result["category"]] = stats["categories"].get(result["category"], 0) + 1
                if result.get("gmail_archived"):
                    stats["archived"] += 1
                if result.get("escalated"):
                    stats["escalated"] += 1
            except Exception as e:
                log.error(f"nightly sweep process error {account_key}:{stub.get('message_id')}: {e}")
                acct_stats["errors"] += 1

        stats["per_account"][account_key] = acct_stats

    return stats
```

- [ ] **Step 3: Run existing standup tests to confirm nothing regressed**

```bash
pytest tests/test_standup.py -v
```

Expected: all PASS (tests that previously mocked the sweep still work because the function name and return-dict shape are intact).

- [ ] **Step 4: Commit**

```bash
git add standup.py
git commit -m "Email mining: cut overnight sweep over to email_mining pipeline"
```

---

## Task 13: Add Claude tools — search_email_archive, get_ap_summary, get_cx_summary

**Files:**
- Create: `tools/email_tools.py`

- [ ] **Step 1: Create the tools file**

```python
# tools/email_tools.py
"""Claude tools for querying Shams's email archive + routed tables."""
from __future__ import annotations

import logging

import db
from tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="search_email_archive",
    description="Search Shams's full email archive across all connected Gmail accounts. Supports free-text search on body/subject plus optional filters.",
    agent=None,
    schema={
        "properties": {
            "query": {"type": "string", "description": "Free-text query (matches body and subject)"},
            "account": {"type": "string", "enum": ["personal", "coinbits", "qcc"], "description": "Limit to one account"},
            "category": {"type": "string", "description": "Filter by category (e.g. 'invoice')"},
            "from_addr": {"type": "string", "description": "Filter by sender email"},
            "since": {"type": "string", "description": "ISO date, return emails on/after this date"},
            "limit": {"type": "integer", "description": "Max rows (default 20, max 100)"},
        },
        "required": [],
    },
)
def search_email_archive(
    query: str = "",
    account: str = "",
    category: str = "",
    from_addr: str = "",
    since: str = "",
    limit: int = 20,
) -> str:
    limit = max(1, min(int(limit or 20), 100))
    sql = ["SELECT id, account, date, from_addr, subject, category, priority FROM shams_email_archive WHERE 1=1"]
    params: list = []

    if query:
        sql.append("AND (to_tsvector('english', coalesce(body,'')) @@ plainto_tsquery('english', %s) OR subject ILIKE %s)")
        params.extend([query, f"%{query}%"])
    if account:
        sql.append("AND account = %s"); params.append(account)
    if category:
        sql.append("AND category = %s"); params.append(category)
    if from_addr:
        sql.append("AND from_addr ILIKE %s"); params.append(f"%{from_addr}%")
    if since:
        sql.append("AND date >= %s"); params.append(since)

    sql.append("ORDER BY date DESC LIMIT %s")
    params.append(limit)

    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
    finally:
        db.put_conn(conn)

    if not rows:
        return "No emails match those filters."
    lines = [f"Found {len(rows)} email(s):"]
    for id_, acct, date, fa, subj, cat, prio in rows:
        lines.append(f"  #{id_} [{acct} {prio} {cat}] {date} — {fa} — {subj}")
    return "\n".join(lines)


@tool(
    name="get_ap_summary",
    description="Summarize Shams's AP queue (invoices extracted from email). Filter by status, vendor, min amount.",
    agent=None,
    schema={
        "properties": {
            "status": {"type": "string", "enum": ["unpaid", "paid", "disputed", "ignored"], "description": "Filter"},
            "vendor": {"type": "string", "description": "Filter by vendor name (partial match)"},
            "min_amount_cents": {"type": "integer", "description": "Only invoices ≥ this amount"},
            "limit": {"type": "integer", "description": "Max rows (default 25, max 200)"},
        },
        "required": [],
    },
)
def get_ap_summary(status: str = "", vendor: str = "", min_amount_cents: int = 0, limit: int = 25) -> str:
    limit = max(1, min(int(limit or 25), 200))
    sql = [
        "SELECT id, vendor, amount_cents, currency, invoice_number, due_date, status",
        "FROM shams_ap_queue WHERE 1=1",
    ]
    params: list = []
    if status:
        sql.append("AND status = %s"); params.append(status)
    if vendor:
        sql.append("AND vendor ILIKE %s"); params.append(f"%{vendor}%")
    if min_amount_cents:
        sql.append("AND amount_cents >= %s"); params.append(int(min_amount_cents))
    sql.append("ORDER BY due_date ASC NULLS LAST, amount_cents DESC LIMIT %s")
    params.append(limit)

    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_cents),0) FROM shams_ap_queue WHERE status='unpaid'"
            )
            unpaid_count, unpaid_total = cur.fetchone()
    finally:
        db.put_conn(conn)

    header = f"AP queue: {unpaid_count} unpaid totaling ${unpaid_total/100:,.2f}."
    if not rows:
        return header + "\n(no rows match current filter)"
    lines = [header, ""]
    for id_, v, amt, cur_, inv, due, st in rows:
        amt_str = f"${(amt or 0)/100:,.2f} {cur_}"
        due_str = str(due) if due else "no due date"
        lines.append(f"  #{id_} {st:8s} {amt_str:>15s} — {v or '?'} — inv {inv or '?'} — due {due_str}")
    return "\n".join(lines)


@tool(
    name="get_cx_summary",
    description="Summarize Shams's customer complaint log. Filter by status or severity.",
    agent=None,
    schema={
        "properties": {
            "status": {"type": "string", "enum": ["open", "resolved"], "description": "Filter"},
            "severity": {"type": "string", "enum": ["low", "med", "high"], "description": "Filter"},
            "limit": {"type": "integer", "description": "Max rows (default 25, max 100)"},
        },
        "required": [],
    },
)
def get_cx_summary(status: str = "", severity: str = "", limit: int = 25) -> str:
    limit = max(1, min(int(limit or 25), 100))
    sql = [
        "SELECT id, customer_email, customer_name, issue_summary, severity, status, created_at",
        "FROM shams_cx_log WHERE 1=1",
    ]
    params: list = []
    if status:
        sql.append("AND status = %s"); params.append(status)
    if severity:
        sql.append("AND severity = %s"); params.append(severity)
    sql.append("ORDER BY created_at DESC LIMIT %s")
    params.append(limit)

    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
    finally:
        db.put_conn(conn)

    if not rows:
        return "No CX entries match."
    lines = [f"CX log ({len(rows)} rows):"]
    for id_, ce, cn, iss, sev, st, ts in rows:
        lines.append(f"  #{id_} [{st} {sev or '?'}] {ts} — {cn or ce or '?'}: {(iss or '')[:100]}")
    return "\n".join(lines)
```

- [ ] **Step 2: Confirm tools auto-register**

Shams's `tools/registry.py` walks the `tools/` package. New files are picked up automatically provided the app imports `tools` during startup. Smoke test by booting the Flask app:

```bash
cd /Users/mj/code/Shams
python3 -c "
import os
for line in open('.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1); os.environ[k] = v
import tools.email_tools  # force-register
from tools import registry
defs = registry.get_tool_definitions()
names = {d['name'] for d in defs}
assert 'search_email_archive' in names
assert 'get_ap_summary' in names
assert 'get_cx_summary' in names
print('All three tools registered OK')
"
```

Expected: `All three tools registered OK`.

- [ ] **Step 3: Commit**

```bash
git add tools/email_tools.py
git commit -m "Email mining: Claude tools for archive search, AP summary, CX summary"
```

---

## Task 14: Integration test — dry-run backfill on 100 real emails

**Files:**
- Create: `tests/test_email_mining_backfill.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_email_mining_backfill.py
"""Integration test: dry-run backfill against real Gmail + real Postgres.

Skipped unless GOOGLE_CLIENT_ID + DATABASE_URL are set.
Always runs in dry-run — never mutates Gmail.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


REQUIRED_ENV = ["DATABASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ANTHROPIC_API_KEY"]


@pytest.mark.skipif(
    any(not os.environ.get(k) for k in REQUIRED_ENV),
    reason="integration env missing",
)
@pytest.mark.usefixtures("setup_db")
def test_dry_run_backfill_processes_emails_without_mutating_gmail():
    env = {**os.environ, "EMAIL_MINING_DRY_RUN": "true"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backfill_email_mining",
         "--account", "qcc", "--limit", "100"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "processed=" in result.stdout or "processed=" in result.stderr

    import db
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            # At least 50 rows inserted (classifier may error on some).
            cur.execute("SELECT COUNT(*) FROM shams_email_archive WHERE account='qcc'")
            assert cur.fetchone()[0] >= 50
            # No rows marked gmail_archived under dry-run.
            cur.execute("SELECT COUNT(*) FROM shams_email_archive WHERE account='qcc' AND gmail_archived = TRUE")
            assert cur.fetchone()[0] == 0
            # Category distribution is non-trivial (not all one category).
            cur.execute("SELECT COUNT(DISTINCT category) FROM shams_email_archive WHERE account='qcc'")
            assert cur.fetchone()[0] >= 3
    finally:
        db.put_conn(conn)
```

- [ ] **Step 2: Run it**

```bash
cd /Users/mj/code/Shams
export GOOGLE_CLIENT_ID="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_ID"])')"
export GOOGLE_CLIENT_SECRET="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_SECRET"])')"
pytest tests/test_email_mining_backfill.py -v
```

Expected: PASS after ~2–5 minutes (real API calls). `shams_email_archive` will have ~100 qcc rows with a realistic category spread.

- [ ] **Step 3: Manually spot-check 20 random classifications**

```bash
psql "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" -c "
  SELECT id, from_addr, subject, category, priority
  FROM shams_email_archive
  WHERE account='qcc'
  ORDER BY random() LIMIT 20;"
```

Expected: read through. Confirm categorizations look right. Key things to verify:
- Invoices actually show `category='invoice'`
- Mercury/Shopify/etc. show `category='automated_notification'`
- Newsletters show `category='newsletter'`
- No priority categories miscategorized as noise.

If any category looks systematically wrong, tune `_SYSTEM_PROMPT` in `email_mining.py` and re-run (rows are idempotent — existing ones won't duplicate, but you'll need to DELETE and re-run if you want them reclassified).

- [ ] **Step 4: Commit**

```bash
git add tests/test_email_mining_backfill.py
git commit -m "Email mining: integration test for dry-run backfill"
```

---

## Task 15: Run live backfill on one account (qcc first — smallest)

**Files:**
- (no file changes — operational task)

- [ ] **Step 1: Run live backfill on qcc only**

```bash
cd /Users/mj/code/Shams
export GOOGLE_CLIENT_ID="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_ID"])')"
export GOOGLE_CLIENT_SECRET="$(railway variables --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["GOOGLE_CLIENT_SECRET"])')"
# NOTE: No EMAIL_MINING_DRY_RUN env — this mutates Gmail.
python3 -m scripts.backfill_email_mining --account qcc 2>&1 | tee backfill-qcc.log
```

Expected: runs for 1–3 hours. Logs show chunks of 500 processed. Gmail INBOX count for qcc drops over time. Tail `backfill-qcc.log` to monitor.

- [ ] **Step 2: Verify qcc inbox is close to zero**

In Gmail: open `maher@qcitycoffee.com` inbox. Expected: only priority emails + 'personal' + anything the classifier flagged `_error` remain. Rest are archived (visible in "All Mail").

- [ ] **Step 3: Verify Telegram got any priority pings (if there were new priority threads)**

Check Telegram for Shams escalation messages. If any threads in qcc were `coinbits_legal`/`prime_trust_lawsuit`/`investor_relations`/`somerville_purchase` with no prior row in `shams_priority_threads`, you should have received one ping per new thread.

- [ ] **Step 4: Commit the log (optional — informational)**

```bash
git add backfill-qcc.log
git commit -m "Email mining: live backfill log for qcc account"
```

---

## Task 16: Run live backfill on coinbits + personal

**Files:**
- (operational)

- [ ] **Step 1: Backfill coinbits**

```bash
cd /Users/mj/code/Shams
python3 -m scripts.backfill_email_mining --account coinbits 2>&1 | tee backfill-coinbits.log
```

Expected: 4–8 hours (22K emails). Monitor log.

- [ ] **Step 2: Backfill personal**

```bash
python3 -m scripts.backfill_email_mining --account personal 2>&1 | tee backfill-personal.log
```

Expected: 3–6 hours (14K emails).

- [ ] **Step 3: Final inbox counts**

```bash
python3 -c "
import os
for line in open('.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1); os.environ[k] = v
os.environ.setdefault('GOOGLE_CLIENT_ID', os.environ.get('GOOGLE_CLIENT_ID',''))
os.environ.setdefault('GOOGLE_CLIENT_SECRET', os.environ.get('GOOGLE_CLIENT_SECRET',''))
import importlib, config; importlib.reload(config)
import requests
from google_client import _get_access_token, GOOGLE_ACCOUNTS
for a, e in GOOGLE_ACCOUNTS.items():
    t = _get_access_token(a)
    if not t: continue
    r = requests.get('https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX', headers={'Authorization':f'Bearer {t}'}, timeout=10).json()
    print(f'{a} ({e}): inbox={r.get(\"messagesTotal\")}')
"
```

Expected: all three accounts show inbox counts in the low hundreds at most (only priority + personal + errors remain).

- [ ] **Step 4: Commit logs**

```bash
git add backfill-coinbits.log backfill-personal.log
git commit -m "Email mining: live backfill logs for coinbits + personal"
```

---

## Task 17: Deploy

**Files:**
- (operational)

- [ ] **Step 1: Push to Railway**

```bash
cd /Users/mj/code/Shams
git push origin main
```

Expected: Railway auto-builds and deploys. Watch the deploy logs in Railway dashboard.

- [ ] **Step 2: Verify overnight sweep is live**

In Railway logs, the 3am cron will run `_step_email_sweep` (now calling `email_mining.process_email` under the hood). The first real-run night after deploy, check morning standup message — it should report `processed=N archived=M escalated=K categories={...}`.

- [ ] **Step 3: Document done state**

```bash
git commit --allow-empty -m "Email mining backend: deployed + backfill complete"
```

---

## Task 18: Drop old `shams_email_triage` table (follow-up migration)

**Deferred — do NOT run this until morning standup has been verified reading from the new tables for at least a week.**

**Files:**
- Create: `migrations/2026-04-20-drop-email-triage.sql` (date whenever you actually run it)

- [ ] **Step 1: Write drop migration**

```sql
-- migrations/2026-04-20-drop-email-triage.sql
DROP TABLE IF EXISTS shams_email_triage;
```

- [ ] **Step 2: Apply + commit**

```bash
psql "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" -f migrations/2026-04-20-drop-email-triage.sql
git add migrations/2026-04-20-drop-email-triage.sql
git commit -m "Email mining: drop deprecated shams_email_triage table"
```

---

## Known Deferrals

Items from the spec that this plan intentionally does NOT ship in v1, with rationale:

1. **API retry with exponential backoff** (spec says "retry with exponential backoff, 3 attempts"). This plan falls straight through to `category='_error'` on the first classifier failure. Rationale: `_error` rows are preserved + never auto-archived, so nothing is lost — they surface in the review queue and can be reprocessed later. Simpler v1.
2. **Gmail API batch metadata fetches + asyncio concurrency** (spec says "100-msg batch endpoint, 10 parallel calls"). Backfill is sequential with `time.sleep(1)` between chunks. Cost: backfill takes ~10–15 hours wall-clock instead of ~2. Rationale: one-time job, safer to start sequential, easy to parallelize later.
3. **Body storage optimization** (spec open question: 2.8GB of body text in Postgres). This plan truncates bodies at 50KB per email (Task 10) but otherwise stores them in `shams_email_archive.body`. Follow-up if DB size pressure emerges: move bodies to object storage and keep only snippet + pointer in Postgres.
4. **Reprocessing workflow** for `_error` and misclassified rows. Manual `DELETE FROM shams_email_archive WHERE id IN (...)` + re-run backfill works today. A cleaner reprocess CLI can come later.

Track as follow-up issues after v1 is live and real usage data tells us which of these matter.

---

## Summary of Commits

| # | Task | Commit message |
|---|---|---|
| 1 | Migration SQL | `Email mining: add migration for archive, ap_queue, cx_log, priority_threads` |
| 2 | Apply migration | (operational) |
| 3 | Sync schema.sql | `Email mining: sync schema.sql with migration` |
| 4 | Memory helpers | `Email mining: memory helpers for archive, ap_queue, cx_log, priority_threads, backfill cursor` |
| 5 | Classifier | `Email mining: classifier + extractor with category taxonomy` |
| 6 | Router | `Email mining: router to AP queue, CX log, Scout pipeline` |
| 7 | Gmail archiver | `Email mining: Gmail archiver with priority safety net + dry-run support` |
| 8 | Escalator | `Email mining: Telegram escalator for new priority threads only` |
| 9 | Orchestrator | `Email mining: process_email orchestrator end-to-end` |
| 10 | Full-message fetch | `Email mining: add fetch_full_message helper to google_client` |
| 11 | Backfill script | `Email mining: resumable historical backfill script` |
| 12 | Overnight sweep cutover | `Email mining: cut overnight sweep over to email_mining pipeline` |
| 13 | Claude tools | `Email mining: Claude tools for archive search, AP summary, CX summary` |
| 14 | Integration test | `Email mining: integration test for dry-run backfill` |
| 15 | Live backfill qcc | (log commit) |
| 16 | Live backfill coinbits + personal | (log commit) |
| 17 | Deploy | `Email mining backend: deployed + backfill complete` |
| 18 | Drop old table | `Email mining: drop deprecated shams_email_triage table` (deferred) |
