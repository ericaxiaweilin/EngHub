-- EngHub runtime schema alignment.
-- Idempotent by design: safe to run on every deployment through schema_migrate.py.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- RBAC columns expected by the current application.
ALTER TABLE roles ADD COLUMN IF NOT EXISTS role_code VARCHAR(50);
ALTER TABLE roles ADD COLUMN IF NOT EXISTS role_name VARCHAR(100);
ALTER TABLE roles ADD COLUMN IF NOT EXISTS position VARCHAR(30) DEFAULT 'staff';
ALTER TABLE roles ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'all';
ALTER TABLE roles ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 999;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS data_scope JSONB DEFAULT '{"type":"own"}'::jsonb;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
UPDATE roles
SET role_code = COALESCE(role_code, lower(regexp_replace(name, '[^a-zA-Z0-9]+', '_', 'g'))),
    role_name = COALESCE(role_name, name)
WHERE role_code IS NULL OR role_name IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_role_code ON roles(role_code);

-- Work-order template fields introduced by migration 029.
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS module VARCHAR(30) DEFAULT 'production';
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS form_fields JSONB DEFAULT '[]'::jsonb;
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS standard_ref VARCHAR(200);
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS badge_text VARCHAR(100);
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#1677ff';
ALTER TABLE work_order_templates ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;

-- PP plan table.
CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(36) PRIMARY KEY,
    plan_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    sales_order_id VARCHAR(50),
    quantity INTEGER NOT NULL,
    required_date TIMESTAMP NOT NULL,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'mps',
    customer_level VARCHAR(10) NOT NULL DEFAULT 'b',
    priority INTEGER NOT NULL DEFAULT 50,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    due_date TIMESTAMP,
    priority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    confirmed_by VARCHAR(50),
    confirmed_at TIMESTAMP,
    released_by VARCHAR(50),
    released_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by VARCHAR(50)
);

-- WMS master tables expected by the ORM. Foreign keys are intentionally omitted:
-- the shared database contains mixed UUID/VARCHAR legacy identifiers.
CREATE TABLE IF NOT EXISTS warehouses (
    id VARCHAR(36) PRIMARY KEY,
    warehouse_code VARCHAR(50) UNIQUE NOT NULL,
    warehouse_name VARCHAR(100) NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    warehouse_type VARCHAR(20) NOT NULL,
    address VARCHAR(255),
    status VARCHAR(20) DEFAULT 'active',
    created_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS locations (
    id VARCHAR(36) PRIMARY KEY,
    location_code VARCHAR(50) NOT NULL,
    location_name VARCHAR(100),
    warehouse_id VARCHAR(36) NOT NULL,
    location_type VARCHAR(20) DEFAULT 'rack',
    zone VARCHAR(50),
    capacity INTEGER,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS location_id VARCHAR(36);
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS batch_code VARCHAR(50);

ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS inventory_id VARCHAR(36);
ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS before_qty INTEGER;
ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS after_qty INTEGER;

CREATE TABLE IF NOT EXISTS inventory_counts (
    id VARCHAR(36) PRIMARY KEY,
    count_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    warehouse_id VARCHAR(36) NOT NULL,
    count_type VARCHAR(20) DEFAULT 'periodic',
    status VARCHAR(20) DEFAULT 'draft',
    planned_date DATE,
    counted_by VARCHAR(50),
    approved_by VARCHAR(50),
    total_items INTEGER DEFAULT 0,
    diff_items INTEGER DEFAULT 0,
    total_diff_qty INTEGER DEFAULT 0,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inventory_count_items (
    id VARCHAR(36) PRIMARY KEY,
    count_id VARCHAR(36) NOT NULL,
    inventory_id VARCHAR(36),
    material_id VARCHAR(50) NOT NULL,
    batch_code VARCHAR(50),
    system_qty INTEGER NOT NULL,
    counted_qty INTEGER,
    diff_qty INTEGER,
    adjusted BOOLEAN DEFAULT FALSE,
    remark VARCHAR(200)
);

-- Equipment/TPM additions. equipment_id stays VARCHAR because the application
-- accepts external equipment codes as well as numeric legacy IDs.
ALTER TABLE equipment_downtime ADD COLUMN IF NOT EXISTS downtime_category VARCHAR(30);
ALTER TABLE equipment_downtime ADD COLUMN IF NOT EXISTS reason_code VARCHAR(50);
ALTER TABLE equipment_downtime ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE equipment_downtime ADD COLUMN IF NOT EXISTS reported_by VARCHAR(50);

CREATE TABLE IF NOT EXISTS maintenance_orders (
    id VARCHAR(36) PRIMARY KEY,
    order_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    equipment_id VARCHAR(36) NOT NULL,
    maintenance_type VARCHAR(20) NOT NULL,
    priority VARCHAR(10) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'open',
    description TEXT,
    planned_date TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    assigned_to VARCHAR(50),
    result_summary TEXT,
    downtime_minutes DOUBLE PRECISION DEFAULT 0,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS maintenance_plans (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    equipment_id VARCHAR(36) NOT NULL,
    plan_name VARCHAR(100) NOT NULL,
    frequency_days INTEGER NOT NULL,
    last_executed_at TIMESTAMP,
    next_due_at TIMESTAMP,
    checklist TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- APS task columns expected by the current application.
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS work_order_id VARCHAR(36);
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS product_code VARCHAR(50);
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS operation_seq INTEGER DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS operation_name VARCHAR(100);
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS setup_seconds DOUBLE PRECISION DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS run_seconds DOUBLE PRECISION DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 5;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();

-- Automation config fields expected by API responses.
ALTER TABLE automation_config ADD COLUMN IF NOT EXISTS workflow_name VARCHAR(100);
ALTER TABLE automation_config ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE automation_config ADD COLUMN IF NOT EXISTS auto_rules JSONB DEFAULT '{}'::jsonb;
ALTER TABLE automation_config ADD COLUMN IF NOT EXISTS updated_by VARCHAR(100);
ALTER TABLE automation_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

