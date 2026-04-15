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
