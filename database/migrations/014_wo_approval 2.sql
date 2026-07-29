-- 014: 工单状态审核机制
-- 1) work_orders 增加审核人字段（下达人/完工确认人）
-- 2) wo_status_logs 状态操作日志表（谁/什么角色/何时/做了什么，审核追溯）

ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS released_by VARCHAR(50);   -- 下达人（审核门槛：管理角色且非创建人）
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS completed_by VARCHAR(50);  -- 完工确认人（品质确认门槛）

CREATE TABLE IF NOT EXISTS wo_status_logs (
    id VARCHAR(36) PRIMARY KEY,
    work_order_id VARCHAR(36) NOT NULL REFERENCES work_orders(id),
    action VARCHAR(30) NOT NULL,            -- create/release/start/pause/resume/pending_inbound/complete/close/cancel/split
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL,
    operator VARCHAR(50) NOT NULL,          -- 操作人 username
    operator_role VARCHAR(50),              -- 操作人角色
    comment VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wo_status_logs_wo ON wo_status_logs (work_order_id);
CREATE INDEX IF NOT EXISTS idx_wo_status_logs_created ON wo_status_logs (created_at);
