"""周期盘点：引擎自己决定"这轮该盘哪些行"，人只负责把实测数填进来。

为什么要这一格（10-09 清点）：`inventory_counts` **0 行** —— 建单/录入/审批三个接口都在
`wms_service.py` 里，但从没被调用过。没有盘点，台账说有多少就是多少，谁也没验证过；
10-08 那次"零领料却完工入库 165 件虚假半成品"就是这类没被盘出来的。

现成的 `create_count_order` 是"把整个仓库全量快照"—— 11,228 行一次盘不动，
所以这里补的是**范围判据**：哪些行最值得先盘，每条都要说得出为什么是它。

四条范围（按优先级取第一个命中的理由，一行只挂一个理由，避免重复计数）：
· never_moved —— 台账有量却从没记过一次移动（`last_movement_at` 空）：最可能是导入时灌进来的数；
· no_location —— 没有库位号：连"去哪一格数"都回答不了；
· class_a     —— A 类料：值高、错得多，周期盘点本来就该先盘它；
· zero_stock  —— 零库存但历史上动过：要确认是真是用完了，还是被扣错/漏记。

幂等：已经在**未完成**盘点单里的行不重复开单（不是"今天开过就不开"，
而是"这一批还没盘完就别再堆一层")。apply=false 只回报会开哪些行。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 一轮最多开多少行：200 行是一个仓管半天能盘完的量，再多就盘不完、单会一直挂着
MAX_ITEMS_PER_ORDER = 200
# 未完成的盘点单：这些状态下的行不算"没盘过"，不重复开
OPEN_COUNT_STATUSES = ("draft", "counting", "pending_approval")

SCOPE_SQL = """
    SELECT i.id, i.material_code, i.material_name, i.batch_code, i.location_code,
           i.warehouse_id, i.total_qty, i.available_qty, i.abc_class, i.last_movement_at,
           (SELECT COUNT(*) FROM inventory_transactions t
             WHERE t.inventory_id = i.id) AS movement_rows
    FROM inventory i
    WHERE i.factory_id = :fid
      AND (CAST(:wid AS text) IS NULL OR i.warehouse_id = CAST(:wid AS text))
      AND UPPER(COALESCE(i.material_code,'')) NOT IN ('NAN','NULL','NONE','NA')
    ORDER BY i.total_qty DESC
"""


def plan_scope(rows: List[Dict[str, Any]], *, already_counted: Optional[List[str]] = None,
               max_items: int = MAX_ITEMS_PER_ORDER,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """纯函数：把库存行分进四条盘点范围，每条给理由；已开过单的行不再进来。"""
    skip = set(already_counted or [])
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    picked: List[Dict[str, Any]] = []
    # 每个理由各自一摞，最后**轮转取**：一轮 200 行如果全按件数大小排，
    # 会被"从没动过的大件"占满，没库位/A 类/零库存这三类问题一行都盘不到。
    buckets: Dict[str, List[Dict[str, Any]]] = {"never_moved": [], "no_location": [],
                                                "class_a": [], "zero_stock": []}
    excluded_dirty = 0
    for r in rows or []:
        rid = str(r.get("id") or "")
        code = str(r.get("material_code") or "").strip().upper()
        if not rid:
            continue
        if code in ("NAN", "NULL", "NONE", "NA"):
            excluded_dirty += 1
            continue
        if rid in skip:
            continue
        qty = float(r.get("total_qty") or 0)
        last = r.get("last_movement_at")
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = None
        reason = None
        if qty > 0 and last is None:
            reason = "never_moved"
        elif not str(r.get("location_code") or "").strip():
            reason = "no_location"
        elif str(r.get("abc_class") or "").strip().upper() == "A":
            reason = "class_a"
        elif qty == 0 and int(r.get("movement_rows") or 0) > 0:
            reason = "zero_stock"
        if reason is None:
            continue
        buckets[reason].append({"inventory_id": rid, "material_code": str(r.get("material_code") or ""),
                                "batch_code": r.get("batch_code"), "system_qty": qty,
                                "location_code": r.get("location_code"), "reason": reason})
    candidates = {k: len(v) for k, v in buckets.items()}
    order = ["never_moved", "no_location", "class_a", "zero_stock"]
    while len(picked) < max_items and any(buckets[k] for k in order):
        for k in order:
            if buckets[k] and len(picked) < max_items:
                picked.append(buckets[k].pop(0))
    reasons = {k: sum(1 for p in picked if p["reason"] == k) for k in order}
    return {"items": picked, "items_planned": len(picked), "by_reason": reasons,
            "candidates_by_reason": candidates,
            "excluded_dirty_rows": excluded_dirty,
            "reason_text": {
                "never_moved": "台账有量却从没记过一次移动 —— 最可能是导入时灌进来的数，没被验证过",
                "no_location": "没有库位号：连去哪一格数都回答不了",
                "class_a": "A 类料：值高、错得起不起，周期盘点本来就该先盘它",
                "zero_stock": "零库存但历史动过：确认是真用完了还是被扣错/漏记"}}


async def open_periodic_count(db, factory_id: str, *, warehouse_id: Optional[str] = None,
                              apply: bool = False,
                              max_items: int = MAX_ITEMS_PER_ORDER,
                              actor: str = "engine") -> Dict[str, Any]:
    """按范围开一张盘点单（把系统数快照进明细）。apply=false 只回报会开哪些行。"""
    from sqlalchemy import text

    rows = (await db.execute(text(SCOPE_SQL),
                             {"fid": factory_id, "wid": warehouse_id})).mappings().all()
    busy = (await db.execute(text("""
        SELECT ci.inventory_id FROM inventory_count_items ci
        JOIN inventory_counts c ON c.id = ci.count_id
        WHERE c.factory_id = :fid AND LOWER(c.status) = ANY(CAST(:st AS text[]))
          AND ci.counted_qty IS NULL
    """), {"fid": factory_id, "st": list(OPEN_COUNT_STATUSES)})).scalars().all()

    plan = plan_scope([dict(r) for r in rows], already_counted=[str(x) for x in busy],
                      max_items=max_items)
    out: Dict[str, Any] = {"factory_id": factory_id, "warehouse_id": warehouse_id,
                           "items_planned": plan["items_planned"], "by_reason": plan["by_reason"],
                           "excluded_dirty_rows": plan["excluded_dirty_rows"],
                           "candidates_by_reason": plan["candidates_by_reason"],
                           "already_open_items": len(busy), "apply": apply,
                           "reason_text": plan["reason_text"]}
    if not apply or not plan["items"]:
        out["items"] = plan["items"][:12]
        out["note"] = "apply=false，只算不写" if not apply else "没有要盘的行"
        return out

    # 未完成单没盘完就不再叠一张：范围有 1 万多行候选，不设这道闸的话每跑一次就多 200 行明细，
    # 仓管面前永远是一堆没关的单 —— 幂等的对象是"这一轮"，不是"这一批行"。
    if plan["items"] and int(out["already_open_items"] or 0) > 0:
        out["would_create"] = plan["items_planned"]
        out["items_planned"] = 0
        out["items"] = []
        out["note"] = (f"已有一张未完成的盘点单（{out['already_open_items']} 行还没录实测数）—— "
                       "不再叠第二张；先把这一张盘完再开下一轮")
        return out

    import uuid

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count_id = str(uuid.uuid4())
    # 单号带 uuid 前缀：表上 count_code 是唯一约束，只到分钟的号在同一分钟里开两次必撞
    # （实测撞过一次：IC-FAC_-202610091045）
    count_code = f"IC-{(factory_id or '')[:4]}-{now:%Y%m%d%H%M}-{count_id[:6]}"
    # 明细可能跨仓（范围是按"哪一行可疑"选的，不是按仓选的），单头只记发起时的仓
    first_wh = warehouse_id or (str(rows[0]["warehouse_id"]) if len(rows) else None)
    await db.execute(text("""
        INSERT INTO inventory_counts (id, count_code, factory_id, warehouse_id, count_type,
                                      status, planned_date, total_items, remark, created_at)
        VALUES (:id, :code, :fid, :wid, 'periodic', 'counting', CURRENT_DATE, :n, :rm, NOW())
    """), {"id": count_id, "code": count_code, "fid": factory_id, "wid": first_wh,
           "n": plan["items_planned"],
           "rm": ("引擎按范围自动开的周期盘点：" +
                  "、".join(f"{k} {v} 行" for k, v in plan["by_reason"].items() if v))})
    for i in plan["items"]:
        await db.execute(text("""
            INSERT INTO inventory_count_items (id, count_id, inventory_id, material_id,
                                               batch_code, system_qty, created_at)
            VALUES (:id, :cid, :iid, :mid, :bc, :qty, NOW())
        """), {"id": str(uuid.uuid4()), "cid": count_id, "iid": i["inventory_id"],
               "mid": i["material_code"], "bc": i["batch_code"], "qty": i["system_qty"]})
    await db.commit()
    out.update({"created": True, "count_id": count_id, "count_code": count_code,
                "items_written": plan["items_planned"]})
    return out


async def count_status(db, factory_id: str) -> Dict[str, Any]:
    """盘点这条腿走到哪一步了：开了几张、盘了几行、审批了几张、调差多少件。"""
    from sqlalchemy import text

    row = (await db.execute(text("""
        SELECT COUNT(*) AS 单数,
               COUNT(*) FILTER (WHERE LOWER(status) IN ('draft','counting','pending_approval')) AS 未完成,
               COUNT(*) FILTER (WHERE LOWER(status) = 'approved') AS 已审批,
               COALESCE(SUM(total_items),0) AS 明细行,
               COALESCE(SUM(diff_items),0) AS 差异行,
               COALESCE(SUM(total_diff_qty),0) AS 差异件数
        FROM inventory_counts WHERE factory_id = :fid"""), {"fid": factory_id})).mappings().first()
    items = (await db.execute(text("""
        SELECT COUNT(*) AS 明细, COUNT(*) FILTER (WHERE ci.counted_qty IS NOT NULL) AS 已录入
        FROM inventory_count_items ci JOIN inventory_counts c ON c.id = ci.count_id
        WHERE c.factory_id = :fid"""), {"fid": factory_id})).mappings().first()
    return {"orders": dict(row or {}), "items": dict(items or {})}
