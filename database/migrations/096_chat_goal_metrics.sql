-- Business metrics and evidence snapshots attached to durable thread Goals.
CREATE TABLE IF NOT EXISTS chat_goal_metrics (
    id                VARCHAR(36) PRIMARY KEY,
    goal_id           VARCHAR(36) NOT NULL REFERENCES chat_goals(id) ON DELETE CASCADE,
    metric_code       VARCHAR(40) NOT NULL,
    label             VARCHAR(120) NOT NULL,
    comparator        VARCHAR(8) NOT NULL DEFAULT 'gte',
    target_value      NUMERIC(18, 4),
    unit              VARCHAR(32),
    current_value     NUMERIC(18, 4),
    status            VARCHAR(20) NOT NULL DEFAULT 'observed',
    source_tool       VARCHAR(80),
    evidence          JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_checked_at   TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_goal_metrics_goal_code UNIQUE (goal_id, metric_code)
);

CREATE INDEX IF NOT EXISTS idx_chat_goal_metrics_goal_status
    ON chat_goal_metrics(goal_id, status);
CREATE INDEX IF NOT EXISTS idx_chat_goal_metrics_checked
    ON chat_goal_metrics(last_checked_at);
