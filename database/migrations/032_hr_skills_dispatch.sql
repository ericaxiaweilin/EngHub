-- ============================================================
-- 032 HR 员工档案细化 + 内部工序技能库 + 人力调配
--
-- 1. hr_employees 增加 身高(height_cm) / 体重(weight_kg)
-- 2. 预置分层内部工序技能库（写入 skills 表，幂等）
-- 3. 新建花名册员工技能关联表 hr_employee_skills
-- 4. 种子：按 station 给现有员工赋对应工序技能 + 回填身高体重
-- ============================================================

-- ── 1. hr_employees 增列 ──
ALTER TABLE hr_employees ADD COLUMN IF NOT EXISTS height_cm NUMERIC(5,1);
ALTER TABLE hr_employees ADD COLUMN IF NOT EXISTS weight_kg NUMERIC(5,1);

-- ── 2. skills 表幂等保护（ORM 已建则跳过）──
CREATE TABLE IF NOT EXISTS skills (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_skills_code ON skills(code);
CREATE INDEX IF NOT EXISTS ix_skills_category ON skills(category);

-- ── 2.1 预置内部工序技能库（分层：category → 子技能）──
INSERT INTO skills (code, name, category, description, is_active) VALUES
    -- 组立
    ('ZL-LS', '螺丝组装', '组立', '组立工序-螺丝锁付作业', TRUE),
    ('ZL-BZ', '包装',     '组立', '组立工序-包装作业',     TRUE),
    ('ZL-TS', '组装调试', '组立', '组立工序-组装与调试',   TRUE),
    -- 焊接
    ('HJ-DH', '点焊',     '焊接', '焊接工序-点焊作业',     TRUE),
    ('HJ-HH', '弧焊',     '焊接', '焊接工序-弧焊作业',     TRUE),
    ('HJ-XH', '锡焊',     '焊接', '焊接工序-锡焊作业',     TRUE),
    -- 检测
    ('JC-WG', '外观检测', '检测', '检测工序-外观检查',     TRUE),
    ('JC-CC', '尺寸检测', '检测', '检测工序-尺寸测量',     TRUE),
    ('JC-GN', '功能检测', '检测', '检测工序-功能测试',     TRUE),
    -- 注塑
    ('ZS-CX', '注塑成型', '注塑', '注塑工序-注塑成型',     TRUE),
    ('ZS-JS', '浸塑',     '注塑', '注塑工序-浸塑作业',     TRUE),
    -- 加工
    ('JG-JJ', '精加工',   '加工', '加工工序-精密加工',     TRUE),
    ('JG-GL', '滚轮加工', '加工', '加工工序-滚轮加工',     TRUE),
    -- 涂装
    ('TZ-PT', '喷涂',     '涂装', '涂装工序-喷涂作业',     TRUE),
    -- 包装
    ('BZ-NB', '内包装',   '包装', '包装工序-内包装作业',   TRUE),
    ('BZ-WB', '外包装',   '包装', '包装工序-外包装作业',   TRUE)
ON CONFLICT (code) DO NOTHING;

-- ── 3. 花名册员工技能关联表 ──
CREATE TABLE IF NOT EXISTS hr_employee_skills (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    hr_employee_id VARCHAR(36) NOT NULL REFERENCES hr_employees(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    level VARCHAR(10) NOT NULL DEFAULT 'L1',
    certified_date DATE,
    expiry_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(hr_employee_id, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_hr_emp_skill_emp ON hr_employee_skills(hr_employee_id);
CREATE INDEX IF NOT EXISTS idx_hr_emp_skill_skill ON hr_employee_skills(skill_id);

-- ── 4.1 种子：按 station 给现有员工赋对应工序技能（level 沿用 skill_level）──
WITH station_skill AS (
    SELECT * FROM (VALUES
        ('焊接',   'HJ-DH'),
        ('焊接',   'HJ-HH'),
        ('组立',   'ZL-LS'),
        ('组立',   'ZL-BZ'),
        ('注塑',   'ZS-CX'),
        ('浸塑',   'ZS-JS'),
        ('精加工', 'JG-JJ'),
        ('加工',   'JG-JJ'),
        ('滚轮',   'JG-GL'),
        ('涂装',   'TZ-PT')
    ) AS m(station, skill_code)
)
INSERT INTO hr_employee_skills (hr_employee_id, skill_id, level, certified_date)
SELECT e.id, s.id, e.skill_level, CURRENT_DATE - (random() * 730)::INT
FROM hr_employees e
JOIN station_skill ss ON ss.station = e.station
JOIN skills s ON s.code = ss.skill_code
ON CONFLICT (hr_employee_id, skill_id) DO NOTHING;

-- ── 4.2 回填身高体重（仅对缺失者，按性别给合理随机值）──
UPDATE hr_employees SET
    height_cm = CASE WHEN gender = '男'
                     THEN ROUND((165 + random() * 15)::NUMERIC, 1)
                     ELSE ROUND((155 + random() * 13)::NUMERIC, 1) END,
    weight_kg = CASE WHEN gender = '男'
                     THEN ROUND((55 + random() * 20)::NUMERIC, 1)
                     ELSE ROUND((45 + random() * 15)::NUMERIC, 1) END
WHERE height_cm IS NULL;
