-- Follow-up alignment discovered by the full read-only API sweep.

-- The shared BOM table predates EngHub's MES columns.
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS id VARCHAR(36);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS factory_id VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS product_id VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS bom_version VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS material_code VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS material_name VARCHAR(100);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS qty_per_unit DOUBLE PRECISION DEFAULT 1;
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS remark VARCHAR(255);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

CREATE TABLE IF NOT EXISTS pull_replenishment_tasks (
    id VARCHAR(36) PRIMARY KEY,
    task_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    source_warehouse_id VARCHAR(36),
    target_location_id VARCHAR(36),
    material_id VARCHAR(50) NOT NULL,
    requested_qty INTEGER NOT NULL DEFAULT 0,
    fulfilled_qty INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    trigger_type VARCHAR(20) DEFAULT 'min_reached',
    work_order_id VARCHAR(36),
    threshold_id VARCHAR(36),
    assigned_to VARCHAR(50),
    created_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_traceability (
    id VARCHAR(36) PRIMARY KEY,
    item_code VARCHAR(50) UNIQUE NOT NULL,
    item_type VARCHAR(20) DEFAULT 'finished',
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(36),
    product_id VARCHAR(36),
    material_batch_id VARCHAR(50),
    material_supplier_id VARCHAR(50),
    station_id VARCHAR(50),
    equipment_id VARCHAR(36),
    operator_id VARCHAR(50),
    quality_check_result VARCHAR(20),
    serial_number VARCHAR(50),
    next_item_code VARCHAR(36),
    inspection_record_id VARCHAR(36),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- The existing Phase-5 maintenance table only had scheduler seed columns.
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS task_code VARCHAR(50);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(30);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium';
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS station_id VARCHAR(50);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS planned_date DATE;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS planned_duration_minutes INTEGER DEFAULT 60;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(50);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'manual';
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS result VARCHAR(30);
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS findings TEXT;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS parts_used TEXT;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS cost DOUBLE PRECISION DEFAULT 0;
ALTER TABLE maintenance_tasks ADD COLUMN IF NOT EXISTS actual_duration_minutes INTEGER DEFAULT 0;

-- RCC tables are application-owned but were absent from the shared database.
CREATE TABLE IF NOT EXISTS rcc_tasks (
    id VARCHAR(36) PRIMARY KEY, task_code VARCHAR(50) UNIQUE NOT NULL,
    org_unit_id VARCHAR(36), task_type VARCHAR(30) NOT NULL, title VARCHAR(200) NOT NULL,
    description TEXT, affected_params JSONB DEFAULT '[]', affected_entities JSONB DEFAULT '[]',
    expected_impact_summary TEXT, status VARCHAR(20) DEFAULT 'pending',
    approved_by VARCHAR(50), approved_at TIMESTAMP, rejected_by VARCHAR(50),
    rejection_reason TEXT, executed_at TIMESTAMP, completed_at TIMESTAMP,
    requested_by VARCHAR(50), request_context JSONB DEFAULT '{}', source_ticket_id VARCHAR(36),
    created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS global_adjustable_params (
    id VARCHAR(36) PRIMARY KEY, param_code VARCHAR(100) UNIQUE NOT NULL,
    param_name VARCHAR(100) NOT NULL, org_unit_id VARCHAR(36), position_cap_id VARCHAR(36),
    category VARCHAR(20) NOT NULL, param_type VARCHAR(20) NOT NULL,
    default_value VARCHAR, current_value VARCHAR, effective_from TIMESTAMP DEFAULT NOW(),
    target_value VARCHAR, min_value DOUBLE PRECISION, max_value DOUBLE PRECISION,
    step_value DOUBLE PRECISION, unit VARCHAR(50), options JSONB DEFAULT '[]',
    sensitivity VARCHAR(20) DEFAULT 'normal', affects_logic_chains JSONB DEFAULT '[]',
    rollback_allowed BOOLEAN DEFAULT TRUE, rollback_window_minutes INTEGER DEFAULT 60,
    changed_by VARCHAR(50), change_reason TEXT, previous_value VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS parameter_change_audit (
    id VARCHAR(36) PRIMARY KEY, param_id VARCHAR(36), from_value VARCHAR, to_value VARCHAR,
    changed_by VARCHAR(50), changed_at TIMESTAMP DEFAULT NOW(), reason TEXT,
    approval_required BOOLEAN DEFAULT FALSE, approval_status VARCHAR(20) DEFAULT 'auto_approved',
    approval_record_id VARCHAR(36), source VARCHAR(20) DEFAULT 'panel', impact_summary TEXT
);
CREATE TABLE IF NOT EXISTS chatbot_tickets (
    id VARCHAR(36) PRIMARY KEY, ticket_code VARCHAR(50) UNIQUE NOT NULL,
    requester_id VARCHAR(50) NOT NULL, requester_org_unit VARCHAR(36),
    ticket_type VARCHAR(30) NOT NULL, raw_message TEXT NOT NULL,
    parsed_intents JSONB DEFAULT '{}', parsed_slots JSONB DEFAULT '{}',
    requested_resource JSONB DEFAULT '{}', requested_time_window JSONB DEFAULT '{}',
    related_param_id VARCHAR(36), related_rcc_task_id VARCHAR(36),
    related_andon_id VARCHAR(36), related_work_order_id VARCHAR(36),
    status VARCHAR(20) DEFAULT 'open', priority VARCHAR(20) DEFAULT 'medium',
    routed_to_org_unit VARCHAR(36), routed_to_position VARCHAR(50),
    resolved_by VARCHAR(50), resolution TEXT, resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS deterministic_logic_chains (
    id VARCHAR(36) PRIMARY KEY, chain_code VARCHAR(50) UNIQUE NOT NULL,
    chain_name VARCHAR(100) NOT NULL, org_unit_id VARCHAR(36), position_cap_id VARCHAR(36),
    trigger_event VARCHAR(100) NOT NULL, conditions JSONB DEFAULT '[]',
    action_sequence JSONB DEFAULT '[]', enabled BOOLEAN DEFAULT TRUE,
    execution_order INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
