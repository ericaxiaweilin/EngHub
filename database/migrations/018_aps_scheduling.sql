-- 018: APS 排程引擎持久化表
-- 排程方案 + 排程任务明细 + 工作日历

-- 排程方案（一次排程生成一个方案）
CREATE TABLE IF NOT EXISTS aps_schedules (
  id VARCHAR(36) PRIMARY KEY,
  schedule_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  mode VARCHAR(20) NOT NULL DEFAULT 'hybrid',
  optimize_for VARCHAR(20) DEFAULT 'delivery',
  status VARCHAR(20) DEFAULT 'draft',
  horizon_start TIMESTAMP NOT NULL,
  horizon_end TIMESTAMP NOT NULL,
  on_time_rate FLOAT,
  avg_utilization FLOAT,
  total_setup_minutes FLOAT,
  avg_cycle_hours FLOAT,
  total_tasks INT DEFAULT 0,
  unscheduled_count INT DEFAULT 0,
  created_by VARCHAR(50),
  confirmed_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aps_sched_factory ON aps_schedules(factory_id, status);

-- 排程任务明细（每道工序一条）
CREATE TABLE IF NOT EXISTS aps_schedule_tasks (
  id VARCHAR(36) PRIMARY KEY,
  schedule_id VARCHAR(36) NOT NULL REFERENCES aps_schedules(id),
  work_order_id VARCHAR(36),
  order_code VARCHAR(50),
  product_code VARCHAR(50),
  operation_seq INT NOT NULL,
  operation_name VARCHAR(100),
  station_id VARCHAR(50) NOT NULL,
  planned_start TIMESTAMP NOT NULL,
  planned_end TIMESTAMP NOT NULL,
  setup_seconds FLOAT DEFAULT 0,
  run_seconds FLOAT DEFAULT 0,
  quantity INT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'planned',
  is_locked BOOLEAN DEFAULT FALSE,
  priority INT DEFAULT 5,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aps_task_sched ON aps_schedule_tasks(schedule_id);
CREATE INDEX IF NOT EXISTS idx_aps_task_station ON aps_schedule_tasks(station_id, planned_start);
CREATE INDEX IF NOT EXISTS idx_aps_task_wo ON aps_schedule_tasks(work_order_id);

-- 工作日历（工位/产线的可用时间段）
CREATE TABLE IF NOT EXISTS aps_work_calendars (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  resource_id VARCHAR(50) NOT NULL,
  resource_type VARCHAR(20) DEFAULT 'station',
  shift_name VARCHAR(50) DEFAULT '标准班',
  day_of_week INT NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  effective_from DATE,
  effective_to DATE
);
CREATE INDEX IF NOT EXISTS idx_aps_cal_resource ON aps_work_calendars(resource_id, day_of_week);

-- 默认工作日历：周一到周六 08:00-20:00（标准两班制）
INSERT INTO aps_work_calendars (id, factory_id, resource_id, resource_type, shift_name, day_of_week, start_time, end_time, is_active)
SELECT
  'cal-default-' || d.dow,
  'default',
  '*',
  'factory',
  '标准班',
  d.dow,
  '08:00'::time,
  '20:00'::time,
  TRUE
FROM generate_series(0, 5) AS d(dow)
ON CONFLICT DO NOTHING;
