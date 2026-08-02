-- WMS 全量增强：批次/库位/预警/报表/条码RFID/自动化/多仓/调拨审批/冻结/盘点差异

-- ============== 1. 库位三维 + 状态 ==============
ALTER TABLE locations ADD COLUMN IF NOT EXISTS row_num INTEGER;
ALTER TABLE locations ADD COLUMN IF NOT EXISTS col_num INTEGER;
ALTER TABLE locations ADD COLUMN IF NOT EXISTS level_num INTEGER;
ALTER TABLE locations ADD COLUMN IF NOT EXISTS occupancy_status VARCHAR(20) DEFAULT 'idle';
-- idle / occupied / locked

-- ============== 2. 批次/保质期配置 ==============
ALTER TABLE safety_stock_config ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER DEFAULT 0;
ALTER TABLE safety_stock_config ADD COLUMN IF NOT EXISTS expiry_warn_days INTEGER DEFAULT 30;
ALTER TABLE safety_stock_config ADD COLUMN IF NOT EXISTS slow_moving_days INTEGER DEFAULT 60;

ALTER TABLE inventory ADD COLUMN IF NOT EXISTS abc_class VARCHAR(5) DEFAULT 'C';
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS lock_reason VARCHAR(200);
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS locked_by VARCHAR(50);
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS production_date DATE;

-- ============== 3. 库存冻结记录 ==============
CREATE TABLE IF NOT EXISTS inventory_freezes (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    inventory_id VARCHAR(36) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    batch_code VARCHAR(50),
    reason_code VARCHAR(50) NOT NULL,
    reason_text VARCHAR(500),
    freeze_until TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active',
    frozen_by VARCHAR(50),
    unfrozen_by VARCHAR(50),
    unfrozen_at TIMESTAMP,
    auto_unfreeze BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inv_freeze_factory ON inventory_freezes(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_inv_freeze_until ON inventory_freezes(freeze_until) WHERE status = 'active';

-- ============== 4. 调拨申请/审批 ==============
CREATE TABLE IF NOT EXISTS wms_transfer_requests (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    request_code VARCHAR(50) UNIQUE NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    material_name VARCHAR(100),
    quantity INTEGER NOT NULL,
    from_warehouse_id VARCHAR(36) NOT NULL,
    to_warehouse_id VARCHAR(36) NOT NULL,
    to_location_id VARCHAR(36),
    status VARCHAR(20) DEFAULT 'draft',
    -- draft / pending / approved / rejected / in_transit / completed / cancelled
    requested_by VARCHAR(50),
    approved_by VARCHAR(50),
    approved_at TIMESTAMP,
    rejected_reason VARCHAR(500),
    completed_at TIMESTAMP,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wms_xfer_factory ON wms_transfer_requests(factory_id, status);

-- ============== 5. 条码 ==============
CREATE TABLE IF NOT EXISTS wms_barcodes (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50) NOT NULL,
    barcode VARCHAR(100) NOT NULL,
    barcode_type VARCHAR(20) DEFAULT 'CODE128',
    batch_code VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, barcode)
);
CREATE INDEX IF NOT EXISTS idx_wms_barcode_mat ON wms_barcodes(factory_id, material_code);

-- ============== 6. RFID ==============
CREATE TABLE IF NOT EXISTS wms_rfid_tags (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    tag_id VARCHAR(100) NOT NULL,
    material_id VARCHAR(50),
    material_code VARCHAR(50),
    inventory_id VARCHAR(36),
    batch_code VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, tag_id)
);

CREATE TABLE IF NOT EXISTS wms_rfid_count_sessions (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    warehouse_id VARCHAR(36),
    session_code VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'open',
    total_tags INTEGER DEFAULT 0,
    matched_tags INTEGER DEFAULT 0,
    variance_tags INTEGER DEFAULT 0,
    created_by VARCHAR(50),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wms_rfid_count_items (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES wms_rfid_count_sessions(id),
    tag_id VARCHAR(100) NOT NULL,
    material_code VARCHAR(50),
    expected_qty INTEGER DEFAULT 1,
    scanned_qty INTEGER DEFAULT 0,
    variance_qty INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============== 7. 自动化设备任务 ==============
CREATE TABLE IF NOT EXISTS wms_automation_jobs (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    job_code VARCHAR(50) UNIQUE NOT NULL,
    job_type VARCHAR(30) NOT NULL,
    -- agv_dispatch / stacker_move / auto_sort
    payload JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'queued',
    -- queued / dispatched / running / completed / failed / cancelled
    priority INTEGER DEFAULT 5,
    source_location VARCHAR(100),
    target_location VARCHAR(100),
    material_code VARCHAR(50),
    quantity INTEGER,
    error_message TEXT,
    dispatched_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wms_auto_factory ON wms_automation_jobs(factory_id, status);

-- ============== 8. 多仓库存共享池 ==============
CREATE TABLE IF NOT EXISTS wms_inventory_pools (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    pool_code VARCHAR(50) NOT NULL,
    pool_name VARCHAR(100) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    shared_qty INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, pool_code, material_id)
);

CREATE TABLE IF NOT EXISTS wms_inventory_pool_members (
    id VARCHAR(36) PRIMARY KEY,
    pool_id VARCHAR(36) NOT NULL REFERENCES wms_inventory_pools(id),
    warehouse_id VARCHAR(36) NOT NULL,
    allocated_qty INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pool_id, warehouse_id)
);

-- ============== 9. 盘点差异审批 (cycle count) ==============
ALTER TABLE cycle_count_tasks ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) DEFAULT 'none';
ALTER TABLE cycle_count_tasks ADD COLUMN IF NOT EXISTS approved_by VARCHAR(50);
ALTER TABLE cycle_count_tasks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;
ALTER TABLE cycle_count_tasks ADD COLUMN IF NOT EXISTS variance_adjusted BOOLEAN DEFAULT FALSE;

ALTER TABLE cycle_count_items ADD COLUMN IF NOT EXISTS variance_reason VARCHAR(500);
ALTER TABLE cycle_count_items ADD COLUMN IF NOT EXISTS adjusted BOOLEAN DEFAULT FALSE;

ALTER TABLE inventory_counts ADD COLUMN IF NOT EXISTS variance_summary JSONB;
