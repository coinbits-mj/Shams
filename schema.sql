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

CREATE TABLE IF NOT EXISTS shams_agents (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) NOT NULL UNIQUE,     -- 'shams', 'rumi', 'leo'
    role            VARCHAR(100) NOT NULL,            -- 'Chief of Staff', 'Operations', 'Health Coach'
    status          VARCHAR(20) NOT NULL DEFAULT 'idle' CHECK (status IN ('active', 'idle', 'offline', 'error')),
    health_url      VARCHAR(500) DEFAULT '',           -- URL to ping for health check
    last_heartbeat  TIMESTAMPTZ,
    config          JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_missions (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    description     TEXT DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'inbox' CHECK (status IN ('inbox', 'assigned', 'active', 'review', 'done', 'dropped')),
    priority        VARCHAR(10) NOT NULL DEFAULT 'normal' CHECK (priority IN ('urgent', 'high', 'normal', 'low')),
    assigned_agent  VARCHAR(50) REFERENCES shams_agents(name),
    tags            TEXT[] DEFAULT '{}',
    result          TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_activity_feed (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL,
    event_type      VARCHAR(50) NOT NULL,  -- 'message', 'tool_call', 'mission_update', 'alert', 'heartbeat'
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
CREATE INDEX IF NOT EXISTS idx_missions_status ON shams_missions (status);
CREATE INDEX IF NOT EXISTS idx_missions_agent ON shams_missions (assigned_agent);
CREATE INDEX IF NOT EXISTS idx_activity_feed_ts ON shams_activity_feed (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_feed_agent ON shams_activity_feed (agent_name, timestamp DESC);

CREATE TABLE IF NOT EXISTS shams_notifications (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(50) NOT NULL,
    title           VARCHAR(500) NOT NULL,
    detail          TEXT DEFAULT '',
    link_type       VARCHAR(20) DEFAULT '',
    link_id         INTEGER,
    seen            BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_unseen ON shams_notifications (seen, created_at DESC);

-- Add mission file room columns (idempotent via DO block)
DO $$ BEGIN
    ALTER TABLE shams_files ADD COLUMN mission_id INTEGER REFERENCES shams_missions(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_files ADD COLUMN file_category VARCHAR(50) DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_files ADD COLUMN version INTEGER DEFAULT 1;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_files ADD COLUMN uploaded_by VARCHAR(50) DEFAULT 'maher';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_files_mission ON shams_files (mission_id);

CREATE TABLE IF NOT EXISTS shams_email_triage (
    id              SERIAL PRIMARY KEY,
    account         VARCHAR(50) NOT NULL,
    message_id      VARCHAR(200) NOT NULL UNIQUE,
    from_addr       TEXT DEFAULT '',
    subject         TEXT DEFAULT '',
    snippet         TEXT DEFAULT '',
    priority        VARCHAR(5) DEFAULT 'P4',
    routed_to       TEXT[] DEFAULT '{}',
    action          TEXT DEFAULT '',
    draft_reply     TEXT DEFAULT '',
    archived        BOOLEAN DEFAULT FALSE,
    triaged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_email_triage_priority ON shams_email_triage (priority);
CREATE INDEX IF NOT EXISTS idx_email_triage_account ON shams_email_triage (account);
CREATE INDEX IF NOT EXISTS idx_email_triage_archived ON shams_email_triage (archived);

CREATE TABLE IF NOT EXISTS shams_actions (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL,
    action_type     VARCHAR(50) NOT NULL,
    title           VARCHAR(500) NOT NULL,
    description     TEXT DEFAULT '',
    payload         JSONB DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'executing', 'completed', 'failed')),
    result          TEXT DEFAULT '',
    mission_id      INTEGER REFERENCES shams_missions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON shams_actions (status);
CREATE INDEX IF NOT EXISTS idx_actions_agent ON shams_actions (agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_actions_created ON shams_actions (created_at DESC);

CREATE TABLE IF NOT EXISTS shams_projects (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    brief           TEXT DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    start_date      DATE,
    target_date     DATE,
    color           VARCHAR(20) DEFAULT '#38bdf8',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add project_id, start_date, end_date, depends_on to missions
DO $$ BEGIN
    ALTER TABLE shams_missions ADD COLUMN project_id INTEGER REFERENCES shams_projects(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_missions ADD COLUMN start_date DATE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_missions ADD COLUMN end_date DATE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE shams_missions ADD COLUMN depends_on INTEGER[];
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS shams_deals (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    deal_type       VARCHAR(50) DEFAULT 'acquisition',
    stage           VARCHAR(30) NOT NULL DEFAULT 'lead'
        CHECK (stage IN ('lead', 'researching', 'evaluating', 'loi', 'due_diligence', 'closing', 'closed', 'dead')),
    value           NUMERIC DEFAULT 0,
    contact         VARCHAR(255) DEFAULT '',
    source          VARCHAR(100) DEFAULT '',
    location        VARCHAR(255) DEFAULT '',
    next_action     TEXT DEFAULT '',
    deadline        DATE,
    score           INTEGER DEFAULT 0,
    notes           TEXT DEFAULT '',
    assigned_agent  VARCHAR(50) DEFAULT 'scout',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON shams_deals (stage);

CREATE TABLE IF NOT EXISTS shams_alert_rules (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    metric          VARCHAR(100) NOT NULL,
    condition       VARCHAR(10) NOT NULL DEFAULT '<',
    threshold       NUMERIC NOT NULL,
    message_template TEXT NOT NULL,
    enabled         BOOLEAN DEFAULT TRUE,
    last_triggered  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_scheduled_tasks (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    cron_expression VARCHAR(100) NOT NULL,
    prompt          TEXT NOT NULL,
    agent_name      VARCHAR(50) DEFAULT 'shams',
    enabled         BOOLEAN DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    last_result     TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_workflows (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    description     TEXT DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'failed')),
    current_step    INTEGER DEFAULT 1,
    mission_id      INTEGER REFERENCES shams_missions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_workflow_steps (
    id              SERIAL PRIMARY KEY,
    workflow_id     INTEGER NOT NULL REFERENCES shams_workflows(id),
    step_number     INTEGER NOT NULL,
    agent_name      VARCHAR(50) NOT NULL,
    instruction     TEXT NOT NULL,
    requires_approval BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'completed', 'skipped', 'failed')),
    input_context   TEXT DEFAULT '',
    output_result   TEXT DEFAULT '',
    action_id       INTEGER REFERENCES shams_actions(id),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    UNIQUE (workflow_id, step_number)
);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow ON shams_workflow_steps (workflow_id, step_number);

CREATE TABLE IF NOT EXISTS shams_trust_scores (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL UNIQUE,
    total_proposed  INTEGER DEFAULT 0,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shams_group_chat (
    id              SERIAL PRIMARY KEY,
    agent_name      VARCHAR(50) NOT NULL,     -- 'maher', 'shams', 'rumi', 'leo'
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_group_chat_ts ON shams_group_chat (timestamp DESC);

CREATE TABLE IF NOT EXISTS shams_overnight_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      VARCHAR(20) DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    results     JSONB DEFAULT '{}',
    summary     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_overnight_runs_started ON shams_overnight_runs (started_at DESC);

-- Migrate email triage from P1-P4 priority to Reply/Read/Archive tiers
DO $$ BEGIN
    ALTER TABLE shams_email_triage ADD COLUMN tier VARCHAR(10) DEFAULT 'archive'
        CHECK (tier IN ('reply', 'read', 'archive'));
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_email_triage_tier ON shams_email_triage (tier);

CREATE TABLE IF NOT EXISTS shams_trust_actions (
    id              SERIAL PRIMARY KEY,
    action_type     VARCHAR(50) NOT NULL UNIQUE,
    total_approved  INTEGER DEFAULT 0,
    total_rejected  INTEGER DEFAULT 0,
    auto_approve    BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trust_actions_type ON shams_trust_actions (action_type);

CREATE TABLE IF NOT EXISTS shams_pl_entries (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,
    entry_type  VARCHAR(20) NOT NULL CHECK (entry_type IN ('revenue', 'cost')),
    category    VARCHAR(50) NOT NULL,
    description TEXT DEFAULT '',
    amount      NUMERIC(10,4) NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pl_entries_date ON shams_pl_entries (date DESC);
CREATE INDEX IF NOT EXISTS idx_pl_entries_type ON shams_pl_entries (entry_type, date DESC);
