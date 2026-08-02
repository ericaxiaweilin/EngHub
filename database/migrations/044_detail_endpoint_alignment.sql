-- Detail endpoint schema alignment.
-- Idempotent: safe to run once per environment through enghub_schema_migrations.

ALTER TABLE inbound_orders
    ADD COLUMN IF NOT EXISTS purchase_order_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS location_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITHOUT TIME ZONE;

CREATE TABLE IF NOT EXISTS wo_status_logs (
    id VARCHAR(36) PRIMARY KEY,
    work_order_id UUID NOT NULL,
    action VARCHAR(30) NOT NULL,
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL,
    operator VARCHAR(50) NOT NULL,
    operator_role VARCHAR(50),
    comment VARCHAR(500),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_wo_status_logs_work_order_id
    ON wo_status_logs (work_order_id);
CREATE INDEX IF NOT EXISTS ix_wo_status_logs_created_at
    ON wo_status_logs (created_at);
