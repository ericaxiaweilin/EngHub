-- Fix missing columns in work_orders table to match ORM model
-- Execute via: psql -d your_database -f fix_workorder_schema.sql

-- Add these columns if they don't exist
ALTER TABLE work_orders 
ADD COLUMN IF NOT EXISTS current_stage VARCHAR(50),
ADD COLUMN IF NOT EXISTS in_progress_status BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS partial_completion_percentage DECIMAL(5,2) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS next_station_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(50),
ADD COLUMN IF NOT EXISTS work_center VARCHAR(50);

-- Also add the fields referenced in other queries that may be missing
ALTER TABLE work_orders 
ADD COLUMN IF NOT EXISTS routing_template_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS remark TEXT,
ADD COLUMN IF NOT EXISTS released_by VARCHAR(50),
ADD COLUMN IF NOT EXISTS completed_by VARCHAR(50);

-- Add these to production_report table as well (referenced in some views)
ALTER TABLE production_reports 
ADD COLUMN IF NOT EXISTS station_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS operation_name VARCHAR(100);

-- Note: This is a minimal incremental fix. For long-term consistency,
-- consider generating proper migrations from the models.py definitions.