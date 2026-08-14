-- Persist the relation between a chat turn and uploaded files/photos so
-- attachments can be searched and reused after the request is over.

CREATE TABLE IF NOT EXISTS chat_message_attachments (
    id          VARCHAR(36) PRIMARY KEY,
    message_id  VARCHAR(36) NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id  VARCHAR(36) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    file_id     VARCHAR(36) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind        VARCHAR(16),
    ordinal     INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_msg_att_session
    ON chat_message_attachments(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_msg_att_file
    ON chat_message_attachments(file_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_msg_att_message
    ON chat_message_attachments(message_id, ordinal);
