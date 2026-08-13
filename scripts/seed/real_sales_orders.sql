-- 阶段3：销售订单真实感重造（关键要素齐全：客户/产品/数量/交期/出货期/金额/状态/业务背景）
-- 确定性生成（md5 随机），幂等（订单号唯一）

-- 1) 出货期列
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS ship_date DATE;

-- 2) 订单池：10 客户 × 3 真实机种，48 张
WITH customers AS (
  SELECT * FROM (VALUES
    ('CUST-001', '威克体育用品'), ('CUST-002', '健行者健康科技'), ('CUST-003', '海沃健身器材'),
    ('CUST-004', '鼎力健身'), ('CUST-005', '蓝海运动贸易'), ('CUST-006', '康泰体育'),
    ('CUST-007', 'DECATHLON SPORT'), ('CUST-008', 'FITNESS FIRST GMBH'), ('CUST-009', 'ACTIVE LIFE INC'),
    ('CUST-010', 'EUROSPORT TRADING')
  ) AS c(code, name)
),
products AS (
  SELECT * FROM (VALUES
    ('MPL0113-00', 5600), ('A-30-04-F', 4200), ('A-50-04-F', 4800)
  ) AS p(code, price)
),
seq AS (SELECT generate_series(1, 48) AS n),
calc AS (
  SELECT
    s.n,
    c.code AS cust_code, c.name AS cust_name,
    p.code AS prod_code, p.price,
    -- 确定性随机 0-999
    (ABS((('x' || substr(md5('so' || s.n || c.code), 1, 8))::bit(32)::int) % 1000) / 1000.0) AS rnd,
    -- 数量 20-80（跑步机 B2B 单笔真实量级，2 台步进）
    20 + (ABS((('x' || substr(md5('q' || s.n), 1, 8))::bit(32)::int) % 31)) * 2 AS qty,
    -- 下单日：过去 3~27 天
    (CURRENT_DATE - (s.n % 25 + 3)::int) AS created_d,
    -- 交期：下单 + 35~75 天
    (35 + ABS((('x' || substr(md5('d' || s.n), 1, 8))::bit(32)::int) % 41)) AS lead,
    -- 出货期：交期 - 5~12 天
    (5 + ABS((('x' || substr(md5('s' || s.n), 1, 8))::bit(32)::int) % 8)) AS ship_lead,
    -- 优先级：每 7 张一张急单
    CASE WHEN s.n % 7 = 0 THEN 'high' WHEN s.n % 13 = 0 THEN 'low' ELSE 'medium' END AS prio,
    -- 备注场景池
    (ARRAY[
      '电商大促备货，交期优先', '新客户首批订单，需重点跟进', '年度框架协议第2批',
      '客户急单，已收加急费', '海外展会样机，数量小交期紧', '常规补货订单',
      '经销商季度备货', '新品上市铺货', '出口订单，需预留海运时间', '返单，历史订单复购'
    ])[(s.n % 10) + 1] AS rm
  FROM seq s
  JOIN customers c ON c.code = 'CUST-' || lpad(((s.n - 1) % 10 + 1)::text, 3, '0')
  JOIN products p ON p.code = (ARRAY['MPL0113-00','A-30-04-F','A-50-04-F'])[(s.n % 3) + 1]
)
INSERT INTO sales_orders (id, order_code, factory_id, customer_name, customer_code, product_id, product_name,
  quantity, unit, delivery_date, ship_date, priority, status, unit_price, total_amount, currency, remark, created_by, created_at, updated_at)
SELECT
  'so' || md5('so' || n || cust_code),
  'SO-2026-' || lpad(n::text, 4, '0'),
  'FAC_MECH_001', cust_name, cust_code, prod_code, prod_code,
  qty, '台',
  (created_d + lead)::date AS delivery_date,
  (created_d + lead - ship_lead)::date AS ship_date,
  prio,
  -- 状态由交期紧迫度决定
  CASE
    WHEN (created_d + lead - CURRENT_DATE) <= 15 THEN 'in_progress'
    WHEN (created_d + lead - CURRENT_DATE) <= 30 THEN 'released'
    WHEN (created_d + lead - CURRENT_DATE) <= 45 THEN 'confirmed'
    ELSE 'pending'
  END AS status,
  price, qty * price, 'CNY', rm, 'erp_sync', created_d, created_d
FROM calc;

-- 验证
SELECT COUNT(*) total,
  COUNT(*) FILTER (WHERE customer_name IS NOT NULL AND delivery_date IS NOT NULL AND ship_date IS NOT NULL AND total_amount > 0) complete,
  COUNT(DISTINCT customer_code) customers, COUNT(DISTINCT product_id) products,
  COUNT(*) FILTER (WHERE status='pending') pending, COUNT(*) FILTER (WHERE status='confirmed') confirmed,
  COUNT(*) FILTER (WHERE status='released') released, COUNT(*) FILTER (WHERE status='in_progress') in_prog,
  MIN(delivery_date) min_dd, MAX(delivery_date) max_dd
FROM sales_orders WHERE id LIKE 'so%' AND id ~ '^so[0-9a-f]{32}$';
