-- 066: APS 计划控制闭环
-- 目的：保留 MPS 来源、唯一当前版本、插单/审批审计，以及协调会和计划员手工调整数据。

ALTER TABLE IF EXISTS work_orders
    ADD COLUMN IF NOT EXISTS source_plan_id VARCHAR(36);

ALTER TABLE IF EXISTS pp_plans
    ADD COLUMN IF NOT EXISTS work_order_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS cancelled_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS completed_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS update_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_work_orders_source_plan ON work_orders(source_plan_id);
-- 部分历史环境只部署了旧的 plans 表；在 pp_plans 尚未初始化时不能让
-- APS 的附加索引阻断整批迁移。pp_plans 建好后再次执行本迁移即可补上。
DO $$
BEGIN
    IF to_regclass('public.pp_plans') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pp_plans_work_order ON pp_plans(work_order_id)';
    END IF;
END $$;

ALTER TABLE IF EXISTS aps_schedules
    ADD COLUMN IF NOT EXISTS approved_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS released_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS released_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS supersedes_schedule_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS change_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_aps_schedule_current
    ON aps_schedules(factory_id, is_current, created_at DESC);

-- 历史数据若存在多个 current，只保留最近的一个，再由数据库保证工厂级唯一当前版本。
WITH ranked_current AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY factory_id ORDER BY created_at DESC, id DESC) AS rn
    FROM aps_schedules
    WHERE is_current = TRUE
)
UPDATE aps_schedules s
SET is_current = FALSE
FROM ranked_current r
WHERE s.id = r.id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_aps_schedule_one_current
    ON aps_schedules(factory_id)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS aps_plan_events (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    plan_id VARCHAR(36),
    schedule_id VARCHAR(36),
    work_order_id VARCHAR(36),
    event_type VARCHAR(40) NOT NULL,
    actor VARCHAR(50) NOT NULL,
    reason TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aps_plan_events_factory_time
    ON aps_plan_events(factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aps_plan_events_plan
    ON aps_plan_events(plan_id, created_at DESC);

CREATE TABLE IF NOT EXISTS aps_coordination_meetings (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    meeting_date DATE NOT NULL,
    meeting_type VARCHAR(40) NOT NULL DEFAULT 'production_coordination',
    plan_version VARCHAR(80),
    attendees JSONB NOT NULL DEFAULT '[]'::jsonb,
    decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aps_meeting_factory_date
    ON aps_coordination_meetings(factory_id, meeting_date DESC);

CREATE TABLE IF NOT EXISTS aps_planner_activities (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    activity_type VARCHAR(40) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'aps_ui',
    plan_version VARCHAR(80),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_minutes NUMERIC(10, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aps_activity_factory_time
    ON aps_planner_activities(factory_id, started_at DESC);
