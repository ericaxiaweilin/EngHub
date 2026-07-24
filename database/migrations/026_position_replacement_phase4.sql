-- 026: 岗位替代 Phase 4 - 替代质检员
-- 检验任务工作流 + SPC 控制图配置 + 不良分类统计

-- ============== 检验任务（结构化工作流）==============
CREATE TABLE IF NOT EXISTS inspection_tasks (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  task_code VARCHAR(50) UNIQUE NOT NULL,
  -- 类型与来源
  inspect_type VARCHAR(10) NOT NULL,         -- IQC/IPQC/FQC/OQC
  source_type VARCHAR(30),                   -- purchase_order/work_order/shipment/manual
  source_id VARCHAR(36),
  source_code VARCHAR(50),                   -- 来源单号
  -- 检验对象
  material_id VARCHAR(50),
  material_code VARCHAR(50),
  material_name VARCHAR(100),
  product_id VARCHAR(50),
  work_order_id VARCHAR(36),
  station_id VARCHAR(50),
  -- 抽样
  batch_qty INT DEFAULT 0,                   -- 批量
  sample_qty INT DEFAULT 0,                  -- 抽样数
  aql_level VARCHAR(20) DEFAULT 'General-II',
  -- 结果
  status VARCHAR(20) DEFAULT 'pending',      -- pending/inspecting/passed/failed/conditional
  defect_qty INT DEFAULT 0,
  defect_rate FLOAT DEFAULT 0,
  result VARCHAR(20),                        -- PASS/FAIL/CONDITIONAL
  disposition VARCHAR(30),                   -- accept/reject/rework/concession
  -- 执行
  inspector VARCHAR(50),
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  remark TEXT,
  created_by VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_it_factory ON inspection_tasks(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_it_type ON inspection_tasks(inspect_type, status);

-- ============== 检验项（Checklist）==============
CREATE TABLE IF NOT EXISTS inspection_items (
  id VARCHAR(36) PRIMARY KEY,
  task_id VARCHAR(36) NOT NULL REFERENCES inspection_tasks(id),
  seq INT DEFAULT 1,
  -- 检验项
  item_name VARCHAR(200) NOT NULL,           -- 检验项目名称
  item_code VARCHAR(50),
  category VARCHAR(30),                      -- dimension/appearance/function/performance
  -- 标准
  spec_value VARCHAR(100),                   -- 规格值（如 "10±0.5mm"）
  upper_limit FLOAT,
  lower_limit FLOAT,
  target_value FLOAT,
  -- 实测
  measured_value FLOAT,
  is_pass BOOLEAN,
  defect_type VARCHAR(50),                   -- 不良类型
  severity VARCHAR(20),                      -- critical/major/minor
  remark VARCHAR(200),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ii_task ON inspection_items(task_id);

-- ============== SPC 控制图配置 ==============
CREATE TABLE IF NOT EXISTS spc_chart_config (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  characteristic_code VARCHAR(50) NOT NULL,
  characteristic_name VARCHAR(100),
  -- 控制图类型
  chart_type VARCHAR(20) DEFAULT 'Xbar-R',   -- Xbar-R/Xbar-S/I-MR/p/np/c/u
  -- 控制限
  ucl FLOAT,
  cl FLOAT,
  lcl FLOAT,
  usl FLOAT,                                  -- 规格上限
  lsl FLOAT,                                  -- 规格下限
  target FLOAT,
  -- 子组
  subgroup_size INT DEFAULT 5,
  -- 状态
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, characteristic_code)
);
CREATE INDEX IF NOT EXISTS idx_scc_factory ON spc_chart_config(factory_id);

-- ============== 不良分类统计（按日汇总）==============
CREATE TABLE IF NOT EXISTS defect_daily_summary (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  summary_date DATE NOT NULL,
  -- 分类
  defect_type VARCHAR(50) NOT NULL,
  defect_name VARCHAR(100),
  station_id VARCHAR(50),
  product_id VARCHAR(50),
  -- 数量
  defect_count INT DEFAULT 0,
  inspected_qty INT DEFAULT 0,
  -- 严重度
  critical_count INT DEFAULT 0,
  major_count INT DEFAULT 0,
  minor_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(factory_id, summary_date, defect_type, station_id)
);
CREATE INDEX IF NOT EXISTS idx_dds_factory ON defect_daily_summary(factory_id, summary_date);
