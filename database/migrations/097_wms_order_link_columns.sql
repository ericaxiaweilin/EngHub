-- WMS 出入库单 ORM 与生产库表结构对齐。
-- inbound_orders.production_order_id 与 outbound_orders.sales_order_id 两列
-- 在生产库已存在（业务先建表），但 ORM 模型缺失，导致 inbound()/outbound()
-- 构造对象即 TypeError，全量入库/销售出库 crash。IF NOT EXISTS 保证幂等。
ALTER TABLE inbound_orders
    ADD COLUMN IF NOT EXISTS production_order_id VARCHAR(50);
ALTER TABLE outbound_orders
    ADD COLUMN IF NOT EXISTS sales_order_id VARCHAR(50);
