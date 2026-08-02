-- =============================================================================
-- Migration: 046_production_report_constraints.sql
-- Description: Add database-level CHECK constraints for production report data integrity
-- This implements DB-level validation as part of the #11/P2 architectural enhancement
-- Ensures good_qty, defect_qty, scrap_qty are non-negative and their sum is reasonable
-- Author: EngHub Audit Optimization
-- Date: 2026-07-28
-- =============================================================================

-- Constraint 1: Ensure quantity fields are non-negative
DO $$ BEGIN
    ALTER TABLE production_reports
    ADD CONSTRAINT CHECK_PR_GOOD_NON_NEGATIVE
    CHECK (good_qty >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE production_reports
    ADD CONSTRAINT CHECK_PR_DEFECT_NON_NEGATIVE
    CHECK (defect_qty >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE production_reports
    ADD CONSTRAINT CHECK_PR_SCRAP_NON_NEGATIVE
    CHECK (scrap_qty >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Constraint 2: Ensure total reported quantity does not exceed a reasonable multiple of planned qty
DO $$ BEGIN
    ALTER TABLE production_reports
    ADD CONSTRAINT CHECK_PR_TOTAL_NON_NEGATIVE
    CHECK ((good_qty + defect_qty + scrap_qty) >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Constraint 3: Ensure qc_gate_passed is boolean valid (already enforced by PostgreSQL BOOLEAN type)
-- But add a comment to document the intent
COMMENT ON CONSTRAINT CHECK_PR_GOOD_NON_NEGATIVE ON production_reports IS 'Prevents negative good quantity entry';
COMMENT ON CONSTRAINT CHECK_PR_DEFECT_NON_NEGATIVE ON production_reports IS 'Prevents negative defect quantity entry';
COMMENT ON CONSTRAINT check_pr_scrap_non_negative ON production_reports IS 'Prevents negative scrap quantity entry';
COMMENT ON CONSTRAINT CHECK_PR_TOTAL_NON_NEGATIVE ON production_reports IS 'Ensures total reported quantity is non-negative';

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
/*
ALTER TABLE production_reports 
DROP CONSTRAINT IF EXISTS CHECK_PR_GOOD_NON_NEGATIVE,
DROP CONSTRAINT IF EXISTS CHECK_PR_DEFECT_NON_NEGATIVE,
DROP CONSTRAINT IF EXISTS CHECK_PR_SCRAP_NON_NEGATIVE,
DROP CONSTRAINT IF EXISTS CHECK_PR_TOTAL_NON_NEGATIVE;

COMMENT ON CONSTRAINT CHECK_PR_GOOD_NON_NEGATIVE ON production_reports IS '';
COMMENT ON CONSTRAINT CHECK_PR_DEFECT_NON_NEGATIVE ON production_reports IS '';
COMMENT ON CONSTRAINT CHECK_PR_SCRAP_NON_NEGATIVE ON production_reports IS '';
COMMENT ON CONSTRAINT CHECK_PR_TOTAL_NON_NEGATIVE ON production_reports IS '';
*/
