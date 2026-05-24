-- EngHub MES 数据库初始化脚本
-- 用于 P0 阶段基础数据准备

-- 1. 创建超级管理员账号 (密码: Admin@123456)
INSERT INTO users (username, email, hashed_password, is_active, is_superuser, created_at)
VALUES (
    'admin', 
    'admin@enghub.com', 
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G.2fZ9F5U7M0iK', 
    true, 
    true, 
    NOW()
) ON CONFLICT (username) DO NOTHING;

-- 2. 创建基础角色
INSERT INTO roles (name, description, permissions, created_at)
VALUES 
    ('Super Admin', '系统超级管理员', '{"*": "*"}', NOW()),
    ('Production Manager', '生产经理', '{"work_order": ["read", "write", "delete"], "production_report": ["read", "write"], "plan": ["read", "write"]}', NOW()),
    ('Quality Inspector', '质量检验员', '{"inspection": ["read", "write"], "defect": ["read", "write"]}', NOW()),
    ('Warehouse Keeper', '仓库管理员', '{"inventory": ["read", "write"], "wms_inbound": ["read", "write"], "wms_outbound": ["read", "write"]}', NOW()),
    ('Operator', '操作工', '{"work_order": ["read"], "production_report": ["write"]}', NOW())
ON CONFLICT (name) DO NOTHING;

-- 3. 默认工厂日历 (2024 年)
INSERT INTO factory_calendars (year, month, day, is_working_day, shift_type, created_at)
SELECT 
    generate_series(2024, 2024) as year,
    generate_series(1, 12) as month,
    generate_series(1, 31) as day,
    CASE WHEN EXTRACT(DOW FROM DATE(generate_series(2024,1,1) + (generate_series(1,31)-1 || ' days')::interval)) NOT IN (0,6) THEN true ELSE false END,
    'day',
    NOW()
WHERE NOT EXISTS (SELECT 1 FROM factory_calendars WHERE year = 2024);

-- 4. 默认仓库配置
INSERT INTO warehouses (code, name, type, location, capacity, is_active, created_at)
VALUES 
    ('WH-RAW-001', '原材料仓', 'raw_material', 'A 区 1 栋', 10000, true, NOW()),
    ('WH-FG-001', '成品仓', 'finished_goods', 'B 区 2 栋', 5000, true, NOW()),
    ('WH-WIP-001', '在制品仓', 'wip', '车间 A 区', 2000, true, NOW())
ON CONFLICT (code) DO NOTHING;

-- 5. 默认库位
INSERT INTO storage_locations (warehouse_id, code, name, location_type, max_capacity, created_at)
SELECT w.id, 'LOC-' || w.code || '-001', '主存储区', 'bulk', w.capacity, NOW()
FROM warehouses w
WHERE NOT EXISTS (SELECT 1 FROM storage_locations sl WHERE sl.warehouse_id = w.id);

-- 6. 基础计量单位
INSERT INTO units_of_measure (code, name, category, conversion_factor, is_base_unit, created_at)
VALUES 
    ('PCS', '件', 'quantity', 1.0, true, NOW()),
    ('BOX', '箱', 'quantity', 12.0, false, NOW()),
    ('PALLET', '托盘', 'quantity', 48.0, false, NOW()),
    ('KG', '千克', 'weight', 1.0, true, NOW()),
    ('TON', '吨', 'weight', 1000.0, false, NOW()),
    ('M', '米', 'length', 1.0, true, NOW())
ON CONFLICT (code) DO NOTHING;

-- 7. 默认工作中心/工位
INSERT INTO workstations (code, name, workstation_type, capacity_per_hour, shift_count, is_active, created_at)
VALUES 
    ('WS-ASSY-001', '组装线 1 号', 'assembly', 100, 2, true, NOW()),
    ('WS-TEST-001', '测试站 1 号', 'testing', 150, 2, true, NOW()),
    ('WS-PACK-001', '包装线 1 号', 'packaging', 200, 2, true, NOW())
ON CONFLICT (code) DO NOTHING;

-- 8. 默认检验类型配置
INSERT INTO inspection_types (code, name, stage, sampling_plan, aql_level, is_active, created_at)
VALUES 
    ('IQC-GENERAL', '来料检验 - 通用', 'IQC', 'normal', 'II', true, NOW()),
    ('IPQC-FIRST', '首件检验', 'IPQC', '100%', null, true, NOW()),
    ('IPQC-PATROL', '巡检', 'IPQC', 'normal', 'II', true, NOW()),
    ('FQC-FINAL', '最终检验', 'FQC', 'normal', 'II', true, NOW()),
    ('OQC-SHIP', '出货检验', 'OQC', 'tightened', 'II', true, NOW())
ON CONFLICT (code) DO NOTHING;

-- 9. 默认不良代码分类
INSERT INTO defect_categories (code, name, severity, description, created_at)
VALUES 
    ('CRITICAL', '致命缺陷', 'critical', '影响产品安全或法规符合性', NOW()),
    ('MAJOR', '主要缺陷', 'major', '影响产品功能或性能', NOW()),
    ('MINOR', '次要缺陷', 'minor', '轻微外观问题，不影响功能', NOW())
ON CONFLICT (code) DO NOTHING;

-- 10. 初始库存 (示例数据)
-- INSERT INTO inventory_transactions (...) -- 根据实际业务需求添加

-- 11. 系统参数配置
INSERT INTO system_parameters (param_key, param_value, description, updated_at)
VALUES 
    ('DEFAULT_WAREHOUSE_ID', '1', '默认仓库 ID', NOW()),
    ('ENABLE_AUTO_MRP', 'true', '启用自动 MRP 计算', NOW()),
    ('MRP_RUN_TIME', '02:00', 'MRP 每日运行时间', NOW()),
    ('QUALITY_AQL_DEFAULT', 'II', '默认 AQL 检验水平', NOW()),
    ('COST_ACCOUNTING_ENABLED', 'true', '启用成本核算', NOW())
ON CONFLICT (param_key) DO UPDATE SET param_value = EXCLUDED.param_value;

-- 完成提示
SELECT '数据库初始化完成！' AS status;
