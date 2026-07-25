-- CrewAI推理层 + 个人知识层 表结构

-- Crew决策记录（组织层，可审计）
CREATE TABLE IF NOT EXISTS crew_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    crew_key VARCHAR(50) NOT NULL,
    crew_name VARCHAR(100),
    context JSONB DEFAULT '{}',
    decision JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crew_dec_factory ON crew_decisions(factory_id, created_at);

-- 个人知识沉淀
CREATE TABLE IF NOT EXISTS personal_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    employee_id VARCHAR(50) NOT NULL,
    category VARCHAR(20) NOT NULL DEFAULT 'tip',  -- tip/lesson/expertise/decision/trick
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    tags JSONB DEFAULT '[]',
    source VARCHAR(30) DEFAULT 'manual',  -- manual/auto_extract/decision_log
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pk_employee ON personal_knowledge(factory_id, employee_id);
CREATE INDEX IF NOT EXISTS idx_pk_category ON personal_knowledge(category);

-- 个人决策历史
CREATE TABLE IF NOT EXISTS personal_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    employee_id VARCHAR(50) NOT NULL,
    decision_type VARCHAR(50) NOT NULL,  -- quality_judge/priority_call/material_sub/exception_handle
    situation TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT,
    outcome TEXT,  -- 后续补充结果
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pd_employee ON personal_decisions(factory_id, employee_id);
CREATE INDEX IF NOT EXISTS idx_pd_type ON personal_decisions(decision_type);

-- 员工表增加专长标签
ALTER TABLE hr_employees ADD COLUMN IF NOT EXISTS expertise_tags JSONB DEFAULT '[]';
