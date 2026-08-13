-- 订单评审：PMC 评审销售订单
-- 结论直接挂在订单行上（review_status/承诺交期/风险等级/意见/评审人/评审时间）
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS review_status VARCHAR(32);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS committed_delivery DATE;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS risk_level VARCHAR(16);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(64);
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;