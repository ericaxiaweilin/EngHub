-- =============================================================================
-- Migration: 052_workflow_action_gate_table.sql
-- Description: Create workflow_action_gates table for permission configuration
-- Table: workflow_action_gates - Maps actions to required roles (D方案)
-- Author: EngHub Audit Optimization (Plan D - State Machine Config)
-- Date: 2026-07-28
-- =============================================================================

CREATE TABLE IF NOT EXISTS workflow_action_gates (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL,
    required_role VARCHAR(20) NOT NULL,
    description VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_factory_action ON workflow_action_gates(factory_id, action);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_factory_action_role ON workflow_action_gates(factory_id, action, required_role);

-- Seed with default values matching original ACTION_ROLE_GATES
INSERT INTO workflow_action_gates (id, factory_id, action, required_role, description, sort_order) VALUES
    (gen_random_uuid(), 'ALL', 'release', 'factory_manager', 'Factory manager can release work orders', 1),
    (gen_random_uuid(), 'ALL', 'release', 'production_manager', 'Production manager can release work orders', 2),
    (gen_random_uuid(), 'ALL', 'release', 'admin', 'Admin can release work orders', 3),
    (gen_random_uuid(), 'ALL', 'complete', 'factory_manager', 'Factory manager can complete work orders', 4),
    (gen_random_uuid(), 'ALL', 'complete', 'quality_manager', 'Quality manager can complete work orders', 5),
    (gen_random_uuid(), 'ALL', 'complete', 'admin', 'Admin can complete work orders', 6),
    (gen_random_uuid(), 'ALL', 'close', 'factory_manager', 'Factory manager can close work orders', 7),
    (gen_random_uuid(), 'ALL', 'close', 'admin', 'Admin can close work orders', 8),
    (gen_random_uuid(), 'ALL', 'pause', 'operator', 'Operator can pause work orders', 9),
    (gen_random_uuid(), 'ALL', 'pause', 'team_leader', 'Team leader can pause work orders', 10),
    (gen_random_uuid(), 'ALL', 'resume', 'operator', 'Operator can resume work orders', 11),
    (gen_random_uuid(), 'ALL', 'resume', 'team_leader', 'Team leader can resume work orders', 12)
ON CONFLICT (factory_id, action, required_role) DO NOTHING;

-- =============================================================================
-- Downgrade script
-- DROP TABLE IF EXISTS workflow_action_gates CASCADE;
DROP INDEX IF EXISTS idx_factory_action;
DROP INDEX IF EXISTS uniq_factory_action_role;
-- =============================================================================
