-- migrations/2026-04-24-meeting-notes.sql

CREATE TABLE IF NOT EXISTS shams_meeting_notes (
    id                    BIGSERIAL PRIMARY KEY,
    event_id              TEXT,
    recall_bot_id         TEXT UNIQUE,
    title                 TEXT,
    started_at            TIMESTAMPTZ,
    ended_at              TIMESTAMPTZ,
    duration_min          INT,
    attendees             JSONB NOT NULL DEFAULT '[]'::jsonb,
    platform              TEXT,
    transcript            TEXT,
    summary               TEXT,
    action_items          JSONB NOT NULL DEFAULT '[]'::jsonb,
    decisions             JSONB NOT NULL DEFAULT '[]'::jsonb,
    commitments_created   INT[] DEFAULT '{}',
    commitments_resolved  INT[] DEFAULT '{}',
    persona_used          TEXT,
    meeting_type          TEXT,
    telegram_sent         BOOLEAN NOT NULL DEFAULT FALSE,
    email_sent            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meeting_notes_event
    ON shams_meeting_notes(event_id);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_started
    ON shams_meeting_notes(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_attendees_gin
    ON shams_meeting_notes USING GIN (attendees);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_action_items_gin
    ON shams_meeting_notes USING GIN (action_items);
