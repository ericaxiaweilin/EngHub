-- fix_schema_all_missing_columns.sql
-- Run this to add all missing columns referenced in ORM models that don't exist in DB tables
-- Execute via: psql -d <your_database> -f scripts/fix_schema_all_missing_columns.sql

-- Fix Inventory table (missing columns referenced in inventory model)
ALTER TABLE inventory 
ADD COLUMN IF NOT EXISTS expiry_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS storage_location VARCHAR(255),
ADD COLUMN IF NOT EXISTS qualified_status VARCHAR(20),
ADD COLUMN IF NOT EXISTS unit_cost DECIMAL(10,2);

-- Fix WorkOrder table (missing columns)
ALTER TABLE work_orders 
ADD COLUMN IF NOT EXISTS current_stage VARCHAR(50),
ADD COLUMN IF NOT EXISTS in_progress_status BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS partial_completion_percentage DECIMAL(5,2) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS next_station_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(50),
ADD COLUMN IF NOT EXISTS work_center VARCHAR(100),
ADD COLUMN IF NOT EXISTS routing_template_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS remark TEXT,
ADD COLUMN IF NOT EXISTS released_by VARCHAR(50),
ADD COLUMN IF NOT EXISTS completed_by VARCHAR(50);

-- Fix ProductionReport (if needed for some queries)
ALTER TABLE production_reports 
ADD COLUMN IF NOT EXISTS station_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS operation_name VARCHAR(100);

-- Add any other commonly accessed but missing columns
ALTER TABLE products 
ADD COLUMN IF NOT EXISTS uom VARCHAR(20);