-- ════════════════════════════════════════════════════════════════════
-- 数据缺口审计清单（MPS 断链根因）
-- 说明：运行系统里 MPS 计划是手工生成，销售订单仅 1/58 纳入计划；
--       主力工厂 581 个产品只有 6 条工艺路线、106 个有 BOM。
--       本脚本列出"待补主数据"的具体清单，供工艺/IE/工程/采购录入。
-- 用法：在运行库（docker-postgres-1 容器）执行：
--       docker exec docker-postgres-1 psql -U enghub -d enghub -f gap_audit.sql
-- ════════════════════════════════════════════════════════════════════

-- ① 未纳入 MPS 计划的销售订单（PMC 需建计划）
WITH covered AS (
    SELECT DISTINCT sales_order_id FROM pp_plans WHERE sales_order_id IS NOT NULL
)
SELECT
    so.order_code,
    so.customer_name,
    so.product_id,
    so.product_name,
    so.quantity,
    so.delivery_date,
    so.status,
    so.decomposed,
    CASE WHEN b.id IS NULL THEN '缺BOM' ELSE '有BOM' END  AS bom_status,
    CASE WHEN r.id IS NULL THEN '缺路由' ELSE '有路由' END AS routing_status
FROM sales_orders so
LEFT JOIN bom_items b ON b.product_id = so.product_id AND b.factory_id = so.factory_id
LEFT JOIN routings r
       ON r.factory_id = so.factory_id AND r.product_id = so.product_id AND r.is_active = TRUE
WHERE so.status NOT IN ('cancelled', 'completed')
  AND so.order_code NOT IN (SELECT sales_order_id FROM covered)
ORDER BY so.delivery_date;

-- ② 在售但没有工艺路线的产品（工艺/IE 需补路由）
SELECT p.product_code, p.product_name, p.category
FROM products p
WHERE p.factory_id = 'FAC_MECH_001'
  AND p.status = 'active'
  AND NOT EXISTS (SELECT 1 FROM routings r
                  WHERE r.factory_id = p.factory_id AND r.product_id = p.id AND r.is_active = TRUE)
ORDER BY p.product_code;

-- ③ 在售但没有 BOM 的产品（工程/PP 需维护 BOM 版本）
SELECT p.product_code, p.product_name, p.category
FROM products p
WHERE p.factory_id = 'FAC_MECH_001'
  AND p.status = 'active'
  AND NOT EXISTS (SELECT 1 FROM bom_items b
                  WHERE b.factory_id = p.factory_id AND b.product_id = p.id)
ORDER BY p.product_code;

-- ④ 采购订单物料与 BOM 物料编码不匹配（无法评估含 PO 齐套）
SELECT po.po_code, po.material_code, po.material_name,
       po.status, po.expected_date, po.qty
FROM purchase_orders po
WHERE po.factory_id = 'FAC_MECH_001'
  AND po.status NOT IN ('received', 'cancelled')
  AND NOT EXISTS (SELECT 1 FROM bom_items b WHERE b.material_code = po.material_code)
ORDER BY po.expected_date;

-- ⑤ 供应商报价缺失（supplier_prices 为空，LT 恒 unknown）
--    若报价中长期不维护，可降级在 supplier_materials 维护 LT。
SELECT 'supplier_prices' AS table_name, count(*) AS rows
FROM supplier_prices
UNION ALL
SELECT 'supplier_materials', count(*) FROM supplier_materials
UNION ALL
SELECT 'suppliers', count(*) FROM suppliers;

-- ⑥ 汇总（快速总览）
SELECT
    (SELECT count(*) FROM sales_orders WHERE status NOT IN ('cancelled','completed')) AS so_total,
    (SELECT count(*) FROM sales_orders so WHERE so.status NOT IN ('cancelled','completed')
       AND NOT EXISTS (SELECT 1 FROM pp_plans pp WHERE pp.sales_order_id = so.order_code)) AS so_unplanned,
    (SELECT count(*) FROM products WHERE factory_id='FAC_MECH_001' AND status='active') AS products_active,
    (SELECT count(*) FROM products p WHERE p.factory_id='FAC_MECH_001' AND p.status='active'
       AND NOT EXISTS (SELECT 1 FROM routings r WHERE r.factory_id=p.factory_id AND r.product_id=p.id AND r.is_active=TRUE)) AS products_no_routing,
    (SELECT count(*) FROM products p WHERE p.factory_id='FAC_MECH_001' AND p.status='active'
       AND NOT EXISTS (SELECT 1 FROM bom_items b WHERE b.factory_id=p.factory_id AND b.product_id=p.id)) AS products_no_bom;