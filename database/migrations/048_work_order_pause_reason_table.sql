-- =============================================================================
-- Migration: 048_work_order_pause_reason_table.sql
-- Description: Create work_order_pause_reasons table for structured stoppage reasons
-- Table: work_order_pause_reasons - Standardized codes for machine downtime analysis
-- Author: EngHub Audit Optimization (B Plan Implementation)
-- Date: 2026-07-28
-- =============================================================================

-- Create pause reason enumeration table with standard codes
CREATE TABLE IF NOT EXISTS work_order_pause_reasons (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    code VARCHAR(20) UNIQUE NOT NULL,           -- EQUIP/MATERIAL/QUALITY/OTHER
    description VARCHAR(100) NOT NULL,          -- 中文描述
    category VARCHAR(20) NOT NULL,              -- equipment/material/quality/other
    is_active BOOLEAN DEFAULT TRUE,             -- 是否可用
    sort_order INTEGER DEFAULT 0,               -- 排序顺序
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add indexes for efficient querying


-- Trigger to automatically update updated_at on row modification
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_work_order_pause_reasons_timestamp
BEFORE UPDATE ON work_order_pause_reasons
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE INDEX IF NOT EXISTS idx_factory_code ON work_order_pause_reasons(factory_id, code);
CREATE INDEX IF NOT EXISTS idx_code_active ON work_order_pause_reasons(code, is_active);
CREATE INDEX IF NOT EXISTS idx_category ON work_order_pause_reasons(category);

-- Insert standard pre-defined pause reason codes (one per factory, or factory-wide shared)
-- These represent the typical categories used in manufacturing plants
INSERT INTO work_order_pause_reasons (id, factory_id, code, description, category, is_active, sort_order, created_by)
VALUES 
    -- Equipment-related stops
    (gen_random_uuid(), 'ALL', 'EQUIP', '设备故障/维护', 'equipment', TRUE, 1, 'system'),
    (gen_random_uuid(), 'ALL', 'EQUIP_MAINT', '计划性保养', 'equipment', TRUE, 2, 'system'),
    
    -- Material-related stops
    (gen_random_uuid(), 'ALL', 'MATERIAL', '物料短缺/缺料', 'material', TRUE, 3, 'system'),
    (gen_random_uuid(), 'ALL', 'MAT_QUALITY', '来料品质异常', 'material', TRUE, 4, 'system'),
    
    -- Quality-related stops
    (gen_random_uuid(), 'ALL', 'QUALITY', '品质异常/返工等待', 'quality', TRUE, 5, 'system'),
    (gen_random_uuid(), 'ALL', 'QC_HOLD', '质量检验暂停', 'quality', TRUE, 6, 'system'),
    
    -- Other/general stops
    (gen_random_uuid(), 'ALL', 'OTHER', '其他原因（需备注）', 'other', TRUE, 7, 'system'),
    (gen_random_uuid(), 'ALL', 'TRAINING', '人员培训/换型', 'other', TRUE, 8, 'system'),
    (gen_random_uuid(), 'ALL', 'POWER', '停电/断电', 'other', TRUE, 9, 'system')
ON CONFLICT (factory_id, code) DO NOTHING;

-- For specific factories, you can create factory-specific overrides if needed
-- Example: FAC_ELEC_001 may have additional custom reasons

-- Add a column to work_orders to reference the pause reason
-- This will be done in a separate migration after this one exists
ALTER TABLE work_orders 
ADD COLUMN IF NOT EXISTS pause_reason_id VARCHAR(36) REFERENCES work_order_pause_reasons(id),
ADD COLUMN IF NOT EXISTS pause_start_time TIMESTAMP,
ADD COLUMN IF NOT EXISTS pause_end_time TIMESTAMP;

-- Create index on the new pause_reason_id column
CREATE INDEX IF NOT EXISTS idx_wo_pause_reason ON work_orders(pause_reason_id);

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
