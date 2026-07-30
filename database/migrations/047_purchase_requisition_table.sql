-- =============================================================================
-- Migration: 047_purchase_requisition_table.sql
-- Description: Create purchase requisitions table for MRP procurement workflow
-- Table: purchase_requisitions - Stores MRP-generated采购申请单，驱动采购流程
-- Author: EngHub Audit Optimization (MRP Implementation)
-- Date: 2026-07-28
-- =============================================================================

-- Create purchase_requisitions table with all necessary columns for MRP workflow
CREATE TABLE IF NOT EXISTS purchase_requisitions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_code VARCHAR(50) UNIQUE NOT NULL,  -- Format: PR-YYYYMMDD-XXX
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(100) NOT NULL,
    required_qty INTEGER NOT NULL,              -- Total demand from BOM expansion
    suggested_qty INTEGER NOT NULL,            -- Optimized order quantity (EOQ/MOQ adjusted)
    shortage_qty INTEGER NOT NULL,             -- Required - Available
    suggested_date TIMESTAMP NOT NULL,         -- Recommended purchasing date
    priority VARCHAR(20) DEFAULT 'NORMAL',     -- URGENT/HIGH/NORMAL/LOW
    status VARCHAR(20) DEFAULT 'PENDING',      -- PENDING/APPROVED/CANCELLED/ORDERED
    mrp_plan_id VARCHAR(36),                   -- Links back to the MRP plan that generated it
    estimated_cost NUMERIC(15, 2),             -- Total estimated cost = suggested_qty * unit_cost
    supplier_id VARCHAR(50),                   -- Recommended supplier ID
    lead_time_days INTEGER,                    -- Supplier lead time in days
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE purchase_requisitions
ADD COLUMN IF NOT EXISTS purchase_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS material_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS required_qty INTEGER,
ADD COLUMN IF NOT EXISTS suggested_qty INTEGER,
ADD COLUMN IF NOT EXISTS shortage_qty INTEGER,
ADD COLUMN IF NOT EXISTS suggested_date TIMESTAMP,
ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'NORMAL',
ADD COLUMN IF NOT EXISTS mrp_plan_id VARCHAR(36),
ADD COLUMN IF NOT EXISTS estimated_cost NUMERIC(15, 2),
ADD COLUMN IF NOT EXISTS supplier_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS lead_time_days INTEGER,
ADD COLUMN IF NOT EXISTS created_by VARCHAR(50),
ADD COLUMN IF NOT EXISTS pr_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mrp',
ADD COLUMN IF NOT EXISTS source_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS qty NUMERIC,
ADD COLUMN IF NOT EXISTS unit VARCHAR(20) DEFAULT 'PCS',
ADD COLUMN IF NOT EXISTS required_date DATE,
ADD COLUMN IF NOT EXISTS auto_approved BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS approved_by VARCHAR(50);

-- Add indexes for efficient querying and reporting
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_requisitions_purchase_code ON purchase_requisitions(purchase_code);
CREATE INDEX IF NOT EXISTS idx_pr_factory_material ON purchase_requisitions(factory_id, material_id);
CREATE INDEX IF NOT EXISTS idx_pr_status ON purchase_requisitions(status);
CREATE INDEX IF NOT EXISTS idx_pr_suggested_date ON purchase_requisitions(suggested_date);
CREATE INDEX IF NOT EXISTS idx_pr_factory_status ON purchase_requisitions(factory_id, status);

-- Add foreign key constraints (commented as referenced tables may not exist yet)
-- ALTER TABLE purchase_requisitions ADD CONSTRAINT fk_pr_factory FOREIGN KEY (factory_id) REFERENCES factories(id);
-- ALTER TABLE purchase_requisitions ADD CONSTRAINT pr_mrp_plan FOREIGN KEY (mrp_plan_id) REFERENCES mrp_plans(id);

-- Seed sample data (for testing/demo purposes)
INSERT INTO purchase_requisitions (
    id, pr_code, purchase_code, factory_id, source, source_id, material_id,
    material_code, material_name, qty, unit, required_date, required_qty,
    suggested_qty, shortage_qty, suggested_date, priority, status, auto_approved,
    mrp_plan_id, estimated_cost, supplier_id, lead_time_days, created_by
)
VALUES 
(gen_random_uuid(), 'PR-20260728-001', 'PR-20260728-001', 'FAC_MECH_001', 'mrp', 'MRP-PLAN-20260728-01', 'MAT-RES-10K', 'RES-10K-0603', '贴片电阻10K',
  5000, 'PCS', CURRENT_DATE + 7, 5000, 5000, 3000, NOW() + INTERVAL '7 days', 'HIGH', 'PENDING', FALSE, 'MRP-PLAN-20260728-01', 50.00, 'SUP-001', 7, 'system'),
(gen_random_uuid(), 'PR-20260728-002', 'PR-20260728-002', 'FAC_MECH_001', 'mrp', 'MRP-PLAN-20260728-01', 'MAT-CAP-100NF', 'CAP-100NF-0603', '贴片电容100NF',
  3000, 'PCS', CURRENT_DATE + 7, 3000, 3000, 2000, NOW() + INTERVAL '7 days', 'MEDIUM', 'PENDING', FALSE, 'MRP-PLAN-20260728-01', 60.00, 'SUP-002', 10, 'system')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss will occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS purchase_requisitions CASCADE;

DROP INDEX IF EXISTS idx_pr_factory_material;
DROP INDEX IF EXISTS idx_pr_status;
DROP INDEX IF EXISTS idx_pr_suggested_date;
DROP INDEX IF EXISTS idx_pr_factory_status;
*/
