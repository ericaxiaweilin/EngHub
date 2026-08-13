-- 085: PMC 控制塔运行库闭环
--
-- The chatbot's PMC control tower reads these sources across PP, APS,
-- procurement and engineering.  Older installations may have deployed only
-- the workbench tables, so this migration is intentionally idempotent and
-- creates the missing operational tables without inserting demo transactions.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Demand, MRP and procurement evidence.
CREATE TABLE IF NOT EXISTS sales_orders (
    id VARCHAR(36) PRIMARY KEY,
    order_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    customer_name VARCHAR(100),
    customer_code VARCHAR(50),
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(100),
    quantity INTEGER NOT NULL DEFAULT 0,
    unit VARCHAR(20) DEFAULT 'pcs',
    delivery_date DATE,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'pending',
    decomposed BOOLEAN DEFAULT FALSE,
    decomposed_at TIMESTAMP,
    work_order_ids TEXT,
    material_ready BOOLEAN DEFAULT FALSE,
    material_check_at TIMESTAMP,
    unit_price DOUBLE PRECISION,
    total_amount DOUBLE PRECISION,
    currency VARCHAR(10) DEFAULT 'CNY',
    remark TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_sales_orders_factory ON sales_orders(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_pmc_sales_orders_delivery ON sales_orders(factory_id, delivery_date);

CREATE TABLE IF NOT EXISTS order_decomposition_logs (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    sales_order_id VARCHAR(36) NOT NULL,
    action VARCHAR(30) NOT NULL,
    result TEXT,
    work_orders_created INTEGER DEFAULT 0,
    operator VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_decomposition_order ON order_decomposition_logs(sales_order_id);

CREATE TABLE IF NOT EXISTS mrp_results (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    plan_id VARCHAR(36) NOT NULL,
    calculated_at TIMESTAMP DEFAULT NOW(),
    target_date DATE,
    status VARCHAR(20) DEFAULT 'pending',
    total_required NUMERIC(18, 4),
    total_available NUMERIC(18, 4),
    total_shortage NUMERIC(18, 4),
    total_value NUMERIC(18, 2),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_mrp_results_plan ON mrp_results(plan_id, calculated_at DESC);

CREATE TABLE IF NOT EXISTS mrp_items (
    id VARCHAR(36) PRIMARY KEY,
    mrp_result_id VARCHAR(36) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    material_name VARCHAR(200),
    required_qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    available_qty NUMERIC(18, 4) DEFAULT 0,
    reserved_qty NUMERIC(18, 4) DEFAULT 0,
    on_order_qty NUMERIC(18, 4) DEFAULT 0,
    shortage_qty NUMERIC(18, 4) DEFAULT 0,
    unit VARCHAR(20),
    unit_cost NUMERIC(18, 4),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_mrp_items_result ON mrp_items(mrp_result_id);
CREATE INDEX IF NOT EXISTS idx_pmc_mrp_items_material ON mrp_items(material_code);

CREATE TABLE IF NOT EXISTS purchase_suggestions (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    mrp_item_id VARCHAR(36),
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    material_name VARCHAR(200),
    required_qty NUMERIC(18, 4),
    suggested_qty NUMERIC(18, 4),
    suggested_date DATE,
    priority VARCHAR(20) DEFAULT 'normal',
    estimated_cost NUMERIC(18, 2),
    supplier_id VARCHAR(50),
    supplier_name VARCHAR(200),
    status VARCHAR(20) DEFAULT 'pending',
    purchase_order_id VARCHAR(50),
    suggested_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_purchase_suggestions_factory ON purchase_suggestions(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_pmc_purchase_suggestions_material ON purchase_suggestions(material_code);

CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    supplier_code VARCHAR(50) NOT NULL,
    supplier_name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(50),
    email VARCHAR(200),
    category VARCHAR(50),
    rating NUMERIC(3, 2) DEFAULT 3.0,
    on_time_rate NUMERIC(5, 2) DEFAULT 0,
    quality_rate NUMERIC(5, 2) DEFAULT 0,
    avg_lead_days INTEGER DEFAULT 7,
    is_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, supplier_code)
);
CREATE INDEX IF NOT EXISTS idx_pmc_suppliers_factory ON suppliers(factory_id);

CREATE TABLE IF NOT EXISTS supplier_prices (
    id VARCHAR(36) PRIMARY KEY,
    supplier_id VARCHAR(36) NOT NULL,
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    unit_price NUMERIC(12, 4) NOT NULL,
    currency VARCHAR(10) DEFAULT 'CNY',
    moq INTEGER DEFAULT 1,
    lead_days INTEGER DEFAULT 7,
    valid_from DATE,
    valid_to DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(supplier_id, material_code)
);
CREATE INDEX IF NOT EXISTS idx_pmc_supplier_prices_material ON supplier_prices(material_code, is_active);

CREATE TABLE IF NOT EXISTS supplier_materials (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_id VARCHAR(36) NOT NULL,
    material_code VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_primary BOOLEAN DEFAULT FALSE,
    unit_cost NUMERIC(15, 2) DEFAULT 0,
    min_order_qty INTEGER DEFAULT 1,
    lead_time_days INTEGER DEFAULT 7,
    quality_rating DOUBLE PRECISION DEFAULT 5.0,
    description VARCHAR(200),
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(supplier_id, material_code)
);
CREATE INDEX IF NOT EXISTS idx_pmc_supplier_material_code ON supplier_materials(material_code, is_active);

CREATE TABLE IF NOT EXISTS purchase_requisitions (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    pr_code VARCHAR(50) NOT NULL UNIQUE,
    source VARCHAR(30) DEFAULT 'mrp',
    source_id VARCHAR(50),
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    qty NUMERIC(12, 3) NOT NULL DEFAULT 0,
    unit VARCHAR(20) DEFAULT 'PCS',
    required_date DATE,
    status VARCHAR(20) DEFAULT 'pending',
    auto_approved BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_purchase_requisitions_factory ON purchase_requisitions(factory_id, status);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    po_code VARCHAR(50) NOT NULL UNIQUE,
    pr_id VARCHAR(36),
    supplier_id VARCHAR(36),
    supplier_name VARCHAR(200),
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    qty NUMERIC(12, 3) NOT NULL DEFAULT 0,
    unit_price NUMERIC(12, 4),
    total_amount NUMERIC(14, 2),
    currency VARCHAR(10) DEFAULT 'CNY',
    order_date DATE DEFAULT CURRENT_DATE,
    expected_date DATE,
    actual_date DATE,
    status VARCHAR(20) DEFAULT 'draft',
    auto_generated BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_purchase_orders_factory ON purchase_orders(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_pmc_purchase_orders_supplier ON purchase_orders(supplier_id);

-- Engineering change evidence.
CREATE TABLE IF NOT EXISTS engineering_changes (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    ecn_code VARCHAR(50) NOT NULL UNIQUE,
    title VARCHAR(300) NOT NULL,
    change_type VARCHAR(30) DEFAULT 'process',
    affected_product VARCHAR(100),
    affected_routing_id VARCHAR(36),
    description TEXT,
    old_value TEXT,
    new_value TEXT,
    status VARCHAR(20) DEFAULT 'draft',
    affected_wo_count INTEGER DEFAULT 0,
    propagated_at TIMESTAMP,
    created_by VARCHAR(50),
    approved_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_ecn_factory ON engineering_changes(factory_id, status);

-- Capacity and planning audit sources used by APS/PMC.
CREATE TABLE IF NOT EXISTS station_capacity (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    station_id VARCHAR(50) NOT NULL,
    available_hours_per_day DOUBLE PRECISION DEFAULT 16,
    efficiency_rate DOUBLE PRECISION DEFAULT 0.85,
    setup_time_minutes DOUBLE PRECISION DEFAULT 30,
    max_concurrent_orders INTEGER DEFAULT 1,
    maintenance_day VARCHAR(10),
    required_skills TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, station_id)
);
CREATE INDEX IF NOT EXISTS idx_pmc_station_capacity_factory ON station_capacity(factory_id);

CREATE TABLE IF NOT EXISTS aps_plan_events (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    plan_id VARCHAR(36),
    schedule_id VARCHAR(36),
    work_order_id VARCHAR(36),
    event_type VARCHAR(40) NOT NULL,
    actor VARCHAR(50) NOT NULL,
    reason TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_aps_plan_events_factory_time ON aps_plan_events(factory_id, created_at DESC);

CREATE TABLE IF NOT EXISTS aps_coordination_meetings (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    meeting_date DATE NOT NULL,
    meeting_type VARCHAR(40) NOT NULL DEFAULT 'production_coordination',
    plan_version VARCHAR(80),
    attendees JSONB NOT NULL DEFAULT '[]'::jsonb,
    decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_aps_meetings_factory_date ON aps_coordination_meetings(factory_id, meeting_date DESC);

CREATE TABLE IF NOT EXISTS aps_planner_activities (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    activity_type VARCHAR(40) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'aps_ui',
    plan_version VARCHAR(80),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_minutes NUMERIC(10, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pmc_aps_activities_factory_time ON aps_planner_activities(factory_id, started_at DESC);

