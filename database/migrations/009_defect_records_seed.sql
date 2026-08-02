-- 009: 创建 defect_records 表 + 从 production_reports 生成种子数据
-- 确保 Dashboard 不良品数与 QMS 不良品模块数据一致

CREATE TABLE IF NOT EXISTS defect_records (
    id              VARCHAR(36) PRIMARY KEY,
    record_code     VARCHAR(50) NOT NULL UNIQUE,
    factory_id      VARCHAR(50) NOT NULL,
    work_order_id   VARCHAR(36) REFERENCES work_orders(id),
    production_report_id VARCHAR(36) REFERENCES production_reports(id),
    product_id      VARCHAR(36) REFERENCES products(id),
    material_id     VARCHAR(50),
    batch_code      VARCHAR(50),
    station_id      VARCHAR(50),
    equipment_id    VARCHAR(36) REFERENCES equipment(id),
    defect_type     VARCHAR(50) NOT NULL,
    severity        VARCHAR(20) NOT NULL DEFAULT 'minor',
    quantity        INTEGER NOT NULL DEFAULT 0,
    disposition     VARCHAR(20),
    disposition_by  VARCHAR(50),
    disposition_at  TIMESTAMP,
    disposition_remark TEXT,
    ocap_status     VARCHAR(20) DEFAULT 'pending',
    description     TEXT,
    created_by      VARCHAR(50),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    is_finalized    BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_defect_records_factory_id ON defect_records(factory_id);
CREATE INDEX IF NOT EXISTS ix_defect_records_record_code ON defect_records(record_code);
CREATE INDEX IF NOT EXISTS ix_defect_records_work_order_id ON defect_records(work_order_id);
CREATE INDEX IF NOT EXISTS ix_defect_records_production_report_id ON defect_records(production_report_id);
CREATE INDEX IF NOT EXISTS ix_defect_records_product_id ON defect_records(product_id);
CREATE INDEX IF NOT EXISTS ix_defect_records_station_id ON defect_records(station_id);
CREATE INDEX IF NOT EXISTS ix_defect_records_ocap_status ON defect_records(ocap_status);
CREATE INDEX IF NOT EXISTS ix_defect_records_is_finalized ON defect_records(is_finalized);
CREATE INDEX IF NOT EXISTS idx_dr_factory_batch ON defect_records(factory_id, batch_code);
CREATE INDEX IF NOT EXISTS idx_dr_disposition_severity ON defect_records(disposition, severity);

-- 从 production_reports 中 defect_qty > 0 的记录生成缺陷记录
-- 报工1: 6件不良 (function)
INSERT INTO defect_records (id, record_code, factory_id, work_order_id, production_report_id, product_id, station_id, defect_type, severity, quantity, description, created_by, created_at, updated_at)
VALUES (
    'dr-seed-001',
    'DEF-20260721-001',
    'FAC_ELEC_DEMO_2026',
    '409bd5c3-6e7f-4fe1-9783-a1194af9c81d',
    'eb9fe9c1-ded9-4583-9491-db2f2d18853b',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    '09f399a1-cdb0-4448-99fd-54fa80d70180',
    'function',
    'major',
    6,
    'SMT贴片后功能测试发现6件蓝牙连接异常',
    'admin',
    '2026-07-21 18:14:40',
    '2026-07-21 18:14:40'
) ON CONFLICT (id) DO NOTHING;

-- 报工2: 7件不良 (appearance)
INSERT INTO defect_records (id, record_code, factory_id, work_order_id, production_report_id, product_id, station_id, defect_type, severity, quantity, description, created_by, created_at, updated_at)
VALUES (
    'dr-seed-002',
    'DEF-20260721-002',
    'FAC_ELEC_DEMO_2026',
    'bcbbeb04-23f8-4bdd-ab35-451a02ade5ce',
    '58543d36-2f50-4226-a3c2-1138d613e7ce',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    'b63a0fa1-4bb7-4ddc-8ce3-d97b184e5805',
    'appearance',
    'minor',
    7,
    '包装前外观检验发现7件外壳划痕',
    'admin',
    '2026-07-21 18:14:40',
    '2026-07-21 18:14:40'
) ON CONFLICT (id) DO NOTHING;

-- 报工3: 8件不良 (dimension)
INSERT INTO defect_records (id, record_code, factory_id, work_order_id, production_report_id, product_id, station_id, defect_type, severity, quantity, description, created_by, created_at, updated_at)
VALUES (
    'dr-seed-003',
    'DEF-20260721-003',
    'FAC_ELEC_DEMO_2026',
    'c378ef64-de7e-4483-b738-9a33fcfab51c',
    '375ce2b0-d7b4-4b4e-8bbe-2a55de284000',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    '09f399a1-cdb0-4448-99fd-54fa80d70180',
    'dimension',
    'major',
    8,
    '试产批次尺寸检测发现8件PCB板定位孔偏移超标',
    'admin',
    '2026-07-21 18:14:40',
    '2026-07-21 18:14:40'
) ON CONFLICT (id) DO NOTHING;
