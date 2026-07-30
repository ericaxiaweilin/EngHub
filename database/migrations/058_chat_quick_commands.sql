-- =============================================================================
-- Migration: 058_chat_quick_commands.sql
-- Description: Chatbot 快速命令表（支持 CRUD + 智能体自动归类）
-- Table: chat_quick_commands - 用户/工厂级快捷指令，新增时自动归类到对应智能体
-- Date: 2026-07-30
-- =============================================================================

CREATE TABLE IF NOT EXISTS chat_quick_commands (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(64),                      -- 所属工厂（NULL = 全局预置）
    created_by VARCHAR(64),                      -- 创建人 username（NULL = 系统预置）
    command_text VARCHAR(500) NOT NULL,          -- 命令语句（点击后直接发送给 chatbot）
    agent_key VARCHAR(64),                       -- 归类的智能体 key（NULL = 通用/自动调度）
    agent_name VARCHAR(64),                      -- 归类的智能体名称（冗余展示用）
    classify_source VARCHAR(16) DEFAULT 'auto',  -- 归类来源: auto(自动) / manual(手动指定)
    is_preset BOOLEAN DEFAULT FALSE,             -- 是否系统预置（预置不可删除）
    sort_order INTEGER DEFAULT 100,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quick_cmd_factory ON chat_quick_commands(factory_id, sort_order);

COMMENT ON TABLE chat_quick_commands IS 'Chatbot 快速命令（预设语句 + 用户自定义，自动归类智能体）';

-- 系统预置命令（与前端原硬编码 QUICK_COMMANDS 对齐，并补充智能体调度类命令）
INSERT INTO chat_quick_commands (id, factory_id, command_text, agent_key, agent_name, classify_source, is_preset, sort_order)
VALUES
    (gen_random_uuid(), NULL, '今天生产情况怎么样？', NULL, NULL, 'manual', TRUE, 10),
    (gen_random_uuid(), NULL, '查询在制工单', 'dispatch_agent', '派工智能体', 'manual', TRUE, 20),
    (gen_random_uuid(), NULL, '查询库存水平', 'warehouse_agent', '仓储智能体', 'manual', TRUE, 30),
    (gen_random_uuid(), NULL, '最近有哪些不良品？', 'quality_agent', '质量智能体', 'manual', TRUE, 40),
    (gen_random_uuid(), NULL, '设备运行状态如何？', 'equipment_agent', '设备智能体', 'manual', TRUE, 50),
    (gen_random_uuid(), NULL, '跑一次高温加班合规仿真', NULL, NULL, 'manual', TRUE, 60),
    (gen_random_uuid(), NULL, '最近的仿真审计记录', NULL, NULL, 'manual', TRUE, 70)
ON CONFLICT DO NOTHING;
