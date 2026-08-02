-- 自动化等级配置（工厂可选择每条工作流的自动化程度）
-- Level 0: 纯手工（系统只记录）
-- Level 1: 辅助提醒（系统预警+建议，人决定+执行）
-- Level 2: 半自动（标准自动，异常人处理）
-- Level 3: 全自动（全部自动+异常自动升级）

CREATE TABLE IF NOT EXISTS automation_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    workflow_key VARCHAR(50) NOT NULL,       -- 工作流标识
    workflow_name VARCHAR(100) NOT NULL,     -- 中文名称
    automation_level INTEGER NOT NULL DEFAULT 1,  -- 0/1/2/3
    description TEXT,
    auto_rules JSONB DEFAULT '{}',           -- 该level下的具体规则
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, workflow_key)
);

-- 预置工作流配置（默认L1辅助提醒，让工厂逐步升级）
-- 工厂可以按自己管理成熟度选择level
COMMENT ON TABLE automation_config IS '自动化等级配置 - 工厂按成熟度选择每条工作流的自动化程度';
