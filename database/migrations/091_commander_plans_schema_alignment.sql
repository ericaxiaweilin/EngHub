-- 091: Restore the commander plan table required by the task-center inbox.
-- Legacy databases may contain followup_tasks without the plan aggregate.
CREATE TABLE IF NOT EXISTS commander_plans (
    id           VARCHAR(36) PRIMARY KEY,
    factory_id   VARCHAR(64) NOT NULL,
    created_by   VARCHAR(64) NOT NULL,
    cycle_id     VARCHAR(36),
    objective    VARCHAR(500) NOT NULL,
    mode         VARCHAR(20),
    status       VARCHAR(20) NOT NULL DEFAULT 'active',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    item_count   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_commander_plans_factory
    ON commander_plans(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_commander_plans_created
    ON commander_plans(factory_id, created_at DESC);
