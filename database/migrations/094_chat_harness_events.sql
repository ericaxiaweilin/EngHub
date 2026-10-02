-- Thread/Turn/Item event stream for the unified chat harness.
-- Existing chat_sessions/chat_messages remain the compatibility projection;
-- this table is the replayable execution ledger.

CREATE TABLE IF NOT EXISTS chat_events (
    id          VARCHAR(36) PRIMARY KEY,
    event_id    VARCHAR(36) NOT NULL UNIQUE,
    session_id  VARCHAR(36) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    request_id  VARCHAR(64) NOT NULL,
    sequence    BIGINT NOT NULL,
    event_type  VARCHAR(64) NOT NULL,
    item_id     VARCHAR(64),
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_events_session_sequence UNIQUE (session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_chat_events_session_sequence
    ON chat_events(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_chat_events_request
    ON chat_events(request_id, sequence);
CREATE INDEX IF NOT EXISTS idx_chat_events_type
    ON chat_events(event_type, created_at);
