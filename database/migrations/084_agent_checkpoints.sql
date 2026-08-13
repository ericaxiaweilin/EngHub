-- 084_agent_checkpoints.sql
-- AgentLoop 断点冷存储；内存 ring 仍作为实时热路径。

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checkpoint_key VARCHAR(64) NOT NULL UNIQUE,
    request_id VARCHAR(64) NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    messages_fp VARCHAR(64) NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    actions_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_request
    ON agent_checkpoints(request_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_created
    ON agent_checkpoints(created_at DESC);
