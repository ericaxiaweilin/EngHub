-- 089: Align legacy follow-up task tables with the current task-center contract.
-- Older deployments may have created followup_tasks before commander plan
-- linkage was introduced. Keep this migration safe to run repeatedly.
ALTER TABLE IF EXISTS followup_tasks
    ADD COLUMN IF NOT EXISTS plan_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS plan_seq INTEGER;

DO $$
BEGIN
    IF to_regclass('public.followup_tasks') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_followup_plan ON followup_tasks(plan_id)';
    END IF;
END $$;
