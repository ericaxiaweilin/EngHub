-- ============================================================================
-- EngHub MES System - Database Migration 039
-- Industrial Engineering (IE) Module
-- Date: 2026-07-27
-- Description: 新增标准工时管理、时间研究、产线平衡分析、工序价值分析表
-- ============================================================================

-- ============================================================
-- 1. 标准工时表 (standard_operation_times)
-- 用于存储每个工序的标准作业时间，包括基础时间和宽放率
-- ============================================================

CREATE TABLE IF NOT EXISTS standard_operation_times (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    routing_step VARCHAR(20),
    operation_name VARCHAR(100) NOT NULL,
    station_id VARCHAR(50),
    work_center VARCHAR(20),
    standard_time_min FLOAT NOT NULL,              -- 标准工时（分钟）
    unit_time_type VARCHAR(20) DEFAULT 'per_piece',  -- per_piece / per_batch / setup
    setup_time_min FLOAT DEFAULT 0.0,              -- Setup time（分钟）
    batch_size INTEGER DEFAULT 1,                  -- 批量大小
    rating_factor FLOAT DEFAULT 1.0,               -- 评定系数（正常速度为1.0）
    allowance_rate FLOAT DEFAULT 0.15,             -- 宽放率（默认15%）
    effective_standard_time FLOAT NOT NULL,        -- 有效标准时间（已含宽放）
    version VARCHAR(10) DEFAULT 'v1',              -- 版本号
    is_active BOOLEAN DEFAULT TRUE,                -- 是否生效
    validity_start TIMESTAMP NOT NULL,             -- 生效开始时间
    validity_end TIMESTAMP,                        -- 失效结束时间
    created_by VARCHAR(50),
    updated_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraint on factory + product + step + version
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_sot_factory_product_step 
ON standard_operation_times (factory_id, product_id, routing_step, version);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sot_factory_station ON standard_operation_times (factory_id, station_id);
CREATE INDEX IF NOT EXISTS idx_sot_validity ON standard_operation_times (validity_start, is_active);


-- ============================================================
-- 2. 时间研究记录表 (time_study_records)
-- 存储实际观测的时间研究数据，用于计算标准工时
-- ============================================================

CREATE TABLE IF NOT EXISTS time_study_records (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    station_id VARCHAR(50) NOT NULL,
    operation_name VARCHAR(100) NOT NULL,
    operator_id VARCHAR(50) NOT NULL,            -- 观测操作员
    observer_id VARCHAR(50) NOT NULL,            -- 时间研究员
    observation_date TIMESTAMP NOT NULL,         -- 观测日期和时间
    observed_cycles JSON DEFAULT '[]'::json,     -- 多个循环观测时间数组 [minute]
    cycle_count INTEGER DEFAULT 1,               -- 观测循环次数
    average_time FLOAT NOT NULL,                 -- 平均观测时间
    rating_factor FLOAT DEFAULT 1.0,             -- 评定系数
    normal_time FLOAT NOT NULL,                  -- 正常时间 = 平均时间 × 评定系数
    allowed_time FLOAT NOT NULL,                 -- 允许时间 = 正常时间 × (1 + 宽放率)
    allowance_rate FLOAT DEFAULT 0.15,           -- 宽放率
    method VARCHAR(20) DEFAULT 'stopwatch',      -- stopwatch / video / electronic
    status VARCHAR(20) DEFAULT 'pending',        -- pending / approved / review
    created_by VARCHAR(50),
    approved_by VARCHAR(50),                     -- 批准人
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ts_factory_operator ON time_study_records (factory_id, operator_id);
CREATE INDEX IF NOT EXISTS idx_ts_observation ON time_study_records (observation_date);


-- ============================================================
-- 3. 产线平衡分析表 (line_balance_analyses)
-- 存储生产线平衡分析结果，用于识别瓶颈和改善建议
-- ============================================================

CREATE TABLE IF NOT EXISTS line_balance_analyses (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    line_id VARCHAR(50) NOT NULL,               -- 产线ID
    analysis_date TIMESTAMP NOT NULL,            -- 分析日期
    takt_time_min FLOAT NOT NULL,                -- 客户需求节拍时间（分钟/件）
    cycle_time_max FLOAT NOT NULL,               -- 最大工序耗时（瓶颈工序）
    cycle_time_avg FLOAT NOT NULL,               -- 平均工序耗时
    balance_rate FLOAT NOT NULL,                 -- 平衡率（%） = 总有效时间 / (工位数 × 最长工时)
    idle_time_total FLOAT NOT NULL,              -- 总闲置时间
    workstation_count INTEGER DEFAULT 0,         -- 工位数
    is_balanced BOOLEAN DEFAULT FALSE,           -- 是否平衡（平衡率 > 90%）
    station_details JSON DEFAULT '[]'::json,     -- [{"station_id", "cycle_time", "idle_time", "balance_pct"}]
    bottleneck_station VARCHAR(50),              -- 瓶颈工位
    bottleneck_time FLOAT,                       -- 瓶颈工序耗时
    recommendations JSON DEFAULT '[]'::json,     -- 改善建议列表
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_lb_factory_line ON line_balance_analyses (factory_id, line_id);
CREATE INDEX IF NOT EXISTS idx_lb_product ON line_balance_analyses (product_id, analysis_date);


-- ============================================================
-- 4. 工序价值分析表 (process_analyses)
-- 存储工序的 VA/NVA 时间分解数据，支持精益改善分析
-- ============================================================

CREATE TABLE IF NOT EXISTS process_analyses (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    operation_code VARCHAR(20) NOT NULL,         -- 工序代码
    analysis_date TIMESTAMP NOT NULL,            -- 分析日期
    total_process_time_min FLOAT NOT NULL,       -- 总过程时间
    va_time_min FLOAT NOT NULL,                  -- 增值时间（Value Added）
    nva_time_min FLOAT NOT NULL,                 -- 非增值时间（Non-Value Added）
    wait_time_min FLOAT NOT NULL,                -- 等待时间
    move_time_min FLOAT NOT NULL,                -- 搬运时间
    inspect_time_min FLOAT NOT NULL,             -- 检验时间
    va_ratio FLOAT NOT NULL,                     -- 增值比率 = VA / Total Time
    lead_time FLOAT NOT NULL,                    -- 交付周期时间
    efficiency_score FLOAT NOT NULL,             -- 效率评分（0-100）
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraint on factory + product + operation + date
CREATE UNIQUE INDEX IF NOT EXISTS unique_pa_factory_product_op 
ON process_analyses (factory_id, product_id, operation_code, analysis_date);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_pa_factory ON process_analyses (factory_id, analysis_date);


-- ============================================================
-- 5. 初始化 IE 模块相关权限 (Permissions)
-- ============================================================

-- 如果权限表不存在，先插入 IE 模块的基本权限
INSERT INTO PERMISSIONS (module, action, module_name, action_name, description)
VALUES 
    ('ie_standard_time', 'view', '标准工时管理', '查看', '查看标准工时记录'),
    ('ie_standard_time', 'create', '标准工时管理', '创建', '创建新标准工时'),
    ('ie_standard_time', 'update', '标准工时管理', '修改', '修改标准工时记录'),
    ('ie_standard_time', 'delete', '标准工时管理', '删除', '删除标准工时记录'),
    
    ('ie_time_study', 'view', '时间研究', '查看', '查看时间研究记录'),
    ('ie_time_study', 'create', '时间研究', '创建', '新建时间研究观测'),
    ('ie_time_study', 'update', '时间研究', '修改', '更新时间研究记录'),
    ('ie_time_study', 'approve', '时间研究', '批准', '批准时间研究数据以生成标准工时'),
    
    ('ie_line_balance', 'view', '产线平衡分析', '查看', '查看产线平衡分析报告'),
    ('ie_line_balance', 'analyze', '产线平衡分析', '执行分析', '执行产线平衡计算'),
    ('ie_line_balance', 'report', '产线平衡分析', '导出报告', '导出平衡分析报告'),
    
    ('ie_process_analysis', 'view', '工序价值分析', '查看', '查看工序价值流分析')
ON CONFLICT (module, action) DO NOTHING;

-- ============================================================
-- 6. 将 IE 角色关联到已有的 ie_engineer 角色
-- ============================================================

-- 获取 ie_engineer 的角色 ID
WITH ie_role AS (
    SELECT id FROM roles WHERE role_code = 'ie_engineer' LIMIT 1
)
INSERT INTO role_permissions (role_id, permission_id)
SELECT ir.id, p.id
FROM ie_role ir
JOIN permissions p ON p.module IN ('ie_standard_time', 'ie_time_study', 'ie_line_balance', 'ie_process_analysis')
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions rp WHERE rp.role_id = ir.id AND rp.permission_id = p.id
)
ON CONFLICT DO NOTHING;

-- ============================================================
-- 迁移完成
-- ============================================================
COMMIT;
