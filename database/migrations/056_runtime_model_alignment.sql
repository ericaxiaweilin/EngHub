-- Columns required by background reporting after the consolidated model merge.
ALTER TABLE IF EXISTS production_alerts
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
