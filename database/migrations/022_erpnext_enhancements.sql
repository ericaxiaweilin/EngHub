-- 022: ERPNext 参考增强 - Job Card 计时 / 质量目标 / 拣货单
-- 参考 ERPNext: Job Card Time Log, Quality Goal/Review, Pick List

-- ============== Job Card 工序计时日志 ==============
CREATE TABLE IF NOT EXISTS job_card_time_logs (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  work_order_id VARCHAR(36) REFERENCES work_orders(id),
  operation_seq INT,
  operation_name VARCHAR(100),
  station_id VARCHAR(50),
  operator VARCHAR(50),
  start_time TIMESTAMP NOT NULL,
  end_time TIMESTAMP,
  duration_minutes FLOAT,
  completed_qty INT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'running',   -- running/paused/completed
  remark VARCHAR(200),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_jctl_wo ON job_card_time_logs(work_order_id);
CREATE INDEX idx_jctl_station ON job_card_time_logs(factory_id, station_id, start_time);

-- ============== 质量目标 ==============
CREATE TABLE IF NOT EXISTS quality_goals (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  goal_code VARCHAR(50) UNIQUE NOT NULL,
  goal_name VARCHAR(200) NOT NULL,
  metric_type VARCHAR(30) NOT NULL,       -- yield_rate/defect_ppm/customer_complaint/inspection_pass
  target_value FLOAT NOT NULL,
  current_value FLOAT,
  unit VARCHAR(20) DEFAULT '%',
  period VARCHAR(20) DEFAULT 'monthly',   -- daily/weekly/monthly/quarterly
  responsible VARCHAR(50),
  status VARCHAR(20) DEFAULT 'active',    -- active/achieved/expired
  review_frequency_days INT DEFAULT 30,
  last_reviewed_at TIMESTAMP,
  next_review_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_qg_factory ON quality_goals(factory_id, status);

-- 质量目标评审记录
CREATE TABLE IF NOT EXISTS quality_goal_reviews (
  id VARCHAR(36) PRIMARY KEY,
  goal_id VARCHAR(36) NOT NULL REFERENCES quality_goals(id),
  review_date TIMESTAMP DEFAULT NOW(),
  measured_value FLOAT,
  gap FLOAT,
  status VARCHAR(20) DEFAULT 'on_track',  -- on_track/at_risk/off_track
  action_plan TEXT,
  reviewed_by VARCHAR(50),
  remark VARCHAR(500)
);

-- ============== 拣货单 ==============
CREATE TABLE IF NOT EXISTS pick_lists (
  id VARCHAR(36) PRIMARY KEY,
  pick_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  work_order_id VARCHAR(36) REFERENCES work_orders(id),
  work_order_code VARCHAR(50),
  status VARCHAR(20) DEFAULT 'draft',     -- draft/picking/picked/cancelled
  warehouse_id VARCHAR(36),
  total_items INT DEFAULT 0,
  picked_items INT DEFAULT 0,
  picked_by VARCHAR(50),
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_pl_wo ON pick_lists(work_order_id);

-- 拣货明细
CREATE TABLE IF NOT EXISTS pick_list_items (
  id VARCHAR(36) PRIMARY KEY,
  pick_list_id VARCHAR(36) NOT NULL REFERENCES pick_lists(id),
  material_id VARCHAR(50) NOT NULL,
  material_name VARCHAR(100),
  required_qty INT NOT NULL,
  picked_qty INT DEFAULT 0,
  batch_code VARCHAR(50),
  location VARCHAR(50),
  status VARCHAR(20) DEFAULT 'pending',   -- pending/picked/shortage
  remark VARCHAR(200)
);
