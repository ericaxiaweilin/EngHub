-- ============================================================
-- 补全空白页面数据 seed 脚本
-- 目标：让所有关键业务模块页面有数据展示
-- ============================================================

BEGIN;

-- ============================================================
-- 1. Products（产品）— 匹配 work_orders 中引用的 product_id
-- ============================================================
INSERT INTO products (id, factory_id, product_code, product_name, category, unit, description, status, standard_cost, selling_price, current_bom_version, created_by)
VALUES
  (gen_random_uuid(), 'F01', 'PRD-001',       '精密齿轮箱',       'finished_product', 'pcs', '高精度齿轮箱总成',         'active', 280.00, 450.00, 'V2.1', 'system'),
  (gen_random_uuid(), 'F01', 'PROD-AL7075',   'AL7075铝板',       'raw_material',     'kg',  '航空级7075铝合金板材',     'active', 45.00,  68.00,  'V1.0', 'system'),
  (gen_random_uuid(), 'F01', 'PROD-CU1100',   'T2紫铜棒',         'raw_material',     'kg',  'T2紫铜圆棒φ20',           'active', 62.00,  95.00,  'V1.0', 'system'),
  (gen_random_uuid(), 'F01', 'PROD-SUS304',   'SUS304不锈钢板',   'raw_material',     'kg',  '304不锈钢冷轧板',          'active', 28.00,  42.00,  'V1.2', 'system'),
  (gen_random_uuid(), 'F01', 'PROD-AL6061',   'AL6061铝型材',     'raw_material',     'kg',  '6061-T6铝型材',            'active', 35.00,  55.00,  'V1.1', 'system'),
  (gen_random_uuid(), 'F01', 'PROD-TI-ALLOY', 'TC4钛合金棒',      'raw_material',     'kg',  'TC4钛合金棒材φ15',         'active', 180.00, 280.00, 'V1.0', 'system'),
  (gen_random_uuid(), 'FAC_MECH_001', 'FG-WIRE-01',     '镀锌铁丝成品',     'finished_product', 'roll', '0.8mm镀锌铁丝卷',          'active', 12.00,  22.00,  'V3.0', 'system'),
  (gen_random_uuid(), 'FAC_MECH_001', 'FG-WHEEL-01',    '铝合金轮毂',       'finished_product', 'pcs',  '18寸铝合金轮毂',            'active', 320.00, 580.00, 'V2.5', 'system'),
  (gen_random_uuid(), 'FAC_MECH_001', 'FG-DUMBBELL-01', '电镀哑铃',         'finished_product', 'pcs',  '20kg电镀哑铃对',            'active', 85.00,  150.00, 'V1.8', 'system'),
  (gen_random_uuid(), 'FAC_MECH_001', 'FG-METER-01',    '数字功率计',       'finished_product', 'pcs',  '工业数字功率计',            'active', 210.00, 380.00, 'V2.0', 'system')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 2. Warehouses（仓库）
-- ============================================================
INSERT INTO warehouses (id, warehouse_code, warehouse_name, factory_id, warehouse_type, address, status, created_by)
VALUES
  ('WH-F01-RM',  'WH-F01-RM',  '主工厂原材料仓',   'F01',          'raw_material',   'A栋1层', 'active', 'system'),
  ('WH-F01-FG',  'WH-F01-FG',  '主工厂成品仓',     'F01',          'finished_goods', 'A栋2层', 'active', 'system'),
  ('WH-F01-WIP', 'WH-F01-WIP', '主工厂在制品仓',   'F01',          'in_transit',     'A栋1层半', 'active', 'system'),
  ('WH-MECH-RM', 'WH-MECH-RM', '机械厂原材料仓',   'FAC_MECH_001', 'raw_material',   'B栋1层', 'active', 'system'),
  ('WH-MECH-FG', 'WH-MECH-FG', '机械厂成品仓',     'FAC_MECH_001', 'finished_goods', 'B栋2层', 'active', 'system')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 3. Locations（库位）
-- ============================================================
INSERT INTO locations (id, location_code, location_name, warehouse_id, location_type, zone, capacity, status, aisle, rack, level)
VALUES
  ('LOC-F01-A01', 'F01-A01-01', '原材料A区1排1层', 'WH-F01-RM', 'rack', 'A', 500, 'active', 'A', '01', '1'),
  ('LOC-F01-A02', 'F01-A01-02', '原材料A区1排2层', 'WH-F01-RM', 'rack', 'A', 500, 'active', 'A', '01', '2'),
  ('LOC-F01-B01', 'F01-B01-01', '原材料B区1排1层', 'WH-F01-RM', 'rack', 'B', 400, 'active', 'B', '01', '1'),
  ('LOC-F01-FG1', 'F01-FG-01',  '成品区1排',       'WH-F01-FG', 'rack', 'FG', 300, 'active', 'FG', '01', '1'),
  ('LOC-F01-FG2', 'F01-FG-02',  '成品区2排',       'WH-F01-FG', 'rack', 'FG', 300, 'active', 'FG', '02', '1'),
  ('LOC-MECH-A01','MECH-A01-01','机械厂A区',        'WH-MECH-RM','rack', 'A', 600, 'active', 'A', '01', '1'),
  ('LOC-MECH-FG1','MECH-FG-01', '机械厂成品区',     'WH-MECH-FG','rack', 'FG', 400, 'active', 'FG', '01', '1')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 4. Production Lines（产线）
-- ============================================================
INSERT INTO production_lines (company_id, code, name, description)
VALUES
  ('F01',          'LINE-CNC',    'CNC加工产线',     'CNC数控加工中心产线'),
  ('F01',          'LINE-GRIND',  '磨削产线',        '精密磨削产线'),
  ('F01',          'LINE-ASSY',   '装配产线',        '总成装配产线'),
  ('FAC_MECH_001', 'LINE-WIRE',   '铁丝生产线',      '镀锌铁丝拉拔生产线'),
  ('FAC_MECH_001', 'LINE-WHEEL',  '轮毂加工线',      '铝合金轮毂机加工线'),
  ('FAC_MECH_001', 'LINE-COAT',   '电镀涂装线',      '哑铃电镀涂装线')
ON CONFLICT DO NOTHING;

-- 更新 equipment 关联产线
UPDATE equipment SET production_line_id = (SELECT id FROM production_lines WHERE code = 'LINE-CNC' AND company_id = 'F01') WHERE equipment_code = 'CNC-001';
UPDATE equipment SET production_line_id = (SELECT id FROM production_lines WHERE code = 'LINE-CNC' AND company_id = 'F01') WHERE equipment_code = 'CNC-002';
UPDATE equipment SET production_line_id = (SELECT id FROM production_lines WHERE code = 'LINE-CNC' AND company_id = 'F01') WHERE equipment_code = 'CNC-003';
UPDATE equipment SET production_line_id = (SELECT id FROM production_lines WHERE code = 'LINE-GRIND' AND company_id = 'F01') WHERE equipment_code = 'GRIND-001';
UPDATE equipment SET production_line_id = (SELECT id FROM production_lines WHERE code = 'LINE-ASSY' AND company_id = 'F01') WHERE equipment_code = 'EDM-001';

-- ============================================================
-- 5. Shifts（班次）
-- ============================================================
INSERT INTO shifts (id, factory_id, shift_name, shift_code, start_time, end_time, status)
VALUES
  ('SHIFT-F01-DAY',   'F01',          '白班', 'DAY',   '08:00:00', '16:00:00', 'active'),
  ('SHIFT-F01-NIGHT', 'F01',          '夜班', 'NIGHT', '16:00:00', '00:00:00', 'active'),
  ('SHIFT-F01-MID',   'F01',          '中班', 'MID',   '00:00:00', '08:00:00', 'active'),
  ('SHIFT-MECH-DAY',  'FAC_MECH_001', '白班', 'DAY',   '07:30:00', '15:30:00', 'active'),
  ('SHIFT-MECH-NIGHT','FAC_MECH_001', '夜班', 'NIGHT', '15:30:00', '23:30:00', 'active')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 6. Process Routes & Operations（工艺路线与工序）
-- ============================================================
INSERT INTO process_routes (company_id, code, name, version, status)
VALUES
  ('F01',          'ROUTE-GEAR',    '齿轮箱加工工艺',    'V2.1', 'active'),
  ('F01',          'ROUTE-CNC-PRT', 'CNC零件加工工艺',  'V1.0', 'active'),
  ('FAC_MECH_001', 'ROUTE-WIRE',    '铁丝拉拔工艺',    'V3.0', 'active'),
  ('FAC_MECH_001', 'ROUTE-WHEEL',   '轮毂加工工艺',    'V2.5', 'active'),
  ('FAC_MECH_001', 'ROUTE-COAT',    '电镀涂装工艺',    'V1.8', 'active')
ON CONFLICT DO NOTHING;

INSERT INTO process_operations (company_id, route_id, sequence, code, name, production_line_id)
SELECT pr.company_id, pr.id, seq.seq, seq.code, seq.name, pl.id
FROM (
  VALUES
    ('F01',          'ROUTE-GEAR',    10, 'OP-CUT',    '下料切割',   'LINE-CNC'),
    ('F01',          'ROUTE-GEAR',    20, 'OP-CNC',    'CNC粗加工',  'LINE-CNC'),
    ('F01',          'ROUTE-GEAR',    30, 'OP-GRIND',  '精密磨削',   'LINE-GRIND'),
    ('F01',          'ROUTE-GEAR',    40, 'OP-ASSY',   '总成装配',   'LINE-ASSY'),
    ('F01',          'ROUTE-GEAR',    50, 'OP-INSP',   '终检',       'LINE-ASSY'),
    ('F01',          'ROUTE-CNC-PRT', 10, 'OP-CUT2',   '备料',       'LINE-CNC'),
    ('F01',          'ROUTE-CNC-PRT', 20, 'OP-TURN',   '车削',       'LINE-CNC'),
    ('F01',          'ROUTE-CNC-PRT', 30, 'OP-MILL',   '铣削',       'LINE-CNC'),
    ('FAC_MECH_001', 'ROUTE-WIRE',    10, 'OP-DRAW',   '拉拔',       'LINE-WIRE'),
    ('FAC_MECH_001', 'ROUTE-WIRE',    20, 'OP-GALV',   '镀锌',       'LINE-WIRE'),
    ('FAC_MECH_001', 'ROUTE-WIRE',    30, 'OP-SPOOL',  '卷绕包装',   'LINE-WIRE'),
    ('FAC_MECH_001', 'ROUTE-WHEEL',   10, 'OP-CAST',   '铸造',       'LINE-WHEEL'),
    ('FAC_MECH_001', 'ROUTE-WHEEL',   20, 'OP-MACH',   '机加工',     'LINE-WHEEL'),
    ('FAC_MECH_001', 'ROUTE-WHEEL',   30, 'OP-POLISH', '抛光',       'LINE-WHEEL'),
    ('FAC_MECH_001', 'ROUTE-COAT',    10, 'OP-PREP',   '前处理',     'LINE-COAT'),
    ('FAC_MECH_001', 'ROUTE-COAT',    20, 'OP-PLATE',  '电镀',       'LINE-COAT'),
    ('FAC_MECH_001', 'ROUTE-COAT',    30, 'OP-CURE',   '固化',       'LINE-COAT')
) AS seq(factory, route_code, seq, code, name, line_code)
JOIN process_routes pr ON pr.code = seq.route_code AND pr.company_id = seq.factory
LEFT JOIN production_lines pl ON pl.code = seq.line_code AND pl.company_id = seq.factory;

-- ============================================================
-- 7. Production Alerts（生产告警）
-- ============================================================
INSERT INTO production_alerts (id, factory_id, alert_type, severity, title, message, source_type, source_id, metric_value, threshold_value, is_read, is_resolved, triggered_at, created_by)
VALUES
  (gen_random_uuid(), 'F01', 'machine_stop',    'critical', 'CNC-001 主轴温度过高',     '主轴温度达到85°C，超过阈值80°C，建议立即停机检查', 'equipment', '1001', 85.0, 80.0, false, false, NOW() - INTERVAL '2 hours', 'system'),
  (gen_random_uuid(), 'F01', 'below_target',    'warning',  '齿轮箱产出低于目标',       '当前班次产出120件，目标180件，达成率66.7%',        'work_order', NULL,  120.0, 180.0, true,  false, NOW() - INTERVAL '5 hours', 'system'),
  (gen_random_uuid(), 'F01', 'material_short',  'high',     'AL7075铝板库存不足',       '当前库存50kg，安全库存100kg，建议紧急采购',        'material',   NULL,  50.0,  100.0, false, false, NOW() - INTERVAL '1 day',   'system'),
  (gen_random_uuid(), 'FAC_MECH_001', 'yield_drop', 'warning', '轮毂加工良率下降', '当前良率92%，低于目标95%', 'quality', NULL, 92.0, 95.0, true, true, NOW() - INTERVAL '3 days', 'system'),
  (gen_random_uuid(), 'F01', 'order_delay',     'medium',   'WO-P-2026-003 交期风险',   '预计延期2天，建议协调加班或外协',                  'work_order', NULL,  NULL,  NULL,  false, false, NOW() - INTERVAL '6 hours', 'system');

-- ============================================================
-- 8. Hourly Output Snapshots（小时产出快照）
-- ============================================================
INSERT INTO hourly_output_snapshots (id, factory_id, snapshot_date, snapshot_hour, station_id, output_qty, good_qty, defect_qty, target_qty)
SELECT
  gen_random_uuid(),
  'F01',
  d::date,
  h,
  s.station_code,
  CASE WHEN h BETWEEN 8 AND 17 THEN 25 + (random()*10)::int ELSE 10 + (random()*5)::int END,
  CASE WHEN h BETWEEN 8 AND 17 THEN 23 + (random()*8)::int  ELSE 9  + (random()*4)::int END,
  CASE WHEN h BETWEEN 8 AND 17 THEN 2  + (random()*3)::int  ELSE 1  + (random()*2)::int END,
  28
FROM generate_series(CURRENT_DATE - 6, CURRENT_DATE, '1 day') d
CROSS JOIN generate_series(8, 17, 1) h
CROSS JOIN (SELECT station_code FROM stations WHERE factory_id = 'F01' LIMIT 3) s
ON CONFLICT DO NOTHING;

-- ============================================================
-- 9. OEE Daily（OEE 日统计）
-- ============================================================
INSERT INTO oee_daily (id, factory_id, equipment_id, snapshot_date, planned_production_minutes, actual_run_minutes, downtime_minutes, availability, performance, quality, oee, planned_output, actual_output, good_output, breakdown_minutes, setup_minutes, idle_minutes)
SELECT
  gen_random_uuid(),
  'F01',
  e.equipment_code,
  d::date,
  480.0,
  480.0 - (random()*60)::int::float,
  (random()*30)::int::float,
  0.85 + random()*0.12,
  0.80 + random()*0.15,
  0.90 + random()*0.08,
  (0.85 + random()*0.12) * (0.80 + random()*0.15) * (0.90 + random()*0.08),
  500,
  420 + (random()*80)::int,
  400 + (random()*60)::int,
  (random()*15)::int::float,
  (random()*20)::int::float,
  (random()*10)::int::float
FROM generate_series(CURRENT_DATE - 13, CURRENT_DATE, '1 day') d
CROSS JOIN (SELECT equipment_code FROM equipment WHERE factory_id = 'F01') e
ON CONFLICT DO NOTHING;

COMMIT;

-- 验证
SELECT 'products' as tbl, count(*) FROM products
UNION ALL SELECT 'warehouses', count(*) FROM warehouses
UNION ALL SELECT 'locations', count(*) FROM locations
UNION ALL SELECT 'production_lines', count(*) FROM production_lines
UNION ALL SELECT 'shifts', count(*) FROM shifts
UNION ALL SELECT 'process_routes', count(*) FROM process_routes
UNION ALL SELECT 'process_operations', count(*) FROM process_operations
UNION ALL SELECT 'production_alerts', count(*) FROM production_alerts
UNION ALL SELECT 'hourly_output_snapshots', count(*) FROM hourly_output_snapshots
UNION ALL SELECT 'oee_daily', count(*) FROM oee_daily
ORDER BY tbl;
