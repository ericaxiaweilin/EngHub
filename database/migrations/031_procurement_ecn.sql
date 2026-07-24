-- 031: 采购员岗位替代 - 供应商 + 采购申请 + 采购订单
-- 核心理念：标准物料自动比价下单，例外才人工

CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    supplier_code VARCHAR(50) NOT NULL,
    supplier_name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(50),
    email VARCHAR(200),
    category VARCHAR(50),           -- 物料类别（电子/机构/包材）
    rating DECIMAL(3,2) DEFAULT 3.0, -- 综合评分 1-5
    on_time_rate DECIMAL(5,2) DEFAULT 0,  -- 准时交付率 %
    quality_rate DECIMAL(5,2) DEFAULT 0,  -- 来料合格率 %
    avg_lead_days INTEGER DEFAULT 7,      -- 平均交期（天）
    is_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, supplier_code)
);
CREATE INDEX IF NOT EXISTS idx_supplier_factory ON suppliers(factory_id);
CREATE INDEX IF NOT EXISTS idx_supplier_category ON suppliers(factory_id, category);

-- 供应商物料价格表（比价核心）
CREATE TABLE IF NOT EXISTS supplier_prices (
    id VARCHAR(36) PRIMARY KEY,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id),
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    unit_price DECIMAL(12,4) NOT NULL,
    currency VARCHAR(10) DEFAULT 'CNY',
    moq INTEGER DEFAULT 1,           -- 最小起订量
    lead_days INTEGER DEFAULT 7,     -- 交期
    valid_from DATE,
    valid_to DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(supplier_id, material_code)
);
CREATE INDEX IF NOT EXISTS idx_sp_material ON supplier_prices(material_code, is_active);

-- 采购申请（MRP 自动生成）
CREATE TABLE IF NOT EXISTS purchase_requisitions (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    pr_code VARCHAR(50) NOT NULL UNIQUE,
    source VARCHAR(30) DEFAULT 'mrp',    -- mrp/manual/reorder
    source_id VARCHAR(50),               -- 关联 MRP plan_id
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    qty DECIMAL(12,3) NOT NULL,
    unit VARCHAR(20) DEFAULT 'PCS',
    required_date DATE,
    status VARCHAR(20) DEFAULT 'pending', -- pending/approved/ordered/cancelled
    auto_approved BOOLEAN DEFAULT FALSE,  -- 系统自动审批
    approved_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pr_factory ON purchase_requisitions(factory_id, status);

-- 采购订单（自动比价后生成）
CREATE TABLE IF NOT EXISTS purchase_orders (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    po_code VARCHAR(50) NOT NULL UNIQUE,
    pr_id VARCHAR(36) REFERENCES purchase_requisitions(id),
    supplier_id VARCHAR(36) REFERENCES suppliers(id),
    supplier_name VARCHAR(200),
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(200),
    qty DECIMAL(12,3) NOT NULL,
    unit_price DECIMAL(12,4),
    total_amount DECIMAL(14,2),
    currency VARCHAR(10) DEFAULT 'CNY',
    order_date DATE DEFAULT CURRENT_DATE,
    expected_date DATE,           -- 预计到货
    actual_date DATE,             -- 实际到货
    status VARCHAR(20) DEFAULT 'draft', -- draft/confirmed/shipped/received/closed/cancelled
    auto_generated BOOLEAN DEFAULT FALSE, -- 系统自动生成
    created_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_po_factory ON purchase_orders(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);

-- 工艺变更单 ECN（工艺员替代核心）
CREATE TABLE IF NOT EXISTS engineering_changes (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    ecn_code VARCHAR(50) NOT NULL UNIQUE,
    title VARCHAR(300) NOT NULL,
    change_type VARCHAR(30) DEFAULT 'process', -- process/material/parameter/design
    affected_product VARCHAR(100),
    affected_routing_id VARCHAR(36),
    description TEXT,
    old_value TEXT,              -- 变更前（JSON）
    new_value TEXT,              -- 变更后（JSON）
    status VARCHAR(20) DEFAULT 'draft', -- draft/reviewing/approved/propagated/closed
    affected_wo_count INTEGER DEFAULT 0,
    propagated_at TIMESTAMP,
    created_by VARCHAR(50),
    approved_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ecn_factory ON engineering_changes(factory_id, status);
