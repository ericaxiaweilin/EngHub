-- =============================================================================
-- Migration: 059_followup_tasks.sql
-- Description: 任务中心（待办跟进）表 — 智能体处理不完的长任务挂到这里持续跟进
-- Table: followup_tasks - 用户交代但暂时无法完成的任务，按用户设置的频率定期扫描跟进
-- Date: 2026-07-30
-- =============================================================================

CREATE TABLE IF NOT EXISTS followup_tasks (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(64) NOT NULL,             -- 工厂隔离
    created_by VARCHAR(64) NOT NULL,             -- 交代任务的用户 username
    title VARCHAR(200) NOT NULL,                 -- 任务标题（一句话）
    description TEXT,                            -- 任务详情/原始指令
    agent_key VARCHAR(64),                       -- 负责跟进的智能体（NULL = 通用，模型自选）
    agent_name VARCHAR(64),                      -- 智能体名称（冗余展示）
    status VARCHAR(20) NOT NULL DEFAULT 'open',  -- open(跟进中) / blocked(受阻) / done(完成) / cancelled(取消)
    block_reason VARCHAR(500),                   -- 当前受阻原因（为什么一下子完成不了）
    source VARCHAR(20) DEFAULT 'manual',         -- manual(用户手动挂) / chatbot(对话中自动挂)
    conversation_hint VARCHAR(500),              -- 来源对话摘要（chatbot 挂入时记录上下文）
    follow_interval_minutes INTEGER NOT NULL DEFAULT 120,  -- 跟进频率（分钟，默认 2 小时）
    next_follow_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- 下次跟进时间（扫描器据此取任务）
    last_follow_at TIMESTAMP WITH TIME ZONE,     -- 上次跟进时间
    last_follow_note TEXT,                       -- 上次跟进结论（智能体产出）
    follow_count INTEGER NOT NULL DEFAULT 0,     -- 已跟进次数
    max_follows INTEGER NOT NULL DEFAULT 60,     -- 最大跟进次数（防失控，默认 60 次）
    progress_pct INTEGER NOT NULL DEFAULT 0,     -- 进度百分比（智能体/用户更新）
    result_summary TEXT,                         -- 完成结论
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at TIMESTAMP WITH TIME ZONE           -- done/cancelled 时间
);

CREATE INDEX IF NOT EXISTS idx_followup_factory_status ON followup_tasks(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_followup_due ON followup_tasks(status, next_follow_at);
CREATE INDEX IF NOT EXISTS idx_followup_owner ON followup_tasks(created_by, status);

COMMENT ON TABLE followup_tasks IS '任务中心：暂时无法完成的任务挂账跟进，按 follow_interval_minutes 定期扫描';

-- 跟进历史（每次扫描/手动跟进留痕，形成任务时间线）
CREATE TABLE IF NOT EXISTS followup_task_logs (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(36) NOT NULL,                -- 关联 followup_tasks.id
    factory_id VARCHAR(64) NOT NULL,
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'schedule',  -- schedule(定期扫描) / manual(手动跟进) / status(状态变更)
    note TEXT,                                   -- 跟进结论/变更说明
    status_after VARCHAR(20),                    -- 本次跟进后的任务状态
    progress_pct INTEGER,                        -- 本次跟进后的进度
    created_by VARCHAR(64),                      -- 触发人（system = 定期扫描）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_followup_logs_task ON followup_task_logs(task_id, created_at DESC);

COMMENT ON TABLE followup_task_logs IS '任务中心跟进历史（定期扫描与手动跟进的时间线留痕）';
