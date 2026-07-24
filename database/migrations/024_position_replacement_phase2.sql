-- 024: 岗位替代 Phase 2 - 替代计划员
-- 销售订单 + 订单拆分日志 + APS 排程增强

-- ============== 销售订单（需求源头）==============
CREATE TABLE IF NOT EXISTS sales_orders (
  id VARCHAR(36) PRIMARY KEY,
  order_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  customer_name VARCHAR(100),
  customer_code VARCHAR(50),
  product_id VARCHAR(50) NOT NULL,
  product_name VARCHAR(100),
  quantity INT NOT NULL DEFAULT 0,
  unit VARCHAR(20) DEFAULT 'pcs',
  delivery_date DATE,
  priority VARCHAR(20) DEFAULT 'medium',    -- urgent/high/medium/low
  status VARCHAR(20) DEFAULT 'pending',     -- pending/planning/released/in_progress/completed/cancelled
  -- 拆分状态
  decomposed BOOLEAN DEFAULT FALSE,
  decomposed_at TIMESTAMP,
  work_order_ids TEXT,                       -- JSON array of generated WO ids
  -- 物料齐套
  material_ready BOOLEAN DEFAULT FALSE,
  material_check_at TIMESTAMP,
  -- 金额
  unit_price FLOAT,
  total_amount FLOAT,
  currency VARCHAR(10) DEFAULT 'CNY',
  -- 备注
  remark TEXT,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_so_factory ON sales_orders(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_so_delivery ON sales_orders(factory_id, delivery_date);
CREATE INDEX IF NOT EXISTS idx_so_product ON sales_orders(product_id);

-- ============== 订单拆分日志 ==============
CREATE TABLE IF NOT EXISTS order_decomposition_logs (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  sales_order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id),
  action VARCHAR(30) NOT NULL,              -- decompose/material_check/priority_change/cancel
  result TEXT,                               -- JSON: 拆分结果/齐套结果
  work_orders_created INT DEFAULT 0,
  operator VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_odl_so ON order_decomposition_logs(sales_order_id);

-- ============== APS 排程增强字段 ==============
ALTER TABLE aps_schedules ADD COLUMN IF NOT EXISTS algorithm VARCHAR(30) DEFAULT 'EDD';
ALTER TABLE aps_schedules ADD COLUMN IF NOT EXISTS constraint_summary TEXT;
ALTER TABLE aps_schedules ADD COLUMN IF NOT EXISTS conflict_count INT DEFAULT 0;

ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS setup_minutes FLOAT DEFAULT 0;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS material_ready BOOLEAN DEFAULT TRUE;
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS sequence_in_station INT;

-- ============== 设备产能参数（排程约束）==============
CREATE TABLE IF NOT EXISTS station_capacity (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  station_id VARCHAR(50) NOT NULL,
  -- 产能参数
  available_hours_per_day FLOAT DEFAULT 16,    -- 每日可用小时（2班×8h）
  efficiency_rate FLOAT DEFAULT 0.85,          -- 效率系数
  setup_time_minutes FLOAT DEFAULT 30,         -- 默认换型时间
  max_concurrent_orders INT DEFAULT 1,         -- 最大并行工单数
  -- 维护窗口
  maintenance_day VARCHAR(10),                 -- 固定维护日（如 "Sunday"）
  -- 技能要求
  required_skills TEXT,                         -- JSON array
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, station_id)
);
CREATE INDEX IF NOT EXISTS idx_sc_factory ON station_capacity(factory_id);
