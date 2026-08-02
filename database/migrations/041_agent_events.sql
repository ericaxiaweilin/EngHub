-- 041: 智能体事件持久化表（审计链DB备份，内存环形缓冲为主，DB为长期存储）
-- 参考 Pi Agent 的 JSONL 会话持久化设计

CREATE TABLE IF NOT EXISTS agent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(36) NOT NULL,
    event_type VARCHAR(30) NOT NULL,       -- agent_start/agent_end/action_start/action_update/action_end/steer_injected/hook_blocked/error
    agent_key VARCHAR(50) NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    task_id UUID,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_factory ON agent_events(factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type);

-- 审计链持久化表（长期存储，比内存环形缓冲更持久）
CREATE TABLE IF NOT EXISTS agent_audit_trail (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id VARCHAR(36) NOT NULL,
    agent_key VARCHAR(50) NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    task_id UUID,
    phase VARCHAR(20) NOT NULL,            -- decide/execute/verify/steer/block
    action VARCHAR(100) NOT NULL,
    input_summary TEXT DEFAULT '',
    output_summary TEXT DEFAULT '',
    duration_ms REAL DEFAULT 0,
    blocked BOOLEAN DEFAULT FALSE,
    block_reason TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_factory ON agent_audit_trail(factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON agent_audit_trail(agent_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_task ON agent_audit_trail(task_id);

-- Steer 纠偏记录表
CREATE TABLE IF NOT EXISTS agent_steers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL,
    content TEXT NOT NULL,
    injected_by VARCHAR(50) DEFAULT 'human',
    priority VARCHAR(20) DEFAULT 'normal',
    consumed BOOLEAN DEFAULT FALSE,
    consumed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_steers_task ON agent_steers(task_id, consumed);
