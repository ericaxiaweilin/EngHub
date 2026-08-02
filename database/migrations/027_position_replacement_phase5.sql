-- 027: 岗位替代 Phase 5 - 替代设备维护员
-- 维保任务工作流 + 设备点检记录 + OEE 日快照 + 故障预测

-- ============== 维保任务（结构化工作流）==============
CREATE TABLE IF NOT EXISTS maintenance_tasks (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  task_code VARCHAR(50) UNIQUE NOT NULL,
  -- 类型
  task_type VARCHAR(20) NOT NULL,            -- inspection/lubrication/repair/overhaul/calibration
  priority VARCHAR(20) DEFAULT 'medium',     -- urgent/high/medium/low
  -- 设备
  equipment_id VARCHAR(50) NOT NULL,
  equipment_name VARCHAR(100),
  station_id VARCHAR(50),
  -- 计划
  planned_date DATE,
  planned_duration_minutes INT DEFAULT 60,
  frequency_days INT,                        -- 保养周期（天）
  -- 状态
  status VARCHAR(20) DEFAULT 'pending',      -- pending/in_progress/completed/overdue/cancelled
  -- 执行
  assigned_to VARCHAR(50),
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  actual_duration_minutes INT,
  -- 结果
  result VARCHAR(20),                        -- normal/abnormal/replaced/repaired
  findings TEXT,
  parts_used TEXT,                           -- JSON: 更换的备件
  cost FLOAT DEFAULT 0,
  -- 来源
  source VARCHAR(30) DEFAULT 'manual',       -- manual/auto_schedule/breakdown/prediction
  remark TEXT,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mt_factory ON maintenance_tasks(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_mt_equip ON maintenance_tasks(equipment_id, status);
CREATE INDEX IF NOT EXISTS idx_mt_date ON maintenance_tasks(planned_date, status);

-- ============== 点检项 ==============
CREATE TABLE IF NOT EXISTS maintenance_checklist (
  id VARCHAR(36) PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES maintenance_tasks(id),
  seq INT DEFAULT 1,
  item_name VARCHAR(200) NOT NULL,
  category VARCHAR(30),                      -- visual/measurement/function/safety
  standard_value VARCHAR(100),               -- 标准值
  measured_value VARCHAR(100),               -- 实测值
  is_normal BOOLEAN,
  remark VARCHAR(200),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mc_task ON maintenance_checklist(task_id);

-- ============== 设备运行数据（传感器/读数）==============
CREATE TABLE IF NOT EXISTS equipment_readings (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  equipment_id VARCHAR(50) NOT NULL,
  -- 读数
  metric_type VARCHAR(30) NOT NULL,          -- temperature/vibration/hours/pressure/current
  metric_value FLOAT NOT NULL,
  unit VARCHAR(20),
  -- 阈值
  warning_threshold FLOAT,
  alarm_threshold FLOAT,
  is_alarm BOOLEAN DEFAULT FALSE,
  -- 时间
  recorded_at TIMESTAMP DEFAULT NOW(),
  recorded_by VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_er_equip ON equipment_readings(equipment_id, metric_type, recorded_at);

-- ============== OEE 日快照 ==============
CREATE TABLE IF NOT EXISTS oee_daily (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  equipment_id VARCHAR(50) NOT NULL,
  snapshot_date DATE NOT NULL,
  -- 时间
  planned_production_minutes FLOAT DEFAULT 0,
  actual_run_minutes FLOAT DEFAULT 0,
  downtime_minutes FLOAT DEFAULT 0,
  -- 三大率
  availability FLOAT DEFAULT 0,              -- 时间稼动率
  performance FLOAT DEFAULT 0,               -- 性能稼动率
  quality FLOAT DEFAULT 0,                   -- 良品率
  oee FLOAT DEFAULT 0,                       -- 综合设备效率
  -- 产出
  planned_output INT DEFAULT 0,
  actual_output INT DEFAULT 0,
  good_output INT DEFAULT 0,
  -- 停机分类
  breakdown_minutes FLOAT DEFAULT 0,
  setup_minutes FLOAT DEFAULT 0,
  idle_minutes FLOAT DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, equipment_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_oee_factory ON oee_daily(factory_id, snapshot_date);
