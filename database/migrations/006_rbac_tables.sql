-- ============================================================================
-- EngHub MES System - Database Migration 006
-- Role & Permission System (RBAC)
-- Date: 2026-07-21
-- Description: 新增角色、权限、用户角色关联表 + 用户表扩展字段
-- ============================================================================

-- 1. 权限表 (permissions)
CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    module VARCHAR(50) NOT NULL,
    action VARCHAR(30) NOT NULL,
    module_name VARCHAR(50),
    action_name VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_perm_module_action ON permissions(module, action);
CREATE INDEX IF NOT EXISTS idx_perm_module ON permissions(module);
CREATE INDEX IF NOT EXISTS idx_perm_action ON permissions(action);

-- 2. 角色表 (roles)
CREATE TABLE IF NOT EXISTS roles (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    role_code VARCHAR(50) NOT NULL UNIQUE,
    role_name VARCHAR(100) NOT NULL,
    position VARCHAR(30) NOT NULL,
    department VARCHAR(50) DEFAULT 'all',
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,
    level INTEGER DEFAULT 999,
    permissions JSONB DEFAULT '[]'::jsonb,
    data_scope JSONB DEFAULT '{"type":"own"}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_role_position_dept ON roles(position, department);
CREATE INDEX IF NOT EXISTS idx_role_is_system ON roles(is_system);

-- 3. 用户-角色关联表 (user_roles)
CREATE TABLE IF NOT EXISTS user_roles (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT TRUE,
    assigned_by VARCHAR(50),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_role_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_role_role ON user_roles(role_id);

-- 4. 角色-权限关联表 (role_permissions)
CREATE TABLE IF NOT EXISTS role_permissions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id VARCHAR(36) NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_role_perm_role ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_role_perm_perm ON role_permissions(permission_id);

-- 5. 扩展 users 表：添加 role_id 外键
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id UUID REFERENCES roles(id);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);

-- 6. 初始化默认权限
INSERT INTO permissions (id, module, action, module_name, action_name, description)
VALUES
    ('00000000-0000-0000-0000-000000000001', 'work_order', 'view', '工单管理', '查看', '查看工单信息'),
    ('00000000-0000-0000-0000-000000000002', 'work_order', 'create', '工单管理', '创建', '创建新工单'),
    ('00000000-0000-0000-0000-000000000003', 'work_order', 'edit', '工单管理', '编辑', '编辑工单'),
    ('00000000-0000-0000-0000-000000000004', 'work_order', 'delete', '工单管理', '删除', '删除工单'),
    ('00000000-0000-0000-0000-000000000005', 'work_order', 'approve', '工单管理', '审批', '审批工单'),
    ('00000000-0000-0000-0000-000000000006', 'work_order', 'release', '工单管理', '下达', '下达工单'),
    ('00000000-0000-0000-0000-000000000007', 'work_order', 'start', '工单管理', '开工', '启动工单'),
    ('00000000-0000-0000-0000-000000000008', 'work_order', 'complete', '工单管理', '完工', '完成工单'),
    ('00000000-0000-0000-0000-000000000009', 'work_order', 'cancel', '工单管理', '取消', '取消工单'),
    ('00000000-0000-0000-0000-000000000010', 'work_order', 'confirm_report', '工单管理', '确认报工', '确认生产报工'),
    ('00000000-0000-0000-0000-000000000011', 'work_order', 'modify_report', '工单管理', '修改报工', '修改生产报工'),
    ('00000000-0000-0000-0000-000000000012', 'work_order', 'export', '工单管理', '导出', '导出工单数据'),
    ('00000000-0000-0000-0000-000000000013', 'work_order', 'manage', '工单管理', '管理', '管理工单基础数据'),
    ('00000000-0000-0000-0000-000000000014', 'production_report', 'view', '生产报工', '查看', '查看生产报工'),
    ('00000000-0000-0000-0000-000000000015', 'production_report', 'create', '生产报工', '创建', '创建生产报工'),
    ('00000000-0000-0000-0000-000000000016', 'production_report', 'edit', '生产报工', '编辑', '编辑生产报工'),
    ('00000000-0000-0000-0000-000000000017', 'production_report', 'delete', '生产报工', '删除', '删除生产报工'),
    ('00000000-0000-0000-0000-000000000018', 'station', 'view', '工位管理', '查看', '查看工位信息'),
    ('00000000-0000-0000-0000-000000000019', 'station', 'create', '工位管理', '创建', '创建立位'),
    ('00000000-0000-0000-0000-000000000020', 'station', 'edit', '工位管理', '编辑', '编辑工位'),
    ('00000000-0000-0000-0000-000000000021', 'station', 'delete', '工位管理', '删除', '删除工位'),
    ('00000000-0000-0000-0000-000000000022', 'station', 'manage', '工位管理', '管理', '管理工位基础数据'),
    ('00000000-0000-0000-0000-000000000023', 'routing', 'view', '工艺路线', '查看', '查看工艺路线'),
    ('00000000-0000-0000-0000-000000000024', 'routing', 'create', '工艺路线', '创建', '创建工艺路线'),
    ('00000000-0000-0000-0000-000000000025', 'routing', 'edit', '工艺路线', '编辑', '编辑工艺路线'),
    ('00000000-0000-0000-0000-000000000026', 'routing', 'delete', '工艺路线', '删除', '删除工艺路线'),
    ('00000000-0000-0000-0000-000000000027', 'routing', 'manage', '工艺路线', '管理', '管理工艺路线基础数据'),
    ('00000000-0000-0000-0000-000000000028', 'equipment', 'view', '设备管理', '查看', '查看设备信息'),
    ('00000000-0000-0000-0000-000000000029', 'equipment', 'create', '设备管理', '创建', '创建设备'),
    ('00000000-0000-0000-0000-000000000030', 'equipment', 'edit', '设备管理', '编辑', '编辑设备'),
    ('00000000-0000-0000-0000-000000000031', 'equipment', 'delete', '设备管理', '删除', '删除设备'),
    ('00000000-0000-0000-0000-000000000032', 'equipment', 'manage', '设备管理', '管理', '管理设备基础数据'),
    ('00000000-0000-0000-0000-000000000033', 'wms', 'view', '仓储管理', '查看', '查看仓储信息'),
    ('00000000-0000-0000-0000-000000000034', 'wms', 'create', '仓储管理', '创建', '创建仓储记录'),
    ('00000000-0000-0000-0000-000000000035', 'wms', 'edit', '仓储管理', '编辑', '编辑仓储记录'),
    ('00000000-0000-0000-0000-000000000036', 'wms', 'delete', '仓储管理', '删除', '删除仓储记录'),
    ('00000000-0000-0000-0000-000000000037', 'wms', 'approve', '仓储管理', '审批', '审批仓储操作'),
    ('00000000-0000-0000-0000-000000000038', 'inventory', 'view', '库存管理', '查看', '查看库存'),
    ('00000000-0000-0000-0000-000000000039', 'inventory', 'create', '库存管理', '创建', '创建库存记录'),
    ('00000000-0000-0000-0000-000000000040', 'inventory', 'edit', '库存管理', '编辑', '编辑库存'),
    ('00000000-0000-0000-0000-000000000041', 'inventory', 'delete', '库存管理', '删除', '删除库存'),
    ('00000000-0000-0000-0000-000000000042', 'inbound', 'view', '入库管理', '查看', '查看入库单'),
    ('00000000-0000-0000-0000-000000000043', 'inbound', 'create', '入库管理', '创建', '创建入库单'),
    ('00000000-0000-0000-0000-000000000044', 'inbound', 'edit', '入库管理', '编辑', '编辑入库单'),
    ('00000000-0000-0000-0000-000000000045', 'inbound', 'approve', '入库管理', '审批', '审批入库单'),
    ('00000000-0000-0000-0000-000000000046', 'outbound', 'view', '出库管理', '查看', '查看出库单'),
    ('00000000-0000-0000-0000-000000000047', 'outbound', 'create', '出库管理', '创建', '创建出库单'),
    ('00000000-0000-0000-0000-000000000048', 'outbound', 'edit', '出库管理', '编辑', '编辑出库单'),
    ('00000000-0000-0000-0000-000000000049', 'outbound', 'approve', '出库管理', '审批', '审批出库单'),
    ('00000000-0000-0000-0000-000000000050', 'qms', 'view', '质量管理', '查看', '查看质量记录'),
    ('00000000-0000-0000-0000-000000000051', 'qms', 'create', '质量管理', '创建', '创建质量记录'),
    ('00000000-0000-0000-0000-000000000052', 'qms', 'edit', '质量管理', '编辑', '编辑质量记录'),
    ('00000000-0000-0000-0000-000000000053', 'qms', 'delete', '质量管理', '删除', '删除质量记录'),
    ('00000000-0000-0000-0000-000000000054', 'qms', 'approve', '质量管理', '审批', '审批质量记录'),
    ('00000000-0000-0000-0000-000000000055', 'defect', 'view', '不良品管理', '查看', '查看不良品'),
    ('00000000-0000-0000-0000-000000000056', 'defect', 'create', '不良品管理', '创建', '创建不良品单'),
    ('00000000-0000-0000-0000-000000000057', 'defect', 'edit', '不良品管理', '编辑', '编辑不良品单'),
    ('00000000-0000-0000-0000-000000000058', 'defect', 'delete', '不良品管理', '删除', '删除不良品单'),
    ('00000000-0000-0000-0000-000000000059', 'defect', 'approve', '不良品管理', '审批', '审批不良品处理'),
    ('00000000-0000-0000-0000-000000000060', 'inspection', 'view', '检验管理', '查看', '查看检验单'),
    ('00000000-0000-0000-0000-000000000061', 'inspection', 'create', '检验管理', '创建', '创建检验单'),
    ('00000000-0000-0000-0000-000000000062', 'inspection', 'edit', '检验管理', '编辑', '编辑检验单'),
    ('00000000-0000-0000-0000-000000000063', 'inspection', 'approve', '检验管理', '审批', '审批检验结果'),
    ('00000000-0000-0000-0000-000000000064', 'pp', 'view', '生产计划', '查看', '查看生产计划'),
    ('00000000-0000-0000-0000-000000000065', 'pp', 'create', '生产计划', '创建', '创建生产计划'),
    ('00000000-0000-0000-0000-000000000066', 'pp', 'edit', '生产计划', '编辑', '编辑生产计划'),
    ('00000000-0000-0000-0000-000000000067', 'pp', 'approve', '生产计划', '审批', '审批生产计划'),
    ('00000000-0000-0000-0000-000000000068', 'pp', 'release', '生产计划', '下达', '下达生产计划'),
    ('00000000-0000-0000-0000-000000000069', 'cost', 'view', '成本核算', '查看', '查看成本数据'),
    ('00000000-0000-0000-0000-000000000070', 'cost', 'export', '成本核算', '导出', '导出成本数据'),
    ('00000000-0000-0000-0000-000000000071', 'hr', 'view', '人员管理', '查看', '查看人员信息'),
    ('00000000-0000-0000-0000-000000000072', 'hr', 'create', '人员管理', '创建', '创建人员记录'),
    ('00000000-0000-0000-0000-000000000073', 'hr', 'edit', '人员管理', '编辑', '编辑人员记录'),
    ('00000000-0000-0000-0000-000000000074', 'hr', 'delete', '人员管理', '删除', '删除人员记录'),
    ('00000000-0000-0000-0000-000000000075', 'hr', 'manage', '人员管理', '管理', '管理HR基础数据'),
    ('00000000-0000-0000-0000-000000000076', 'skill_matrix', 'view', '技能矩阵', '查看', '查看技能矩阵'),
    ('00000000-0000-0000-0000-000000000077', 'skill_matrix', 'create', '技能矩阵', '创建', '创建技能记录'),
    ('00000000-0000-0000-0000-000000000078', 'skill_matrix', 'edit', '技能矩阵', '编辑', '编辑技能记录'),
    ('00000000-0000-0000-0000-000000000079', 'skill_matrix', 'delete', '技能矩阵', '删除', '删除技能记录'),
    ('00000000-0000-0000-0000-000000000080', 'training', 'view', '培训记录', '查看', '查看培训记录'),
    ('00000000-0000-0000-0000-000000000081', 'training', 'create', '培训记录', '创建', '创建培训记录'),
    ('00000000-0000-0000-0000-000000000082', 'training', 'edit', '培训记录', '编辑', '编辑培训记录'),
    ('00000000-0000-0000-0000-000000000083', 'training', 'delete', '培训记录', '删除', '删除培训记录'),
    ('00000000-0000-0000-0000-000000000084', 'training', 'manage', '培训记录', '管理', '管理培训基础数据'),
    ('00000000-0000-0000-0000-000000000085', 'simulation', 'view', '仿真引擎', '查看', '查看仿真结果'),
    ('00000000-0000-0000-0000-000000000086', 'simulation', 'export', '仿真引擎', '导出', '导出仿真数据'),
    ('00000000-0000-0000-0000-000000000087', 'tms', 'view', '任务管理', '查看', '查看任务'),
    ('00000000-0000-0000-0000-000000000088', 'tms', 'approve', '任务管理', '审批', '审批任务'),
    ('00000000-0000-0000-0000-000000000089', 'ai', 'view', 'AI助手', '查看', '使用AI助手');

-- 7. 初始化系统角色（admin）
INSERT INTO roles (id, role_code, role_name, position, department, description, is_system, level, permissions, data_scope)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'admin',
    '系统管理员',
    'factory_manager',
    'all',
    '超级管理员，拥有系统全部权限',
    true,
    100,
    '["__all__"]'::jsonb,
    '{"type":"all"}'::jsonb
);

-- 8. 初始化业务角色
INSERT INTO roles (id, role_code, role_name, position, department, description, is_system, level, permissions, data_scope)
VALUES
    -- 厂长
    ('00000000-0000-0000-0000-000000000101', 'factory_manager', '厂长', 'factory_manager', 'all',
     '工厂最高管理者，拥有全厂所有模块的完全权限', false, 100,
     '[{"module":"__all__","actions":["view","create","edit","delete","approve","release","start","complete","cancel","confirm_report","modify_report","export","manage"]}]'::jsonb,
     '{"type":"all"}'::jsonb),

    -- 生产经理
    ('00000000-0000-0000-0000-000000000102', 'production_manager', '生产经理', 'manager', 'production',
     '生产部最高负责人，管理全部生产相关模块', false, 200,
     '[{"module":"work_order","actions":["view","create","edit","delete","release","start","complete","cancel","export"]},{"module":"production_report","actions":["view","create","confirm_report","modify_report","export"]},{"module":"station","actions":["view","manage"]},{"module":"routing","actions":["view","manage"]},{"module":"equipment","actions":["view","manage"]},{"module":"pp","actions":["view","create","edit","approve","release","export"]},{"module":"cost","actions":["view","export"]},{"module":"simulation","actions":["view","export"]},{"module":"tms","actions":["view","approve"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 品质经理
    ('00000000-0000-0000-0000-000000000103', 'quality_manager', '品质经理', 'manager', 'quality',
     '品质部最高负责人', false, 200,
     '[{"module":"qms","actions":["view","create","edit","delete","approve","export"]},{"module":"defect","actions":["view","create","edit","delete","approve","export"]},{"module":"inspection","actions":["view","create","edit","approve","export"]},{"module":"work_order","actions":["view","export"]},{"module":"production_report","actions":["view","export"]},{"module":"simulation","actions":["view","export"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 工程经理
    ('00000000-0000-0000-0000-000000000104', 'engineering_manager', '工程经理', 'manager', 'engineering',
     '工程部最高负责人（工艺/设备/PE/IE）', false, 200,
     '[{"module":"routing","actions":["view","create","edit","delete","manage","export"]},{"module":"equipment","actions":["view","create","edit","delete","manage","export"]},{"module":"station","actions":["view","create","edit","delete","manage","export"]},{"module":"work_order","actions":["view","export"]},{"module":"pp","actions":["view","create","edit","export"]},{"module":"simulation","actions":["view","export"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 仓储经理
    ('00000000-0000-0000-0000-000000000105', 'warehouse_manager', '仓储经理', 'manager', 'warehouse',
     '仓储部最高负责人', false, 200,
     '[{"module":"wms","actions":["view","create","edit","delete","approve","export"]},{"module":"inventory","actions":["view","create","edit","delete","export"]},{"module":"inbound","actions":["view","create","edit","approve","export"]},{"module":"outbound","actions":["view","create","edit","approve","export"]},{"module":"work_order","actions":["view","export"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 人事经理
    ('00000000-0000-0000-0000-000000000106', 'hr_manager', '人事经理', 'manager', 'hr',
     '人事部最高负责人', false, 200,
     '[{"module":"hr","actions":["view","create","edit","delete","manage","export"]},{"module":"skill_matrix","actions":["view","create","edit","delete","manage","export"]},{"module":"training","actions":["view","create","edit","delete","manage","export"]},{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 生产处长
    ('00000000-0000-0000-0000-000000000107', 'production_director', '生产处长', 'director', 'production',
     '生产处最高负责人，管理多个生产课', false, 300,
     '[{"module":"work_order","actions":["view","create","edit","delete","release","start","complete","cancel","export"]},{"module":"production_report","actions":["view","create","confirm_report","modify_report","export"]},{"module":"station","actions":["view","manage"]},{"module":"routing","actions":["view","manage"]},{"module":"equipment","actions":["view","manage"]},{"module":"pp","actions":["view","create","edit","approve","release","export"]},{"module":"cost","actions":["view","export"]},{"module":"simulation","actions":["view","export"]},{"module":"tms","actions":["view","approve"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"factory"}'::jsonb),

    -- 生产课长
    ('00000000-0000-0000-0000-000000000108', 'production_section_chief', '生产课长', 'section_chief', 'production',
     '生产课长，管理本课产线和班组', false, 400,
     '[{"module":"work_order","actions":["view","create","edit","release","start","complete","cancel","export"]},{"module":"production_report","actions":["view","create","confirm_report","modify_report","export"]},{"module":"station","actions":["view","manage"]},{"module":"routing","actions":["view"]},{"module":"equipment","actions":["view"]},{"module":"pp","actions":["view"]},{"module":"tms","actions":["view","approve"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 品质课长
    ('00000000-0000-0000-0000-000000000109', 'quality_section_chief', '品质课长', 'section_chief', 'quality',
     '品质课长，管理检验和不良品处理', false, 400,
     '[{"module":"qms","actions":["view","create","edit","delete","approve","export"]},{"module":"defect","actions":["view","create","edit","delete","approve","export"]},{"module":"inspection","actions":["view","create","edit","approve","export"]},{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 工程课长
    ('00000000-0000-0000-0000-000000000110', 'engineering_section_chief', '工程课长', 'section_chief', 'engineering',
     '工程课长，管理工艺路线和设备', false, 400,
     '[{"module":"routing","actions":["view","create","edit","delete","manage","export"]},{"module":"equipment","actions":["view","create","edit","delete","manage","export"]},{"module":"station","actions":["view","manage"]},{"module":"work_order","actions":["view"]},{"module":"pp","actions":["view","create","edit"]},{"module":"simulation","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 仓储课长
    ('00000000-0000-0000-0000-000000000111', 'warehouse_section_chief', '仓储课长', 'section_chief', 'warehouse',
     '仓储课长，管理入库出库和库存', false, 400,
     '[{"module":"wms","actions":["view","create","edit","delete","approve","export"]},{"module":"inventory","actions":["view","create","edit","delete","export"]},{"module":"inbound","actions":["view","create","edit","approve","export"]},{"module":"outbound","actions":["view","create","edit","approve","export"]},{"module":"work_order","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 生产组长
    ('00000000-0000-0000-0000-000000000112', 'production_team_leader', '生产组长', 'team_leader', 'production',
     '生产组长，管理特定班组的生产活动', false, 500,
     '[{"module":"work_order","actions":["view","start","complete","export"]},{"module":"production_report","actions":["view","create","confirm_report","modify_report","export"]},{"module":"station","actions":["view"]},{"module":"equipment","actions":["view"]},{"module":"tms","actions":["view","approve"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 品质组长
    ('00000000-0000-0000-0000-000000000113', 'quality_team_leader', '品质组长', 'team_leader', 'quality',
     '品质组长，执行检验管理和不良品判定', false, 500,
     '[{"module":"qms","actions":["view","create","edit","approve"]},{"module":"defect","actions":["view","create","edit","approve"]},{"module":"inspection","actions":["view","create","edit","approve"]},{"module":"work_order","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 线长
    ('00000000-0000-0000-0000-000000000114', 'line_leader', '线长', 'line_leader', 'production',
     '产线线长，管理单条产线的日常生产', false, 600,
     '[{"module":"work_order","actions":["view","start","complete"]},{"module":"production_report","actions":["view","create","confirm_report","modify_report"]},{"module":"station","actions":["view"]},{"module":"equipment","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"line"}'::jsonb),

    -- 工艺工程师
    ('00000000-0000-0000-0000-000000000115', 'process_engineer', '工艺工程师', 'engineer', 'engineering',
     '工艺工程师，维护工艺路线和参数', false, 700,
     '[{"module":"routing","actions":["view","create","edit","delete","manage"]},{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view"]},{"module":"station","actions":["view"]},{"module":"simulation","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 设备工程师
    ('00000000-0000-0000-0000-000000000116', 'equipment_engineer', '设备工程师', 'engineer', 'engineering',
     '设备工程师，管理设备维护和状态', false, 700,
     '[{"module":"equipment","actions":["view","create","edit","delete","manage"]},{"module":"station","actions":["view","manage"]},{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 质量工程师
    ('00000000-0000-0000-0000-000000000117', 'quality_engineer', '质量工程师', 'engineer', 'quality',
     '质量工程师，执行检验和分析', false, 700,
     '[{"module":"qms","actions":["view","create","edit","approve"]},{"module":"defect","actions":["view","create","edit","approve"]},{"module":"inspection","actions":["view","create","edit","approve"]},{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- PE工程师
    ('00000000-0000-0000-0000-000000000118', 'pe_engineer', 'PE工程师', 'engineer', 'engineering',
     '生产工程师，协助生产计划和产能分析', false, 700,
     '[{"module":"pp","actions":["view","create","edit","export"]},{"module":"work_order","actions":["view","create","edit"]},{"module":"production_report","actions":["view","export"]},{"module":"station","actions":["view"]},{"module":"equipment","actions":["view"]},{"module":"simulation","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- IE工程师
    ('00000000-0000-0000-0000-000000000119', 'ie_engineer', 'IE工程师', 'engineer', 'engineering',
     '工业工程师，产能分析和效率改善', false, 700,
     '[{"module":"pp","actions":["view","export"]},{"module":"work_order","actions":["view","export"]},{"module":"production_report","actions":["view","export"]},{"module":"station","actions":["view","manage"]},{"module":"simulation","actions":["view","export"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 生产专员
    ('00000000-0000-0000-0000-000000000120', 'production_specialist', '生产专员', 'specialist', 'production',
     '生产专员，处理生产行政事务', false, 800,
     '[{"module":"work_order","actions":["view","create","edit","export"]},{"module":"production_report","actions":["view","create","export"]},{"module":"pp","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 仓储专员
    ('00000000-0000-0000-0000-000000000121', 'warehouse_specialist', '仓储专员', 'specialist', 'warehouse',
     '仓储专员，处理出入库事务', false, 800,
     '[{"module":"wms","actions":["view","create","edit","approve"]},{"module":"inventory","actions":["view","create","edit","export"]},{"module":"inbound","actions":["view","create","edit","approve"]},{"module":"outbound","actions":["view","create","edit","approve"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 品质专员
    ('00000000-0000-0000-0000-000000000122', 'quality_specialist', '品质专员', 'specialist', 'quality',
     '品质专员，检验记录和数据分析', false, 800,
     '[{"module":"qms","actions":["view","create","edit"]},{"module":"defect","actions":["view","create","edit"]},{"module":"inspection","actions":["view","create","edit"]},{"module":"work_order","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 人事专员
    ('00000000-0000-0000-0000-000000000123', 'hr_specialist', '人事专员', 'specialist', 'hr',
     '人事专员，员工技能和培训管理', false, 800,
     '[{"module":"hr","actions":["view","create","edit","delete","manage"]},{"module":"skill_matrix","actions":["view","create","edit","delete","manage"]},{"module":"training","actions":["view","create","edit","delete","manage"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"department"}'::jsonb),

    -- 操作员
    ('00000000-0000-0000-0000-000000000124', 'operator', '操作员', 'operator', 'production',
     '一线操作员，仅能报工和查看自己的工单', false, 900,
     '[{"module":"work_order","actions":["view"]},{"module":"production_report","actions":["view","create"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"own"}'::jsonb),

    -- 检验员
    ('00000000-0000-0000-0000-000000000125', 'inspector', '检验员', 'operator', 'quality',
     '质检员，执行检验操作', false, 900,
     '[{"module":"qms","actions":["view","create"]},{"module":"inspection","actions":["view","create","edit"]},{"module":"defect","actions":["view","create"]},{"module":"work_order","actions":["view"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"own"}'::jsonb),

    -- 仓管员
    ('00000000-0000-0000-0000-000000000126', 'warehouse_operator', '仓管员', 'operator', 'warehouse',
     '仓库操作员，执行出入库操作', false, 900,
     '[{"module":"wms","actions":["view","create","edit"]},{"module":"inventory","actions":["view","create","edit"]},{"module":"inbound","actions":["view","create","edit"]},{"module":"outbound","actions":["view","create","edit"]},{"module":"ai","actions":["view"]}]'::jsonb,
     '{"type":"own"}'::jsonb);

-- 9. 更新 users 表的 role 字段注释
COMMENT ON COLUMN users.role IS '角色编码：admin, factory_manager, production_manager, quality_manager, engineering_manager, warehouse_manager, hr_manager, production_director, production_section_chief, quality_section_chief, engineering_section_chief, warehouse_section_chief, production_team_leader, quality_team_leader, line_leader, process_engineer, equipment_engineer, quality_engineer, pe_engineer, ie_engineer, production_specialist, warehouse_specialist, quality_specialist, hr_specialist, operator, inspector, warehouse_operator';
