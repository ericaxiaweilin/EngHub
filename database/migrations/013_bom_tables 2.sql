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

-- ===== 种子数据：蓝牙音箱 BOM（BOM-SPK-A1，物料与 inventory 种子数据对应）=====
INSERT INTO bom_items (id, factory_id, product_id, bom_version, material_code, material_name, qty_per_unit, unit, level, remark) VALUES
  ('bom-spk-001', 'FAC_ELEC_DEMO_2026', 'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5', 'BOM-SPK-A1', 'BT-CHIP-XR5',   '蓝牙音频芯片 XR5',   1, 'pcs', 1, '主控芯片'),
  ('bom-spk-002', 'FAC_ELEC_DEMO_2026', 'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5', 'BOM-SPK-A1', 'PCB-SPK-4L',    '音箱主板 4层PCB',    1, 'pcs', 1, 'SMT贴片基板'),
  ('bom-spk-003', 'FAC_ELEC_DEMO_2026', 'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5', 'BOM-SPK-A1', 'SPK-DRV-40MM',  '40mm全频扬声器',     2, 'pcs', 1, '左右声道各一'),
  ('bom-spk-004', 'FAC_ELEC_DEMO_2026', 'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5', 'BOM-SPK-A1', 'BAT-LI-3000',   '锂电池 3000mAh',     1, 'pcs', 1, '续航8小时'),
  ('bom-spk-005', 'FAC_ELEC_DEMO_2026', 'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5', 'BOM-SPK-A1', 'SPK-BT-FINISHED', '音箱成品外壳套件', 1, 'set', 1, '含面网/底座')
ON CONFLICT DO NOTHING;

-- ===== 种子数据：精密塑胶模具 BOM（BOM-MOLD-V1）=====
INSERT INTO bom_items (id, factory_id, product_id, bom_version, material_code, material_name, qty_per_unit, unit, level, remark) VALUES
  ('bom-mold-001', 'FAC_MECH_DEMO_2026', '86a3f108-8c9c-4f4f-9c87-ce7ca2e4cdd1', 'BOM-MOLD-V1', 'MOLD-STEEL-P20',  'P20模具钢',       1, 'block', 1, '模仁材料'),
  ('bom-mold-002', 'FAC_MECH_DEMO_2026', '86a3f108-8c9c-4f4f-9c87-ce7ca2e4cdd1', 'BOM-MOLD-V1', 'HOT-RUNNER-SYS',  '热流道系统',      1, 'set',   1, '4点进胶'),
  ('bom-mold-003', 'FAC_MECH_DEMO_2026', '86a3f108-8c9c-4f4f-9c87-ce7ca2e4cdd1', 'BOM-MOLD-V1', 'MOLD-BASE-S50C',  'S50C标准模架',    1, 'set',   1, 'CI型模架'),
  ('bom-mold-004', 'FAC_MECH_DEMO_2026', '86a3f108-8c9c-4f4f-9c87-ce7ca2e4cdd1', 'BOM-MOLD-V1', 'EJECTOR-PIN-6',   '6mm顶针',        12, 'pcs',   2, '顶出系统')
ON CONFLICT DO NOTHING;
