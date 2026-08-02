-- ============================================================
-- P0 修复：补齐所有缺失的列和表（修复 500 错误）
-- 回滚：git reset --hard pre-arch-debt-fix && 恢复数据库备份
-- ============================================================

BEGIN;

-- ============================================================
-- 1. shift_summaries 表缺失列
-- ============================================================
ALTER TABLE shift_summaries ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE shift_summaries ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);

-- ============================================================
-- 2. inventory_counts 表缺失列
-- ============================================================
ALTER TABLE inventory_counts ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE inventory_counts ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);

-- ============================================================
-- 3. inventory_transactions 表缺失列
-- ============================================================
ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS work_order_id VARCHAR(36);
ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);

-- ============================================================
-- 4. pp_plans 表缺失列
-- ============================================================
ALTER TABLE pp_plans ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);

-- ============================================================
-- 5. andon_escalation_logs 表（完整创建）
-- ============================================================
CREATE TABLE IF NOT EXISTS andon_escalation_logs (
  id VARCHAR(36) PRIMARY KEY,
  ticket_id UUID NOT NULL REFERENCES andon_tickets(id),
  event_type VARCHAR(30) NOT NULL,
  from_role VARCHAR(50),
  to_role VARCHAR(50),
  message TEXT,
  triggered_by VARCHAR(50) DEFAULT 'system',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aes_ticket_created ON andon_escalation_logs(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_aes_event_type ON andon_escalation_logs(event_type);

-- ============================================================
-- 6. 其他可能缺失的审计字段（预防性修复）
-- ============================================================
-- notifications 表
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);

-- production_alerts 表（应该已有，但保险起见）
ALTER TABLE production_alerts ADD COLUMN IF NOT EXISTS created_by VARCHAR(50);
ALTER TABLE production_alerts ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50);
ALTER TABLE production_alerts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

COMMIT;

-- 验证
SELECT 'shift_summaries' as tbl, 
  (SELECT count(*) FROM information_schema.columns WHERE table_name='shift_summaries' AND column_name='created_by') as has_created_by
UNION ALL SELECT 'inventory_counts', 
  (SELECT count(*) FROM information_schema.columns WHERE table_name='inventory_counts' AND column_name='created_by')
UNION ALL SELECT 'inventory_transactions', 
  (SELECT count(*) FROM information_schema.columns WHERE table_name='inventory_transactions' AND column_name='work_order_id')
UNION ALL SELECT 'pp_plans', 
  (SELECT count(*) FROM information_schema.columns WHERE table_name='pp_plans' AND column_name='updated_by')
UNION ALL SELECT 'andon_escalation_logs', 
  (SELECT count(*) FROM information_schema.tables WHERE table_name='andon_escalation_logs');
