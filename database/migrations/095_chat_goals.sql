-- Durable thread-level goals aligned with Codex thread/goal/set|get|clear.
CREATE TABLE IF NOT EXISTS chat_goals (
    id                  VARCHAR(36) PRIMARY KEY,
    session_id          VARCHAR(36) NOT NULL UNIQUE REFERENCES chat_sessions(id) ON DELETE CASCADE,
    factory_id          VARCHAR(32) NOT NULL,
    user_id             VARCHAR(36) NOT NULL,
    objective           TEXT NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    token_budget        INTEGER,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    time_used_seconds   INTEGER NOT NULL DEFAULT 0,
    progress_pct        INTEGER NOT NULL DEFAULT 0,
    summary             TEXT,
    blocked_reason      TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    cleared_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_goals_thread_status
    ON chat_goals(session_id, status);
CREATE INDEX IF NOT EXISTS idx_chat_goals_factory_status
    ON chat_goals(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_chat_goals_user
    ON chat_goals(user_id, updated_at DESC);
