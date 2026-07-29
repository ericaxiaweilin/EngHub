-- 025: 岗位替代 Phase 3 - 替代仓管员
-- 库存预警 + 盘点任务 + 安全库存配置 + 物料最后动销追踪

-- ============== 安全库存配置 ==============
CREATE TABLE IF NOT EXISTS safety_stock_config (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  material_id VARCHAR(50) NOT NULL,
  material_code VARCHAR(50),
  material_name VARCHAR(100),
  -- 库存水位
  safety_stock INT DEFAULT 0,              -- 安全库存
  reorder_point INT DEFAULT 0,             -- 补货点
  max_stock INT DEFAULT 0,                 -- 最大库存
  -- 呆滞判定
  dead_stock_days INT DEFAULT 90,          -- 超过N天无动销判定为呆滞
  -- 状态
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, material_id)
);
CREATE INDEX IF NOT EXISTS idx_ssc_factory ON safety_stock_config(factory_id);

-- ============== 库存预警 ==============
CREATE TABLE IF NOT EXISTS stock_alerts (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  alert_type VARCHAR(30) NOT NULL,          -- below_safety/above_max/dead_stock/expiring
  material_id VARCHAR(50) NOT NULL,
  material_code VARCHAR(50),
  material_name VARCHAR(100),
  warehouse_id VARCHAR(36),
  -- 数据
  current_qty INT,
  threshold_qty INT,                        -- 安全库存/最大库存
  days_inactive INT,                        -- 呆滞天数
  -- 状态
  severity VARCHAR(20) DEFAULT 'warning',   -- info/warning/critical
  status VARCHAR(20) DEFAULT 'open',        -- open/acknowledged/resolved
  resolved_by VARCHAR(50),
  resolved_at TIMESTAMP,
  remark TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sa_factory ON stock_alerts(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_sa_type ON stock_alerts(alert_type, status);

-- ============== 盘点任务 ==============
CREATE TABLE IF NOT EXISTS cycle_count_tasks (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  task_code VARCHAR(50) UNIQUE NOT NULL,
  -- 范围
  warehouse_id VARCHAR(36),
  zone VARCHAR(50),                         -- 区域（A/B/C 分类）
  count_type VARCHAR(20) DEFAULT 'cycle',   -- cycle/full/spot
  -- 状态
  status VARCHAR(20) DEFAULT 'pending',     -- pending/in_progress/completed/cancelled
  total_items INT DEFAULT 0,
  counted_items INT DEFAULT 0,
  diff_items INT DEFAULT 0,                 -- 有差异的项
  -- 执行
  assigned_to VARCHAR(50),
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  -- 结果
  accuracy_rate FLOAT,                      -- 盘点准确率
  total_diff_qty INT DEFAULT 0,
  remark TEXT,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cct_factory ON cycle_count_tasks(factory_id, status);

-- ============== 盘点明细 ==============
CREATE TABLE IF NOT EXISTS cycle_count_items (
  id VARCHAR(36) PRIMARY KEY,
  task_id VARCHAR(36) NOT NULL REFERENCES cycle_count_tasks(id),
  material_id VARCHAR(50) NOT NULL,
  material_code VARCHAR(50),
  location_id VARCHAR(36),
  -- 数量
  system_qty INT DEFAULT 0,                 -- 系统数量
  counted_qty INT,                          -- 实盘数量
  diff_qty INT,                             -- 差异
  -- 状态
  status VARCHAR(20) DEFAULT 'pending',     -- pending/counted/confirmed
  counted_by VARCHAR(50),
  counted_at TIMESTAMP,
  remark VARCHAR(200),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cci_task ON cycle_count_items(task_id);

-- ============== 库存表增强：最后动销时间 ==============
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS last_movement_at TIMESTAMP;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS material_name VARCHAR(100);
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS unit VARCHAR(20) DEFAULT 'pcs';
