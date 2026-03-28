-- Shams schema — all tables prefixed with shams_ to coexist in shared Railway Postgres

CREATE TABLE IF NOT EXISTS shams_conversations (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role            VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS shams_memory (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(255) NOT NULL UNIQUE,
    value           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_open_loops (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    context         TEXT DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dropped')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_decisions (
    id              SERIAL PRIMARY KEY,
    summary         VARCHAR(500) NOT NULL,
    reasoning       TEXT DEFAULT '',
    outcome         TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_briefings (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(50) NOT NULL,
    content         TEXT NOT NULL,
    delivered_at    TIMESTAMPTZ,
    channel         VARCHAR(50) NOT NULL DEFAULT 'whatsapp'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON shams_conversations (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memory_key ON shams_memory (key);
CREATE INDEX IF NOT EXISTS idx_open_loops_status ON shams_open_loops (status);
CREATE INDEX IF NOT EXISTS idx_briefings_type_delivered ON shams_briefings (type, delivered_at DESC);
