-- 067: PMC 工作台基础架构与机械虚拟工厂证据链
--
-- 目的：让 PMC 工作台从接口读取一条可验证的 MPS → 工单 → BOM/库存 →
-- 工艺/工位 → VN 2026 日历链路。所有写入均为幂等初始化数据，不覆盖用户订单。

-- 现有运行库曾只创建 legacy plans 表，当前 ORM 使用 pp_plans。
CREATE TABLE IF NOT EXISTS pp_plans (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    plan_code VARCHAR(50) UNIQUE NOT NULL,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'mps',
    product_id VARCHAR(50) NOT NULL,
    sales_order_id VARCHAR(50),
    quantity INTEGER NOT NULL,
    required_date DATE NOT NULL,
    due_date DATE,
    customer_level VARCHAR(10) DEFAULT 'b',
    priority INTEGER DEFAULT 50,
    priority_score NUMERIC(10, 2),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    planning_cycle VARCHAR(30),
    release_status VARCHAR(20) DEFAULT 'unreleased',
    planner_id VARCHAR(50),
    work_order_id VARCHAR(36),
    cancelled_by VARCHAR(50),
    cancelled_at TIMESTAMP,
    completed_by VARCHAR(50),
    update_reason TEXT,
    station_id VARCHAR(50),
    scheduled_start_date DATE,
    scheduled_end_date DATE,
    mrp_status VARCHAR(20) DEFAULT 'pending',
    created_by VARCHAR(50),
    updated_by VARCHAR(50),
    confirmed_by VARCHAR(50),
    released_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    released_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pp_plans_factory ON pp_plans(factory_id);
CREATE INDEX IF NOT EXISTS idx_pp_plans_status ON pp_plans(status);
CREATE INDEX IF NOT EXISTS idx_pp_plans_product ON pp_plans(product_id);
CREATE INDEX IF NOT EXISTS idx_pp_plans_required_date ON pp_plans(required_date);

CREATE TABLE IF NOT EXISTS work_order_materials (
    id VARCHAR(36) PRIMARY KEY,
    work_order_id VARCHAR(36) NOT NULL,
    material_id VARCHAR(50),
    material_code VARCHAR(50),
    material_name VARCHAR(256),
    qty_per_unit INTEGER,
    required_qty INTEGER NOT NULL DEFAULT 0,
    unit VARCHAR(20),
    received_qty INTEGER DEFAULT 0,
    available_qty INTEGER DEFAULT 0,
    shortage_qty INTEGER DEFAULT 0,
    remark TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_work_order_materials_work_order ON work_order_materials(work_order_id);

CREATE TABLE IF NOT EXISTS aps_holidays (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    calendar_code VARCHAR(80) NOT NULL,
    year INTEGER NOT NULL,
    holiday_date DATE NOT NULL,
    holiday_name VARCHAR(150) NOT NULL,
    holiday_type VARCHAR(30) NOT NULL DEFAULT 'legal',
    is_working_day BOOLEAN NOT NULL DEFAULT FALSE,
    source_name VARCHAR(200),
    source_url VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_aps_holiday_factory_date UNIQUE (factory_id, holiday_date)
);
CREATE INDEX IF NOT EXISTS idx_aps_holiday_factory_year ON aps_holidays(factory_id, year);

ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS source_plan_id VARCHAR(36);
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS next_station VARCHAR(100);
CREATE INDEX IF NOT EXISTS idx_work_orders_source_plan ON work_orders(source_plan_id);

-- ORM 当前会读取这些产品字段；没有它们，PMC 读取产品主数据会直接失败。
ALTER TABLE products ADD COLUMN IF NOT EXISTS current_routing_id VARCHAR(50);
ALTER TABLE products ADD COLUMN IF NOT EXISTS engineering_lead_time_days DOUBLE PRECISION;
ALTER TABLE products ADD COLUMN IF NOT EXISTS manufacturing_lead_time_days DOUBLE PRECISION;

-- The active model contains both the EngHub BOM columns and the legacy
-- EngFlow source columns.  Keep reads portable while local seed data uses the
-- EngHub fields below.
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS company_id VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS product_sap_code VARCHAR(100);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS part_number VARCHAR(100);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS quantity DOUBLE PRECISION;
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS unit_price DOUBLE PRECISION;
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS total_cost DOUBLE PRECISION;
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS vendor_code VARCHAR(50);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS vendor_name VARCHAR(255);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS parent_sap VARCHAR(100);
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);

-- 本运行库的 bom_items 以 id 为主键，而旧 ORM 查询还会读取 row_id。
-- 为兼容两个结构补齐唯一行标识，不改动原有 id 及业务数据。
ALTER TABLE bom_items ADD COLUMN IF NOT EXISTS row_id BIGSERIAL;
DO $$
DECLARE sequence_name TEXT;
BEGIN
    SELECT pg_get_serial_sequence('bom_items', 'row_id') INTO sequence_name;
    IF sequence_name IS NOT NULL THEN
        EXECUTE format('UPDATE bom_items SET row_id = nextval(%L) WHERE row_id IS NULL', sequence_name);
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_items_row_id ON bom_items(row_id);

-- Current APS task readers materialize the complete ORM object, so align the
-- legacy task table before PMC subtracts scheduled hours from capacity.
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS actual_start TIMESTAMP;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS actual_end TIMESTAMP;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS deviation_reason TEXT;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS setup_minutes DOUBLE PRECISION DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS material_ready BOOLEAN DEFAULT TRUE;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS sequence_in_station INTEGER;

-- Older production schemas retain a daily capacity summary beside the newer
-- capacity_per_hour column.  Fill both representations for portable seeds.
ALTER TABLE stations ADD COLUMN IF NOT EXISTS capacity INTEGER;
ALTER TABLE stations ADD COLUMN IF NOT EXISTS capacity_unit VARCHAR(20);
ALTER TABLE stations ADD COLUMN IF NOT EXISTS equipment_count INTEGER;

-- 2026 Vietnam working calendar.  Both factories use the same legal calendar;
-- company-specific closures remain separate records/API inputs.
WITH calendar_days(holiday_date, holiday_name, holiday_type) AS (
    VALUES
        (DATE '2026-01-01', 'Tết Dương lịch', 'legal'),
        (DATE '2026-02-14', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-15', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-16', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-17', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-18', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-19', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-20', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-21', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-02-22', 'Tết Nguyên đán', 'legal'),
        (DATE '2026-04-25', 'Giỗ Tổ Hùng Vương', 'legal'),
        (DATE '2026-04-26', 'Giỗ Tổ Hùng Vương', 'legal'),
        (DATE '2026-04-27', 'Giỗ Tổ Hùng Vương - nghỉ bù', 'compensatory'),
        (DATE '2026-04-30', 'Ngày Giải phóng miền Nam', 'legal'),
        (DATE '2026-05-01', 'Ngày Quốc tế Lao động', 'legal'),
        (DATE '2026-09-01', 'Quốc khánh - ngày liền kề', 'legal'),
        (DATE '2026-09-02', 'Quốc khánh', 'legal')
), factories(factory_id) AS (
    VALUES ('FAC_MECH_001'), ('FAC_ELEC_DEMO_2026')
)
INSERT INTO aps_holidays (
    id, factory_id, calendar_code, year, holiday_date, holiday_name,
    holiday_type, is_working_day, source_name, source_url, is_active,
    created_by, created_at, updated_at
)
SELECT
    'vn26-' || lower(replace(factory_id, '_', '-')) || '-' || to_char(holiday_date, 'YYYYMMDD'),
    factory_id, 'VN-LABOR-2026', 2026, holiday_date, holiday_name,
    holiday_type, FALSE, 'Vietnam Government Portal / Ministry of Home Affairs',
    'https://baochinhphu.vn/bo-noi-vu-thong-bao-lich-nghi-tet-am-lich-va-nghi-le-quoc-khanh-nam-2026-102251017095507785.htm',
    TRUE, 'pmc_bootstrap', NOW(), NOW()
FROM factories CROSS JOIN calendar_days
ON CONFLICT (factory_id, holiday_date) DO UPDATE SET
    calendar_code = EXCLUDED.calendar_code,
    holiday_name = EXCLUDED.holiday_name,
    holiday_type = EXCLUDED.holiday_type,
    source_name = EXCLUDED.source_name,
    source_url = EXCLUDED.source_url,
    is_active = TRUE,
    updated_at = NOW();

-- Mechanical virtual factory master data. Codes are intentionally stable so
-- the UI, MPS, APS and chatbot all refer to the same interface data.
INSERT INTO warehouses (
    id, warehouse_code, warehouse_name, factory_id, warehouse_type,
    address, status, created_by, created_at, updated_at
)
VALUES ('wh-vf-mech-001', 'WH-MECH-RM', '机械厂原料仓', 'FAC_MECH_001', 'raw_material',
        'FAC_MECH_001', 'active', 'pmc_bootstrap', NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    warehouse_name = EXCLUDED.warehouse_name,
    status = EXCLUDED.status,
    updated_at = NOW();

INSERT INTO products (
    id, factory_id, product_code, product_name, category, unit, description,
    status, current_bom_version, current_routing_id,
    engineering_lead_time_days, manufacturing_lead_time_days, created_by,
    created_at, updated_at
)
VALUES
    ('FG-TREAD-001', 'FAC_MECH_001', 'FG-TREAD-001', '跑步机 - 体验缺料订单', 'fitness', 'pcs', 'PMC 训练用：含可追溯缺料风险。', 'active', 'CURRENT', 'rt-vf-tread-001', 1, 3, 'pmc_bootstrap', NOW(), NOW()),
    ('FG-TREAD-002', 'FAC_MECH_001', 'FG-TREAD-002', '跑步机 - 交期可信订单', 'fitness', 'pcs', 'PMC 训练用：物料齐套、路线和产能可计算。', 'active', 'CURRENT', 'rt-vf-tread-002', 1, 3, 'pmc_bootstrap', NOW(), NOW()),
    ('FG-TREAD-003', 'FAC_MECH_001', 'FG-TREAD-003', '跑步机 - 常规订单', 'fitness', 'pcs', 'PMC 训练用常规订单。', 'active', 'CURRENT', 'rt-vf-tread-003', 1, 3, 'pmc_bootstrap', NOW(), NOW())
ON CONFLICT (product_code) DO UPDATE SET
    product_name = EXCLUDED.product_name,
    category = EXCLUDED.category,
    unit = EXCLUDED.unit,
    description = EXCLUDED.description,
    status = EXCLUDED.status,
    current_bom_version = EXCLUDED.current_bom_version,
    current_routing_id = EXCLUDED.current_routing_id,
    engineering_lead_time_days = EXCLUDED.engineering_lead_time_days,
    manufacturing_lead_time_days = EXCLUDED.manufacturing_lead_time_days,
    updated_at = NOW();

INSERT INTO stations (
    id, station_code, station_name, factory_id, station_type, workshop_id,
    capacity, capacity_unit, equipment_count, capacity_per_hour, status,
    equipment_ids, created_by, created_at, updated_at
)
SELECT *
FROM (
VALUES
    ('st-vf-hj-01', 'ST-HJ-01', '车架焊接单元', 'FAC_MECH_001', 'welding', 'WS-MECH-01', 60, 'pcs/day', 1, 6, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW()),
    ('st-vf-tz-01', 'ST-TZ-01', '表面涂装单元', 'FAC_MECH_001', 'coating', 'WS-MECH-01', 80, 'pcs/day', 1, 8, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW()),
    ('st-vf-jd-01', 'ST-JD-01', '电控装配单元', 'FAC_MECH_001', 'assembly', 'WS-MECH-02', 50, 'pcs/day', 1, 5, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW()),
    ('st-vf-zl-01', 'ST-ZL-01', '总装单元', 'FAC_MECH_001', 'assembly', 'WS-MECH-02', 70, 'pcs/day', 1, 7, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW()),
    ('st-vf-qc-02', 'ST-QC-02', '成品检验单元', 'FAC_MECH_001', 'quality', 'WS-MECH-03', 100, 'pcs/day', 1, 10, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW()),
    ('st-vf-pk-01', 'ST-PK-01', '包装入库单元', 'FAC_MECH_001', 'packing', 'WS-MECH-03', 120, 'pcs/day', 1, 12, 'active', '[]'::jsonb, 'pmc_bootstrap', NOW(), NOW())
) AS seed(
    id, station_code, station_name, factory_id, station_type, workshop_id,
    capacity, capacity_unit, equipment_count, capacity_per_hour, status,
    equipment_ids, created_by, created_at, updated_at
)
WHERE NOT EXISTS (
    SELECT 1 FROM stations existing WHERE existing.station_code = seed.station_code
)
-- Station codes are the shared business key in production.  Preserve a
-- pre-existing real station's name/capacity instead of creating a duplicate
-- demo resource with the same code.
ON CONFLICT (id) DO NOTHING;

INSERT INTO routings (
    id, routing_code, factory_id, product_id, version, steps, is_active,
    created_by, created_at, updated_at
)
VALUES
    ('rt-vf-tread-001', 'RT-TREAD-001', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', '[{"step_no":10,"name":"车架焊接","station":"ST-HJ-01","UHN":0.17},{"step_no":20,"name":"表面涂装","station":"ST-TZ-01","UHN":0.13},{"step_no":30,"name":"电控装配","station":"ST-JD-01","UHN":0.20},{"step_no":40,"name":"跑步机总装","station":"ST-ZL-01","UHN":0.14},{"step_no":50,"name":"成品检验","station":"ST-QC-02","UHN":0.10},{"step_no":60,"name":"包装入库","station":"ST-PK-01","UHN":0.08}]'::jsonb, TRUE, 'pmc_bootstrap', NOW(), NOW()),
    ('rt-vf-tread-002', 'RT-TREAD-002', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', '[{"step_no":10,"name":"车架焊接","station":"ST-HJ-01","UHN":0.17},{"step_no":20,"name":"表面涂装","station":"ST-TZ-01","UHN":0.13},{"step_no":30,"name":"电控装配","station":"ST-JD-01","UHN":0.20},{"step_no":40,"name":"跑步机总装","station":"ST-ZL-01","UHN":0.14},{"step_no":50,"name":"成品检验","station":"ST-QC-02","UHN":0.10},{"step_no":60,"name":"包装入库","station":"ST-PK-01","UHN":0.08}]'::jsonb, TRUE, 'pmc_bootstrap', NOW(), NOW()),
    ('rt-vf-tread-003', 'RT-TREAD-003', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', '[{"step_no":10,"name":"车架焊接","station":"ST-HJ-01","UHN":0.17},{"step_no":20,"name":"表面涂装","station":"ST-TZ-01","UHN":0.13},{"step_no":30,"name":"电控装配","station":"ST-JD-01","UHN":0.20},{"step_no":40,"name":"跑步机总装","station":"ST-ZL-01","UHN":0.14},{"step_no":50,"name":"成品检验","station":"ST-QC-02","UHN":0.10},{"step_no":60,"name":"包装入库","station":"ST-PK-01","UHN":0.08}]'::jsonb, TRUE, 'pmc_bootstrap', NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    routing_code = EXCLUDED.routing_code,
    steps = EXCLUDED.steps,
    is_active = TRUE,
    updated_at = NOW();

-- BOM uses product codes as canonical interface keys; the PMC service resolves
-- both product.id and product_code to support existing user master data.
INSERT INTO bom_items (
    id, factory_id, product_id, bom_version, material_code, material_name,
    qty_per_unit, unit, level, remark, created_at, updated_at
)
VALUES
    ('bom-vf-t001-frame', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', 'RM-FRAME-002', '跑步机车架', 1, 'pcs', 1, 'TREAD-001 缺料训练项', NOW(), NOW()),
    ('bom-vf-t001-control', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', 'RM-CONTROL-002', '电控板', 1, 'pcs', 1, 'TREAD-001 缺料训练项', NOW(), NOW()),
    ('bom-vf-t001-motor', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', 'RM-MOTOR-002', '驱动电机', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t001-belt', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', 'RM-BELT-002', '跑带组件', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t001-pack', 'FAC_MECH_001', 'FG-TREAD-001', 'CURRENT', 'RM-PACK-002', '包装套件', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t002-frame', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', 'RM-FRAME-002', '跑步机车架', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t002-control', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', 'RM-CONTROL-002', '电控板', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t002-motor', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', 'RM-MOTOR-002', '驱动电机', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t002-belt', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', 'RM-BELT-002', '跑带组件', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t002-pack', 'FAC_MECH_001', 'FG-TREAD-002', 'CURRENT', 'RM-PACK-002', '包装套件', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t003-frame', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', 'RM-FRAME-002', '跑步机车架', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t003-control', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', 'RM-CONTROL-002', '电控板', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t003-motor', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', 'RM-MOTOR-002', '驱动电机', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t003-belt', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', 'RM-BELT-002', '跑带组件', 1, 'pcs', 1, NULL, NOW(), NOW()),
    ('bom-vf-t003-pack', 'FAC_MECH_001', 'FG-TREAD-003', 'CURRENT', 'RM-PACK-002', '包装套件', 1, 'pcs', 1, NULL, NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    material_name = EXCLUDED.material_name,
    qty_per_unit = EXCLUDED.qty_per_unit,
    remark = EXCLUDED.remark,
    updated_at = NOW();

INSERT INTO inventory (
    id, material_id, material_code, material_name, factory_id, warehouse_id,
    batch_code, total_qty, available_qty, reserved_qty, unit_cost, unit,
    status, qualified_status, last_movement_at, created_at, updated_at
)
VALUES
    ('inv-vf-frame-002', 'mat-vf-frame-002', 'RM-FRAME-002', '跑步机车架', 'FAC_MECH_001', 'wh-vf-mech-001', 'TREAD-OPENING-20260810', 22, 22, 0, 45.00, 'pcs', 'available', 'qualified', TIMESTAMP '2026-08-10 16:00:00', NOW(), NOW()),
    ('inv-vf-control-002', 'mat-vf-control-002', 'RM-CONTROL-002', '电控板', 'FAC_MECH_001', 'wh-vf-mech-001', 'TREAD-OPENING-20260810', 18, 18, 0, 80.00, 'pcs', 'available', 'qualified', TIMESTAMP '2026-08-10 16:00:00', NOW(), NOW()),
    ('inv-vf-motor-002', 'mat-vf-motor-002', 'RM-MOTOR-002', '驱动电机', 'FAC_MECH_001', 'wh-vf-mech-001', 'TREAD-OPENING-20260810', 25, 25, 0, 60.00, 'pcs', 'available', 'qualified', TIMESTAMP '2026-08-10 16:00:00', NOW(), NOW()),
    ('inv-vf-belt-002', 'mat-vf-belt-002', 'RM-BELT-002', '跑带组件', 'FAC_MECH_001', 'wh-vf-mech-001', 'TREAD-OPENING-20260810', 25, 25, 0, 24.00, 'pcs', 'available', 'qualified', TIMESTAMP '2026-08-10 16:00:00', NOW(), NOW()),
    ('inv-vf-pack-002', 'mat-vf-pack-002', 'RM-PACK-002', '包装套件', 'FAC_MECH_001', 'wh-vf-mech-001', 'TREAD-OPENING-20260810', 25, 25, 0, 12.00, 'pcs', 'available', 'qualified', TIMESTAMP '2026-08-10 16:00:00', NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    total_qty = EXCLUDED.total_qty,
    available_qty = EXCLUDED.available_qty,
    reserved_qty = EXCLUDED.reserved_qty,
    status = EXCLUDED.status,
    qualified_status = EXCLUDED.qualified_status,
    last_movement_at = EXCLUDED.last_movement_at,
    updated_at = NOW();

INSERT INTO pp_plans (
    id, factory_id, plan_code, plan_type, product_id, quantity, required_date,
    due_date, customer_level, priority, priority_score, status, planning_cycle,
    release_status, planner_id, scheduled_start_date, scheduled_end_date,
    mrp_status, created_by, updated_by, confirmed_by, released_by,
    created_at, updated_at, confirmed_at, released_at
)
VALUES
    ('mps-vf-tread-001-20260810', 'FAC_MECH_001', 'MPS-TREAD-20260810-001', 'mps', 'FG-TREAD-001', 24, DATE '2026-08-18', DATE '2026-08-18', 'a', 90, 90, 'released', 'weekly', 'released', 'pmc_demo', DATE '2026-08-10', DATE '2026-08-18', 'calculated', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', 'pmc_demo', NOW(), NOW(), NOW(), NOW()),
    ('mps-vf-tread-002-20260810', 'FAC_MECH_001', 'MPS-TREAD-20260810-002', 'mps', 'FG-TREAD-002', 18, DATE '2026-08-21', DATE '2026-08-21', 'b', 75, 75, 'released', 'weekly', 'released', 'pmc_demo', DATE '2026-08-11', DATE '2026-08-21', 'calculated', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', 'pmc_demo', NOW(), NOW(), NOW(), NOW()),
    ('mps-vf-tread-003-20260810', 'FAC_MECH_001', 'MPS-TREAD-20260810-003', 'mps', 'FG-TREAD-003', 12, DATE '2026-08-25', DATE '2026-08-25', 'b', 65, 65, 'released', 'weekly', 'released', 'pmc_demo', DATE '2026-08-12', DATE '2026-08-25', 'calculated', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', 'pmc_demo', NOW(), NOW(), NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    quantity = EXCLUDED.quantity,
    required_date = EXCLUDED.required_date,
    due_date = EXCLUDED.due_date,
    status = EXCLUDED.status,
    release_status = EXCLUDED.release_status,
    mrp_status = EXCLUDED.mrp_status,
    scheduled_start_date = EXCLUDED.scheduled_start_date,
    scheduled_end_date = EXCLUDED.scheduled_end_date,
    updated_at = NOW();

INSERT INTO work_orders (
    id, work_order_code, factory_id, source_plan_id, product_id, routing_id,
    planned_qty, unit, completed_qty, good_qty, defect_qty, scrap_qty, status,
    priority, planned_start, planned_due, assigned_station_id,
    current_routing_step, current_stage, next_station, in_progress_status,
    bom_version, wo_type, created_by, updated_by, released_by, remark,
    created_at, updated_at
)
VALUES
    ('wo-vf-tread-001-20260810', 'WO-TREAD-20260810-001', 'FAC_MECH_001', 'mps-vf-tread-001-20260810', 'FG-TREAD-001', 'rt-vf-tread-001', 24, 'pcs', 6, 5, 1, 0, 'in_progress', 'high', TIMESTAMP '2026-08-10 08:00:00', TIMESTAMP '2026-08-18 17:00:00', 'st-vf-jd-01', 30, '电控装配', 'ST-JD-01', TRUE, 'CURRENT', 'master', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', '跑步机1号：保留缺料和质量复判训练场景。', NOW(), NOW()),
    ('wo-vf-tread-002-20260810', 'WO-TREAD-20260810-002', 'FAC_MECH_001', 'mps-vf-tread-002-20260810', 'FG-TREAD-002', 'rt-vf-tread-002', 18, 'pcs', 0, 0, 0, 0, 'released', 'medium', TIMESTAMP '2026-08-11 08:00:00', TIMESTAMP '2026-08-21 17:00:00', 'st-vf-hj-01', 10, '车架焊接', 'ST-HJ-01', FALSE, 'CURRENT', 'master', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', '跑步机2号：用于 PMC 交期可信性评审。', NOW(), NOW()),
    ('wo-vf-tread-003-20260810', 'WO-TREAD-20260810-003', 'FAC_MECH_001', 'mps-vf-tread-003-20260810', 'FG-TREAD-003', 'rt-vf-tread-003', 12, 'pcs', 0, 0, 0, 0, 'released', 'medium', TIMESTAMP '2026-08-12 08:00:00', TIMESTAMP '2026-08-25 17:00:00', 'st-vf-hj-01', 10, '车架焊接', 'ST-HJ-01', FALSE, 'CURRENT', 'master', 'pmc_bootstrap', 'pmc_bootstrap', 'pmc_demo', '跑步机3号：常规生产节奏。', NOW(), NOW())
ON CONFLICT (work_order_code) DO UPDATE SET
    source_plan_id = EXCLUDED.source_plan_id,
    product_id = EXCLUDED.product_id,
    routing_id = EXCLUDED.routing_id,
    planned_qty = EXCLUDED.planned_qty,
    planned_start = EXCLUDED.planned_start,
    planned_due = EXCLUDED.planned_due,
    assigned_station_id = EXCLUDED.assigned_station_id,
    status = EXCLUDED.status,
    priority = EXCLUDED.priority,
    current_routing_step = EXCLUDED.current_routing_step,
    current_stage = EXCLUDED.current_stage,
    next_station = EXCLUDED.next_station,
    in_progress_status = EXCLUDED.in_progress_status,
    updated_at = NOW();

-- Map seeded work orders to the actual resource ID selected by the code above.
UPDATE work_orders w
SET assigned_station_id = s.id,
    updated_at = NOW()
FROM stations s
WHERE w.factory_id = 'FAC_MECH_001'
  AND s.factory_id = w.factory_id
  AND (
      (w.id = 'wo-vf-tread-001-20260810' AND s.station_code = 'ST-JD-01')
      OR (w.id IN ('wo-vf-tread-002-20260810', 'wo-vf-tread-003-20260810') AND s.station_code = 'ST-HJ-01')
  );

UPDATE pp_plans p
SET work_order_id = w.id,
    updated_at = NOW()
FROM work_orders w
WHERE p.factory_id = 'FAC_MECH_001'
  AND w.factory_id = p.factory_id
  AND w.source_plan_id = p.id
  AND p.id IN ('mps-vf-tread-001-20260810', 'mps-vf-tread-002-20260810', 'mps-vf-tread-003-20260810');

INSERT INTO work_order_materials (
    id, work_order_id, material_id, material_code, material_name, qty_per_unit,
    required_qty, unit, received_qty, available_qty, shortage_qty, remark, created_at
)
SELECT
    'wom-' || md5(w.id || ':' || b.material_code),
    w.id, 'mat-vf-' || lower(replace(b.material_code, 'RM-', '')),
    b.material_code, b.material_name, CEIL(b.qty_per_unit)::INTEGER,
    CEIL(b.qty_per_unit * w.planned_qty)::INTEGER, b.unit,
    COALESCE(i.total_qty, 0), COALESCE(i.available_qty, 0),
    GREATEST(0, CEIL(b.qty_per_unit * w.planned_qty)::INTEGER - COALESCE(i.available_qty, 0)),
    '由 PMC 初始化链路生成', NOW()
FROM work_orders w
JOIN bom_items b ON b.factory_id = w.factory_id AND b.product_id = w.product_id
LEFT JOIN inventory i ON i.factory_id = w.factory_id AND i.material_code = b.material_code
WHERE w.factory_id = 'FAC_MECH_001'
  AND w.id IN ('wo-vf-tread-001-20260810', 'wo-vf-tread-002-20260810', 'wo-vf-tread-003-20260810')
ON CONFLICT (id) DO UPDATE SET
    required_qty = EXCLUDED.required_qty,
    received_qty = EXCLUDED.received_qty,
    available_qty = EXCLUDED.available_qty,
    shortage_qty = EXCLUDED.shortage_qty;
