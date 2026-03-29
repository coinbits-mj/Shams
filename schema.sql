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

CREATE TABLE IF NOT EXISTS shams_folders (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    parent_id       INTEGER REFERENCES shams_folders(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_files (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(500) NOT NULL,
    file_type       VARCHAR(50) NOT NULL,     -- 'photo', 'voice', 'document', 'pdf'
    mime_type       VARCHAR(100) DEFAULT '',
    file_size       INTEGER DEFAULT 0,
    folder_id       INTEGER REFERENCES shams_folders(id),
    telegram_file_id VARCHAR(500) DEFAULT '',
    summary         TEXT DEFAULT '',           -- AI-generated summary of content
    transcript      TEXT DEFAULT '',           -- voice transcription or extracted text
    tags            TEXT[] DEFAULT '{}',       -- searchable tags
    conversation_id INTEGER REFERENCES shams_conversations(id),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_sessions (
    id              SERIAL PRIMARY KEY,
    token           VARCHAR(100) NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS shams_magic_links (
    id              SERIAL PRIMARY KEY,
    token           VARCHAR(100) NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL,
    used            BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON shams_conversations (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memory_key ON shams_memory (key);
CREATE INDEX IF NOT EXISTS idx_open_loops_status ON shams_open_loops (status);
CREATE INDEX IF NOT EXISTS idx_briefings_type_delivered ON shams_briefings (type, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_uploaded ON shams_files (uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_type ON shams_files (file_type);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON shams_sessions (token);
CREATE INDEX IF NOT EXISTS idx_magic_links_token ON shams_magic_links (token);
