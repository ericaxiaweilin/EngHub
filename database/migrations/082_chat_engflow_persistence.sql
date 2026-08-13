-- 082_chat_engflow_persistence.sql
-- EngFlow Chat V2 会话、消息、遥测与评估用例持久化。
-- ORM 同步定义见 database/models.py；本 migration 用于生产部署，避免依赖 create_all。

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          VARCHAR(36) PRIMARY KEY,
    factory_id  VARCHAR(32) NOT NULL,
    user_id     VARCHAR(36),
    title       VARCHAR(255),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_factory_user
    ON chat_sessions(factory_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id            VARCHAR(36) PRIMARY KEY,
    session_id    VARCHAR(36) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role          VARCHAR(16) NOT NULL,
    content       TEXT,
    tool_calls    JSONB,
    tool_results  JSONB,
    model         VARCHAR(64),
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    request_id    VARCHAR(64),
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages(session_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_request
    ON chat_messages(request_id);

CREATE TABLE IF NOT EXISTS chat_telemetry (
    id            VARCHAR(36) PRIMARY KEY,
    request_id    VARCHAR(64) NOT NULL,
    session_id    VARCHAR(36) REFERENCES chat_sessions(id) ON DELETE SET NULL,
    phase         VARCHAR(32) NOT NULL DEFAULT 'total',
    duration_ms   NUMERIC(10,2) NOT NULL DEFAULT 0,
    model         VARCHAR(64),
    provider      VARCHAR(32),
    tools_called  JSONB NOT NULL DEFAULT '[]'::jsonb,
    rounds        INTEGER NOT NULL DEFAULT 0,
    success       BOOLEAN NOT NULL DEFAULT TRUE,
    error         TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_telemetry_request
    ON chat_telemetry(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_telemetry_session
    ON chat_telemetry(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_telemetry_failures
    ON chat_telemetry(success, created_at);

CREATE TABLE IF NOT EXISTS chat_eval_cases (
    id                     VARCHAR(36) PRIMARY KEY,
    name                   VARCHAR(120) NOT NULL,
    prompt                 TEXT NOT NULL,
    expected_tool          VARCHAR(64),
    expected_reply_keyword VARCHAR(120),
    model                  VARCHAR(64),
    factory_id             VARCHAR(32) NOT NULL DEFAULT 'F01',
    enabled                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_eval_cases_factory_enabled
    ON chat_eval_cases(factory_id, enabled, created_at DESC);
