-- 061: bind every equipment asset to an HR equipment engineer.
-- The owner is used by OEE/TPM views and drill-through traceability.
ALTER TABLE equipment
    ADD COLUMN IF NOT EXISTS responsible_engineer_id VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_equipment_responsible_engineer
    ON equipment(responsible_engineer_id);
