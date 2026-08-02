-- EngHub WMS & Cost Database Migration
-- Tables: Warehouse Management, Cost Accounting
-- Created: 2026-02-24

-- ============================================
-- WMS - Warehouse Management Tables
-- ============================================

-- 仓库表
CREATE TABLE IF NOT EXISTS wms_warehouses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    warehouse_code VARCHAR(50) UNIQUE NOT NULL,
    warehouse_name VARCHAR(200) NOT NULL,
    warehouse_type VARCHAR(20) NOT NULL,  -- raw_material, finished_goods, wip, return, qc_hold
    address TEXT,
    manager_id VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_warehouse_factory FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_wms_warehouses_factory ON wms_warehouses(factory_id);
CREATE INDEX idx_wms_warehouses_type ON wms_warehouses(warehouse_type);

-- 库位表
CREATE TABLE IF NOT EXISTS wms_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warehouse_id UUID NOT NULL,
    location_code VARCHAR(50) UNIQUE NOT NULL,
    location_name VARCHAR(200),
    location_type VARCHAR(20) DEFAULT 'rack',  -- rack, floor, buffer
    zone VARCHAR(50),
    row_num INTEGER,
    col_num INTEGER,
    level_num INTEGER,
    capacity INTEGER,
    status VARCHAR(20) DEFAULT 'active',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_location_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id)
);

CREATE INDEX idx_wms_locations_warehouse ON wms_locations(warehouse_id);
CREATE INDEX idx_wms_locations_zone ON wms_locations(zone);

-- 批次库存表
CREATE TABLE IF NOT EXISTS wms_inventory_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    batch_code VARCHAR(50) NOT NULL,
    
    warehouse_id UUID NOT NULL,
    location_id UUID,
    
    quantity DECIMAL(18, 4) NOT NULL DEFAULT 0,
    available_qty DECIMAL(18, 4) DEFAULT 0,
    reserved_qty DECIMAL(18, 4) DEFAULT 0,
    frozen_qty DECIMAL(18, 4) DEFAULT 0,
    qc_hold_qty DECIMAL(18, 4) DEFAULT 0,
    
    supplier_id VARCHAR(50),
    receive_date DATE,
    manufacture_date DATE,
    expire_date DATE,
    
    unit_cost DECIMAL(18, 4),
    
    status VARCHAR(20) DEFAULT 'available',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_inventory_batch_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id)
);

CREATE INDEX idx_wms_inventory_batches_material ON wms_inventory_batches(material_id);
CREATE INDEX idx_wms_inventory_batches_batch ON wms_inventory_batches(batch_code);
CREATE INDEX idx_wms_inventory_batches_warehouse ON wms_inventory_batches(warehouse_id);

-- 库存汇总表 (按物料+仓库)
CREATE TABLE IF NOT EXISTS wms_inventory_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    warehouse_id UUID NOT NULL,
    
    total_qty DECIMAL(18, 4) DEFAULT 0,
    available_qty DECIMAL(18, 4) DEFAULT 0,
    reserved_qty DECIMAL(18, 4) DEFAULT 0,
    frozen_qty DECIMAL(18, 4) DEFAULT 0,
    
    last_transaction_at TIMESTAMP,
    
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_inventory_summary_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id),
    UNIQUE(factory_id, material_id, warehouse_id)
);

CREATE INDEX idx_wms_inventory_summary_material ON wms_inventory_summary(material_id);

-- 库存事务表 (出入库流水)
CREATE TABLE IF NOT EXISTS wms_inventory_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    transaction_type VARCHAR(30) NOT NULL,
    
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    batch_code VARCHAR(50),
    
    warehouse_id UUID NOT NULL,
    location_id UUID,
    
    quantity DECIMAL(18, 4) NOT NULL,
    unit_cost DECIMAL(18, 4),
    total_cost DECIMAL(18, 4),
    
    reference_type VARCHAR(50),  -- work_order, purchase_order, sales_order
    reference_id VARCHAR(50),
    
    work_order_id VARCHAR(50),
    purchase_order_id VARCHAR(50),
    sales_order_id VARCHAR(50),
    
    supplier_id VARCHAR(50),
    customer_id VARCHAR(50),
    
    remark TEXT,
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_transaction_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id)
);

CREATE INDEX idx_wms_transactions_material ON wms_inventory_transactions(material_id);
CREATE INDEX idx_wms_transactions_type ON wms_inventory_transactions(transaction_type);
CREATE INDEX idx_wms_transactions_reference ON wms_inventory_transactions(reference_type, reference_id);
CREATE INDEX idx_wms_transactions_work_order ON wms_inventory_transactions(work_order_id);
CREATE INDEX idx_wms_transactions_created ON wms_inventory_transactions(created_at);

-- 库存预留表
CREATE TABLE IF NOT EXISTS wms_inventory_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    warehouse_id UUID NOT NULL,
    
    quantity DECIMAL(18, 4) NOT NULL,
    work_order_id VARCHAR(50),
    
    status VARCHAR(20) DEFAULT 'reserved',
    
    reserved_by VARCHAR(50),
    reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMP,
    
    CONSTRAINT fk_reservation_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id)
);

CREATE INDEX idx_wms_reservations_work_order ON wms_inventory_reservations(work_order_id);

-- 盘点单表
CREATE TABLE IF NOT EXISTS wms_inventory_counts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    warehouse_id UUID NOT NULL,
    
    count_code VARCHAR(50) UNIQUE NOT NULL,
    count_date DATE NOT NULL,
    count_type VARCHAR(20) DEFAULT 'periodic',  -- periodic, spot, cycle
    
    status VARCHAR(20) DEFAULT 'draft',  -- draft, in_progress, completed, cancelled
    
    total_items INTEGER DEFAULT 0,
    total_system_qty DECIMAL(18, 4) DEFAULT 0,
    total_counted_qty DECIMAL(18, 4) DEFAULT 0,
    total_difference DECIMAL(18, 4) DEFAULT 0,
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    
    CONSTRAINT fk_count_warehouse FOREIGN KEY (warehouse_id) REFERENCES wms_warehouses(id)
);

CREATE INDEX idx_wms_inventory_counts_status ON wms_inventory_counts(status);

-- 盘点明细表
CREATE TABLE IF NOT EXISTS wms_inventory_count_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    count_id UUID NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    batch_code VARCHAR(50),
    
    system_qty DECIMAL(18, 4),
    counted_qty DECIMAL(18, 4),
    difference DECIMAL(18, 4),
    
    location_id UUID,
    remark TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_count_item_count FOREIGN KEY (count_id) REFERENCES wms_inventory_counts(id)
);

-- ============================================
-- Cost Accounting Tables
-- ============================================

-- 工单成本表
CREATE TABLE IF NOT EXISTS cost_work_order_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(50) UNIQUE NOT NULL,
    work_order_code VARCHAR(50),
    
    product_id VARCHAR(50),
    produced_qty INTEGER DEFAULT 0,
    
    -- 成本明细
    material_cost DECIMAL(18, 4) DEFAULT 0,
    labor_cost DECIMAL(18, 4) DEFAULT 0,
    overhead_cost DECIMAL(18, 4) DEFAULT 0,
    total_cost DECIMAL(18, 4) DEFAULT 0,
    unit_cost DECIMAL(18, 4) DEFAULT 0,
    
    -- 抛料成本
    scrapped_material_cost DECIMAL(18, 4) DEFAULT 0,
    
    status VARCHAR(20) DEFAULT 'pending',
    
    calculated_by VARCHAR(50),
    calculated_at TIMESTAMP,
    confirmed_by VARCHAR(50),
    confirmed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_cost_work_order_costs_work_order ON cost_work_order_costs(work_order_id);
CREATE INDEX idx_cost_work_order_costs_product ON cost_work_order_costs(product_id);

-- 产品标准成本表
CREATE TABLE IF NOT EXISTS cost_product_standard_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    product_code VARCHAR(50),
    
    bom_version VARCHAR(50),
    
    material_cost DECIMAL(18, 4) DEFAULT 0,
    labor_cost DECIMAL(18, 4) DEFAULT 0,
    overhead_cost DECIMAL(18, 4) DEFAULT 0,
    total_standard_cost DECIMAL(18, 4) DEFAULT 0,
    
    effective_date DATE,
    status VARCHAR(20) DEFAULT 'active',
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(factory_id, product_id, bom_version, effective_date)
);

CREATE INDEX idx_cost_product_standard_costs_product ON cost_product_standard_costs(product_id);

-- 成本差异分析表
CREATE TABLE IF NOT EXISTS cost_variance_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(50) NOT NULL,
    
    actual_cost DECIMAL(18, 4),
    standard_cost DECIMAL(18, 4),
    total_variance DECIMAL(18, 4),
    variance_rate DECIMAL(10, 2),
    
    material_variance DECIMAL(18, 4),
    labor_variance DECIMAL(18, 4),
    overhead_variance DECIMAL(18, 4),
    
    analysis_note TEXT,
    
    analyzed_by VARCHAR(50),
    analyzed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(factory_id, work_order_id)
);

-- 人工费率表
CREATE TABLE IF NOT EXISTS cost_labor_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    station_id VARCHAR(50),
    station_name VARCHAR(200),
    
    labor_rate DECIMAL(18, 4) NOT NULL,  -- 每小时人工费
    overtime_rate DECIMAL(18, 4),        -- 加班费率
    
    effective_date DATE,
    status VARCHAR(20) DEFAULT 'active',
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(factory_id, station_id, effective_date)
);

-- 制造费用率表
CREATE TABLE IF NOT EXISTS cost_overhead_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    
    overhead_type VARCHAR(50),  -- machine_depreciation, utilities, etc.
    rate DECIMAL(10, 4) NOT NULL,  -- 费用率 (如 0.3 表示30%人工成本)
    rate_type VARCHAR(20) DEFAULT 'labor_based',  -- labor_based, machine_based
    
    effective_date DATE,
    status VARCHAR(20) DEFAULT 'active',
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- Comments
-- ============================================

COMMENT ON TABLE wms_warehouses IS '仓库表';
COMMENT ON TABLE wms_locations IS '库位表';
COMMENT ON TABLE wms_inventory_batches IS '批次库存表';
COMMENT ON TABLE wms_inventory_summary IS '库存汇总表';
COMMENT ON TABLE wms_inventory_transactions IS '库存事务表';
COMMENT ON TABLE wms_inventory_reservations IS '库存预留表';
COMMENT ON TABLE wms_inventory_counts IS '盘点单表';
COMMENT ON TABLE wms_inventory_count_items IS '盘点明细表';
COMMENT ON TABLE cost_work_order_costs IS '工单成本表';
COMMENT ON TABLE cost_product_standard_costs IS '产品标准成本表';
COMMENT ON TABLE cost_variance_analysis IS '成本差异分析表';
COMMENT ON TABLE cost_labor_rates IS '人工费率表';
COMMENT ON TABLE cost_overhead_rates IS '制造费用率表';
