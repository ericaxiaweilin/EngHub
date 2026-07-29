-- 012: 工单体系化编码 - 主工单/工序工单层级字段
-- ============================================================
-- 支持主工单派生工序工单（如 ELEC-S20260720-001 -> ELEC-S20260720-001-SMT01）
-- 对齐 ISA-95 / ISO 9001 可追溯性 / SAP 工序惯例
-- 编码结构: {PLANT}-{TYPE}{DATE}-{SEQ}[-{PROCESS}{OP_SEQ}]

-- 1. 层级字段（幂等）
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS parent_work_order_id VARCHAR(36);            -- 工序工单指向主工单 id
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS wo_type VARCHAR(20) NOT NULL DEFAULT 'master'; -- master=主工单 / operation=工序工单
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS process_code VARCHAR(20);                    -- 行业通用工序代码 SMT/INJ/MACH...，主工单为空
ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS operation_seq INT;                           -- 同一工序内道次序号 01/02...

-- 2. 外键（幂等：自引用 work_orders.id）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_wo_parent') THEN
        ALTER TABLE work_orders
            ADD CONSTRAINT fk_wo_parent
            FOREIGN KEY (parent_work_order_id) REFERENCES work_orders(id);
    END IF;
END $$;

-- 3. 索引（幂等）
CREATE INDEX IF NOT EXISTS idx_wo_parent ON work_orders(parent_work_order_id);
CREATE INDEX IF NOT EXISTS idx_wo_type ON work_orders(wo_type);
CREATE INDEX IF NOT EXISTS idx_wo_process_code ON work_orders(process_code);

-- 4. 回填：存量工单全部视为主工单（DEFAULT 已处理，此处兜底）
UPDATE work_orders SET wo_type = 'master' WHERE wo_type IS NULL;
