-- =============================================================================
-- Migration: 046_work_order_inventory_reservation_fields.sql
-- Description: Add inventory reservation fields to work_orders for MES-WMS integration
-- Added: reserved_warehouse, reserved_qty, reserved_at, release_id (for tracking reservation)
-- Author: EngHub Audit Optimization
-- Date: 2026-07-28
-- =============================================================================

-- Add reservation-related columns to work_orders table
ALTER TABLE work_orders 
ADD COLUMN IF NOT EXISTS reserved_warehouse VARCHAR(50),
ADD COLUMN IF NOT EXISTS reserved_qty INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS release_action_id VARCHAR(36);  -- 关联释放操作ID以便追溯

-- Create indexes for efficient querying on reservation status
CREATE INDEX IF NOT EXISTS idx_wo_reserved ON work_orders(reserved_warehouse, reserved_qty);
CREATE INDEX IF NOT EXISTS idx_wo_reservation_status ON work_orders(status, reserved_qty) 
    WHERE status IN ('released', 'in_progress', 'pending_inbound');

-- Add column descriptions
COMMENT ON COLUMN work_orders.reserved_warehouse IS 'Warehouse code where inventory was reserved for this work order';
COMMENT ON COLUMN work_orders.reserved_qty IS 'Quantity of inventory reserved from warehouse';
COMMENT ON COLUMN work_orders.reserved_at IS 'Timestamp when inventory reservation was made';
COMMENT ON COLUMN work_orders.release_action_id IS 'External reservation action ID from WMS system';

-- For existing records, initialize reservation fields appropriately
UPDATE work_orders 
SET 
    reserved_warehouse = NULL,
    reserved_qty = 0,
    reserved_at = NULL,
    release_action_id = NULL
WHERE reserved_warehouse IS NULL;

-- =============================================================================
-- Downgrade script (if needed)
-- NOTE: In production, do NOT downgrade without backup. Data loss may occur.
-- =============================================================================
/*
ALTER TABLE work_orders 
DROP COLUMN IF EXISTS reserved_warehouse,
DROP COLUMN IF EXISTS reserved_qty,
DROP COLUMN IF EXISTS reserved_at,
DROP COLUMN IF EXISTS release_action_id;

DROP INDEX IF EXISTS idx_wo_reserved;
DROP INDEX IF EXISTS idx_wo_reservation_status;
*/
