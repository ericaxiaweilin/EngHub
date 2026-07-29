-- ============================================================================
-- EngHub MES v2.5 - Data Consistency & Traceability Migration
-- Date: 2026-07-22
-- Description: 新增缺陷记录表、批次追溯表、对账表、线边仓补货水位表
-- ============================================================================

-- 1. 缺陷记录表 (DefectRecord) - 与 ProductionReport 原子关联
CREATE TABLE IF NOT EXISTS defect_records (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    record_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(36) REFERENCES work_orders(id),
    production_report_id VARCHAR(36) REFERENCES production_reports(id),
    product_id VARCHAR(36) REFERENCES products(id),
    material_id VARCHAR(50),
    batch_code VARCHAR(50),
    station_id VARCHAR(50),
    equipment_id VARCHAR(36) REFERENCES equipment(id),
    defect_type VARCHAR(50) NOT NULL,        -- appearance, dimension, function, performance, material, process, other
    severity VARCHAR(20) NOT NULL DEFAULT 'minor', -- critical, major, minor, observation
    quantity INTEGER NOT NULL DEFAULT 0,
    disposition VARCHAR(20),                 -- rework, repair, scrap, concession, return
    disposition_by VARCHAR(50),
    disposition_at TIMESTAMP,
    disposition_remark TEXT,
    ocap_status VARCHAR(20) DEFAULT 'pending', -- pending, triggered, in_progress, completed
    description TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_finalized BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_dr_work_order ON defect_records(work_order_id);
CREATE INDEX IF NOT EXISTS idx_dr_factory_batch ON defect_records(factory_id, batch_code);
CREATE INDEX IF NOT EXISTS idx_dr_status ON defect_records(disposition);
CREATE INDEX IF NOT EXISTS idx_dr_severity ON defect_records(severity);
CREATE INDEX IF NOT EXISTS idx_dr_ocap ON defect_records(ocap_status);

COMMENT ON COLUMN defect_records.defect_type IS '缺陷类型：appearance/dimension/function/performance/material/process/other';
COMMENT ON COLUMN defect_records.severity IS '严重等级：critical/major/minor/observation';
COMMENT ON COLUMN defect_records.disposition IS '处置方式：rework/repair/scrap/concession/return';

-- 2. 一物一码追溯链 (ItemTraceability)
CREATE TABLE IF NOT EXISTS item_traceability (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    item_code VARCHAR(50) UNIQUE NOT NULL,       -- 成品序列号 / 半成品条码
    item_type VARCHAR(20) NOT NULL DEFAULT 'finished', -- raw_material, semi_finished, finished
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(36) REFERENCES work_orders(id),
    product_id VARCHAR(36) REFERENCES products(id),
    material_batch_id VARCHAR(50),              -- 原材料批次号
    material_supplier_id VARCHAR(50),
    station_id VARCHAR(50),
    equipment_id VARCHAR(36) REFERENCES equipment(id),
    operator_id VARCHAR(50),
    quality_check_result VARCHAR(20),           -- pass, fail, rework_pass
    serial_number VARCHAR(50),                  -- 序列号（成品）
    next_item_code VARCHAR(36),                 -- 子件/关联件 trace code
    inspection_record_id VARCHAR(36),
    metadata_ JSONB DEFAULT '{}'::jsonb,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_it_item_code ON item_traceability(item_code);
CREATE INDEX IF NOT EXISTS idx_it_work_order ON item_traceability(work_order_id);
CREATE INDEX IF NOT EXISTS idx_it_factory_product ON item_traceability(factory_id, product_id);
CREATE INDEX IF NOT EXISTS idx_it_operator ON item_traceability(operator_id);
CREATE INDEX IF NOT EXISTS idx_it_serial ON item_traceability(serial_number);

-- 3. 数据对账日志 (ReconciliationLog) - 自动对账机器人产物
CREATE TABLE IF NOT EXISTS reconciliation_logs (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    reconcile_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    work_order_id VARCHAR(36) REFERENCES work_orders(id),
    planned_qty INTEGER NOT NULL DEFAULT 0,
    good_qty INTEGER NOT NULL DEFAULT 0,
    defect_qty INTEGER NOT NULL DEFAULT 0,
    scrap_qty INTEGER NOT NULL DEFAULT 0,
    net_change INTEGER NOT NULL DEFAULT 0,       -- 良品+不良品+报废
    expected_delta INTEGER NOT NULL DEFAULT 0,   -- 工单进度变化期望值
    delta INTEGER NOT NULL DEFAULT 0,            -- 差异
    status VARCHAR(20) NOT NULL DEFAULT 'ok',    -- ok, mismatch, investigating
    discrepancy_detail TEXT,
    checked_by VARCHAR(50) DEFAULT 'auto_reconciler',
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rl_work_order ON reconciliation_logs(work_order_id);
CREATE INDEX IF NOT EXISTS idx_rl_factory_date ON reconciliation_logs(factory_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_rl_status ON reconciliation_logs(status);

-- 4. Min-Max 线边仓水位表 (ReplenishmentThreshold)
CREATE TABLE IF NOT EXISTS replenishment_thresholds (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    warehouse_id VARCHAR(36) REFERENCES warehouses(id),
    location_id VARCHAR(36) REFERENCES locations(id),
    material_id VARCHAR(50) NOT NULL,
    min_level INTEGER NOT NULL DEFAULT 0,          -- 最低库存水位（触发补货）
    max_level INTEGER NOT NULL DEFAULT 0,          -- 目标库存水位
    safety_stock INTEGER NOT NULL DEFAULT 0,       -- 安全库存
    reorder_lot_size INTEGER NOT NULL DEFAULT 1,   -- 每次补货批量
    reorder_lead_time_hours FLOAT DEFAULT 24.0,    -- 补货提前期（小时）
    line_side_location VARCHAR(50),               -- 线边仓位
    active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(factory_id, material_id, line_side_location)
);

CREATE INDEX IF NOT EXISTS idx_rt_factory ON replenishment_thresholds(factory_id);
CREATE INDEX IF NOT EXISTS idx_rt_material ON replenishment_thresholds(material_id);
CREATE INDEX IF NOT EXISTS idx_rt_warehouse ON replenishment_thresholds(warehouse_id);

-- 5. 拉动式补货任务 (PullReplenishmentTask)
CREATE TABLE IF NOT EXISTS pull_replenishment_tasks (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    task_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    source_warehouse_id VARCHAR(36) REFERENCES warehouses(id),
    target_location_id VARCHAR(36) REFERENCES locations(id),
    material_id VARCHAR(50) NOT NULL,
    requested_qty INTEGER NOT NULL DEFAULT 0,
    fulfilled_qty INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, approved, picking, delivering, completed, cancelled
    trigger_type VARCHAR(20) DEFAULT 'min_reached', -- min_reached, manual, scheduled, work_order_pull
    work_order_id VARCHAR(36) REFERENCES work_orders(id),
    threshold_id VARCHAR(36) REFERENCES replenishment_thresholds(id),
    assigned_to VARCHAR(50),                     -- 仓管员ID或角色
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prt_factory_status ON pull_replenishment_tasks(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_prt_material ON pull_replenishment_tasks(material_id);
CREATE INDEX IF NOT EXISTS idx_prt_work_order ON pull_replenishment_tasks(work_order_id);

-- 6. 初始化默认权限
INSERT INTO permissions (id, name, module, action, module_name, action_name, description)
VALUES
    ('00000000-0000-0000-0000-000000000090', 'andon:view', 'andon', 'view', '安灯工单', '查看', '查看安灯小工单'),
    ('00000000-0000-0000-0000-000000000091', 'andon:create', 'andon', 'create', '安灯工单', '创建', '创建安灯呼叫工单'),
    ('00000000-0000-0000-0000-000000000092', 'andon:claim', 'andon', 'claim', '安灯工单', '抢单', '认领安灯工单'),
    ('00000000-0000-0000-0000-000000000093', 'andon:escalate', 'andon', 'escalate', '安灯工单', '升级', '升级安灯工单'),
    ('00000000-0000-0000-0000-000000000094', 'work_order_template:view', 'work_order_template', 'view', '程序工单模板', '查看', '查看程序工单模板'),
    ('00000000-0000-0000-0000-000000000095', 'work_order_template:create', 'work_order_template', 'create', '程序工单模板', '创建', '基于模板创建工单'),
    ('00000000-0000-0000-0000-000000000096', 'reconciliation:view', 'reconciliation', 'view', '数据对账', '查看', '查看数据对账结果'),
    ('00000000-0000-0000-0000-000000000097', 'reconciliation:trigger', 'reconciliation', 'trigger', '数据对账', '执行', '手动触发数据对账'),
    ('00000000-0000-0000-0000-000000000098', 'traceability:view', 'traceability', 'view', '追溯', '查看', '查看物料追溯链'),
    ('00000000-0000-0000-0000-000000000099', 'replenishment:view', 'replenishment', 'view', '线边仓补货', '查看', '查看补货任务'),
    ('00000000-0000-0000-0000-000000000100', 'replenishment:create', 'replenishment', 'create', '线边仓补货', '创建', '创建拉动式补货任务')
ON CONFLICT DO NOTHING;
