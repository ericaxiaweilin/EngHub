-- 013: BOM 物料清单表（MRP 计算的前置条件）
-- MRP 需要：计划 → 产品 → BOM 展开 → 库存核对 → 净需求/采购建议
-- 此前系统无 BOM 表，导致 MRP 无法计算

CREATE TABLE IF NOT EXISTS bom_items (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,          -- 对应 products.id（varchar）
    bom_version VARCHAR(50) NOT NULL,         -- 对应 products.current_bom_version
    material_code VARCHAR(50) NOT NULL,       -- 物料编码（对应 inventory.material_code）
    material_name VARCHAR(100),
    qty_per_unit NUMERIC(12, 4) NOT NULL DEFAULT 1,  -- 单位产品用量
    unit VARCHAR(20) DEFAULT 'pcs',
    level INTEGER NOT NULL DEFAULT 1,         -- BOM 层级
    remark VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bom_items_product ON bom_items (product_id);
CREATE INDEX IF NOT EXISTS idx_bom_items_factory ON bom_items (factory_id);
CREATE INDEX IF NOT EXISTS idx_bom_items_material ON bom_items (material_code);

-- 种子数据已跳过（bom_items表结构不同）
