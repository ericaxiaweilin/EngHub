-- =============================================
-- TMS (Task Management System) Tables
-- 企业级任务管理系统 - 以分发为核心
-- =============================================

-- 1. TMS 任务表（核心）
CREATE TABLE IF NOT EXISTS tms_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_code VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    task_type VARCHAR(50) NOT NULL,
    source VARCHAR(50) DEFAULT 'manual',
    priority VARCHAR(20) DEFAULT 'medium',
    points INTEGER DEFAULT 0,

    -- 分发核心字段
    status VARCHAR(30) DEFAULT 'pending_distribution',
    distribution_strategy VARCHAR(50),
    assigned_to UUID REFERENCES users(id),
    assigned_by VARCHAR(100),
    candidate_pool JSONB DEFAULT '[]',
    required_skills JSONB DEFAULT '[]',
    required_roles JSONB DEFAULT '[]',
    deadline TIMESTAMP,

    -- 审批关联
    approval_flow_id UUID,

    -- Agent 元数据
    agent_context JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',

    -- 关联工单
    related_work_order_id UUID REFERENCES work_orders(id),

    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_task_status_priority ON tms_tasks(status, priority);
CREATE INDEX idx_tms_task_type_status ON tms_tasks(task_type, status);
CREATE INDEX idx_tms_task_assigned ON tms_tasks(assigned_to, status);
CREATE INDEX idx_tms_task_code ON tms_tasks(task_code);

-- 2. TMS 审批流表
CREATE TABLE IF NOT EXISTS tms_approval_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_code VARCHAR(50) UNIQUE NOT NULL,
    task_id UUID NOT NULL REFERENCES tms_tasks(id),
    flow_type VARCHAR(50) NOT NULL DEFAULT 'sequential',
    steps JSONB NOT NULL DEFAULT '[]',
    current_step INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'active',
    initiated_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_flow_task ON tms_approval_flows(task_id);
CREATE INDEX idx_tms_flow_status ON tms_approval_flows(status);

-- 3. TMS 审批记录表
CREATE TABLE IF NOT EXISTS tms_approval_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_id UUID NOT NULL REFERENCES tms_approval_flows(id),
    step_index INTEGER NOT NULL,
    approver_id UUID REFERENCES users(id),
    action VARCHAR(20) NOT NULL,
    comment TEXT,
    acted_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_approval_flow_step ON tms_approval_records(flow_id, step_index);

-- 4. TMS 分发日志表（可审计）
CREATE TABLE IF NOT EXISTS tms_distribution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tms_tasks(id),
    strategy VARCHAR(50) NOT NULL,
    candidate_scores JSONB DEFAULT '{}',
    selected_user_id UUID REFERENCES users(id),
    reason TEXT,
    triggered_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_dist_task ON tms_distribution_logs(task_id);

-- 5. TMS Agent 操作日志（全量审计）
CREATE TABLE IF NOT EXISTS tms_agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    target_task_id UUID REFERENCES tms_tasks(id),
    payload JSONB DEFAULT '{}',
    result JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'success',
    requires_confirmation BOOLEAN DEFAULT FALSE,
    idempotency_key VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_agent_action_type ON tms_agent_actions(agent_id, action_type);
CREATE INDEX idx_tms_agent_status ON tms_agent_actions(status);

-- 6. TMS Webhook 订阅表（Agent 事件推送）
CREATE TABLE IF NOT EXISTS tms_webhook_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    event_types JSONB NOT NULL DEFAULT '[]',
    webhook_url VARCHAR(500) NOT NULL,
    secret VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tms_webhook_agent ON tms_webhook_subscriptions(agent_id);

-- 7. 添加外键约束（任务表审批流关联）
ALTER TABLE tms_tasks
    ADD CONSTRAINT fk_tms_task_approval_flow
    FOREIGN KEY (approval_flow_id) REFERENCES tms_approval_flows(id);
