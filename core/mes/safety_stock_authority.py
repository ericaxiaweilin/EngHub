"""安全库存这句话到底是谁说的：两处声明、四条尺，先验依据再报缺口。

实测（FAC_MECH_001，2026-10-09）不是"算不出告警"，是**算得出四个互相矛盾的告警数**：

* `inventory.safety_stock` 有 47 个取值、众数 **2**（10,624/11,228 = 94.6%）；
* `materials.safety_stock` 有 7 个取值、众数 **100**（18,998/31,672 = 60%），且没有一条是 0 或空；
* 两条声明在 11,184 个共有料号上**每一条都不一致**（最狠的一批 SAP 料号是 2 vs 500，差 250 倍）；
* 于是同一句"低于安全库存"按不同出处给出 476（补货触发线）/ 645（inventory 侧）/
  4,666（materials 侧）三个数，而 `safety_stock_config` 那张专门的配置表是 **0 行**。

这个模块做的不是"挑一条算"，而是把每条尺的口径、依据等级、以及"引擎不能替厂里选哪张表"
这件事一起报出去。判模板值的那把尺与 `lead_time_days`（31,452 行只有 10 个取值）用的是同一条：
**取值个数少 + 众数占比高 = 模板铺的默认值，不是逐料号的决定。**
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 判"模板值"的线：绝大多数料号共用同一个数，就是模板铺的，不是逐料号决定的。
# 众数占比单独成立（inventory 侧 47 个取值但 95.7% 都是 2 —— 取值个数并不少，可它就是模板）；
# 取值极多是次级信号（materials 侧那种 7~10 个值），两条任一成立即判 template/coarse。
TEMPLATE_MIN_MODE_SHARE = 0.30
TEMPLATE_MAX_DISTINCT = 20

INV_CENSUS_SQL = """
    SELECT count(*) AS rows_total,
           count(DISTINCT safety_stock) AS distinct_values,
           mode() WITHIN GROUP (ORDER BY safety_stock) AS mode_value,
           count(*) FILTER (WHERE safety_stock IS NULL)::int AS nulls,
           count(*) FILTER (WHERE safety_stock = 0)::int AS zeros
    FROM inventory WHERE factory_id = :fid
"""

MAT_CENSUS_SQL = """
    SELECT count(*) AS rows_total,
           count(DISTINCT safety_stock) AS distinct_values,
           mode() WITHIN GROUP (ORDER BY safety_stock::numeric) AS mode_value,
           count(*) FILTER (WHERE safety_stock IS NULL)::int AS nulls,
           count(*) FILTER (WHERE safety_stock::numeric = 0)::int AS zeros
    FROM materials WHERE factory_id = :fid
"""

MODE_SHARE_SQL = """
    SELECT safety_stock::numeric AS value, count(*) AS n
    FROM {table}
    WHERE factory_id = :fid AND safety_stock IS NOT NULL
    GROUP BY 1 ORDER BY 2 DESC LIMIT 5
"""

DISAGREE_SQL = """
WITH inv AS (
    SELECT material_code, min(safety_stock) AS inv_ss, sum(available_qty) AS available
    FROM inventory WHERE factory_id = :fid
    GROUP BY material_code),
mat AS (
    SELECT material_code, safety_stock::numeric AS mat_ss
    FROM materials WHERE factory_id = :fid AND safety_stock IS NOT NULL)
SELECT count(*) AS joined_materials,
       count(*) FILTER (WHERE inv.inv_ss <> mat.mat_ss) AS disagree,
       count(*) FILTER (WHERE inv.material_code IS NULL) AS only_in_materials,
       count(*) FILTER (WHERE mat.material_code IS NULL) AS only_in_inventory,
       count(*) FILTER (WHERE inv.material_code IS NOT NULL
                              AND mat.material_code IS NOT NULL) AS in_both,
       count(*) FILTER (WHERE inv.available < inv.inv_ss) AS below_by_inventory,
       count(*) FILTER (WHERE inv.available < mat.mat_ss) AS below_by_materials,
       round(sum(GREATEST(mat.mat_ss - inv.available, 0)) FILTER (WHERE inv.available < mat.mat_ss), 1)
           AS shortfall_by_materials,
       round(sum(GREATEST(inv.inv_ss - inv.available, 0)) FILTER (WHERE inv.available < inv.inv_ss), 1)
           AS shortfall_by_inventory
FROM inv FULL JOIN mat ON mat.material_code = inv.material_code
"""

# 触发线那一把尺：与 warehouse_agent_service.on_stock_below_safety 用的是同一个条件，
# 这里只复算它的口径，不改它、也不替它兜底
TRIGGER_SQL = """
    SELECT count(*) AS below_trigger_line,
           count(*) FILTER (WHERE reorder_qty IS NULL OR reorder_qty = 0) AS no_reorder_qty,
           count(*) FILTER (WHERE reorder_point IS NULL) AS no_reorder_point,
           count(*) FILTER (WHERE safety_stock IS NULL) AS no_inventory_safety
    FROM inventory
    WHERE factory_id = :fid AND available_qty >= 0
      AND available_qty <= COALESCE(reorder_point, safety_stock, 10)
"""

CONFIG_TABLE_SQL = "SELECT count(*) AS n FROM safety_stock_config WHERE factory_id = :fid"

TOP_GAP_SQL = """
WITH inv AS (SELECT material_code, min(safety_stock) AS inv_ss, sum(available_qty) AS available
             FROM inventory WHERE factory_id = :fid GROUP BY 1),
mat AS (SELECT material_code, safety_stock::numeric AS mat_ss
        FROM materials WHERE factory_id = :fid AND safety_stock IS NOT NULL)
SELECT inv.material_code, inv.inv_ss AS by_inventory, mat.mat_ss AS by_materials,
       round(inv.available, 1) AS available, abs(inv.inv_ss - mat.mat_ss) AS gap
FROM inv JOIN mat ON mat.material_code = inv.material_code
WHERE inv.inv_ss <> mat.mat_ss
ORDER BY abs(inv.inv_ss - mat.mat_ss) DESC, inv.material_code LIMIT :limit
"""

# 自动补货开出去的单，与引擎当前缺口是否对得上：只看水位不看需求会开出"没人要"的单
AUTO_PR_SQL = """
WITH pr AS (
    SELECT material_code, sum(requested_qty) AS asked, count(*) AS lines,
           max(created_at)::date AS last_created
    FROM purchase_requests WHERE factory_id = :fid GROUP BY 1),
gap AS (
    SELECT m.material_code, sum(GREATEST(COALESCE(m.shortage_qty, 0), 0)) AS need
    FROM work_order_materials m JOIN work_orders o ON o.id = m.work_order_id
    WHERE o.factory_id = :fid GROUP BY 1
    HAVING sum(GREATEST(COALESCE(m.shortage_qty, 0), 0)) > 0)
SELECT (SELECT count(*) FROM pr) AS pr_materials,
       (SELECT coalesce(sum(lines), 0) FROM pr) AS pr_lines,
       (SELECT coalesce(sum(asked), 0) FROM pr) AS pr_units,
       (SELECT count(*) FROM pr WHERE EXISTS (SELECT 1 FROM gap g WHERE g.material_code = pr.material_code)
                                  OR EXISTS (SELECT 1 FROM work_order_materials m
                                             WHERE m.material_code = pr.material_code)) AS pr_in_kit_universe,
       (SELECT count(*) FROM gap) AS gap_materials,
       (SELECT coalesce(round(sum(need)), 0) FROM gap) AS gap_units,
       (SELECT count(*) FROM gap g WHERE NOT EXISTS
            (SELECT 1 FROM pr p WHERE p.material_code = g.material_code)) AS gap_without_request,
       (SELECT count(*) FROM pr p WHERE NOT EXISTS
            (SELECT 1 FROM gap g WHERE g.material_code = p.material_code)) AS request_without_gap,
       (SELECT max(last_created) FROM pr) AS last_created
"""

# 缺口但一条单都没开的料号清单：取数口只有一个（下面的 WORKLIST_SQL / gap_universe），
# 合计与分档都从同一批行里算，不再各跑各的两条 SQL。
# 本厂实测：一次取全量 1.5s（旧口径的合计+清单两条要 3.0s），676 行。


def _as_number(value):
    return None if value is None else float(value)


async def gap_universe(db: AsyncSession, factory_id: str) -> List[Dict[str, Any]]:
    """"真缺口却没开过单"的料号全集，一次取数，逐条带着"还缺哪几格"。

    缺口那一格（合计）与活清单那一格（分档）都从这里取，所以两格的数出自同一次查询 ——
    以前各跑各的两条 SQL，隔两秒引擎重算齐套行就会出现两格数字打脸。
    本厂实测一次约 2 秒（12 万行齐套展开 + 每件对照物料主数据与镜像件号）。
    """
    rows = (await db.execute(text(WORKLIST_SQL), {"fid": factory_id})).mappings().all()
    items: List[Dict[str, Any]] = []
    for r in rows:
        item = {"material_code": str(r["material_code"]),
                "material_name": (str(r["material_name"]) if r["material_name"] else None),
                "shortage_units": _as_number(r["need"]) or 0.0,
                "work_order_lines": int(r["work_orders"] or 0),
                "has_material_master_row": bool(r["has_master_row"]),
                "supplier": (str(r["default_supplier"]) if r["default_supplier"] else None),
                "lead_time_days": _as_number(r["lead_time_days"]),
                "unit_cost": _as_number(r["unit_cost"]),
                "inventory_rows": int(r["inv_rows"] or 0),
                "products_named": int(r["named_products"] or 0),
                "units_on_work_orders_without_product": _as_number(r["units_unattributed"]) or 0.0,
                "waiting_for": (str(r["named_units"]) if r["named_units"] else None)}
        item["ready_to_act"] = True  # 先占位，下面统一按缺项判
        item["missing_items"] = _gap_missing(item)
        item["ready_to_act"] = not item["missing_items"]
        item["missing_label"] = _combo_label(item["missing_items"])
        items.append(item)
    return items


def _backlog_item(i: Dict[str, Any]) -> Dict[str, Any]:
    """缺口那一格对外只给这几列（活清单还带分档，两处字段名保持同源）。"""
    return {"material_code": i["material_code"], "shortage_units": i["shortage_units"],
            "work_orders": i["work_order_lines"], "material_name": i["material_name"],
            "lead_time_days": i["lead_time_days"], "supplier": i["supplier"],
            "unit_cost": i["unit_cost"], "has_material_master_row": i["has_material_master_row"],
            "ready_to_act": i["ready_to_act"]}


async def shortage_backlog(db: Optional[AsyncSession], factory_id: str, *, limit: int = 12,
                           rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """真缺口却没开过单的料号：能催的排前面，催不动的点名缺哪一项主数据。

    这一格只列台账：`purchase_requests` 里没出现过的料号才进清单，
    金额只在三项齐（供应商+提前期+单价）时才给，缺单价的条目不折算成钱。
    """
    items = rows if rows is not None else await gap_universe(db, factory_id)  # type: ignore[arg-type]
    ordered = sorted(items, key=lambda i: not i["ready_to_act"])  # 稳定排序：可催的先列，各自保持缺口件数序
    result = {"parts": len(items),
              "units": round(sum(float(i["shortage_units"] or 0) for i in items), 1),
              "work_order_lines": sum(int(i["work_order_lines"]) for i in items),
              "without_master_row": len([i for i in items if not i["has_material_master_row"]]),
              "without_supplier": len([i for i in items if not i["supplier"]]),
              "without_lead": len([i for i in items if i["lead_time_days"] is None]),
              "without_cost": len([i for i in items
                                   if i["unit_cost"] is None or i["unit_cost"] <= 0]),
              "ready_to_act": len([i for i in items if i["ready_to_act"]]),
              "items": [_backlog_item(i) for i in ordered[:max(1, int(limit))]]}
    # 「可催的那几条单价是不是也只有几个值」要用这几条自己算，不能拿全厂普查顶
    priced = [i for i in items if i["ready_to_act"] and i["unit_cost"] is not None]
    if priced:
        counts: Dict[float, int] = {}
        for i in priced:
            counts[i["unit_cost"]] = counts.get(i["unit_cost"], 0) + 1
        top_cost, top_n = max(counts.items(), key=lambda kv: kv[1])
        result["ready_cost_census"] = {
            "rows_sampled": len(priced), "rows_ready": result["ready_to_act"],
            "complete": len(priced) >= result["ready_to_act"],
            "distinct_values": len(counts), "mode_value": top_cost,
            "mode_share": round(top_n / len(priced), 3)}
    return result


def _units(value: Any) -> str:
    """件数别用 :g —— 4.23767e+06 不是人读的数，现场要能一眼看出量级。"""
    v = float(value or 0)
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


# ── 活清单：同一批"真缺口却没开单"的料号，换个问法 ────────────────────────────
# 缺口那一格报的是"差多少件"，这一格报的是"催这一单还差哪一格、填哪一格能解锁多少件"，
# 以及最要紧的一句：**供应商这一列能不能从台账里回填**。
#
# WORKLIST_SQL 是这批料号的唯一取数口：一次取全量（本厂 676 行，实测 1.5 秒），
# shortage_backlog 的合计和 master_data_worklist 的分档都从同一批行里算 ——
# 两格的数必须来自同一次取数，否则会出现"缺口说 676、活清单说 674"这种互相打脸。
_GAP_CTE = """
WITH gap_lines AS (
    SELECT m.material_code, o.id AS work_order_id, o.product_id,
           GREATEST(COALESCE(m.shortage_qty, 0), 0) AS need
    FROM work_order_materials m JOIN work_orders o ON o.id = m.work_order_id
    WHERE o.factory_id = :fid
      AND GREATEST(COALESCE(m.shortage_qty, 0), 0) > 0),
naked AS (
    SELECT gl.* FROM gap_lines gl WHERE NOT EXISTS
        (SELECT 1 FROM purchase_requests p WHERE p.material_code = gl.material_code)),
per_part AS (SELECT material_code, sum(need) AS need, count(DISTINCT work_order_id) AS work_orders
             FROM naked GROUP BY 1),
"""

WORKLIST_SQL = _GAP_CTE + """prod AS (SELECT nl.material_code,
                  coalesce(pr.product_code, '（工单没写成品号）') AS product_code,
                  sum(nl.need) AS units
           FROM naked nl LEFT JOIN products pr ON pr.id = nl.product_id
           GROUP BY 1, 2),
prod_ranked AS (SELECT material_code, product_code, units,
                       row_number() OVER (PARTITION BY material_code
                                          ORDER BY units DESC, product_code) AS rn,
                       sum(CASE WHEN product_code = '（工单没写成品号）' THEN 0 ELSE 1 END)
                           OVER (PARTITION BY material_code) AS named_products
                FROM prod),
prod_agg AS (SELECT material_code, max(named_products) AS named_products,
                    sum(units) FILTER (WHERE product_code = '（工单没写成品号）') AS units_unattributed,
                    string_agg(CASE WHEN rn <= 3 AND product_code <> '（工单没写成品号）'
                                    THEN product_code || ':' || round(units)::text END,
                               ' / ' ORDER BY rn) AS named_units
             FROM prod_ranked GROUP BY 1),
inv AS (SELECT material_code, min(unit_cost) AS unit_cost, count(*) AS inv_rows
        FROM inventory WHERE factory_id = :fid GROUP BY 1)
SELECT pp.material_code, round(pp.need) AS need, pp.work_orders,
       (t.material_code IS NOT NULL) AS has_master_row, t.material_name,
       t.default_supplier, t.lead_time_days, i.unit_cost, coalesce(i.inv_rows, 0) AS inv_rows,
       coalesce(pa.named_products, 0) AS named_products,
       coalesce(pa.units_unattributed, 0) AS units_unattributed, pa.named_units
FROM per_part pp
LEFT JOIN materials t ON t.material_code = pp.material_code AND t.factory_id = :fid
LEFT JOIN inv i ON i.material_code = pp.material_code
LEFT JOIN prod_agg pa ON pa.material_code = pp.material_code
ORDER BY pp.need DESC, pp.work_orders DESC, pp.material_code
"""

# 能记着"这个料号由谁供"的出处，厂里一共这几张表。逐出处回答两件事：
# ① 这张表自己有没有记过供应商（出处级普查，不靠料号）；② 把它点名的那些料号
# 拿来跟"缺供应商的缺口料号"求交 —— 交集才是"能回填"。第②步用 :codes 传已取出的
# 料号数组，所以这条查询不会重跑齐套展开（那是 2 秒的那条）。
SUPPLIER_SOURCE_SQLS = (
    ("purchase_orders.supplier_name",
     "SELECT material_code AS code, coalesce(supplier_name, '') <> '' AS has_value "
     "FROM purchase_orders WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("purchase_requests.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM purchase_requests "
     "WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("purchase_requisitions.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM purchase_requisitions "
     "WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("arrival_plans.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM arrival_plans "
     "WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("goods_receipts.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM goods_receipts "
     "WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("inbound_orders.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM inbound_orders "
     "WHERE factory_id = :fid AND material_code IS NOT NULL"),
    ("supplier_materials.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM supplier_materials "
     "WHERE material_code IS NOT NULL"),
    ("supplier_prices.supplier_id",
     "SELECT material_code, supplier_id IS NOT NULL FROM supplier_prices "
     "WHERE material_code IS NOT NULL"),
    ("bom_items.vendor_name",
     "SELECT material_code, coalesce(vendor_name, '') <> '' FROM bom_items "
     "WHERE material_code IS NOT NULL"),
)

# 每段 body 本身以 SELECT 开头，这里只补出处标签列：先剥掉前导 SELECT 再拼，
# 否则会写成 SELECT '标签' AS s, SELECT … 这种语法错（列名由 src(...) 的 CTE 声明给出）。
_SCAN_BRANCHES = "\n    UNION ALL\n".join(
    f"    SELECT '{label}' AS s, {body.split('SELECT', 1)[1].lstrip()}"
    for label, body in SUPPLIER_SOURCE_SQLS)

SUPPLIER_SCAN_SQL = """
WITH src(s, code, has_value) AS (
{branches}
),
per_code AS (SELECT s, code, bool_or(has_value) AS any_value FROM src GROUP BY 1, 2),
totals AS (SELECT s, count(*) AS codes_in_source,
                  count(*) FILTER (WHERE any_value) AS codes_with_value
           FROM per_code GROUP BY 1),
hits AS (SELECT s, code, any_value FROM per_code
         WHERE code = ANY(CAST(:codes AS text[])))
SELECT t.s AS source, t.codes_in_source, t.codes_with_value,
       coalesce(array_agg(h.code) FILTER (WHERE h.code IS NOT NULL), '{{}}') AS seen_codes,
       coalesce(array_agg(h.code) FILTER (WHERE h.any_value), '{{}}') AS recoverable_codes
FROM totals t LEFT JOIN hits h ON h.s = t.s
GROUP BY 1, 2, 3 ORDER BY 1
""".format(branches=_SCAN_BRANCHES)
# 排序放在 Python 里做：Postgres 的 ORDER BY 只认输出列名当"简单排序键"，
# 写成 array_length(recoverable_codes,1) 会报 column recoverable_codes does not exist；
# 而在 SQL 里重抄一遍 array_agg 表达式既难读又没法被单测钉住。
#
# 并集不再单开一条查询：本厂实测那条和这条一样贵（各约 1.9 秒，都是把那 9 张表扫一遍），
# 而逐出处返回的 seen_codes/recoverable_codes 已经带着料号本身 —— 在 Python 里求并集就是
# 同一个数。少一条查询是一半，另一半是"同一件事只有一个出处"，否则会出现逐出处加起来 3 个、
# 并集那条说 2 个这种自己跟自己打脸。

# 镜像 BOM 那 48 万行单独判：整列有没有非空 vendor_name 是一次聚合就能定死的（实测 41ms），
# 若一个都没有，逐料号回填必然是 0 —— 那就没必要再花 2.4 秒逐料号查，但要把这个推理写在读法里
MIRROR_VENDOR_GATE_SQL = """
    SELECT count(*) AS rows_total,
           count(DISTINCT part_number) AS distinct_parts,
           count(*) FILTER (WHERE coalesce(vendor_name, '') <> '') AS rows_with_vendor,
           count(DISTINCT part_number) FILTER (WHERE coalesce(vendor_name, '') <> '') AS parts_with_vendor
    FROM enghub_bom_items WHERE factory_id = :fid
"""

SUPPLIER_MASTER_SQL = """
WITH m AS (SELECT default_supplier AS name FROM materials
           WHERE factory_id = :fid AND default_supplier IS NOT NULL)
SELECT (SELECT count(*) FROM suppliers WHERE factory_id = :fid) AS supplier_rows,
       (SELECT count(DISTINCT name) FROM m) AS names_on_materials,
       (SELECT count(DISTINCT name) FROM m mm WHERE NOT EXISTS
            (SELECT 1 FROM suppliers s WHERE s.factory_id = :fid AND s.supplier_name = mm.name)
        ) AS dangling_names,
       (SELECT count(*) FROM m mm WHERE NOT EXISTS
            (SELECT 1 FROM suppliers s WHERE s.factory_id = :fid AND s.supplier_name = mm.name)
        ) AS rows_with_dangling_name
"""

SUPPLIER_DANGLING_SQL = """
SELECT m.default_supplier AS name, count(*) AS material_rows
FROM materials m
WHERE m.factory_id = :fid AND m.default_supplier IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM suppliers s
                  WHERE s.factory_id = m.factory_id AND s.supplier_name = m.default_supplier)
GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT :limit
"""

SUPPLIER_NAMES_SQL = "SELECT supplier_name FROM suppliers WHERE factory_id = :fid"

MASTER_COLUMNS = {"supplier": "materials.default_supplier",
                  "lead": "materials.lead_time_days",
                  "cost": "inventory.unit_cost"}
COLUMN_SHORT = {"supplier": "供应商", "lead": "提前期", "cost": "单价"}


def _combo_label(keys: List[str]) -> str:
    if not keys:
        return "三项齐 —— 今天就能开单/催单"
    if keys == ["no_master_row"]:
        return "物料主数据没这条 —— 要先建档，不是填一列"
    return "差" + "+".join(COLUMN_SHORT[k] for k in keys)


def _gap_missing(item: Dict[str, Any]) -> List[str]:
    """一个料号还差哪几格。主数据行不存在是另一档：那不是填一列，是建这条档。"""
    if not item["has_material_master_row"]:
        return ["no_master_row"]
    missing = []
    if not item["supplier"]:
        missing.append("supplier")
    if item["lead_time_days"] is None:
        missing.append("lead")
    if item["unit_cost"] is None or item["unit_cost"] <= 0:
        missing.append("cost")
    return missing


async def master_data_worklist(db: AsyncSession, factory_id: str, *,
                               limit: int = 12, dangling_examples: int = 5,
                               rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """缺口料号的催单前置条件清单：差哪几格、填哪一格能解锁多少件、供应商能不能回填。

    只读台账。不写 materials/inventory/purchase_requests，也不替缺口料号编供应商 ——
    判"回填不了"用的是逐个出处的普查，不是"没查到"。
    """
    items_all = rows if rows is not None else await gap_universe(db, factory_id)

    def _sum(key: str, subset: List[Dict[str, Any]]) -> float:
        return round(sum(float(x[key] or 0) for x in subset), 1)

    combos: Dict[tuple, Dict[str, Any]] = {}
    for it in items_all:
        bucket = combos.setdefault(tuple(it["missing_items"]), {
            "missing_items": list(it["missing_items"]), "label": it["missing_label"],
            "parts": 0, "units": 0.0, "work_order_lines": 0})
        bucket["parts"] += 1
        bucket["units"] += float(it["shortage_units"] or 0)
        bucket["work_order_lines"] += int(it["work_order_lines"])
    grades = sorted(combos.values(), key=lambda g: (-g["units"], g["label"]))
    for g in grades:
        g["units"] = round(g["units"], 1)

    columns = []
    for key, column in MASTER_COLUMNS.items():
        hit = [i for i in items_all if key in i["missing_items"]]
        only = [i for i in items_all if i["missing_items"] == [key]]
        columns.append({"column": column,
                        "parts_missing": len(hit), "units_missing": _sum("shortage_units", hit),
                        "work_order_lines_missing": sum(i["work_order_lines"] for i in hit),
                        "parts_only_this_missing": len(only),
                        "units_only_this_missing": _sum("shortage_units", only),
                        "who_fills": ("采购选供应商（引擎不代填）" if key == "supplier" else
                                      ("物料主数据的提前期声明" if key == "lead" else
                                       "库存/成本那条链的单价"))})

    # 与缺口那一格的 without_supplier 同一条判据：没声明供应商 = 该列空或整条主数据行不存在
    nosup_items = [i for i in items_all if not i["supplier"]]
    codes = [i["material_code"] for i in nosup_items]
    need_by_code = {i["material_code"]: float(i["shortage_units"] or 0) for i in nosup_items}
    # 没有要回填的对象就不跑：那条普查是把 9 张表各扫一遍（本厂实测约 1.9 秒），
    # 与传进去的料号多少无关 —— 空数组也照付全款，那就更不能白付。
    scan = ((await db.execute(text(SUPPLIER_SCAN_SQL),
                              {"fid": factory_id, "codes": codes})).mappings().all()
            if codes else [])
    gate = (await db.execute(text(MIRROR_VENDOR_GATE_SQL), {"fid": factory_id})).mappings().first()

    def _code_list(value) -> List[str]:
        return [str(c) for c in (value or []) if c is not None]

    def _units_of(codes_list: List[str]) -> float:
        return round(sum(need_by_code.get(c, 0.0) for c in codes_list), 1)

    def _union(key: str) -> List[str]:
        """并集在已取回的逐出处行上算，不再单开一条同样扫 9 张表的查询。"""
        acc = set()
        for s in scan:
            acc.update(_code_list(s[key]))
        return sorted(acc)

    sources = [{"source": str(s["source"]), "codes_in_source": int(s["codes_in_source"] or 0),
                "codes_with_value": int(s["codes_with_value"] or 0),
                "nosup_parts_seen": len(_code_list(s["seen_codes"])),
                "seen_units": _units_of(_code_list(s["seen_codes"])),
                "recoverable_parts": len(_code_list(s["recoverable_codes"])),
                "recoverable_units": _units_of(_code_list(s["recoverable_codes"]))}
               for s in scan]
    # 能回填的排前面、其次是在该出处真出现过的料号数 —— 排序放这里才能被单测钉住
    sources.sort(key=lambda x: (-x["recoverable_parts"], -x["nosup_parts_seen"], x["source"]))
    seen_union = _union("seen_codes")
    union_recoverable = _union("recoverable_codes")
    mirror_rows = int((gate or {}).get("rows_total") or 0)
    mirror_with_vendor = int((gate or {}).get("rows_with_vendor") or 0)
    backfill = {
        "parts_without_supplier": len(nosup_items),
        "units_without_supplier": _sum("shortage_units", nosup_items),
        "parts_seen_in_any_source": len(seen_union),
        "recoverable_parts": len(union_recoverable),
        "recoverable_units": _units_of(union_recoverable),
        "recoverable_material_codes": union_recoverable[:20],
        "sources_scanned": len(sources) + 1,      # +1 = 镜像 BOM 那一条出处级判定
        "scan_ran": bool(codes),
        "scan_why_skipped": (None if codes else
                             "本厂缺口料号没有一个缺供应商，逐出处普查没跑（跑了也是白扫 9 张表）"),
        "sources": sources,
        "mirror_bom": {"rows_total": mirror_rows,
                       "distinct_parts": int((gate or {}).get("distinct_parts") or 0),
                       "rows_with_vendor_name": mirror_with_vendor,
                       "distinct_parts_with_vendor_name": int((gate or {}).get("parts_with_vendor") or 0),
                       "judged_at": "出处级",
                       "why_not_per_part": (
                           f"镜像 {mirror_rows} 行里 vendor_name 有值的是 {mirror_with_vendor} 行"
                           + ("，所以逐料号回填必然是 0，不必再按料号去扫这 48 万行"
                              if mirror_with_vendor == 0 else "，逐料号可回填数见 sources"))},
        "verdict": ("nothing_to_backfill" if not codes else
                    ("no_record_names_a_supplier" if not union_recoverable
                     else "partially_recoverable")),
    }

    master = (await db.execute(text(SUPPLIER_MASTER_SQL), {"fid": factory_id})).mappings().first()
    dangling = (await db.execute(text(SUPPLIER_DANGLING_SQL),
                                 {"fid": factory_id, "limit": max(1, int(dangling_examples))})
                ).mappings().all()
    known = {str(n["supplier_name"]) for n in
             (await db.execute(text(SUPPLIER_NAMES_SQL), {"fid": factory_id})).mappings().all()}
    gap_declared = [i for i in items_all if i["supplier"]]
    gap_dangling = [i for i in gap_declared if i["supplier"] not in known]
    supplier_master = {
        "supplier_rows": int((master or {}).get("supplier_rows") or 0),
        "distinct_names_on_materials": int((master or {}).get("names_on_materials") or 0),
        "names_not_in_supplier_master": int((master or {}).get("dangling_names") or 0),
        "material_rows_with_dangling_name": int((master or {}).get("rows_with_dangling_name") or 0),
        "dangling_examples": [{"supplier_name": str(d["name"]),
                               "material_rows": int(d["material_rows"] or 0)} for d in dangling],
        "gap_parts_declaring_supplier": len(gap_declared),
        "gap_parts_with_dangling_supplier": len(gap_dangling),
        "supplier_names": sorted(known),
    }

    product_attribution = {
        "units_on_work_orders_without_product": _sum("units_on_work_orders_without_product", items_all),
        "parts_fully_unattributed": len([i for i in items_all if i["products_named"] == 0]),
        "note": "『（工单没写成品号）』= work_orders.product_id 为空，报不成机型，只能按工单行计"}

    reading: List[str] = []
    if not items_all:
        reading.append(
            "这一格没有条目：要么当前没有 shortage_qty>0 的工单行，要么每个缺口料号都已经在 "
            "purchase_requests 里出现过 —— 两种都不是『库存正常』，得回到缺口那一格看是哪个")
    else:
        reading.append(
            "催单前置条件分档（同一批料号，按还差哪几格分）：" + "；".join(
                f"{g['label']} {g['parts']} 个 / {_units(g['units'])} 件"
                f"（{g['work_order_lines']} 个工单行）" for g in grades[:4])
            + (f"；另有 {len(grades) - 4} 档更少，没列" if len(grades) > 4 else ""))
        one_col = [c for c in columns if c["parts_only_this_missing"]]
        reading.append(
            "只填一列就能催单的料号："
            + ("、".join(f"{c['column']} {c['parts_only_this_missing']} 个/"
                         f"{_units(c['units_only_this_missing'])} 件" for c in one_col)
               if one_col else f"0 个 —— 三列（{('、'.join(MASTER_COLUMNS.values()))}）"
               f"里没有一个料号是只差其中一列的，所以『补上供应商就能下单』这条推理在本厂不成立；"
               f"缺供应商的 {backfill['parts_without_supplier']} 个料号同时还缺别的"))
        if not backfill["scan_ran"]:
            reading.append(
                "供应商这一列不用回填：本厂缺口料号没有一个缺供应商，所以逐出处普查没跑"
                f"（镜像 BOM {backfill['mirror_bom']['rows_total']} 行里 vendor_name 有值的是 "
                f"{backfill['mirror_bom']['rows_with_vendor_name']} 行）—— "
                "这一格的 0 是『没有对象』，不是『查了没有』")
        else:
            reading.append(
                f"供应商这一列能不能从台账回填：扫了 {backfill['sources_scanned']} 个出处"
                f"（{'、'.join(s['source'] for s in backfill['sources'][:5])} 等），"
                f"能回填的料号 {backfill['recoverable_parts']} 个 / "
                f"{_units(backfill['recoverable_units'])} 件；"
                + (f"镜像 BOM {backfill['mirror_bom']['rows_total']} 行里 vendor_name 有值的是 "
                   f"{backfill['mirror_bom']['rows_with_vendor_name']} 行 —— "
                   "参照厂那套 BOM 本来就没带供应商，所以这不是『我没查到』，是无处可查"
                   if backfill["mirror_bom"]["rows_with_vendor_name"] == 0 else
                   f"镜像里 {backfill['mirror_bom']['rows_with_vendor_name']} 行带 vendor_name，"
                   "可逐料号核对"))
        sm = supplier_master
        dangling_egs = "、".join(f"{d['supplier_name']} {d['material_rows']} 行"
                                 for d in sm["dangling_examples"][:3])
        reading.append(
            f"要填也得先有得选：suppliers 本厂 {sm['supplier_rows']} 行，"
            f"物料上写了 {sm['distinct_names_on_materials']} 个供应商名，其中 "
            f"{sm['names_not_in_supplier_master']} 个在这 {sm['supplier_rows']} 行里不存在"
            f"（涉及 {sm['material_rows_with_dangling_name']} 行物料"
            + (f"，例：{dangling_egs}" if dangling_egs else "")
            + f"）；缺口清单里已声明供应商的 {sm['gap_parts_declaring_supplier']} 个料号里，"
            f"有 {sm['gap_parts_with_dangling_supplier']} 个指向的就是这种悬空名")
        pa = product_attribution
        reading.append(
            f"这些缺口挂在哪些机上：{len([i for i in items_all if i['waiting_for']])} 个料号能报到成品号"
            f"（清单里每行 waiting_for 给了最多 3 个，带各自件数），"
            f"{pa['parts_fully_unattributed']} 个料号一条都报不出机型 —— "
            f"{_units(pa['units_on_work_orders_without_product'])} 件缺口挂在 "
            "work_orders.product_id 为空的工单上，这一格按工单行计，不假装知道是哪台机要的")
    return {"universe": {"parts": len(items_all), "units": _sum("shortage_units", items_all),
                         "work_order_lines": sum(i["work_order_lines"] for i in items_all),
                         "basis": "work_order_materials.shortage_qty>0 且该料号在 purchase_requests 里没出现过"},
            "can_expedite_today": len([i for i in items_all if not i["missing_items"]]),
            "grades": grades, "columns": columns,
            "no_master_row_parts": len([i for i in items_all if not i["has_material_master_row"]]),
            "supplier_backfill": backfill, "supplier_master": supplier_master,
            "cost_placeholders": {
                "parts_without_inventory_row": len([i for i in items_all if i["inventory_rows"] == 0]),
                "parts_with_zero_cost": len([i for i in items_all
                                             if i["unit_cost"] is not None and i["unit_cost"] <= 0]),
                "note": "没库存行的料号连单价的出处都没有，这一格不给金额"},
            "product_attribution": product_attribution,
            "items": items_all[:max(1, int(limit))],
            "items_are": f"前 {min(len(items_all), max(1, int(limit)))} 行，按缺口件数、影响工单行排",
            "rows_total": len(items_all), "reading": reading}


def classify_source(name: str, row: Dict[str, Any], mode_share: float) -> Dict[str, Any]:
    """一处声明一个判定：取值少 + 众数扎堆 = 模板铺的，不是逐料号决定的。"""
    distinct = int(row.get("distinct_values") or 0)
    rows_total = int(row.get("rows_total") or 0)
    template = mode_share >= TEMPLATE_MIN_MODE_SHARE
    coarse = (not template) and 0 < distinct <= TEMPLATE_MAX_DISTINCT
    return {
        "source": name,
        "rows": rows_total,
        "distinct_values": distinct,
        "mode_value": (float(row["mode_value"]) if row.get("mode_value") is not None else None),
        "mode_share": round(mode_share, 3),
        "nulls": int(row.get("nulls") or 0),
        "zeros": int(row.get("zeros") or 0),
        "verdict": ("template_default" if template else
                    ("coarse_default" if coarse else "declared_per_item")),
        "why": (f"{rows_total} 行、{distinct} 个取值、众数 {row.get('mode_value')} 占 {mode_share:.1%} —— "
                + ("绝大多数料号共用同一个数，这是模板铺的默认值，不是逐料号决定的安全库存；"
                   "拿它报警就是把模板当事实" if template else
                   ("取值只有几个，等于按档铺的粗默认值，同样不能逐料号使用" if coarse else
                    "分布不支持『模板铺的』这个判断，可按声明使用"))),
    }


async def _mode_share(db: AsyncSession, table: str, fid: str) -> float:
    """众数占比：只在白名单表名里拼字符串，别把外部输入接到 SQL 上。"""
    if table not in ("inventory", "materials"):
        raise ValueError(f"unknown safety-stock source table: {table}")
    rows = (await db.execute(text(MODE_SHARE_SQL.format(table=table)),
                             {"fid": fid})).mappings().all()
    if not rows:
        return 0.0
    total = sum(int(r["n"]) for r in rows)
    top = sum(int(r["n"]) for r in rows[:1])
    return (top / total) if total else 0.0

# 单价本身是不是也是铺的：只有几个取值就不能拿它算金额
COST_CENSUS_SQL = """
    SELECT count(DISTINCT unit_cost) AS distinct_values,
           mode() WITHIN GROUP (ORDER BY unit_cost) AS mode_value,
           count(*) AS filled
    FROM inventory WHERE factory_id = :fid AND unit_cost IS NOT NULL
"""


async def cost_basis(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """`inventory.unit_cost` 的取值普查：铺出来的价格不能拿来折算金额。"""
    row = (await db.execute(text(COST_CENSUS_SQL), {"fid": factory_id})).mappings().first()
    if not row:
        return {"distinct_values": 0, "mode_share": 0.0, "verdict": "no_cost_data"}
    distinct = int(row["distinct_values"] or 0)
    total = int(row["filled"] or 0)
    share = 0.0
    if total and distinct:
        top = (await db.execute(text("""
            SELECT count(*) AS n FROM inventory
            WHERE factory_id = :fid AND unit_cost = (
                SELECT mode() WITHIN GROUP (ORDER BY unit_cost) FROM inventory
                WHERE factory_id = :fid AND unit_cost IS NOT NULL)"""),
            {"fid": factory_id})).mappings().first()
        share = float((top or {}).get("n") or 0) / total
    zero_share = 0.0
    if total:
        zr = (await db.execute(text("""
            SELECT count(*) FILTER (WHERE unit_cost = 0) AS z,
                   count(*) FILTER (WHERE unit_cost > 0) AS pos
            FROM inventory WHERE factory_id = :fid AND unit_cost IS NOT NULL"""),
            {"fid": factory_id})).mappings().first()
        zero_share = float((zr or {}).get("z") or 0) / total
    template = distinct <= TEMPLATE_MAX_DISTINCT and share >= TEMPLATE_MIN_MODE_SHARE
    return {"zero_cost_rows_share": round(zero_share, 3), "filled_rows_real": None,
            "distinct_values": distinct, "filled_rows": total,
            "mode_value": (float(row["mode_value"]) if row["mode_value"] is not None else None),
            "mode_share": round(share, 3),
            "verdict": ("template_default" if template else "declared_per_item"),
            "why": (f"全厂 {total} 行有单价，只有 {distinct} 个取值、众数 "
                    f"{float(row['mode_value'] or 0):g} 占 {share:.1%}"
                    + (f"，其中 {zero_share:.1%} 的行单价是 0（等于没填价）" if zero_share else "")
                    + " ——" + ("这是铺出来的价，能填表不能算钱" if template
                               else "取值分布支持按声明使用"))}

async def safety_stock_authority(db: Optional[AsyncSession], factory_id: str, *,
                                 examples: int = 5, backlog_limit: int = 12,
                                 worklist_limit: int = 0) -> Dict[str, Any]:
    """两处声明 + 四条尺的实测对照，结论是"该拍哪条"，不是一个假告警数。"""
    if db is None:
        return {"status": "no_session",
                "reading": ["没有数据库会话：两处声明谁作准、各把尺报多少都算不出"]}

    inv = dict((await db.execute(text(INV_CENSUS_SQL), {"fid": factory_id})).mappings().first() or {})
    mat = dict((await db.execute(text(MAT_CENSUS_SQL), {"fid": factory_id})).mappings().first() or {})
    sources = [
        classify_source("inventory.safety_stock", inv, await _mode_share(db, "inventory", factory_id)),
        classify_source("materials.safety_stock", mat, await _mode_share(db, "materials", factory_id)),
    ]

    joined = dict((await db.execute(text(DISAGREE_SQL), {"fid": factory_id})).mappings().first() or {})
    trigger = dict((await db.execute(text(TRIGGER_SQL), {"fid": factory_id})).mappings().first() or {})
    config_rows = int((await db.execute(text(CONFIG_TABLE_SQL), {"fid": factory_id})).scalar() or 0)
    raw_auto = (await db.execute(text(AUTO_PR_SQL), {"fid": factory_id})).mappings().first()
    # 同样逐字段转 Python 原生类型：这里的数会进 chat_messages 的 jsonb
    auto = {}
    for key, value in dict(raw_auto or {}).items():
        if key == "last_created":
            auto[key] = str(value) if value is not None else None
        elif value is None:
            auto[key] = 0
        elif isinstance(value, bool):
            auto[key] = value
        else:
            try:
                auto[key] = float(value)
            except (TypeError, ValueError):
                auto[key] = str(value)
    for count_key in ("pr_materials", "pr_lines", "pr_in_kit_universe", "gap_materials",
                      "gap_without_request", "request_without_gap"):
        auto[count_key] = int(auto.get(count_key) or 0)

    samples = [{"material_code": str(r["material_code"]),
                "by_inventory": float(r["by_inventory"] or 0),
                "by_materials": float(r["by_materials"] or 0),
                "available": float(r["available"] or 0),
                "gap": float(r["gap"] or 0)}
               for r in (await db.execute(text(TOP_GAP_SQL), {"fid": factory_id, "limit": max(1, examples)}))
               .mappings().all()]

    rulers = [
        {"ruler": "补货触发线（warehouse_agent 用的那条）", "grain": "行级（一个仓一行）",
         "condition": "available_qty <= COALESCE(reorder_point, safety_stock, 10)",
         "alerts": int(trigger.get("below_trigger_line") or 0),
         "basis": "inventory.reorder_point（缺时退 inventory.safety_stock，再缺退硬编码 10 —— "
                  "本厂两类空值各有几条见 trigger_fallbacks）"},
        {"ruler": "按 inventory.safety_stock 比（料号级）", "grain": "料号级",
         "condition": "sum(available_qty) < min(inventory.safety_stock) 跨该料号的各仓",
         "alerts": int(joined.get("below_by_inventory") or 0),
         "basis": f"inventory.safety_stock（众数 {sources[0]['mode_value']:g}，"
                  f"判定 {sources[0]['verdict']}）"},
        {"ruler": "按 materials.safety_stock 比（料号级）", "grain": "料号级",
         "condition": "sum(available_qty) < materials.safety_stock",
         "alerts": int(joined.get("below_by_materials") or 0),
         "basis": f"materials.safety_stock（众数 {sources[1]['mode_value']:g}，"
                  f"判定 {sources[1]['verdict']}）"},
        {"ruler": "safety_stock_config 那张专用配置表", "grain": "配置表",
         "condition": "safety_stock_config（stock_alert_service 读它）",
         "alerts": 0,
         "basis": f"本厂 {config_rows} 行 —— 空表不等于『没有要补的料』，"
                  "而是这条链根本没接上主数据"},
    ]

    disagree = int(joined.get("disagree") or 0)
    both = int(joined.get("in_both") or 0)
    counts = [r["alerts"] for r in rulers[:3]]
    spread = (round(max(counts) / min([c for c in counts if c > 0]), 2)
              if any(c > 0 for c in counts) else None)

    out = {
        "status": "ok", "factory_id": factory_id, "sources": sources, "rulers": rulers,
        "disagreement": {"materials_in_both": both,
                         "only_in_inventory": int(joined.get("only_in_inventory") or 0),
                         "only_in_materials": int(joined.get("only_in_materials") or 0),
                         "disagree": disagree,
                         "disagree_share": round(disagree / both, 4) if both else None,
                         "widest_examples": samples},
        "config_table_rows": config_rows,
        "trigger_fallbacks": {
            "no_reorder_point": int(trigger.get("no_reorder_point") or 0),
            "no_inventory_safety": int(trigger.get("no_inventory_safety") or 0),
            "no_reorder_qty": int(trigger.get("no_reorder_qty") or 0)},
        "shortfall_units": {"by_inventory": (float(joined.get("shortfall_by_inventory") or 0)),
                            "by_materials": (float(joined.get("shortfall_by_materials") or 0))},
        "ruler_spread_x": spread,
        "auto_replenishment": auto,
        "reading": [], "claim_guard": "",
    }

    out["reading"] = [
        f"同一句『低于安全库存』按不同出处给出 {rulers[0]['alerts']} / {rulers[1]['alerts']} / "
        f"{rulers[2]['alerts']} 条（配置表那条：safety_stock_config 本厂 {config_rows} 行，报 0 条不是"
        "『都健康』，是这张表根本没被填）"
        + (f"；最大最小差 {spread:g} 倍" if spread else ""),
        "两处声明的模板判定：" + "；".join(
            f"{s['source']} 有 {s['rows']} 行 / {s['distinct_values']} 个取值、众数 "
            f"{s['mode_value']:g} 占 {s['mode_share']:.1%} → {s['verdict']}" for s in sources),
        (f"两表都有的 {both} 个料号里 {disagree} 个声明不一致"
         f"（{out['disagreement']['disagree_share']:.1%}）—— 最宽的几例：" + "、".join(
             f"{s['material_code']} inventory {s['by_inventory']:g} vs materials {s['by_materials']:g}"
             f"（当前可用 {s['available']:g}）" for s in samples[:3])
         if both else "没有两表都覆盖到的料号可比"),
        ("引擎不替厂里选哪张表作准：选 inventory 还是 materials 会让告警数从 "
         f"{min(counts) if counts else 0} 跳到 {max(counts) if counts else 0}，"
         "这不是精度问题而是口径问题。已挂成 /pmc/open-rule-questions 的 "
         "safety_stock_authority 待回答；要落成 stock_alerts 的动作也等这个口径拍定。"),
    ]
    pr_lines = int(auto.get("pr_lines") or 0)
    if pr_lines:
        out["reading"].append(
            f"已经开出去的自动补货：{pr_lines} 条 / {_units(auto.get('pr_units'))} 件"
            f"（最近一次 {auto.get('last_created')}），其中 "
            f"{auto.get('request_without_gap')} 个料号引擎当前并不缺、"
            f"{auto.get('pr_in_kit_universe')} 个料号出现在齐套结构里；"
            f"同期真缺口 {auto.get('gap_materials')} 个料号 / {_units(auto.get('gap_units'))} 件里，"
            f"{auto.get('gap_without_request')} 个一条单都没开 —— "
            "触发线只看库存水位、不看有没有工单要，所以两头都能错")
    backlog, backlog_error = None, None
    gap_rows, worklist, worklist_error = None, None, None
    try:
        gap_rows = await gap_universe(db, factory_id)
        backlog = await shortage_backlog(db, factory_id, limit=max(1, int(backlog_limit)),
                                         rows=gap_rows)
        cost = await cost_basis(db, factory_id)
        backlog["unit_cost_basis"] = cost
    except Exception as exc:  # noqa: BLE001
        backlog, backlog_error = None, type(exc).__name__ + ": " + str(exc)[:160]
    out["shortage_backlog"] = backlog
    out["shortage_backlog_error"] = backlog_error
    # 活清单要按料号逐条分档，还要跑逐出处普查（本厂实测约 1.9 秒，缺供应商的料号为 0 时不跑），
    # 所以默认不跑：要的出口显式传 worklist_limit（PMC 那一格、聊天工具、厂规问题都传）
    if int(worklist_limit or 0) > 0 and gap_rows is not None:
        try:
            worklist = await master_data_worklist(db, factory_id,
                                                  limit=max(1, int(worklist_limit)), rows=gap_rows)
        except Exception as exc:  # noqa: BLE001
            worklist, worklist_error = None, type(exc).__name__ + ": " + str(exc)[:160]
    out["master_data_worklist"] = worklist
    out["master_data_worklist_error"] = worklist_error
    if worklist:
        out["reading"] += worklist["reading"]
        if backlog is not None:
            agree = (int(backlog.get("parts") or 0) == int(worklist["universe"]["parts"])
                     and int(backlog.get("ready_to_act") or 0) == int(worklist["can_expedite_today"]))
            out["backlog_worklist_agreement"] = {
                "backlog_parts": int(backlog.get("parts") or 0),
                "worklist_parts": int(worklist["universe"]["parts"]),
                "backlog_ready": int(backlog.get("ready_to_act") or 0),
                "worklist_ready": int(worklist["can_expedite_today"]),
                "agree": agree,
                "why": "两格出自同一次 gap_universe 取数，所以数字必须一致；"
                       "不一致就是分档那一步算错了，不是数据在动"}
            if not agree:
                out["reading"].append(
                    "⚠ 缺口那一格和活清单这一格数不一致："
                    f"{out['backlog_worklist_agreement']['backlog_parts']} vs "
                    f"{out['backlog_worklist_agreement']['worklist_parts']} 个料号 —— "
                    "两格共用同一次取数却对不上，别引用这两格的数")
    if backlog and backlog.get("parts"):
        out["reading"].append(
            f"缺口却没开过单的料号：{backlog['parts']} 个 / {_units(backlog['units'])} 件"
            f"（挂在 {int(backlog['work_order_lines'])} 个工单行上），其中主数据三项齐、"
            f"今天就能去催的只有 {backlog['ready_to_act']} 个；"
            f"催不动的卡在缺料号自己的 {backlog['without_supplier']} 个没供应商、"
            f"{backlog['without_cost']} 个没单价、{backlog['without_lead']} 个没提前期"
            + (f"（其中 {backlog['without_master_row']} 个连物料主数据行都没有，"
               f"那不是填一列，是建这条档）" if backlog.get("without_master_row") else "")
            + ((f"；可催的这 {rc['rows_sampled']} 条里单价也只有 {rc['distinct_values']} 个值"
                f"（众数 {rc['mode_value']:g} 占 {rc['mode_share']:.1%}"
                f"{'' if rc['complete'] else '，样本只覆盖部分可催条目'}）—— "
                "全厂单价另有 "
                f"{backlog['unit_cost_basis']['zero_cost_rows_share']:.1%} 的行是 0 元占位，"
                "所以这一格只给件数，不给金额")
               if (rc := backlog.get("ready_cost_census")) else
               (" —— 缺单价的那些我不折成金额"
                if (backlog.get("unit_cost_basis") or {}).get("verdict") != "template_default"
                else " —— 单价整体只有 "
                     f"{backlog['unit_cost_basis']['distinct_values']} 个取值，不折成金额")))
    if all(str(s["verdict"]) == "template_default" for s in sources):
        out["reading"].append(
            "两边都是模板值时，任何一边的告警清单都不能当补货依据 —— "
            "先让厂里对最紧的那批料号逐料号写一个数，比调阈值有用")
    out["claim_guard"] = ("缺口件数按各自的声明算，不合并成一个『总缺口』；"
                          "模板值不冒充逐料号决定；空配置表不冒充『库存正常』")
    return out


async def safety_stock_question(db: AsyncSession, factory_id: str) -> Optional[Dict[str, Any]]:
    """把"哪张表作准"挂成待回答的问题；已经拍定（declared）就不再问。"""
    from core.mes.factory_rules import binding_rules

    auth = await safety_stock_authority(db, factory_id)
    if auth.get("status") != "ok":
        return None
    declared = (await binding_rules(db, factory_id)).get("safety_stock_authority")
    if declared:
        return {"declared": {"verdict": declared.get("verdict"), "status": declared.get("status"),
                             "statement": declared.get("statement")}}
    disagree = auth["disagreement"]
    rulers = auth["rulers"]
    return {
        "question": {
            "topic": "safety_stock_authority",
            "question": (f"『安全库存』这两处声明哪个作准 —— inventory.safety_stock"
                         f"（众数 {auth['sources'][0]['mode_value']:g}）还是 materials.safety_stock"
                         f"（众数 {auth['sources'][1]['mode_value']:g}）？"
                         f"两表都有的 {disagree['materials_in_both']} 个料号里 "
                         f"{disagree['disagree']} 个不一致。"),
            "what_records_say": [
                {"ruler": r["ruler"], "alerts": r["alerts"], "condition": r["condition"],
                 "basis": r["basis"]} for r in rulers],
            "widest_examples": disagree["widest_examples"],
            "why_it_matters": (f"同一句『低于安全库存』现在按出处给出 "
                               f"{rulers[0]['alerts']}/{rulers[1]['alerts']}/{rulers[2]['alerts']} 条，"
                               "差到十几倍；自动补货那条链（warehouse_agent）用的是 inventory 侧与 "
                               "reorder_point，而物料主数据那句在 materials 侧 —— 两边的数已经在互相"
                               "否证。`safety_stock_config` 那张本该作准的配置表是 0 行。"),
            "expected_answer": ("① 以 inventory.safety_stock 作准（补货链现有实现就是读它），"
                                "并把 materials 侧的值改成同一条口径；② 以 materials.safety_stock 作准，"
                                "则补货触发线要改读它；③ 逐料号重写（先重写决定开工那一档的件）；"
                                "三条都要落到 line 之外的字段级决定，不是调阈值。"),
            "record_as": {"subject": "safety_stock_authority",
                          "verdict": "inventory|materials|per_item_rewritten",
                          "status": "declared", "source": "chat"},
        }
    }
