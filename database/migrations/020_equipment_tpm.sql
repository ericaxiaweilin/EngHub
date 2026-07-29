-- 020: 设备 TPM 增强
-- 停机记录 + 维护工单 + 预防维护计划

-- 设备停机记录
CREATE TABLE IF NOT EXISTS equipment_downtime (
  id VARCHAR(36) PRIMARY KEY,
  equipment_id VARCHAR(36) NOT NULL REFERENCES equipment(id),
  factory_id VARCHAR(50) NOT NULL,
  start_time TIMESTAMP NOT NULL,
  end_time TIMESTAMP,
  duration_minutes FLOAT,
  downtime_category VARCHAR(30),
  reason_code VARCHAR(50),
  description TEXT,
  reported_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_downtime_eq ON equipment_downtime(equipment_id, start_time);
CREATE INDEX IF NOT EXISTS idx_downtime_factory ON equipment_downtime(factory_id, start_time);

-- 维护工单
CREATE TABLE IF NOT EXISTS maintenance_orders (
  id VARCHAR(36) PRIMARY KEY,
  order_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  equipment_id VARCHAR(36) NOT NULL REFERENCES equipment(id),
  maintenance_type VARCHAR(20) NOT NULL,
  priority VARCHAR(10) DEFAULT 'medium',
  status VARCHAR(20) DEFAULT 'open',
  description TEXT,
  planned_date TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  assigned_to VARCHAR(50),
  result_summary TEXT,
  downtime_minutes FLOAT DEFAULT 0,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_maint_eq ON maintenance_orders(equipment_id, status);
CREATE INDEX IF NOT EXISTS idx_maint_factory ON maintenance_orders(factory_id, status);

-- 维护计划（预防性维护模板）
CREATE TABLE IF NOT EXISTS maintenance_plans (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  equipment_id VARCHAR(36) NOT NULL REFERENCES equipment(id),
  plan_name VARCHAR(100) NOT NULL,
  frequency_days INT NOT NULL,
  last_executed_at TIMESTAMP,
  next_due_at TIMESTAMP,
  checklist TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mplan_eq ON maintenance_plans(equipment_id, is_active);
