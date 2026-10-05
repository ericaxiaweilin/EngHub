"""齐套外购缺口的采购待办（只读聚合，不落单据）。

`item_type='buy'` 的缺口现在已有归属（外购组件也归到这里，见 bom_source 的判据），
但"要买什么、买多少、有没有供应商依据"以前只散在齐套表的行里，没有任何一个动作对象
能承接它。这里把那份需求汇成一张可对账的清单，交给控制塔与对话展示。

**为什么先不自动开采购申请/采购单**：`purchase_requests` 与 `purchase_orders`
在系统里没有任何接口或页面在读（openapi 只有三个补货检查端点）。往没人读的表里灌行
只是把数字换个地方堆着 —— 那张表里已经躺着 890 万条这样的历史。落成单据要有读者，
那是接口/界面的决定，不是这里能替采购部门做的。
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

# 与 MRP 同一个在途口径（bom_source.stock_and_supply）：只认已确认/已发货且预计到货在期内的 PO。
# 注意现网还有 in_transit/ordered/draft 三种状态**不在**这个口径里，
# 也就是说 MRP 看不到它们 —— 这是状态字典的分歧，要报出来给人裁决，不在这里偷偷扩列。
ON_ORDER_SQL = text("""
    SELECT material_code,
           COALESCE(SUM(qty - COALESCE(received_qty, 0)), 0) AS on_order,
           min(expected_date) AS first_expected
    FROM purchase_orders
    WHERE factory_id = :fid AND material_code = ANY(:codes)
      AND status IN ('confirmed', 'shipped')
    GROUP BY material_code
""")
UNRECOGNISED_PO_SQL = text("""
    SELECT status, count(*) AS orders, COALESCE(SUM(qty), 0) AS qty
    FROM purchase_orders
    WHERE factory_id = :fid AND material_code = ANY(:codes)
      AND status NOT IN ('confirmed', 'shipped', 'received')
    GROUP BY status
""")
SUPPLIER_SQL = text("""
    SELECT sm.material_code, s.supplier_name, sm.lead_time_days, sm.min_order_qty
    FROM supplier_materials sm
    JOIN suppliers s ON s.id = sm.supplier_id
    WHERE sm.material_code = ANY(:codes) AND COALESCE(sm.is_active, true)
    ORDER BY sm.material_code, COALESCE(sm.is_primary, false) DESC
""")
PO_HISTORY_SQL = text("""
    SELECT DISTINCT material_code, supplier_name
    FROM purchase_orders
    WHERE factory_id = :fid AND material_code = ANY(:codes)
      AND supplier_id IS NOT NULL AND supplier_name IS NOT NULL
""")


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def kit_shortage_demands(db: Any, factory_id: str, buy_items: List[Dict[str, Any]]
                              ) -> Dict[str, Any]:
    """把 buy 档的缺口汇成采购待办：缺多少、谁在做、有没有供应商依据。

    `buy_items` 来自控制塔的缺口分组（每料号一条，含 shortage_qty 与 affected_work_orders），
    所以这里的数字必须与控制塔同源 —— 不再查第二遍缺口，只补供应商与在途两件事。
    """
    items = [i for i in buy_items if _f(i.get("shortage_qty")) > 0]
    codes = [str(i.get("material_code")) for i in items]
    result: Dict[str, Any] = {
        "materials": len(items),
        "shortage_qty": round(sum(_f(i.get("shortage_qty")) for i in items), 2),
        "supplier_known": 0,
        "supplier_missing": 0,
        "on_order_qty": 0.0,
        "po_status_not_counted": {},
        "top": [],
    }
    if not codes:
        result["note"] = "外购缺口为 0，这一档没有待办。"
        return result

    suppliers: Dict[str, Dict[str, Any]] = {}
    for row in (await db.execute(SUPPLIER_SQL, {"codes": codes})).mappings().all():
        suppliers.setdefault(str(row["material_code"]), {
            "supplier_name": row["supplier_name"],
            "lead_time_days": row["lead_time_days"],
            "min_order_qty": _f(row["min_order_qty"]),
        })
    # 没有维护供应商目录、但厂里真下过单：那家供应商同样是事实依据，不是编出来的
    for row in (await db.execute(PO_HISTORY_SQL, {"fid": factory_id, "codes": codes})).mappings().all():
        suppliers.setdefault(str(row["material_code"]), {
            "supplier_name": row["supplier_name"], "lead_time_days": None,
            "min_order_qty": 0.0, "basis": "历史采购单",
        })

    on_order: Dict[str, float] = {}
    for row in (await db.execute(ON_ORDER_SQL, {
            "fid": factory_id, "codes": codes})).mappings().all():
        on_order[str(row["material_code"])] = _f(row["on_order"])
    for row in (await db.execute(UNRECOGNISED_PO_SQL, {
            "fid": factory_id, "codes": codes})).mappings().all():
        result["po_status_not_counted"][str(row["status"])] = {
            "orders": int(row["orders"] or 0), "qty": round(_f(row["qty"]), 2)}

    known = 0
    for item in items:
        code = str(item.get("material_code"))
        supply = suppliers.get(code)
        if supply:
            known += 1
            item["supplier_name"] = supply["supplier_name"]
            item["supplier_lead_days"] = supply.get("lead_time_days")
        item["on_order_qty"] = on_order.get(code, 0.0)
    result["supplier_known"] = known
    result["supplier_missing"] = len(items) - known
    result["on_order_qty"] = round(sum(on_order.values()), 2)
    result["top"] = sorted(
        ({k: item.get(k) for k in (
            "material_code", "material_name", "shortage_qty", "supplier_name",
            "on_order_qty", "affected_work_orders")} for item in items),
        key=lambda i: -_f(i["shortage_qty"]))[:10]
    result["note"] = (
        "缺口已按当前台账刷新（在途只认 confirmed/shipped 且预计到货在期内的 PO）；"
        "本清单不落采购单据 —— purchase_requests/purchase_orders 目前没有接口或页面在读，"
        "先让人看见要买什么，再决定由谁落成单。"
    )
    if result["po_status_not_counted"]:
        result["note"] += (
            f" 另有状态不在 MRP 在途口径里的采购单：{result['po_status_not_counted']}，"
            "这些量 MRP 现在看不到（状态字典分歧，要有人裁决算不算在途）。"
        )
    return result
