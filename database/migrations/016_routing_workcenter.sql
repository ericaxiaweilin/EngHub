-- 016: 工序流转与多角色视角 — 工艺路线模板 + 工作中心 + 指派
-- ============================================================

-- User 表增加 work_center 字段（工序组编码，如 WCUT/EDM/CUT，null=管理岗不绑定）
ALTER TABLE users ADD COLUMN IF NOT EXISTS work_center VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_users_work_center ON users(work_center);

-- WorkOrder 表增加 assigned_to（指派操作人 user_id）
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(36);
CREATE INDEX IF NOT EXISTS idx_wo_assigned_to ON work_orders(assigned_to);

-- WorkOrder 表增加 work_center（冗余自 process_code，便于索引查询）
-- 注：operation 类型工单的 work_center = process_code，master 为 null
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS work_center VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_wo_work_center ON work_orders(work_center);

-- WorkOrder 表增加 routing_template_id（创建时绑定的工艺路线模板）
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS routing_template_id VARCHAR(36);

-- 工艺路线模板表（独立于产品绑定，可复用）
CREATE TABLE IF NOT EXISTS routing_templates (
  id VARCHAR(36) PRIMARY KEY,
  template_code VARCHAR(50) NOT NULL UNIQUE,
  template_name VARCHAR(100) NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rt_factory ON routing_templates(factory_id);

-- 工艺路线模板工序步骤
CREATE TABLE IF NOT EXISTS routing_template_steps (
  id VARCHAR(36) PRIMARY KEY,
  template_id VARCHAR(36) NOT NULL REFERENCES routing_templates(id),
  seq INTEGER NOT NULL,
  process_code VARCHAR(20) NOT NULL,
  operation_name VARCHAR(100) NOT NULL,
  work_center VARCHAR(20),
  standard_hours NUMERIC(8,2) DEFAULT 0,
  is_parallel BOOLEAN DEFAULT FALSE,
  is_qc_gate BOOLEAN DEFAULT FALSE,
  remark TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rts_template ON routing_template_steps(template_id, seq);
