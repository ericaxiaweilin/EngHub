-- ============================================================================
-- EngHub MES System - Database Migration
-- Version: 1.0.0
-- Date: 2026-02-24
-- Description: MES核心表 - 工厂、车间、工位、产品、工单
-- ============================================================================

-- 1. 工厂表 (factories)
CREATE TABLE IF NOT EXISTS factories (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(50) NOT NULL UNIQUE,
    location VARCHAR(256),
    contact_person VARCHAR(128),
    contact_phone VARCHAR(20),
    address VARCHAR(256),
    country VARCHAR(64) DEFAULT 'China',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(32),
    updated_by VARCHAR(32)
);

CREATE INDEX idx_factories_code ON factories(code);
CREATE INDEX idx_factories_status ON factories(status);

-- 2. 车间表 (workshops)
CREATE TABLE IF NOT EXISTS workshops (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    manager_id VARCHAR(32),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_workshops_factory_id ON workshops(factory_id);
CREATE INDEX idx_workshops_status ON workshops(status);

-- 3. 工位/产线表 (stations)
CREATE TABLE IF NOT EXISTS stations (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    workshop_id VARCHAR(32) NOT NULL,
    station_code VARCHAR(50) NOT NULL,
    station_name VARCHAR(128) NOT NULL,
    station_type VARCHAR(50) NOT NULL,
    capacity INT NOT NULL,
    capacity_unit VARCHAR(50),
    equipment_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (workshop_id) REFERENCES workshops(id)
);

CREATE INDEX idx_stations_factory_id ON stations(factory_id);
CREATE INDEX idx_stations_workshop_id ON stations(workshop_id);
CREATE UNIQUE INDEX idx_stations_code ON stations(factory_id, station_code);

-- 4. 产品表 (products)
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32),
    product_code VARCHAR(50) NOT NULL,
    product_name VARCHAR(256) NOT NULL,
    sku VARCHAR(100),
    category VARCHAR(100),
    description TEXT,
    unit VARCHAR(20),
    standard_cost DECIMAL(18, 6),
    selling_price DECIMAL(18, 6),
    bom_id VARCHAR(32),
    current_bom_version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_products_factory_id ON products(factory_id);
CREATE UNIQUE INDEX idx_products_code ON products(factory_id, product_code);
CREATE INDEX idx_products_status ON products(status);

-- 5. 工艺路线表 (routings)
CREATE TABLE IF NOT EXISTS routings (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    remark TEXT,
    created_by VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE INDEX idx_routings_factory_id ON routings(factory_id);
CREATE INDEX idx_routings_product_id ON routings(product_id);

-- 6. 工序表 (routing_steps)
CREATE TABLE IF NOT EXISTS routing_steps (
    id VARCHAR(32) PRIMARY KEY,
    routing_id VARCHAR(32) NOT NULL,
    sequence INT NOT NULL,
    operation_name VARCHAR(256) NOT NULL,
    operation_code VARCHAR(50),
    station_id VARCHAR(32) NOT NULL,
    setup_time INT DEFAULT 0,
    standard_time INT NOT NULL,
    tools TEXT,
    materials TEXT,
    parameters TEXT,
    quality_check TINYINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (routing_id) REFERENCES routings(id),
    FOREIGN KEY (station_id) REFERENCES stations(id)
);

CREATE INDEX idx_routing_steps_routing_id ON routing_steps(routing_id);
CREATE INDEX idx_routing_steps_station_id ON routing_steps(station_id);

-- 7. 生产工单表 (work_orders)
CREATE TABLE IF NOT EXISTS work_orders (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    sales_order_id VARCHAR(50),
    work_order_code VARCHAR(50) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    routing_id VARCHAR(32),
    planned_qty INT NOT NULL,
    unit VARCHAR(20),
    completed_qty INT DEFAULT 0,
    good_qty INT DEFAULT 0,
    defect_qty INT DEFAULT 0,
    scrap_qty INT DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) DEFAULT 'medium',
    planned_start DATETIME,
    planned_due DATETIME,
    actual_start DATETIME,
    actual_complete DATETIME,
    assigned_station_id VARCHAR(32),
    assigned_to VARCHAR(32),
    current_routing_step INT DEFAULT 0,
    bom_version VARCHAR(50),
    created_by VARCHAR(32) NOT NULL,
    updated_by VARCHAR(32),
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP NULL,
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (routing_id) REFERENCES routings(id),
    FOREIGN KEY (assigned_station_id) REFERENCES stations(id)
);

CREATE INDEX idx_work_orders_factory_id ON work_orders(factory_id);
CREATE INDEX idx_work_orders_status ON work_orders(status);
CREATE UNIQUE INDEX idx_work_orders_code ON work_orders(factory_id, work_order_code);
CREATE INDEX idx_work_orders_sales_order_id ON work_orders(sales_order_id);
CREATE INDEX idx_work_orders_product_id ON work_orders(product_id);
CREATE INDEX idx_work_orders_created_at ON work_orders(factory_id, created_at DESC);
CREATE INDEX idx_work_orders_due_date ON work_orders(planned_due);
CREATE INDEX idx_work_orders_station ON work_orders(assigned_station_id);
CREATE INDEX idx_work_orders_composite ON work_orders(factory_id, status, created_at DESC);

-- 8. 工单物料清单表 (work_order_materials)
CREATE TABLE IF NOT EXISTS work_order_materials (
    id VARCHAR(32) PRIMARY KEY,
    work_order_id VARCHAR(32) NOT NULL,
    material_id VARCHAR(32),
    material_code VARCHAR(50),
    material_name VARCHAR(256),
    qty_per_unit INT,
    required_qty INT,
    unit VARCHAR(20),
    received_qty INT DEFAULT 0,
    available_qty INT DEFAULT 0,
    shortage_qty INT DEFAULT 0,
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
);

CREATE INDEX idx_work_order_materials_wo_id ON work_order_materials(work_order_id);
CREATE INDEX idx_work_order_materials_material_id ON work_order_materials(material_id);

-- 9. 生产报工表 (production_reports)
CREATE TABLE IF NOT EXISTS production_reports (
    id VARCHAR(32) PRIMARY KEY,
    report_code VARCHAR(50) NOT NULL UNIQUE,
    work_order_id VARCHAR(32) NOT NULL,
    work_center_id VARCHAR(32) NOT NULL,
    report_date DATE NOT NULL,
    shift VARCHAR(20),
    report_type VARCHAR(20) NOT NULL DEFAULT 'normal',
    quantity_produced INT DEFAULT 0,
    quantity_qualified INT DEFAULT 0,
    quantity_rejected INT DEFAULT 0,
    rejected_reasons JSON,
    operator_id VARCHAR(32),
    machine_id VARCHAR(50),
    hours_worked DECIMAL(10, 2),
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id),
    FOREIGN KEY (work_center_id) REFERENCES stations(id)
);

CREATE INDEX idx_production_reports_wo_id ON production_reports(work_order_id);
CREATE INDEX idx_production_reports_work_center_id ON production_reports(work_center_id);
CREATE INDEX idx_production_reports_date ON production_reports(report_date);
CREATE INDEX idx_production_reports_shift ON production_reports(shift);

-- 10. 班次表 (shifts)
CREATE TABLE IF NOT EXISTS shifts (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    shift_name VARCHAR(50) NOT NULL,
    shift_code VARCHAR(20) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_shifts_factory_id ON shifts(factory_id);
CREATE UNIQUE INDEX idx_shifts_code ON shifts(factory_id, shift_code);

-- End of migration
