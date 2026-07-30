-- 023: 岗位替代 Phase 1 - 消灭统计员
-- 报工扩展 + 班次汇总 + 生产异常预警

-- ============== production_reports 扩展字段 ==============
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS operation_seq INT;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS operation_name VARCHAR(100);
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS machine_id VARCHAR(50);
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS start_time TIMESTAMP;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS end_time TIMESTAMP;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS cycle_time_sec FLOAT;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS is_undone BOOLEAN DEFAULT FALSE;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS undone_at TIMESTAMP;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS undone_by VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_pr_station_time ON production_reports(factory_id, station_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pr_shift ON production_reports(factory_id, shift, created_at);

-- ============== 班次汇总表（自动聚合，报表数据源）==============
CREATE TABLE IF NOT EXISTS shift_summaries (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  shift_date DATE NOT NULL,
  shift_type VARCHAR(20) NOT NULL,        -- day/middle/night
  station_id VARCHAR(50),
  work_order_id VARCHAR(36),
  product_id VARCHAR(50),
  total_output INT DEFAULT 0,
  good_qty INT DEFAULT 0,
  defect_qty INT DEFAULT 0,
  scrap_qty INT DEFAULT 0,
  yield_rate FLOAT DEFAULT 0,             -- 良品率 %
  target_output INT DEFAULT 0,            -- 目标产出
  achievement_rate FLOAT DEFAULT 0,       -- 达成率 %
  report_count INT DEFAULT 0,             -- 报工次数
  total_cycle_time FLOAT DEFAULT 0,       -- 总工时(秒)
  operator_count INT DEFAULT 0,           -- 参与人数
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, shift_date, shift_type, station_id, work_order_id)
);
CREATE INDEX IF NOT EXISTS idx_ss_date ON shift_summaries(factory_id, shift_date);
CREATE INDEX IF NOT EXISTS idx_ss_station ON shift_summaries(factory_id, station_id, shift_date);

-- ============== 生产异常预警 ==============
CREATE TABLE IF NOT EXISTS production_alerts (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  alert_type VARCHAR(30) NOT NULL,        -- below_target/yield_drop/machine_stop/material_short/order_delay
  severity VARCHAR(10) NOT NULL DEFAULT 'warning',  -- info/warning/critical
  title VARCHAR(200) NOT NULL,
  message TEXT,
  source_type VARCHAR(30),                -- work_order/station/equipment/material
  source_id VARCHAR(50),
  metric_value FLOAT,                     -- 触发值
  threshold_value FLOAT,                  -- 阈值
  is_read BOOLEAN DEFAULT FALSE,
  is_resolved BOOLEAN DEFAULT FALSE,
  resolved_by VARCHAR(50),
  resolved_at TIMESTAMP,
  triggered_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pa_factory ON production_alerts(factory_id, is_read, triggered_at);
CREATE INDEX IF NOT EXISTS idx_pa_type ON production_alerts(factory_id, alert_type, triggered_at);

-- ============== 小时产出快照（看板趋势图数据源）==============
CREATE TABLE IF NOT EXISTS hourly_output_snapshots (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  snapshot_date DATE NOT NULL,
  snapshot_hour INT NOT NULL,             -- 0-23
  station_id VARCHAR(50),
  output_qty INT DEFAULT 0,
  good_qty INT DEFAULT 0,
  defect_qty INT DEFAULT 0,
  target_qty INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, snapshot_date, snapshot_hour, station_id)
);
CREATE INDEX IF NOT EXISTS idx_hos_date ON hourly_output_snapshots(factory_id, snapshot_date);
