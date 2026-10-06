"""按虚拟时钟把"到期的采购单"收成已到货：在途不会自己变成库存。

为什么这一格必须存在（10-06 实测）：`purchase_orders` 里 31 张 confirmed/in_transit 的单，
预计到货日已经过去 1.5 个月（最早 07-20、最晚 08-23），但系统里**没有任何代码**在到点之后
把它变成库存和流水 —— `goods_receipts` 只有镜像带来的 7 行，最后一行停在 08-16。
后果是一整条链：库存不涨 → `refresh_snapshot_supply` 算出来还是缺 → 齐套门不放行 →
下层不完工 → 引擎只能继续拆新单。所以"缺料一直算不平"不是判据错，是**到货这件事没人做**。

MRP 本来就是提前算的：`stock_and_supply` 只看"预计到货日不晚于目标日"的在途，
所以这一格要做的只是把已经承诺过要到的货，按虚拟时钟真正落到账上。

三条边界：
1. 只收库里真实存在的单据（`purchase_orders` 由镜像同步进来），数量 = 未收数量，
   绝不按缺口凭空开一张采购单 —— 58 个外购缺口料号里 57 个没有供应商主数据，
   那些走"缺主数据"上报（procurement_demand 的清单），不进这里；
2. 过账走 `wms_service.record_purchase_receipt`（和完工入库同一条路：落收货单 +
   `apply_movement` 记流水），不另起第二个写入口；
3. 缺 `expected_date` 的单不动：没有依据就不知道它算不算迟到。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_source import OPEN_PO_STATUSES

RECEIVE_ENABLED = os.getenv("PURCHASE_RECEIPT_AUTO", "true").strip().lower() in ("1", "true", "yes", "on")
RECEIPT_LIMIT = max(1, int(os.getenv("PURCHASE_RECEIPT_BATCH", "50")))

DUE_POS_SQL = text("""
    SELECT po.id, po.factory_id, po.po_code, po.material_code, po.supplier_id,
           po.qty, COALESCE(po.received_qty, 0) AS received_qty,
           GREATEST(po.qty - COALESCE(po.received_qty, 0), 0) AS outstanding,
           po.expected_date,
           CAST(COALESCE(CAST(:as_of AS date), po.expected_date) - po.expected_date AS int) AS overdue_days
    FROM purchase_orders po
    WHERE po.status = ANY(:open_statuses)
      AND (CAST(:fid AS varchar) IS NULL OR po.factory_id = CAST(:fid AS varchar))
      AND po.expected_date IS NOT NULL
      AND CAST(po.expected_date AS date) <= COALESCE(CAST(:as_of AS date), CAST(po.expected_date AS date))
      AND GREATEST(po.qty - COALESCE(po.received_qty, 0), 0) > 0
    ORDER BY po.expected_date, po.po_code
    LIMIT :limit
""")


async def _sim_date(factory_id: str, cache: Dict[str, Any]) -> tuple:
    """到货日按虚拟工厂的仿真时间判，不是按这台机器今天的日期。

    返回 (日期, 依据)：读不到仿真时钟时退回真实日期，但依据要一起报出去 ——
    "什么时候算到货"这件事用哪把尺子，看结果的人必须能看见。
    """
    if factory_id not in cache:
        try:
            from api.services.virtual_factory_clock import get_clock
            now = await get_clock().now(factory_id)
        except Exception:  # noqa: BLE001 - 时钟读不到就用真实日期，依据如实标 real_date
            now = None
        if now is not None:
            cache[factory_id] = (now.date(), "sim_clock")
        else:
            cache[factory_id] = (date.today(), "real_date")
    return cache[factory_id]


async def receive_due_purchase_orders(
    db: AsyncSession, *, factory_id: Optional[str] = None,
    as_of: Optional[date] = None, apply: bool = RECEIVE_ENABLED,
    limit: int = RECEIPT_LIMIT,
) -> Dict[str, Any]:
    """把预计到货日已到、还没收货的采购单收成库存（收货单 + 流水 + 状态）。"""
    from api.services.wms_service import InventoryService

    clocks: Dict[str, Any] = {}
    receipt: Dict[str, Any] = {
        "factory_id": factory_id or "全部厂区", "apply": apply, "dry_run": not apply,
        "due_pos": 0, "received": 0, "posted_qty": 0, "overdue_pos": 0,
        "max_overdue_days": 0, "skipped": {}, "examples": [],
    }
    if as_of is None:
        as_of_date, basis = await _sim_date(factory_id or "FAC_MECH_001", clocks)
        receipt["clock_basis"] = basis
    else:
        as_of_date = as_of
        receipt["clock_basis"] = "caller_supplied"
    receipt["as_of"] = str(as_of_date)

    rows = (await db.execute(DUE_POS_SQL, {
        "fid": factory_id, "as_of": as_of_date,
        "open_statuses": list(OPEN_PO_STATUSES), "limit": max(1, limit),
    })).mappings().all()
    receipt["due_pos"] = len(rows)
    if not rows:
        receipt["status"] = "nothing_due"
        return receipt

    wms = InventoryService(db)   # 完工入库同一个服务，到货走同一条路
    for row in rows:
        fid = str(row["factory_id"])
        # 每张单按自己厂区的仿真时间判到货：两个厂区各自推进，不共用一个"今天"
        due_on, _basis = await _sim_date(fid, clocks)
        if row["expected_date"] is None or row["expected_date"] > due_on:
            receipt["skipped"]["not_due_yet"] = receipt["skipped"].get("not_due_yet", 0) + 1
            continue
        qty = int(row["outstanding"] or 0)
        if qty <= 0:
            receipt["skipped"]["no_outstanding"] = receipt["skipped"].get("no_outstanding", 0) + 1
            continue
        overdue = int(row["overdue_days"] or 0)
        if not apply:
            receipt["examples"].append({
                "po_code": str(row["po_code"]), "material_code": str(row["material_code"]),
                "qty": qty, "expected_date": str(row["expected_date"]),
                "overdue_days": (due_on - row["expected_date"]).days,
            })
            continue

        booked = await wms.record_purchase_receipt(
            factory_id=fid, po_id=str(row["id"]), po_code=str(row["po_code"]),
            material_code=str(row["material_code"]), qty=qty,
            supplier_id=str(row["supplier_id"]) if row["supplier_id"] else None,
            received_at=datetime.combine(due_on, datetime.min.time()),
            remark=(f"引擎按仿真时钟收货：{row['material_code']} × {qty}"
                    f"（{row['po_code']}，预计 {row['expected_date']}，"
                    f"逾期 {(due_on - row['expected_date']).days} 天）"),
        )
        if booked.get("reason") != "posted":
            receipt["skipped"][str(booked.get("reason"))] = \
                receipt["skipped"].get(str(booked.get("reason")), 0) + 1
            continue
        overdue_days = (due_on - row["expected_date"]).days
        updated = await db.execute(text("""
            UPDATE purchase_orders
            SET status = 'received', actual_date = :arrived,
                received_qty = COALESCE(received_qty, 0) + :qty,
                updated_at = NOW()
            WHERE id = :id AND status = ANY(:open_statuses)
        """), {"id": str(row["id"]), "arrived": due_on, "qty": qty,
               "open_statuses": list(OPEN_PO_STATUSES)})
        if not int(updated.rowcount or 0):
            # 状态在收货这一步之间被别人改过：库存已经加了，就不重复改单，
            # 但必须把这件事报出来，不能安静地把两笔账对不上
            receipt["skipped"]["status_changed_during_receipt"] = \
                receipt["skipped"].get("status_changed_during_receipt", 0) + 1
        receipt["received"] += 1
        receipt["posted_qty"] += int(booked["posted"])
        receipt["overdue_pos"] += 1 if overdue_days > 0 else 0
        receipt["max_overdue_days"] = max(receipt["max_overdue_days"], overdue_days)

    if apply and receipt["received"]:
        await db.commit()
    receipt["status"] = "ok"
    head = f"{as_of_date} 视角（{receipt['clock_basis']}）：{receipt['due_pos']} 张采购单已过预计到货日"
    if not apply:
        receipt["message"] = head + f"，预演可收货 {len(receipt['examples'])} 张（PURCHASE_RECEIPT_AUTO=false 时只报不动账）"
    elif receipt["received"]:
        receipt["message"] = (head + f"，已收货 {receipt['received']} 张、入库 {receipt['posted_qty']} 件"
                             f"（逾期 {receipt['overdue_pos']} 张，最久 {receipt['max_overdue_days']} 天）")
    else:
        receipt["message"] = head + "，但一张也没收成：" + (json.dumps(receipt["skipped"], ensure_ascii=False)
                                                       if receipt["skipped"] else "无未收数量")
    return receipt
