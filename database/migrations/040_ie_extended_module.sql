-- ============================================================================
-- EngHub MES System - Database Migration 040
-- Extended Industrial Engineering (IE) Module
-- Date: 2026-07-27
-- Description: 新增动作研究、方法研究、工站布局、看板系统、5S审计表
-- ============================================================================

-- ============================================================
-- 1. 动作研究表 (action_studies)
-- ============================================================

CREATE TABLE IF NOT EXISTS action_studies (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    operation_name VARCHAR(100) NOT NULL,
    station_id VARCHAR(50),
    operator_id VARCHAR(50) NOT NULL,
    study_date TIMESTAMP NOT NULL,
    method_type VARCHAR(20) DEFAULT 'mtm',
    recorded_by VARCHAR(50) NOT NULL,
    motions JSON DEFAULT '[]'::json,
    total_time_cycles FLOAT,
    analysis_result JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_factory_product_op ON action_studies (factory_id, product_id, operation_name);


-- ============================================================
-- 2. 方法研究表 (method_studies)
-- ============================================================

CREATE TABLE IF NOT EXISTS method_studies (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    original_operation VARCHAR(100) NOT NULL,
    version VARCHAR(10) DEFAULT 'v1',
    is_basement_method BOOLEAN DEFAULT FALSE,
    is_optimal_method BOOLEAN DEFAULT FALSE,
    description TEXT,
    action_sequence JSON DEFAULT '[]'::json,
    required_resources JSON DEFAULT '[]'::json,
    setup_time_min FLOAT DEFAULT 0.0,
    cycle_time_min FLOAT NOT NULL,
    total_standard_time_min FLOAT NOT NULL,
    validity_start TIMESTAMP NOT NULL,
    validity_end TIMESTAMP,
    created_by VARCHAR(50),
    approved_by VARCHAR(50),
    status VARCHAR(20) DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_method_factory_product_op_version 
ON method_studies (factory_id, product_id, original_operation, version);

CREATE INDEX IF NOT EXISTS idx_method_validity ON method_studies (validity_start, is_optimal_method);


-- ============================================================
-- 3. 工站布局表 (work_cell_layouts)
-- ============================================================

CREATE TABLE IF NOT EXISTS work_cell_layouts (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    work_cell_id VARCHAR(50) NOT NULL,
    product_family_id VARCHAR(50) NOT NULL,
    layout_diagram_url VARCHAR(200),
    material_flow_path JSON DEFAULT '[]'::json,
    operator_movement_path JSON DEFAULT '[]'::json,
    takt_time_alignment VARCHAR(20) DEFAULT 'aligned',
    storage_location_type VARCHAR(20) DEFAULT 'in_process',
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cell_product ON work_cell_layouts (work_cell_id, product_family_id);
CREATE INDEX IF NOT EXISTS idx_factory_cell ON work_cell_layouts (factory_id, work_cell_id);


-- ============================================================
-- 4. 看板系统表 (kanban_systems)
-- ============================================================

CREATE TABLE IF NOT EXISTS kanban_systems (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    kanban_id VARCHAR(50) NOT NULL UNIQUE,
    kanban_type VARCHAR(20) DEFAULT 'continuous',
    upstream_station VARCHAR(50),
    downstream_station VARCHAR(50),
    product_id VARCHAR(50) NOT NULL,
    part_number VARCHAR(50),
    max_card_count INTEGER DEFAULT 5,
    current_card_count INTEGER DEFAULT 0,
    safety_stock_level INTEGER DEFAULT 2,
    card_status VARCHAR(20) DEFAULT 'available',
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_upstream_downstream ON kanban_systems (upstream_station, downstream_station);
CREATE INDEX IF NOT EXISTS idx_product_kanban ON kanban_systems (product_id, kanban_type);


-- ============================================================
-- 5. 5S审计表 (five_s_audits)
-- ============================================================

CREATE TABLE IF NOT EXISTS five_s_audits (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    work_center_id VARCHAR(50) NOT NULL,
    audit_date TIMESTAMP NOT NULL,
    auditor_id VARCHAR(50) NOT NULL,
    seiri_score INTEGER DEFAULT 0,
    seiton_score INTEGER DEFAULT 0,
    seiso_score INTEGER DEFAULT 0,
    seiketsu_score INTEGER DEFAULT 0,
    shitsuke_score INTEGER DEFAULT 0,
    total_score INTEGER DEFAULT 0,
    score_percentage FLOAT DEFAULT 0.0,
    improvement_items JSON DEFAULT '[]'::json,
    next_audit_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_work_center_audit ON five_s_audits (work_center_id, audit_date);
CREATE INDEX IF NOT EXISTS idx_factory_date ON five_s_audits (factory_id, audit_date);


-- ============================================================
-- 6. 初始化 IE 扩展模块权限 (Permissions)
-- ============================================================

INSERT INTO permissions (module, action, module_name, action_name, description) VALUES
    ('ie_action_study', 'view', '动作研究', '查看', '查看动作研究记录'),
    ('ie_action_study', 'create', '动作研究', '创建', '新建动作研究'),
    ('ie_action_study', 'update', '动作研究', '修改', '修改动作研究记录'),
    
    ('ie_method_study', 'view', '方法研究', '查看', '查看方法研究记录'),
    ('ie_method_study', 'create', '方法研究', '创建', '新方法研究方案'),
    ('ie_method_study', 'approve', '方法研究', '批准', '批准最优方法'),
    ('ie_method_study', 'compare', '方法研究', '对比比较', '对比不同方法版本'),
    
    ('ie_work_cell', 'view', '工站布局', '查看', '查看工站布局信息'),
    ('ie_work_cell', 'update', '工站布局', '编辑', '编辑布局设计'),
    ('ie_work_cell', 'analyze', '工站布局', '分析布局', '进行布局效率分析'),
    
    ('ie_kanban', 'view', '看板管理', '查看', '查看看板状态'),
    ('ie_kanban', 'update', '看板管理', '更新卡片', '更新看板卡片数量'),
    ('ie_kanban', 'restock', '看板管理', '补货触发', '补货看板触发'),
    
    ('ie_five_s', 'view', '5S审计', '查看', '查看5S审计记录'),
    ('ie_five_s', 'create', '5S审计', '执行审计', '执行新5S检查'),
    ('ie_five_s', 'report', '5S审计', '生成报告', '生成5S改善报告')
ON CONFLICT (module, action) DO NOTHING;

-- ============================================================
-- 7. 将扩展权限关联到 ie_engineer 角色
-- ============================================================

WITH ie_role AS (
    SELECT id FROM roles WHERE role_code = 'ie_engineer' LIMIT 1
)
INSERT INTO role_permissions (role_id, permission_id)
SELECT ir.id, p.id
FROM ie_role ir
JOIN permissions p ON p.module IN (
    'ie_action_study', 'ie_method_study', 'ie_work_cell', 'ie_kanban', 'ie_five_s'
)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions rp WHERE rp.role_id = ir.id AND rp.permission_id = p.id
)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 迁移完成（扩展IE功能）
-- ============================================================================
COMMIT;
