-- 021: WMS 仓储增强
-- 库存流水 + 盘点单 + 盘点明细

-- 库存流水（每次出入库/调整记录一条）
CREATE TABLE IF NOT EXISTS inventory_transactions (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  inventory_id VARCHAR(36) REFERENCES inventory(id),
  material_id VARCHAR(50) NOT NULL,
  batch_code VARCHAR(50),
  transaction_type VARCHAR(20) NOT NULL,
  quantity INT NOT NULL,
  before_qty INT,
  after_qty INT,
  reference_type VARCHAR(30),
  reference_id VARCHAR(36),
  operator VARCHAR(50),
  remark VARCHAR(200),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inv_txn ON inventory_transactions(factory_id, material_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inv_txn_batch ON inventory_transactions(batch_code, created_at);

-- 盘点单
CREATE TABLE IF NOT EXISTS inventory_counts (
  id VARCHAR(36) PRIMARY KEY,
  count_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id),
  count_type VARCHAR(20) DEFAULT 'periodic',
  status VARCHAR(20) DEFAULT 'draft',
  planned_date DATE,
  counted_by VARCHAR(50),
  approved_by VARCHAR(50),
  total_items INT DEFAULT 0,
  diff_items INT DEFAULT 0,
  total_diff_qty INT DEFAULT 0,
  remark TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_count_factory ON inventory_counts(factory_id, status);

-- 盘点明细
CREATE TABLE IF NOT EXISTS inventory_count_items (
  id VARCHAR(36) PRIMARY KEY,
  count_id VARCHAR(36) NOT NULL REFERENCES inventory_counts(id),
  inventory_id VARCHAR(36) REFERENCES inventory(id),
  material_id VARCHAR(50) NOT NULL,
  batch_code VARCHAR(50),
  system_qty INT NOT NULL,
  counted_qty INT,
  diff_qty INT,
  adjusted BOOLEAN DEFAULT FALSE,
  remark VARCHAR(200)
);
CREATE INDEX IF NOT EXISTS idx_count_items ON inventory_count_items(count_id);
