-- =============================================================================
-- Migration: 050_workflow_rules_tables.sql
-- Description: Create workflow rule tables for state machine configuration
-- Tables: workflow_state_rules, workflow_action_gates, workflow_rule_versions
-- Author: EngHub Audit Optimization (Plan D - State Machine Config)
-- Date: 2026-07-28
-- =============================================================================

-- Create workflow_state_rules table for configurable state transitions
CREATE TABLE IF NOT EXISTS workflow_state_rules (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    current_state VARCHAR(20) NOT NULL,      -- e.g., draft, released, in_progress
    allowed_next_state VARCHAR(20) NOT NULL, -- e.g., pending_inbound, cancelled
    description VARCHAR(200),                -- Optional rule description
    is_active BOOLEAN DEFAULT TRUE,          -- Whether this rule is active
    sort_order INTEGER DEFAULT 0,            -- Sort order for UI display
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create primary indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_factory_current_state ON workflow_state_rules(factory_id, current_state);
CREATE INDEX IF NOT EXISTS idx_factory_allowed ON workflow_state_rules(factory_id, allowed_next_state);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_factory_curr_next 
    ON workflow_state_rules(factory_id, current_state, allowed_next_state);

-- Create workflow_action_gates table for permission role mappings
CREATE TABLE IF NOT EXISTS workflow_action_gates (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL,             -- e.g., release, complete, close, pause
    required_role VARCHAR(20) NOT NULL,      -- e.g., factory_manager, quality_manager
    description VARCHAR(200),                -- Optional rule description
    is_active BOOLEAN DEFAULT TRUE,          -- Whether this gate is active
    sort_order INTEGER DEFAULT 0,            -- Sort order
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for action-based lookups
CREATE INDEX IF NOT EXISTS idx_factory_action ON workflow_action_gates(factory_id, action);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_factory_action_role 
    ON workflow_action_gates(factory_id, action, required_role);

-- Create workflow_rule_versions table for version control and rollback
CREATE TABLE IF NOT EXISTS workflow_rule_versions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    version_number INTEGER NOT NULL,         -- Incrementing version number
    description VARCHAR(500),                -- Version description/change log
    effective_from TIMESTAMP WITH TIME ZONE NOT NULL, -- When this version becomes effective
    expires_at TIMESTAMP WITH TIME ZONE,     -- When this version expires (NULL = permanent)
    is_active BOOLEAN DEFAULT TRUE,          -- Currently active version
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for version queries
CREATE UNIQUE INDEX IF NOT EXISTS uniq_workflow_rule_versions_factory_version
    ON workflow_rule_versions(factory_id, version_number);
CREATE INDEX IF NOT EXISTS idx_factory_version ON workflow_rule_versions(factory_id, version_number);
CREATE INDEX IF NOT EXISTS idx_factory_active ON workflow_rule_versions(factory_id, is_active);

-- Seed default state transition rules matching the current hardcoded TRANSITIONS
-- These represent the initial state machine configuration before any customization
INSERT INTO workflow_state_rules (id, factory_id, current_state, allowed_next_state, description, sort_order)
VALUES 
    -- Draft can go to pending or cancelled
    (gen_random_uuid(), 'ALL', 'draft', 'pending', 'Draft to pending release', 1),
    (gen_random_uuid(), 'ALL', 'draft', 'cancelled', 'Draft cancellation', 2),
    
    -- Pending can go to released or cancelled
    (gen_random_uuid(), 'ALL', 'pending', 'released', 'Pending to released', 3),
    (gen_random_uuid(), 'ALL', 'pending', 'cancelled', 'Pending cancellation', 4),
    
    -- Released can go to in_progress, on_hold, or cancelled
    (gen_random_uuid(), 'ALL', 'released', 'in_progress', 'Released to start production', 5),
    (gen_random_uuid(), 'ALL', 'released', 'on_hold', 'Released to pause/on_hold', 6),
    (gen_random_uuid(), 'ALL', 'released', 'cancelled', 'Released cancellation', 7),
    
    -- In_progress can go to on_hold, pending_inbound, completed, or cancelled
    (gen_random_uuid(), 'ALL', 'in_progress', 'on_hold', 'In progress to pause', 8),
    (gen_random_uuid(), 'ALL', 'in_progress', 'pending_inbound', 'In progress to prepare inbound', 9),
    (gen_random_uuid(), 'ALL', 'in_progress', 'completed', 'In progress to completed', 10),
    (gen_random_uuid(), 'ALL', 'in_progress', 'cancelled', 'In progress cancellation', 11),
    
    -- On_hold can go to in_progress or cancelled
    (gen_random_uuid(), 'ALL', 'on_hold', 'in_progress', 'On hold to resume', 12),
    (gen_random_uuid(), 'ALL', 'on_hold', 'cancelled', 'On hold cancellation', 13),
    
    -- Pending_inbound can only go to completed
    (gen_random_uuid(), 'ALL', 'pending_inbound', 'completed', 'Pending inbound to completed', 14)
    
    -- Completed has no outgoing transitions (terminal state)
    -- Closed has no outgoing transitions (terminal state)
    -- Cancelled has no outgoing transitions (terminal state)
ON CONFLICT (factory_id, current_state, allowed_next_state) DO NOTHING;

-- Seed default action role gates matching current ACTION_ROLE_GATES
-- These define which roles are permitted for each action
INSERT INTO workflow_action_gates (id, factory_id, action, required_role, description, sort_order)
VALUES 
    (gen_random_uuid(), 'ALL', 'release', 'factory_manager', 'Factory manager can release work orders', 1),
    (gen_random_uuid(), 'ALL', 'release', 'production_manager', 'Production manager can release work orders', 2),
    (gen_random_uuid(), 'ALL', 'release', 'admin', 'Admin can release work orders', 3),
    
    (gen_random_uuid(), 'ALL', 'complete', 'factory_manager', 'Factory manager can complete work orders', 4),
    (gen_random_uuid(), 'ALL', 'complete', 'quality_manager', 'Quality manager can complete work orders (with actual output)', 5),
    (gen_random_uuid(), 'ALL', 'complete', 'admin', 'Admin can complete work orders', 6),
    
    (gen_random_uuid(), 'ALL', 'close', 'factory_manager', 'Factory manager can close completed work orders', 7),
    (gen_random_uuid(), 'ALL', 'close', 'admin', 'Admin can close work orders', 8),
    
    (gen_random_uuid(), 'ALL', 'pause', 'operator', 'Operators can pause work orders', 9),
    (gen_random_uuid(), 'ALL', 'pause', 'team_leader', 'Team leaders can pause work orders', 10),
    
    (gen_random_uuid(), 'ALL', 'resume', 'operator', 'Operators can resume paused work orders', 11),
    (gen_random_uuid(), 'ALL', 'resume', 'team_leader', 'Team leaders can resume work orders', 12),
    
    (gen_random_uuid(), 'ALL', 'cancel', 'operator', 'Operators can cancel draft/pending work orders', 13),
    (gen_random_uuid(), 'ALL', 'cancel', 'team_leader', 'Team leaders can cancel work orders', 14)
ON CONFLICT (factory_id, action, required_role) DO NOTHING;

-- Create an initial version record (version 1)
INSERT INTO workflow_rule_versions (id, factory_id, version_number, description, effective_from, expires_at, is_active, created_by)
VALUES 
    (gen_random_uuid(), 'ALL', 1, 'Initial state machine configuration - base release', NOW(), NULL, TRUE, 'system')
ON CONFLICT (factory_id, version_number) DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS workflow_rule_versions CASCADE;
DROP TABLE IF EXISTS workflow_action_gates CASCADE;
DROP TABLE IF EXISTS workflow_state_rules CASCADE;

DROP INDEX IF EXISTS idx_factory_current_state;
DROP INDEX IF EXISTS idx_factory_allowed;
DROP INDEX IF EXISTS uniq_factory_curr_next;
DROP INDEX IF EXISTS idx_factory_action;
DROP INDEX IF EXISTS uniq_factory_action_role;
DROP INDEX IF EXISTS idx_factory_version;
DROP INDEX IF EXISTS idx_factory_active;
*/
