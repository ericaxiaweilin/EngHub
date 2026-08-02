-- 智能体监督引擎（Agent Supervisor）
-- 长任务追踪 + 卡住检测 + 闭环验证

-- 智能体任务执行记录
CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    agent_key VARCHAR(50) NOT NULL,          -- 哪个智能体
    agent_name VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,         -- 任务类型
    task_desc TEXT,                          -- 任务描述
    
    -- 状态追踪
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- running/completed/failed/stalled/cancelled
    progress_pct REAL DEFAULT 0,             -- 进度 0-100
    total_steps INTEGER DEFAULT 1,           -- 总步骤数
    completed_steps INTEGER DEFAULT 0,       -- 已完成步骤
    
    -- 时间追踪
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_progress_at TIMESTAMP DEFAULT NOW(),  -- 最后一次有进展的时间
    completed_at TIMESTAMP,
    timeout_minutes INTEGER DEFAULT 30,      -- 超时阈值
    
    -- 结果
    result JSONB DEFAULT '{}',
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- 闭环验证
    verified BOOLEAN DEFAULT FALSE,          -- 是否已验证执行结果
    verified_at TIMESTAMP,
    verify_result TEXT,                      -- 验证结果
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent ON agent_tasks(factory_id, agent_key);

-- 智能体心跳/感知记录
CREATE TABLE IF NOT EXISTS agent_heartbeats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    agent_key VARCHAR(50) NOT NULL,
    action_taken TEXT,                       -- 做了什么
    trigger_type VARCHAR(50),                -- event/schedule/prediction/manual
    result_summary TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_time ON agent_heartbeats(factory_id, created_at DESC);

COMMENT ON TABLE agent_tasks IS '智能体长任务追踪（进度/卡住/超时/闭环验证）';
COMMENT ON TABLE agent_heartbeats IS '智能体行为心跳（主动感知记录）';
