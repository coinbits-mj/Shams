-- migrations/2026-04-15-open-commitments.sql
-- Tracks outbound commitments MJ made in emails ("I'll send X", "will get back to you by Friday", etc.)
-- so Shams can surface unfulfilled ones during morning standup.

CREATE TABLE IF NOT EXISTS shams_open_commitments (
    id                        BIGSERIAL PRIMARY KEY,
    source_archive_id         BIGINT NOT NULL REFERENCES shams_email_archive(id) ON DELETE CASCADE,
    account                   TEXT NOT NULL,
    recipient_email           TEXT,
    recipient_name            TEXT,
    commitment_text           TEXT NOT NULL,
    commitment_type           TEXT,
    promised_at               TIMESTAMPTZ NOT NULL,
    deadline                  DATE,
    status                    TEXT NOT NULL DEFAULT 'open',
    fulfilled_at              TIMESTAMPTZ,
    fulfilled_via_archive_id  BIGINT REFERENCES shams_email_archive(id) ON DELETE SET NULL,
    notes                     TEXT,
    extracted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_open_commitments_status_promised
    ON shams_open_commitments(status, promised_at DESC);
CREATE INDEX IF NOT EXISTS idx_open_commitments_recipient
    ON shams_open_commitments(recipient_email);
CREATE INDEX IF NOT EXISTS idx_open_commitments_source
    ON shams_open_commitments(source_archive_id);
