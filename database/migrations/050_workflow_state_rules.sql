-- =============================================================================
-- Migration: 050_workflow_state_rules.sql
-- Description: Create workflow_state_rules table for configurable state transitions (D方案补全)
-- Table: workflow_state_rules - Stores allowed state-to-state transitions with factory isolation
-- Author: EngHub Audit Optimization (Plan D - State Machine Configuration)
-- Date: 2026-07-28
-- =============================================================================

CREATE TABLE IF NOT EXISTS workflow_state_rules (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,              -- Factory ID (ALL for global rules)
    current_state VARCHAR(20) NOT NULL,           -- Current state value (draft, released, in_progress...)
    allowed_next_state VARCHAR(20) NOT NULL,      -- Allowed next state value
    description VARCHAR(200),                     -- Rule description (optional)
    is_active BOOLEAN DEFAULT TRUE,               -- Whether this rule is active
    sort_order INTEGER DEFAULT 0,                 -- Sort order for UI display
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT ON UPDATE NOW()
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_factory_state ON workflow_state_rules(factory_id, current_state);
CREATE INDEX IF NOT EXISTS idx_allowed_next ON workflow_state_rules(factory_id, allowed_next_state);
CREATE UNIQUE INDEX IF EXISTS uniq_factory_curr_next 
    ON workflow_state_rules(factory_id, current_state, allowed_next_state);

-- Seed default state transition rules matching the original TRANSITIONS dictionary
-- These serve as the initial configuration before any customization via UI/API
INSERT INTO workflow_state_rules (id, factory_id, current_state, allowed_next_state, description, sort_order, is_active) VALUES
    -- Draft can go to pending or cancelled
    (gen_random_uuid(), 'ALL', 'draft', 'pending', 'Draft to pending release', 1, TRUE),
    (gen_random_uuid(), 'ALL', 'draft', 'cancelled', 'Draft cancellation', 2, TRUE),
    
    -- Pending can go to released or cancelled
    (gen_random_uuid(), 'ALL', 'pending', 'released', 'Pending to released', 3, TRUE),
    (gen_random_uuid(), 'ALL', 'pending', 'cancelled', 'Pending cancellation', 4, TRUE),
    
    -- Released can go to in_progress, on_hold, or cancelled
    (gen_random_uuid(), 'ALL', 'released', 'in_progress', 'Released to start production', 5, TRUE),
    (gen_random_uuid(), 'ALL', 'released', 'on_hold', 'Released to pause/on_hold', 6, TRUE),
    (gen_random_uuid(), 'ALL', 'released', 'cancelled', 'Released cancellation', 7, TRUE),
    
    -- In_progress can go to on_hold, pending_inbound, completed, or cancelled
    (gen_random_uuid(), 'ALL', 'in_progress', 'on_hold', 'In progress to pause', 8, TRUE),
    (gen_random_uuid(), 'ALL', 'in_progress', 'pending_inbound', 'In progress to prepare inbound', 9, TRUE),
    (gen_random_uuid(), 'ALL', 'in_progress', 'completed', 'In progress to completed', 10, TRUE),
    (gen_random_uuid(), 'ALL', 'in_progress', 'cancelled', 'In progress cancellation', 11, TRUE),
    
    -- On_hold can go to in_progress or cancelled
    (gen_random_uuid(), 'ALL', 'on_hold', 'in_progress', 'On hold to resume', 12, TRUE),
    (gen_random_uuid(), 'ALL', 'on_hold', 'cancelled', 'On hold cancellation', 13, TRUE),
    
    -- Pending_inbound can only go to completed
    (gen_random_uuid(), 'ALL', 'pending_inbound', 'completed', 'Pending inbound to completed', 14, TRUE),
    
    -- Terminal states have no outgoing transitions (empty arrays in original TRANSITIONS)
    -- completed, closed, and cancelled have no allowed_next_states by default
    
ON CONFLICT (factory_id, current_state, allowed_next_state) DO NOTHING;

-- Create a version record for workflow rules
INSERT INTO workflow_rule_versions (id, factory_id, version_number, description, effective_from, is_active, created_by)
VALUES (
    gen_random_uuid(),
    'ALL',
    1,
    'Initial state machine configuration base release',
    NOW(),
    TRUE,
    'system'
)
ON CONFLICT (factory_id, version_number) DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS workflow_state_rules CASCADE;
DROP TABLE IF EXISTS workflow_rule_versions CASCADE;

DROP INDEX IF EXISTS idx_factory_state;
DROP INDEX IF EXISTS idx_allowed_next;
DROP INDEX IF EXISTS uniq_factory_curr_next;
*/
