-- =============================================================================
-- Migration: 045_production_report_fields_extension.sql
-- Description: Add missing business fields to production_reports for quality traceability
-- Added: batch_code, tool_id, operator_skill_level, qc_gate_passed, material_batch_code
-- Author: EngHub Audit Optimization
-- Date: 2026-07-28
-- =============================================================================

-- Add batch_code for raw material batch tracing (production traceability chain)
ALTER TABLE production_reports 
ADD COLUMN IF NOT EXISTS batch_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS tool_id VARCHAR(36),
ADD COLUMN IF NOT EXISTS operator_skill_level VARCHAR(20),
ADD COLUMN IF NOT EXISTS qc_gate_passed BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS material_batch_code VARCHAR(50);

-- Create indexes for better query performance on new traceability fields
CREATE INDEX IF NOT EXISTS idx_pr_batch_code ON production_reports(batch_code);
CREATE INDEX IF NOT EXISTS idx_pr_tool_id ON production_reports(tool_id);
CREATE INDEX IF NOT EXISTS idx_pr_operator_skill ON production_reports(operator_skill_level);
CREATE INDEX IF NOT EXISTS idx_pr_qc_gate ON production_reports(qc_gate_passed, factory_id);

-- Add column descriptions/comments (PostgreSQL specific)
COMMENT ON COLUMN production_reports.batch_code IS 'Raw material batch code for quality traceability; links to incoming quality inspection';
COMMENT ON COLUMN production_reports.tool_id IS 'Tool/fixture ID used in this operation; enables tool wear analysis and replacement scheduling';
COMMENT ON COLUMN production_reports.operator_skill_level IS 'Operator skill level (e.g., "Junior", "Senior", "Certified"); correlates with yield rate and defect analysis';
COMMENT ON COLUMN production_reports.qc_gate_passed IS 'QC gate passed flag; critical control point verification before reporting completion';
COMMENT ON COLUMN production_reports.material_batch_code IS 'Material batch code from BOM consumption; distinct from product batch for multi-batch production runs';

-- Seed data migration: For existing records, set reasonable defaults
UPDATE production_reports
SET 
    batch_code = NULL,
    tool_id = NULL,
    operator_skill_level = 'Unknown',
    qc_gate_passed = TRUE,
    material_batch_code = NULL
WHERE batch_code IS NULL;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
/*
ALTER TABLE production_reports 
DROP COLUMN IF EXISTS batch_code,
DROP COLUMN IF EXISTS tool_id,
DROP COLUMN IF EXISTS operator_skill_level,
DROP COLUMN IF EXISTS qc_gate_passed,
DROP COLUMN IF EXISTS material_batch_code;

DROP INDEX IF EXISTS idx_pr_batch_code;
DROP INDEX IF EXISTS idx_pr_tool_id;
DROP INDEX IF EXISTS idx_pr_operator_skill;
DROP INDEX IF EXISTS idx_pr_qc_gate;
*/
