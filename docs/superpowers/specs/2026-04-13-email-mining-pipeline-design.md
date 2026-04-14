# Email Mining Pipeline — Design

**Date:** 2026-04-13
**Status:** Approved
**Author:** MJ + Claude

## Problem

MJ's three Gmail accounts hold ~57,000 emails (~50,000 unread):

| Account | Inbox | Unread |
|---|---|---|
| `maher.janajri@gmail.com` | 14,116 | 21,580 |
| `maher@coinbits.app` | 22,979 | 18,080 |
| `maher@qcitycoffee.com` | 19,712 | 11,302 |

Triaging one-by-one is not viable. These emails contain years of structured business signal (vendor invoices, legal correspondence, investor threads, customer complaints, deal flow) that is currently locked in unsearchable prose. Shams can neither query it nor act on it.

## Goal

Mine the entire Gmail backlog + every new email going forward, extract structured data into Shams's Postgres database, auto-archive non-critical messages in Gmail, and surface the four highest-stakes topic areas via Telegram the moment a new thread appears. Route extracted data into Shams-owned routing tables (no data leaves Shams's domain — does not push into Rumi).

## Non-Goals

- Routing anything to Rumi, Klaviyo, or any other system. Everything stays in Shams.
- Replacing Gmail as the user's primary email client. Shams mines, Shams surfaces, but the user still reads/replies in Gmail.
- Deleting any email. All actions are non-destructive (archive only — emails remain retrievable in Gmail's "All Mail").

## Architecture

Two execution paths share a single pipeline:

```
fetch → classify → extract → route → archive
```

- **One-time historical backfill** (`scripts/backfill_email_mining.py`) processes the ~57K existing emails in chunks of 500. Resumable via cursor in `shams_memory`.
- **Recurring overnight job** (`standup._step_email_mining`) replaces the existing `_step_email_sweep`. Runs at 3am, processes new messages that arrived that day.

Both paths invoke `email_mining.process_email(msg)` which does the full classify → extract → route → archive pipeline for a single message.

## Data Model

Four new Postgres tables, all prefixed `shams_`. All FKs to `shams_email_archive(id)` cascade on delete.

### `shams_email_archive`
One row per email. The system-of-record for every message Shams has seen.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `account` | TEXT | 'personal' \| 'coinbits' \| 'qcc' |
| `gmail_message_id` | TEXT UNIQUE | Dedup key |
| `gmail_thread_id` | TEXT | For thread grouping |
| `from_addr` | TEXT | |
| `from_name` | TEXT | |
| `to_addrs` | TEXT[] | |
| `subject` | TEXT | |
| `date` | TIMESTAMPTZ | |
| `snippet` | TEXT | |
| `body` | TEXT | Full plain-text body, truncated to 50KB |
| `category` | TEXT | One of the category enum values below |
| `priority` | TEXT | 'P1' \| 'P2' \| 'P3' \| 'P4' |
| `entities` | JSONB | Category-specific extracted data |
| `gmail_archived` | BOOLEAN | Whether we removed INBOX label in Gmail |
| `processed_at` | TIMESTAMPTZ | |
| `processed_model` | TEXT | Model name used |

Indexes: `(account, date DESC)`, `(category)`, `(from_addr)`, GIN on `entities`, full-text GIN on `body`.

### `shams_ap_queue`
Routed from `category='invoice'`. One row per invoice.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `archive_id` | BIGINT FK | References `shams_email_archive(id)` |
| `vendor` | TEXT | |
| `amount_cents` | BIGINT | |
| `currency` | TEXT | Default 'USD' |
| `invoice_number` | TEXT | Nullable |
| `due_date` | DATE | Nullable |
| `status` | TEXT | 'unpaid' \| 'paid' \| 'disputed' \| 'ignored' — default 'unpaid' |
| `notes` | TEXT | |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |

### `shams_cx_log`
Routed from `category='customer_complaint'`. One row per complaint.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `archive_id` | BIGINT FK | |
| `customer_email` | TEXT | |
| `customer_name` | TEXT | |
| `issue_summary` | TEXT | |
| `severity` | TEXT | 'low' \| 'med' \| 'high' |
| `status` | TEXT | 'open' \| 'resolved' — default 'open' |
| `resolution_notes` | TEXT | |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |

### `shams_priority_threads`
Tracks which threads already fired a Telegram escalation ping, so replies don't re-ping.

| Column | Type | Notes |
|---|---|---|
| `gmail_thread_id` | TEXT PK | |
| `category` | TEXT | One of the four priority categories |
| `first_seen_at` | TIMESTAMPTZ | |
| `last_email_id` | BIGINT FK | References most recent `shams_email_archive(id)` in thread |

### Scout routing
`category='deal_pitch'` writes to Scout's existing pipeline table. Exact table name to be confirmed when reading `tools/scout.py` / `context/scout_persona.md` during implementation planning.

### Old `shams_email_triage` table
Kept read-only during grace period. Dropped in a follow-up migration once morning standup is migrated to read from new tables. Nothing migrated out of it — it's a cache, not a source of truth.

## Classification

Every email classified into exactly one category. Sonnet 4.6 is the model for both classification and extraction (single prompt returns both).

### Priority categories (P1 — always-escalate, never auto-archive)

| Category | Trigger signals |
|---|---|
| `coinbits_legal` | Counsel emails (Cooley, named attorneys), wind-down mechanics, distribution schedules, regulatory communications related to Coinbits shutdown |
| `prime_trust_lawsuit` | Counsel correspondence, settlement offers, court filings, discovery requests, anything referencing the Prime Trust litigation |
| `investor_relations` | Current or prospective investor/partner outreach — NOT automated investor update newsletters (those are `newsletter`) |
| `somerville_purchase` | Real estate counsel, purchase docs, title/escrow, seller correspondence for the Somerville property |

### Actionable categories (P2 — routes + auto-archives)

| Category | Routing |
|---|---|
| `invoice` | Insert into `shams_ap_queue` with extracted vendor/amount/due_date |
| `customer_complaint` | Insert into `shams_cx_log` with extracted customer/severity |
| `deal_pitch` | Insert into Scout pipeline |
| `personal` | No routing. Stays in Gmail inbox (does not auto-archive, P2 but human-domain) |

### Noise categories (P3/P4 — archive-only)

- `newsletter` (P3)
- `automated_notification` (P3) — Mercury, Shopify, Stripe, GitHub, LinkedIn, etc.
- `transactional_receipt` (P3)
- `spam_adjacent` (P4)
- `other` (P3) — fallback

### Entities extraction

Every email gets an `entities` JSONB blob. Schema varies by category:

```jsonc
// invoice
{ "vendor": "Sysco", "amount_cents": 124000, "currency": "USD",
  "invoice_number": "INV-2026-00412", "due_date": "2026-04-25",
  "line_items": [...] }

// customer_complaint
{ "customer_email": "...", "customer_name": "...", "order_id": "...",
  "issue_summary": "...", "severity": "med" }

// coinbits_legal | prime_trust_lawsuit | somerville_purchase | investor_relations
{ "people": [...], "firms": [...], "action_needed": bool,
  "deadline": "YYYY-MM-DD" | null, "tldr": "..." }

// everything else
{ "action_needed": false }
```

## Gmail-Side Actions

After processing each email:

- **Priority categories (4 above)**: Leave `INBOX` label intact. Do not mark as read. Fire Telegram ping **only if** the `gmail_thread_id` is not already in `shams_priority_threads` (i.e., only on new threads — per approved design, replies don't re-ping).
- **`personal`**: Leave in inbox, don't touch labels.
- **All other categories**: Remove `INBOX` label. Remove `UNREAD` label. Email remains in Gmail's All Mail — never deleted.

Before any label removal, a hard guard asserts `category NOT IN PRIORITY_SET`. Belt and suspenders against classifier mistakes.

## Escalation UX

### Telegram (real-time)
On new priority thread only:
```
🚨 {CATEGORY_EMOJI} {CATEGORY_LABEL} — new thread
From: {from_name} <{from_addr}>
Subject: {subject}
{snippet[:200]}
→ {https://app.myshams.ai/inbox/{archive_id}}
```

### Dashboard (`app.myshams.ai`)
Three new views:

1. **Inbox Zero** — priority emails from last 24hrs, one-click archive or draft-reply actions
2. **AP Queue** — `shams_ap_queue` sortable/filterable by vendor, amount, due date, status; one-click mark-paid writes back to Gmail archive
3. **CX Log** — `shams_cx_log` open complaints first, resolved below
4. **Archive Search** — full-text + structured search over `shams_email_archive`

### Shams chat (Telegram + web)
Three new tools added to `claude_client.py`:
- `search_email_archive(query, filters)` — structured query
- `get_ap_summary(filters)` — "unpaid invoices over $X" etc.
- `get_cx_summary(filters)` — open complaints

### Morning standup
Pulls from new tables instead of `shams_email_triage`:
- N new priority-category emails overnight
- N new invoices routed to AP ($X total)
- N new customer complaints
- N emails auto-archived (noise cleared)

## Error Handling

- **Idempotency**: `gmail_message_id UNIQUE` ensures re-runs never double-process. `ON CONFLICT DO NOTHING` on insert.
- **Priority safety net**: hard assertion before any Gmail label mutation.
- **Failed classifications**: row inserted with `category='_error'`, `entities={"error": "..."}`. Never auto-archived. Surfaced in a "review queue" dashboard view.
- **Anthropic API failures**: retry with exponential backoff (3 attempts), then `_error`. Do not block the whole run on a single email.
- **Gmail API rate limits**: batch metadata fetches (100-msg endpoint). Concurrency cap of 10 parallel Anthropic calls via asyncio semaphore.
- **Backfill resumability**: processes in chunks of 500 messages. Cursor (`email_mining_backfill_cursor_{account}`) in `shams_memory`, updated per chunk commit. Kill + restart safely.

## Testing

- **Unit tests** (`tests/test_email_mining.py`): classifier prompt against a hand-labeled set of 50 representative emails (mix of all categories across all 3 accounts). Pytest with mocked Anthropic client.
- **Integration test** (`tests/test_email_mining_integration.py`): dry-run backfill of 100 sampled messages per account (writes DB rows, skips Gmail label changes). Assertions on category distribution, entity shape, no P1 false-negatives.
- **Manual verification before go-live**: run overnight job in dry-run (`EMAIL_MINING_DRY_RUN=true`) for 3 nights. Review output daily. Flip to live only after accuracy confirmed.

## Rollout Phases

1. **Schema + pipeline + dashboard views** (dry-run only, no Gmail mutations)
2. **Dry-run backfill** → spot-check 100 random classifications per account. Tune prompt.
3. **Live backfill** → sweeps all ~57K emails with auto-archive on. Takes several hours.
4. **Cut over overnight sweep** from `_step_email_sweep` to `_step_email_mining`.
5. **Drop old `shams_email_triage`** table (separate migration, after standup is verified reading from new tables).

## Cost Estimate

- ~57K emails × ~500 tokens input + ~150 tokens output, Sonnet 4.6
- ≈ 28.5M input tokens + 8.5M output tokens
- Current Sonnet 4.6 pricing: ~$3/MTok input, ~$15/MTok output
- **Backfill one-time: ~$215**
- Ongoing: assume ~100 new emails/day across 3 accounts ≈ $0.40/day ≈ **$12/month**

## Open Questions

- Scout pipeline table name — confirm during plan writing by reading `tools/scout.py` / `context/scout_persona.md`.
- Whether `body` storage at 50KB/email × 57K ≈ 2.8GB is acceptable on Railway Postgres. Alternative: store only snippet + truncated body, lean on Gmail API `get_email_body()` for on-demand full retrieval.
