-- EngHub 种子数据 (F01工厂)

-- 设备
INSERT INTO equipment (id, company_id, code, name, equipment_type, status, equipment_code, factory_id, equipment_name, station_id, created_at, updated_at) VALUES
(1001, 'F01', 'CNC-001', 'CNC加工中心1号', 'cnc', 'running', 'CNC-001', 'F01', 'CNC加工中心1号', 'ST-CNC', NOW(), NOW()),
(1002, 'F01', 'CNC-002', 'CNC加工中心2号', 'cnc', 'running', 'CNC-002', 'F01', 'CNC加工中心2号', 'ST-CNC', NOW(), NOW()),
(1003, 'F01', 'CNC-003', 'CNC五轴加工中心', 'cnc', 'idle', 'CNC-003', 'F01', 'CNC五轴加工中心', 'ST-CNC', NOW(), NOW()),
(1004, 'F01', 'GRIND-001', '平面磨床', 'grinding', 'running', 'GRIND-001', 'F01', '平面磨床', 'ST-GRIND', NOW(), NOW()),
(1005, 'F01', 'EDM-001', '电火花机', 'edm', 'maintenance', 'EDM-001', 'F01', '电火花机', 'ST-EDM', NOW(), NOW()),
(1006, 'F01', 'INSP-001', '三坐标测量仪', 'inspection', 'running', 'INSP-001', 'F01', '三坐标测量仪', 'ST-QC', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 工单
INSERT INTO work_orders (id, work_order_code, factory_id, product_id, planned_qty, completed_qty, good_qty, defect_qty, status, priority, planned_start, planned_due, wo_type, created_at, updated_at) VALUES
('a0000001-0000-0000-0000-000000000001', 'WO-2026-0001', 'F01', 'PROD-AL6061', 500, 320, 310, 10, 'in_progress', 'high', NOW() - INTERVAL '3 days', NOW() + INTERVAL '4 days', 'production', NOW() - INTERVAL '5 days', NOW()),
('a0000001-0000-0000-0000-000000000002', 'WO-2026-0002', 'F01', 'PROD-SUS304', 200, 200, 195, 5, 'completed', 'normal', NOW() - INTERVAL '7 days', NOW() - INTERVAL '1 day', 'production', NOW() - INTERVAL '8 days', NOW()),
('a0000001-0000-0000-0000-000000000003', 'WO-2026-0003', 'F01', 'PROD-TI-ALLOY', 100, 0, 0, 0, 'released', 'urgent', NOW() + INTERVAL '1 day', NOW() + INTERVAL '5 days', 'production', NOW() - INTERVAL '1 day', NOW()),
('a0000001-0000-0000-0000-000000000004', 'WO-2026-0004', 'F01', 'PROD-CU1100', 300, 150, 148, 2, 'in_progress', 'normal', NOW() - INTERVAL '2 days', NOW() + INTERVAL '6 days', 'production', NOW() - INTERVAL '4 days', NOW()),
('a0000001-0000-0000-0000-000000000005', 'WO-2026-0005', 'F01', 'PROD-AL7075', 800, 0, 0, 0, 'draft', 'low', NOW() + INTERVAL '7 days', NOW() + INTERVAL '14 days', 'production', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 报工
INSERT INTO production_reports (id, work_order_id, factory_id, good_qty, defect_qty, scrap_qty, is_undone, created_at, station_id, report_code, report_type, shift, operator_id, operation_seq, operation_name, machine_id, start_time, end_time, cycle_time_sec, updated_at) VALUES
('b0000001-0000-0000-0000-000000000001', 'a0000001-0000-0000-0000-000000000001', 'F01', 50, 2, 0, FALSE, NOW() - INTERVAL '2 hours', 'ST-CNC', 'RPT-001', 'normal', 'day', 'eric', 10, 'CNC粗加工', '1001', NOW() - INTERVAL '3 hours', NOW() - INTERVAL '2 hours', 72, NOW()),
('b0000001-0000-0000-0000-000000000002', 'a0000001-0000-0000-0000-000000000001', 'F01', 45, 1, 1, FALSE, NOW() - INTERVAL '1 hour', 'ST-CNC', 'RPT-002', 'normal', 'day', 'eric', 20, 'CNC精加工', '1002', NOW() - INTERVAL '2 hours', NOW() - INTERVAL '1 hour', 80, NOW()),
('b0000001-0000-0000-0000-000000000003', 'a0000001-0000-0000-0000-000000000004', 'F01', 80, 3, 0, FALSE, NOW() - INTERVAL '4 hours', 'ST-GRIND', 'RPT-003', 'normal', 'day', 'eric', 30, '平面磨削', '1004', NOW() - INTERVAL '5 hours', NOW() - INTERVAL '4 hours', 45, NOW()),
('b0000001-0000-0000-0000-000000000004', 'a0000001-0000-0000-0000-000000000002', 'F01', 195, 5, 2, FALSE, NOW() - INTERVAL '1 day', 'ST-CNC', 'RPT-004', 'normal', 'night', 'eric', 10, 'CNC加工', '1001', NOW() - INTERVAL '1 day' - INTERVAL '2 hours', NOW() - INTERVAL '1 day', 37, NOW())
ON CONFLICT (id) DO NOTHING;
