

-- v2.6 - RCC (Resource Control Center) + 参数化面板 + Chatbot工单系统
-- 三位一体调度系统

CREATE TABLE IF NOT EXISTS rcc_organizations (
    id VARCHAR(36) PRIMARY KEY REFERENCES org_units(id),
    org_type VARCHAR(20) NOT NULL DEFAULT 'rcc',
    resource_pool JSONB DEFAULT '{}'::jsonb,
    capacity_model JSONB DEFAULT '{}'::jsonb,
    dispatch_rules JSONB DEFAULT '[]'::jsonb,
    auto_dispatch_enabled BOOLEAN DEFAULT FALSE,
    human_approval_required BOOLEAN DEFAULT TRUE,
    approval_threshold_pct FLOAT DEFAULT 80.0,
    last_sync_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS rcc_tasks (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    task_code VARCHAR(50) UNIQUE NOT NULL,
    org_unit_id VARCHAR(36) REFERENCES org_units(id),
    task_type VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    
    affected_params JSONB DEFAULT '[]'::jsonb,
    affected_entities JSONB DEFAULT '[]'::jsonb,
    expected_impact_summary TEXT,
    
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    
    approved_by VARCHAR(50),
    approved_at TIMESTAMP,
    rejected_by VARCHAR(50),
    rejection_reason TEXT,
    executed_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    requested_by VARCHAR(50),
    request_context JSONB DEFAULT '{}'::jsonb,
    source_ticket_id VARCHAR(36),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS rcc_approval_records (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    rcc_task_id VARCHAR(36) REFERENCES rcc_tasks(id) ON DELETE CASCADE,
    approver_role VARCHAR(50) NOT NULL,
    approver_name VARCHAR(100),
    decision VARCHAR(20) NOT NULL,
    decision_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    comment TEXT,
    escalation_level INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rcc_tasks_status ON rcc_tasks(status);
CREATE INDEX IF NOT EXISTS idx_rcc_tasks_org ON rcc_tasks(org_unit_id);
CREATE INDEX IF NOT EXISTS idx_rcc_approvals_task ON rcc_approval_records(rcc_task_id);

CREATE TABLE IF NOT EXISTS global_adjustable_params (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    param_code VARCHAR(100) NOT NULL UNIQUE,
    param_name VARCHAR(100) NOT NULL,
    
    org_unit_id VARCHAR(36) REFERENCES org_units(id),
    position_cap_id VARCHAR(36) REFERENCES position_capabilities(id),
    
    category VARCHAR(20) NOT NULL,
    param_type VARCHAR(20) NOT NULL,
    default_value TEXT,
    current_value TEXT,
    effective_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    target_value TEXT,
    
    min_value FLOAT,
    max_value FLOAT,
    step_value FLOAT,
    unit VARCHAR(50),
    options JSONB DEFAULT '[]'::jsonb,
    sensitivity VARCHAR(20) DEFAULT 'normal' NOT NULL,
    
    affects_logic_chains JSONB DEFAULT '[]'::jsonb,
    rollback_allowed BOOLEAN DEFAULT TRUE,
    rollback_window_minutes INTEGER DEFAULT 60,
    
    changed_by VARCHAR(50),
    change_reason TEXT,
    previous_value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS parameter_change_audit (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    param_id VARCHAR(36) REFERENCES global_adjustable_params(id),
    from_value TEXT,
    to_value TEXT,
    changed_by VARCHAR(50),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    approval_required BOOLEAN DEFAULT FALSE,
    approval_status VARCHAR(20) DEFAULT 'auto_approved',
    approval_record_id VARCHAR(36),
    source VARCHAR(20) DEFAULT 'panel',
    impact_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_param_audit_param ON parameter_change_audit(param_id);
CREATE INDEX IF NOT EXISTS idx_param_audit_changed_at ON parameter_change_audit(changed_at);

CREATE TABLE IF NOT EXISTS chatbot_tickets (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_code VARCHAR(50) UNIQUE NOT NULL,
    
    requester_id VARCHAR(50) NOT NULL,
    requester_org_unit VARCHAR(36) REFERENCES org_units(id),
    
    ticket_type VARCHAR(30) NOT NULL,
    
    raw_message TEXT NOT NULL,
    parsed_intents JSONB DEFAULT '{}'::jsonb,
    parsed_slots JSONB DEFAULT '{}'::jsonb,
    
    requested_resource JSONB DEFAULT '{}'::jsonb,
    requested_time_window JSONB DEFAULT '{}'::jsonb,
    
    related_param_id VARCHAR(36) REFERENCES global_adjustable_params(id),
    related_rcc_task_id VARCHAR(36) REFERENCES rcc_tasks(id),
    related_andon_id VARCHAR(36),
    related_work_order_id VARCHAR(36) REFERENCES work_orders(id),
    
    status VARCHAR(20) DEFAULT 'open',
    priority VARCHAR(20) DEFAULT 'medium',
    
    routed_to_org_unit VARCHAR(36),
    routed_to_position VARCHAR(50),
    
    resolved_by VARCHAR(50),
    resolution TEXT,
    resolved_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_tickets_requester ON chatbot_tickets(requester_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_tickets_status ON chatbot_tickets(status);
CREATE INDEX IF NOT EXISTS idx_chatbot_tickets_org ON chatbot_tickets(requester_org_unit);

CREATE TABLE IF NOT EXISTS chatbot_ticket_approval_flow (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(36) REFERENCES chatbot_tickets(id) ON DELETE CASCADE,
    step INTEGER NOT NULL,
    role_required VARCHAR(50),
    approver_id VARCHAR(50),
    decision VARCHAR(20),
    decision_at TIMESTAMP,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS deterministic_logic_chains (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_code VARCHAR(50) UNIQUE NOT NULL,
    chain_name VARCHAR(100) NOT NULL,
    
    org_unit_id VARCHAR(36) REFERENCES org_units(id),
    position_cap_id VARCHAR(36) REFERENCES position_capabilities(id),
    
    trigger_event VARCHAR(100) NOT NULL,
    conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    enabled BOOLEAN DEFAULT TRUE,
    execution_order INTEGER DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logic_chains_enabled ON deterministic_logic_chains(enabled);
CREATE INDEX IF NOT EXISTS idx_logic_chains_trigger ON deterministic_logic_chains(trigger_event);

CREATE TABLE IF NOT EXISTS logic_chain_execution_log (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id VARCHAR(36) REFERENCES deterministic_logic_chains(id),
    triggered_by VARCHAR(50),
    trigger_payload JSONB DEFAULT '{}'::jsonb,
    conditions_matched BOOLEAN DEFAULT TRUE,
    actions_executed JSONB DEFAULT '[]'::jsonb,
    action_results JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logic_log_chain ON logic_chain_execution_log(chain_id);
CREATE INDEX IF NOT EXISTS idx_logic_log_created_at ON logic_chain_execution_log(created_at);

-- 初始化默认 RCC 组织
INSERT INTO org_units (id, code, name, parent_id, level_type, factory_id, metadata_) VALUES
('rcc-root', 'RCC_ROOT', '资源控制中心', NULL, 'strategic', NULL, '{"type": "rcc", "description": "全局资源控制与调度中枢"}'),
('line-a', 'LINE_A', '产线A', 'rcc-root', 'operational', NULL, '{"type": "production_line"}'),
('line-b', 'LINE_B', '产线B', 'rcc-root', 'operational', NULL, '{"type": "production_line"}'),
('smt-station-01', 'SMT_01', 'SMT贴片工位01', 'line-a', 'execution', NULL, '{"type": "workstation"}'),
('cnc-station-01', 'CNC_01', 'CNC加工中心01', 'line-a', 'execution', NULL, '{"type": "workstation"}'),
('hr-office', 'HR_OFFICE', '人力资源部', 'rcc-root', 'support', NULL, '{"type": "office"}'),
('quality-dept', 'QMS_DEPT', '品质部', 'rcc-root', 'tactical', NULL, '{"type": "department"}')
ON CONFLICT DO NOTHING;

-- 初始化 RCC 资源控制中心配置
INSERT INTO rcc_organizations (id, org_type, resource_pool, capacity_model, dispatch_rules) 
VALUES (
    'rcc-root', 
    'rcc',
    '{"equipment": [], "personnel": [], "materials": [], "time_slots": []}',
    '{"mode": "mtm", "max_parallel_capacity": 10}',
    '[{"rule_id": "auto_dispatch_above_80pct", "action": "notify_manager", "threshold": 0.8}]'
)
ON CONFLICT (id) DO UPDATE SET
    resource_pool = EXCLUDED.resource_pool,
    capacity_model = EXCLUDED.capacity_model,
    dispatch_rules = EXCLUDED.dispatch_rules;

