-- =============================================================================
-- Migration: 051_workflow_action_gates.sql
-- Description: Create workflow action gates table for permission configuration
-- Table: workflow_action_gates - Maps actions to required roles (D方案)
-- Author: EngHub Audit Optimization (Plan D - State Machine Config)
-- Date: 2026-07-28
-- =============================================================================

-- Create workflow_action_gates table with permission role mappings
CREATE TABLE IF NOT EXISTS workflow_action_gates (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,              -- 工厂ID，ALL表示全局规则
    action VARCHAR(20) NOT NULL,                  -- 动作名称（release, complete, close, pause, resume, cancel）
    required_role VARCHAR(20) NOT NULL,           -- 所需角色（factory_manager, production_manager, quality_manager, admin, operator, team_leader）
    description VARCHAR(200),                     -- 规则说明（可选）
    is_active BOOLEAN DEFAULT TRUE,               -- 是否启用
    sort_order INTEGER DEFAULT 0,                 -- UI排序顺序
    created_by VARCHAR(50),                       -- 创建者
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_factory_action ON workflow_action_gates(factory_id, action);
CREATE INDEX IF NOT EXISTS idx_factory_role ON workflow_action_gates(factory_id, required_role);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_factory_action_role 
    ON workflow_action_gates(factory_id, action, required_role);

-- Seed default action gates matching the original ACTION_ROLE_GATES constants
-- These serve as the initial configuration before any customizations via UI/API
INSERT INTO workflow_action_gates (id, factory_id, action, required_role, description, sort_order)
VALUES 
    -- release action: requires manager roles
    (gen_random_uuid(), 'ALL', 'release', 'factory_manager', 'Factory manager can release work orders', 1),
    (gen_random_uuid(), 'ALL', 'release', 'production_manager', 'Production manager can release work orders', 2),
    (gen_random_uuid(), 'ALL', 'release', 'admin', 'Admin can release work orders', 3),
    
    -- complete action: requires quality manager (with output check) + factory manager
    (gen_random_uuid(), 'ALL', 'complete', 'factory_manager', 'Factory manager can complete work orders', 4),
    (gen_random_uuid(), 'ALL', 'complete', 'quality_manager', 'Quality manager can complete work orders (requires actual output)', 5),
    (gen_random_uuid(), 'ALL', 'complete', 'admin', 'Admin can complete work orders', 6),
    
    -- close action: requires factory manager or admin
    (gen_random_uuid(), 'ALL', 'close', 'factory_manager', 'Factory manager can close completed work orders', 7),
    (gen_random_uuid(), 'ALL', 'close', 'admin', 'Admin can close work orders', 8),
    
    -- pause action: requires operator or team leader
    (gen_random_uuid(), 'ALL', 'pause', 'operator', 'Operators can pause work orders', 9),
    (gen_random_uuid(), 'ALL', 'pause', 'team_leader', 'Team leaders can pause work orders', 10),
    
    -- resume action: requires operator or team leader
    (gen_random_uuid(), 'ALL', 'resume', 'operator', 'Operators can resume paused work orders', 11),
    (gen_random_uuid(), 'ALL', 'resume', 'team_leader', 'Team leaders can resume work orders', 12),
    
    -- cancel action: requires operator or team leader (for draft/pending/in_progress states)
    (gen_random_uuid(), 'ALL', 'cancel', 'operator', 'Operators can cancel draft/pending work orders', 13),
    (gen_random_uuid(), 'ALL', 'cancel', 'team_leader', 'Team leaders can cancel work orders', 14)
ON CONFLICT (factory_id, action, required_role) DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss will occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS workflow_action_gates CASCADE;

DROP INDEX IF EXISTS idx_factory_action;
DROP INDEX IF EXISTS idx_factory_role;
DROP INDEX IF EXISTS uniq_factory_action_role;
*/
