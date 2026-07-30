-- =============================================================================
-- Migration: 049_supplier_table.sql
-- Description: Create suppliers table for MRP procurement integration
-- Table: suppliers - Vendor master data with lead time, MOQ, EOQ parameters
-- Author: EngHub Audit Optimization (MRP C-Phase Implementation)
-- Date: 2026-07-28
-- =============================================================================

-- Create suppliers table with all necessary procurement-related fields
CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_code VARCHAR(50) UNIQUE NOT NULL,  -- 供应商编码，如 SUP-001
    supplier_name VARCHAR(200) NOT NULL,         -- 供应商名称
    contact_person VARCHAR(100),                 -- 联系人
    phone VARCHAR(50),                           -- 电话
    email VARCHAR(100),                          -- 邮箱
    address TEXT,                                -- 地址
    is_active BOOLEAN DEFAULT TRUE,              -- 是否启用
    lead_time_days INTEGER DEFAULT 7,            -- 平均采购提前期（天）
    moq_min INTEGER DEFAULT 1,                   -- 最小订货量
    eoq_suggested NUMERIC(15, 2),                -- 建议经济批量
    preferred_for VARCHAR(200),                  -- 擅长供应的材料类别
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE suppliers
ADD COLUMN IF NOT EXISTS address TEXT,
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS lead_time_days INTEGER DEFAULT 7,
ADD COLUMN IF NOT EXISTS moq_min INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS eoq_suggested NUMERIC(15, 2),
ADD COLUMN IF NOT EXISTS preferred_for VARCHAR(200);

-- Add indexes for efficient querying and reporting
CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_supplier_code ON suppliers(supplier_code);
CREATE INDEX IF NOT EXISTS idx_supplier_code ON suppliers(supplier_code);
CREATE INDEX IF NOT EXISTS idx_supplier_status ON suppliers(is_active);
CREATE INDEX IF NOT EXISTS idx_supplier_search ON UPPER(supplier_name);

-- Seed sample supplier data (for testing/demo purposes)
INSERT INTO suppliers (id, supplier_code, supplier_name, contact_person, phone, email, lead_time_days, moq_min, eoq_suggested, preferred_for, is_active)
VALUES 
    (gen_random_uuid(), 'SUP-RES-001', 'Resistor Components Inc.', 'John Smith', '+1-555-0101', 'john@resistors.com', 7, 1000, 5000.0, '贴片电阻、电容等被动元件', TRUE),
    (gen_random_uuid(), 'SUP-CAP-001', 'Capacitor Tech Corp.', 'Emily Chen', '+1-555-0102', 'emily@captech.com', 10, 500, 3000.0, '各类电容器', TRUE),
    (gen_random_uuid(), 'SUP-CHIPS-001', 'Microchip Solutions', 'Mike Johnson', '+1-555-0103', 'mike@microchips.com', 14, 100, 2000.0, 'IC芯片、微控制器', TRUE)
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss will occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS suppliers CASCADE;

DROP INDEX IF EXISTS idx_supplier_code;
DROP INDEX IF EXISTS idx_supplier_status;
DROP INDEX IF EXISTS idx_supplier_search;
*/
