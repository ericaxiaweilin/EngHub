-- ============================================================
-- 014: 统一码表（基础数据管理）
-- 将散落各处的硬编码枚举集中到数据库，支持系统设置页面自定义扩展
-- 幂等：IF NOT EXISTS + ON CONFLICT DO NOTHING
-- ============================================================

CREATE TABLE IF NOT EXISTS code_tables (
    id          VARCHAR(36) PRIMARY KEY,
    category    VARCHAR(50)  NOT NULL,
    code        VARCHAR(30)  NOT NULL,
    name        VARCHAR(100) NOT NULL,
    name_en     VARCHAR(100),
    description VARCHAR(255),
    keywords    JSONB,
    extra       JSONB,
    sort_order  INT DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    is_system   BOOLEAN DEFAULT FALSE,
    factory_id  VARCHAR(50),
    created_at  TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at  TIMESTAMP DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_code_table_category_code UNIQUE (category, code)
);

CREATE INDEX IF NOT EXISTS idx_code_table_category ON code_tables(category);

-- ============================================================
-- 种子数据：工单类型 (wo_type)
-- ============================================================
INSERT INTO code_tables (id, category, code, name, name_en, description, sort_order, is_system)
VALUES
    (gen_random_uuid()::text, 'wo_type', 'S', '标准量产', 'Standard Production', '常规批量生产工单', 1, TRUE),
    (gen_random_uuid()::text, 'wo_type', 'T', '试产', 'Trial Production', '新产品试产验证', 2, TRUE),
    (gen_random_uuid()::text, 'wo_type', 'R', '返工', 'Rework', '不良品返工处理', 3, TRUE),
    (gen_random_uuid()::text, 'wo_type', 'M', '模具', 'Mold/Trial Tooling', '模具制造/修模', 4, TRUE),
    (gen_random_uuid()::text, 'wo_type', 'E', '工程样品', 'Engineering Sample', '工程验证样品', 5, TRUE)
ON CONFLICT (category, code) DO NOTHING;

-- ============================================================
-- 种子数据：工序代码 (process_code) —— 行业通用英文缩写
-- ============================================================
INSERT INTO code_tables (id, category, code, name, name_en, keywords, sort_order, is_system)
VALUES
    (gen_random_uuid()::text, 'process_code', 'CUT',  '下料/备料', 'Cutting/Blanking',
     '["下料","备料","切割","cut","blank"]', 1, TRUE),
    (gen_random_uuid()::text, 'process_code', 'MACH', '机加', 'Machining',
     '["机加","机械加工","车削","铣削","铣","钻孔","cnc","mach","turn","mill","drill"]', 2, TRUE),
    (gen_random_uuid()::text, 'process_code', 'INJ',  '注塑', 'Injection Molding',
     '["注塑","注射","inj","mold","mould"]', 3, TRUE),
    (gen_random_uuid()::text, 'process_code', 'EDM',  '电火花', 'EDM (Electric Discharge Machining)',
     '["电火花","火花","edm"]', 4, TRUE),
    (gen_random_uuid()::text, 'process_code', 'WCUT', '线切割', 'Wire Cutting',
     '["线切割","线割","wire_cut","wire"]', 5, TRUE),
    (gen_random_uuid()::text, 'process_code', 'WELD', '焊接', 'Welding',
     '["焊接","回流焊","波峰焊","weld","reflow"]', 6, TRUE),
    (gen_random_uuid()::text, 'process_code', 'PAINT','涂装', 'Painting/Coating',
     '["涂装","喷涂","喷漆","paint","coat"]', 7, TRUE),
    (gen_random_uuid()::text, 'process_code', 'ASSY', '组立/装配', 'Assembly',
     '["组立","装配","组装","assy","assembl"]', 8, TRUE),
    (gen_random_uuid()::text, 'process_code', 'PKG',  '包装', 'Packaging',
     '["包装","打包","pack"]', 9, TRUE),
    (gen_random_uuid()::text, 'process_code', 'QC',   '检验', 'Quality Control',
     '["检验","检测","测试","aoi","qc","inspect","test"]', 10, TRUE),
    (gen_random_uuid()::text, 'process_code', 'SMT',  '贴片', 'Surface Mount Technology',
     '["贴片","锡膏","印刷","smt"]', 11, TRUE),
    (gen_random_uuid()::text, 'process_code', 'DIP',  '插件', 'DIP Insertion',
     '["插件","dip"]', 12, TRUE),
    (gen_random_uuid()::text, 'process_code', 'STMP', '冲压', 'Stamping',
     '["冲压","stamp","press"]', 13, TRUE),
    (gen_random_uuid()::text, 'process_code', 'CAST', '铸造', 'Casting',
     '["铸造","cast"]', 14, TRUE),
    (gen_random_uuid()::text, 'process_code', 'HT',   '热处理', 'Heat Treatment',
     '["热处理","heat"]', 15, TRUE),
    (gen_random_uuid()::text, 'process_code', 'FIN',  '表面处理', 'Finishing',
     '["表面处理","电镀","阳极","finish"]', 16, TRUE),
    (gen_random_uuid()::text, 'process_code', 'GRD',  '研磨', 'Grinding',
     '["研磨","磨削","grind"]', 17, TRUE),
    (gen_random_uuid()::text, 'process_code', 'SEW',  '针车/缝纫', 'Sewing',
     '["针车","缝纫","sew"]', 18, TRUE),
    (gen_random_uuid()::text, 'process_code', 'FORM', '成型', 'Forming/Lasting',
     '["成型","贴底","lasting","form"]', 19, TRUE),
    (gen_random_uuid()::text, 'process_code', 'GEN',  '通用工序', 'General',
     '[]', 99, TRUE)
ON CONFLICT (category, code) DO NOTHING;

-- ============================================================
-- 种子数据：工单优先级 (priority)
-- ============================================================
INSERT INTO code_tables (id, category, code, name, name_en, extra, sort_order, is_system)
VALUES
    (gen_random_uuid()::text, 'priority', 'low',    '低', 'Low',       '{"color":"default","dot":"#8c8c8c"}', 1, TRUE),
    (gen_random_uuid()::text, 'priority', 'medium', '普通', 'Medium',  '{"color":"blue","dot":"#1890ff"}',    2, TRUE),
    (gen_random_uuid()::text, 'priority', 'high',   '紧急', 'High',    '{"color":"orange","dot":"#fa8c16"}',  3, TRUE),
    (gen_random_uuid()::text, 'priority', 'urgent', '加急', 'Urgent',  '{"color":"red","dot":"#f5222d"}',     4, TRUE)
ON CONFLICT (category, code) DO NOTHING;

-- ============================================================
-- 种子数据：工单状态 (wo_status) —— 供前端/报表统一引用
-- ============================================================
INSERT INTO code_tables (id, category, code, name, name_en, extra, sort_order, is_system)
VALUES
    (gen_random_uuid()::text, 'wo_status', 'draft',           '草稿',   'Draft',          '{"color":"default"}',    1, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'pending',         '待下发', 'Pending Release','{"color":"processing"}', 2, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'released',        '已下达', 'Released',       '{"color":"blue"}',       3, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'in_progress',     '生产中', 'In Progress',    '{"color":"blue"}',       4, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'on_hold',         '暂停中', 'On Hold',        '{"color":"warning"}',    5, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'pending_inbound', '待入库', 'Pending Inbound','{"color":"cyan"}',       6, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'completed',       '已完成', 'Completed',      '{"color":"success"}',    7, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'closed',          '已关闭', 'Closed',         '{"color":"default"}',    8, TRUE),
    (gen_random_uuid()::text, 'wo_status', 'cancelled',       '已取消', 'Cancelled',      '{"color":"error"}',      9, TRUE)
ON CONFLICT (category, code) DO NOTHING;
