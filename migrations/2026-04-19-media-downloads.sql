-- migrations/2026-04-19-media-downloads.sql
-- Tracks media download requests routed to the bridge so Shams can answer
-- "what's downloading?" and ping MJ when something finishes.

CREATE TABLE IF NOT EXISTS shams_media_downloads (
    id              BIGSERIAL PRIMARY KEY,
    bridge_id       TEXT,
    media_type      TEXT NOT NULL CHECK (media_type IN ('movie', 'tv')),
    title           TEXT NOT NULL,
    year            INTEGER,
    season          INTEGER,
    quality         TEXT,
    status          TEXT NOT NULL DEFAULT 'requested',
    progress_pct    REAL,
    eta_seconds     INTEGER,
    last_checked_at TIMESTAMPTZ,
    notified_ready  BOOLEAN NOT NULL DEFAULT FALSE,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_downloads_status
    ON shams_media_downloads(status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_downloads_bridge
    ON shams_media_downloads(bridge_id);
