-- =============================================================================
-- Migration: 053_supplier_material_junction.sql (Updated)
-- Description: Create supplier_materials junction table for precise material-supplier mapping
-- Table: supplier_materials - Maps materials to suppliers with pricing/timing data (Task 1)
-- Author: EngHub Audit Optimization (Plan C Enhancement)
-- Date: 2026-07-28
-- =============================================================================

CREATE TABLE IF NOT EXISTS supplier_materials (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_id VARCHAR(36) NOT NULL,                      -- FK to suppliers.id
    material_code VARCHAR(50) NOT NULL,                   -- BOM item material code (e.g., MAT-RES-10K)
    is_active BOOLEAN DEFAULT TRUE,                       -- Whether this mapping is active
    is_primary BOOLEAN DEFAULT FALSE,                     -- Is this the primary preferred supplier?
    unit_cost NUMERIC(15, 2) NOT NULL,                    -- Unit purchase cost in currency
    min_order_qty INTEGER DEFAULT 1,                      -- Minimum order quantity
    lead_time_days INTEGER DEFAULT 7,                     -- Days from PO placement to delivery
    quality_rating FLOAT DEFAULT 5.0,                     -- Quality rating (1-5 scale)
    description VARCHAR(200),                             -- Optional remarks/comments
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Foreign key constraint (PostgreSQL syntax)
ALTER TABLE supplier_materials 
ADD CONSTRAINT fk_supplier_material_supplier 
FOREIGN KEY (supplier_id) REFERENCES suppliers(id) 
ON DELETE CASCADE;

-- Create indexes for efficient queries
CREATE UNIQUE INDEX IF NOT EXISTS uniq_supplier_material ON supplier_materials(supplier_id, material_code);
CREATE INDEX IF NOT EXISTS idx_supplier_material ON supplier_materials(supplier_id, material_code);
CREATE INDEX IF NOT EXISTS idx_material_active ON supplier_materials(material_code, is_active);
CREATE INDEX IF NOT EXISTS idx_is_primary ON supplier_materials(is_primary);

-- Seed sample supplier-material mappings based on existing sample suppliers
-- This assumes suppliers table already contains data from migration 049
INSERT INTO supplier_materials (id, supplier_id, material_code, is_primary, unit_cost, min_order_qty, lead_time_days, quality_rating, description, created_by) VALUES
    -- Resistor supplier mappings
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-RES-001'), 'RES-10K-0603', TRUE, 0.0015, 1000, 5, 4.8, 'Primary resistor supplier', 'system'),
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-RES-001'), 'RES-1K-0603', FALSE, 0.0012, 2000, 5, 4.7, 'Alternate resistor option', 'system'),
    
    -- Capacitor supplier mappings
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-CAP-001'), 'CAP-10UF-0603', TRUE, 0.0022, 800, 6, 4.6, 'Main capacitor vendor', 'system'),
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-RES-001'), 'CAP-10UF-0603', FALSE, 0.0025, 500, 7, 4.5, 'Capacitor backup source', 'system'),
    
    -- Chip/MCU supplier mappings
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-CHIPS-001'), 'IC-MCU-ARMv8', TRUE, 2.30, 50, 12, 4.6, 'Primary MCU supplier', 'system'),
    (gen_random_uuid(), (SELECT id FROM suppliers WHERE supplier_code = 'SUP-CHIPS-001'), 'IC-SPARKFUN', FALSE, 5.50, 20, 18, 4.3, 'Development board component', 'system')
ON CONFLICT (supplier_id, material_code) DO NOTHING;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss will occur.
-- =============================================================================
/*
DROP TABLE IF EXISTS supplier_materials CASCADE;

ALTER TABLE supplier_materials DROP CONSTRAINT IF EXISTS fk_supplier_material_supplier;

DROP INDEX IF EXISTS idx_supplier_material;
DROP INDEX IF EXISTS idx_material_active;
DROP INDEX IF EXISTS idx_is_primary;
*/
