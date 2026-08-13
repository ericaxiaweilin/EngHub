-- 088: Align legacy APS schedule tables with the current ORM/API contract.
-- Historical deployments may have created aps_schedules before the approval
-- and version-control fields were introduced.  Keep this migration idempotent
-- so it is safe on both old and current databases.

ALTER TABLE IF EXISTS aps_schedules
    ADD COLUMN IF NOT EXISTS approved_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS released_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS released_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS supersedes_schedule_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS change_reason TEXT;

DO $$
BEGIN
    IF to_regclass('public.aps_schedules') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_aps_schedule_current ON aps_schedules(factory_id, is_current, created_at DESC)';
    END IF;
END $$;
