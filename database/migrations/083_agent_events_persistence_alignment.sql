-- 083_agent_events_persistence_alignment.sql
-- 041 已存在于部分环境，但当前 schema_migrate 从 042 起管理；这里补一份
-- 幂等定义，确保新环境也能启用 Agent Event Bus 的长期审计回放。

CREATE TABLE IF NOT EXISTS agent_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    VARCHAR(36) NOT NULL,
    event_type  VARCHAR(30) NOT NULL,
    agent_key   VARCHAR(50) NOT NULL,
    factory_id  VARCHAR(50) NOT NULL,
    task_id     UUID,
    data        JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_factory
    ON agent_events(factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent
    ON agent_events(agent_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_task
    ON agent_events(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_type
    ON agent_events(event_type);
