-- 068_rush_order_approvals.sql
-- 插单审批流（审计 Q4）：评估→提报→审批→执行→留痕
-- 配套 ORM：database/models.py RushOrderApproval / RushOrderApprovalLog

CREATE TABLE IF NOT EXISTS rush_order_approvals (
    id                VARCHAR(36) PRIMARY KEY,
    approval_code     VARCHAR(50) NOT NULL UNIQUE,
    factory_id        VARCHAR(50) NOT NULL,
    product_id        VARCHAR(50) NOT NULL,
    quantity          INTEGER NOT NULL,
    due_date          DATE,
    rush_priority     VARCHAR(20) NOT NULL DEFAULT 'urgent',
    impact_json       JSONB,
    affected_orders   INTEGER DEFAULT 0,
    max_delay_days    NUMERIC(8,2) DEFAULT 0,
    process_hours     NUMERIC(10,2),
    recommendation    TEXT,
    approval_level    INTEGER NOT NULL DEFAULT 2,
    required_role     VARCHAR(50),
    status            VARCHAR(20) NOT NULL DEFAULT 'draft',
    applicant         VARCHAR(50),
    approver          VARCHAR(50),
    approved_at       TIMESTAMP,
    reject_reason     TEXT,
    target_schedule_id VARCHAR(36),
    target_wo_id      VARCHAR(36),
    executed_at       TIMESTAMP,
    created_by        VARCHAR(50),
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_roa_factory_status ON rush_order_approvals(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_roa_applicant     ON rush_order_approvals(applicant);
CREATE INDEX IF NOT EXISTS idx_roa_required_role ON rush_order_approvals(required_role);

CREATE TABLE IF NOT EXISTS rush_order_approval_logs (
    id           VARCHAR(36) PRIMARY KEY,
    approval_id  VARCHAR(36) NOT NULL REFERENCES rush_order_approvals(id),
    action       VARCHAR(20) NOT NULL,
    actor        VARCHAR(50) NOT NULL,
    actor_role   VARCHAR(50),
    comment      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_roal_approval_id ON rush_order_approval_logs(approval_id);
