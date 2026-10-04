-- MRP 的多层展开结果要一路传到工单齐套表。
-- 少了 level / parent_code / item_type，PMC 看到的 681 行只是一堆料号：
-- 分不清哪行该下采购单、哪行是还没装出来的组件，缺口总数也就没法拆成"买"和"做"。
ALTER TABLE mrp_items ADD COLUMN IF NOT EXISTS level INTEGER;
ALTER TABLE mrp_items ADD COLUMN IF NOT EXISTS parent_code VARCHAR(100);
ALTER TABLE mrp_items ADD COLUMN IF NOT EXISTS allocated_qty NUMERIC(18,4) NOT NULL DEFAULT 0;
ALTER TABLE mrp_items ADD COLUMN IF NOT EXISTS item_type VARCHAR(10);

ALTER TABLE work_order_materials ADD COLUMN IF NOT EXISTS level INTEGER;
ALTER TABLE work_order_materials ADD COLUMN IF NOT EXISTS parent_code VARCHAR(100);
ALTER TABLE work_order_materials ADD COLUMN IF NOT EXISTS allocated_qty NUMERIC(18,4) NOT NULL DEFAULT 0;
ALTER TABLE work_order_materials ADD COLUMN IF NOT EXISTS item_type VARCHAR(10);
