-- 098_chat_session_events.sql
-- Chat 会话事件流（DSH SessionEvent 对齐）：append-only 轨迹。
-- Trajectory 视图从该事件流组装读模型，不再维护第二条独立历史源。
-- ORM 同步定义见 database/models.py ChatSessionEvent。

CREATE TABLE IF NOT EXISTS chat_session_events (
    id          VARCHAR(36) PRIMARY KEY,
    session_id  VARCHAR(36) NOT NULL REFERENCES chat_sessions(id),
    request_id  VARCHAR(64),
    seq         INTEGER NOT NULL,
    event_type  VARCHAR(32) NOT NULL,          -- context_injection/user_message/tool_call/assistant_reply
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_session_events_session
    ON chat_session_events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_chat_session_events_request
    ON chat_session_events(request_id);
