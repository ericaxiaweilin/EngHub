-- 仓储智能体依赖：采购申请表 + 工单物料状态字段

-- 采购申请（仓储智能体自动创建）
CREATE TABLE IF NOT EXISTS purchase_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(100) NOT NULL,
    material_name VARCHAR(200),
    requested_qty NUMERIC NOT NULL DEFAULT 0,
    unit VARCHAR(20) DEFAULT 'pcs',
    urgency VARCHAR(20) DEFAULT 'normal',  -- normal/urgent
    status VARCHAR(20) DEFAULT 'pending',   -- pending/approved/ordered/cancelled
    source VARCHAR(50) DEFAULT 'warehouse_agent',  -- 谁创建的
    supplier_id VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pr_factory ON purchase_requests(factory_id);
CREATE INDEX IF NOT EXISTS idx_pr_status ON purchase_requests(status);
CREATE INDEX IF NOT EXISTS idx_pr_material ON purchase_requests(material_code);

-- 工单增加物料状态字段
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS material_status VARCHAR(20) DEFAULT 'unknown';
-- unknown/ready/shortage/checking

-- 库存表增加仓储智能体所需字段
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS safety_stock INTEGER DEFAULT 10;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_point INTEGER DEFAULT 20;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_qty INTEGER DEFAULT 50;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS abc_class VARCHAR(5) DEFAULT 'C';
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS location_code VARCHAR(50);
