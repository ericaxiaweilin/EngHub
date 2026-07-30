-- v2.5 - Andon 2.0 Smart Work Order Migration

CREATE TABLE IF NOT EXISTS andon_categories (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) UNIQUE NOT NULL,        -- equipment_repair, material_call, quality_issue, tech_support, admin_matter
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    priority_hint VARCHAR(20) DEFAULT 'medium',
    requires_leader_approval BOOLEAN DEFAULT FALSE,
    auto_route_to_tms BOOLEAN DEFAULT FALSE,
    tms_task_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS andon_tickets (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    category_id VARCHAR(36) REFERENCES andon_categories(id),
    category_code VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    location_id VARCHAR(50),
    location_name VARCHAR(100),
    equipment_id VARCHAR(36),
    work_order_id VARCHAR(36) REFERENCES work_orders(id),
    status VARCHAR(30) DEFAULT 'open' NOT NULL,     -- open/assigned/picking/upgrading/in_progress/resolved/closed/cancelled
    priority VARCHAR(20) DEFAULT 'medium',           -- low/medium/high/urgent
    assigned_to VARCHAR(50),
    assigned_by VARCHAR(50),
    claimed_at TIMESTAMP,
    escalation_level INTEGER DEFAULT 0,
    escalator_note TEXT,
    escalated_to VARCHAR(50),
    escalated_at TIMESTAMP,
    reminder_interval_minutes INTEGER DEFAULT 5,
    last_reminder_at TIMESTAMP,
    timeout_minutes_no_response INTEGER DEFAULT 15,
    timeout_minutes_resolve INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    resolved_at TIMESTAMP,
    metadata_ JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_andon_factory_status ON andon_tickets(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_andon_category ON andon_tickets(category_code);
CREATE INDEX IF NOT EXISTS idx_andon_assigned ON andon_tickets(assigned_to);

CREATE TABLE IF NOT EXISTS andon_escalation_logs (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(36) NOT NULL REFERENCES andon_tickets(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,              -- reminder/escalated/resolved_closed
    from_role VARCHAR(50),
    to_role VARCHAR(50),
    message TEXT,
    triggered_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_aes_ticket_created ON andon_escalation_logs(ticket_id, created_at);

-- 初始化默认类别
INSERT INTO andon_categories (id, code, name, description, is_active, priority_hint, auto_route_to_tms) VALUES
    ('andon-cat-equipment-repair', 'equipment_repair', '设备维修', '机器故障、停机、需维修人员处理', true, 'high', true),
    ('andon-cat-material-call', 'material_call', '物料呼叫', '生产线缺料，需从主仓或供应商拉料', true, 'medium', false),
    ('andon-cat-quality-issue', 'quality_issue', '质量异常', '发现不良品、尺寸超差、外观缺陷等质量问题', true, 'urgent', true),
    ('andon-cat-tech-support', 'tech_support', '技术支持', '工艺参数异常、设备调试、技术问题咨询', true, 'high', false),
    ('andon-cat-admin-matter', 'admin_matter', '行政事务', '办公耗材、环境异常、其他行政支持请求', true, 'low', false)
ON CONFLICT DO NOTHING;
