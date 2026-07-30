-- =============================================================================
-- Migration: 054_inventory_safety_stock.sql
-- Description: Add safety_stock column to inventory table for reorder point calculation
-- Table: inventory - Extended with Task 2 safety stock threshold support
-- Author: EngHub Audit Optimization (Task 2: Safety Stock Configuration)
-- Date: 2026-07-28
-- =============================================================================

ALTER TABLE inventory 
ADD COLUMN IF NOT EXISTS safety_stock INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_inventory_safety ON inventory(safety_stock);

-- Sample data: set reasonable default safety stock levels for different material types
-- This is an example; actual values should be determined by business requirements
UPDATE inventory 
SET safety_stock = CASE 
    WHEN material_code LIKE 'IC-%' THEN 10     -- IC chips: higher buffer
    WHEN material_code LIKE 'RES-%' THEN 50    -- Resistors: medium buffer
    WHEN material_code LIKE 'CAP-%' THEN 30    -- Capacitors: medium buffer
    ELSE 5                                    -- Default: low buffer
END
WHERE safety_stock IS NULL OR safety_stock = 0;

-- =============================================================================
-- Downgrade script (if needed)
-- ALTER TABLE inventory DROP COLUMN IF EXISTS safety_stock;
-- DROP INDEX IF EXISTS idx_inventory_safety;
-- =============================================================================
