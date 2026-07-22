-- 010: WMS 种子数据 - 仓库 + 库存
-- 确保 InventoryList 页面有数据展示

-- 仓库
INSERT INTO warehouses (id, warehouse_code, warehouse_name, factory_id, warehouse_type, address, status, created_by, created_at, updated_at)
VALUES
    ('wh-seed-001', 'WH-RAW-01', '原材料仓', 'FAC_ELEC_DEMO_2026', 'raw_material', 'A栋1层', 'active', 'admin', NOW(), NOW()),
    ('wh-seed-002', 'WH-FG-01', '成品仓', 'FAC_ELEC_DEMO_2026', 'finished_goods', 'B栋1层', 'active', 'admin', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 库存记录
INSERT INTO inventory (id, material_id, material_code, factory_id, warehouse_id, batch_code, total_qty, available_qty, reserved_qty, unit_cost, status, created_at, updated_at)
VALUES
    ('inv-seed-001', 'MAT-BT-CHIP-001', 'BT-CHIP-XR5', 'FAC_ELEC_DEMO_2026', 'wh-seed-001', 'BATCH-20260701', 5000, 4800, 200, 3.50, 'normal', NOW(), NOW()),
    ('inv-seed-002', 'MAT-PCB-001', 'PCB-SPK-4L', 'FAC_ELEC_DEMO_2026', 'wh-seed-001', 'BATCH-20260705', 2000, 1850, 150, 8.20, 'normal', NOW(), NOW()),
    ('inv-seed-003', 'MAT-SPK-DRV-001', 'SPK-DRV-40MM', 'FAC_ELEC_DEMO_2026', 'wh-seed-001', 'BATCH-20260710', 3000, 3000, 0, 5.80, 'normal', NOW(), NOW()),
    ('inv-seed-004', 'MAT-BAT-001', 'BAT-LI-3000', 'FAC_ELEC_DEMO_2026', 'wh-seed-001', 'BATCH-20260712', 1500, 1200, 300, 12.00, 'normal', NOW(), NOW()),
    ('inv-seed-005', 'FG-SPK-001', 'SPK-BT-FINISHED', 'FAC_ELEC_DEMO_2026', 'wh-seed-002', 'BATCH-20260718', 800, 750, 50, 85.00, 'normal', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
