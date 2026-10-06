"""下级装配件工单的齐套放行：料齐了才 released，没齐就说卡在哪。

APS 排的是任务顺序，车间能不能真开工看的是料。`release_plan` 那套"缺料就拦"只看
主工单快照，下级工单一直没门：它们大多是 `pending`，即使料早就在库里也没人放行；
而一旦有门，最容易犯的错是**每单都按全量库存判齐套** —— 两张单抢同一种料时双双放行，
到线上才发现只有一份。这里按"未分配剩余量"逐单冲抵，和 MRP/缺口刷新同一个口径。

规则（保守，宁可晚放行也不放空单）：
1. 只处理 `wo_type='component'`、`status='pending'`、且**有工艺路线**的工单；
2. 采购料（`item_type<>'make'`）必须被剩余可用量覆盖，边判边扣；
3. 自制料（make 行）要"本单不靠库存"才算齐：该料有库存够用就冲抵库存，
   否则必须有**自己的子工单已经 completed**（下层先装好，自然形成由深到浅的开工顺序）；
   没有库存、也没有已完工的子工单 → 不放行，原因如实报；
4. 没有路线的工单永不放行（排不出也干不了，别伪装成已就绪）；
5. 齐套表里**一行带需求量的料都没有**也不放行 —— 那是"没有领料依据"，不是"料齐了"
   （实测这样被放行的下级工单有 120 张，全是拆单时从父单快照抄来 0 需求行的那批）。

只改 `status/released_by/released_at/current_stage`，不碰数量与台账。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CANDIDATES_SQL = text("""
    SELECT wo.id, wo.work_order_code, wo.factory_id, wo.planned_due,
           count(m.id) AS lines,
           count(m.id) FILTER (WHERE COALESCE(m.item_type,'buy') = 'make') AS make_lines
    FROM work_orders wo
    JOIN work_order_materials m ON m.work_order_id = wo.id
    WHERE wo.wo_type = 'component'
      AND wo.status = 'pending'
      AND wo.routing_id IS NOT NULL
    GROUP BY wo.id, wo.work_order_code, wo.factory_id, wo.planned_due
    -- 先挑没有自制下层行的单：按交期排会让候选前 20 张全是卡在子件的单，
    -- 于是明明有 73 张料齐的单一直排不进批次，看起来像"一张都放不了"
    -- Postgres 的 ORDER BY 不能直接引用 SELECT 别名，这里重复表达式本身
    ORDER BY (count(m.id) FILTER (WHERE COALESCE(m.item_type,'buy') = 'make') > 0),
             COALESCE(wo.planned_due, CURRENT_DATE), wo.work_order_code
    LIMIT :limit
""")

LINES_SQL = text("""
    SELECT m.material_code, m.required_qty,
           COALESCE(m.item_type, 'buy') AS item_type,
           COALESCE((
               SELECT sum(i.available_qty) FROM inventory i
               WHERE i.factory_id = :fid AND i.material_code = m.material_code
           ), 0) AS on_hand,
           (SELECT cw.status FROM work_orders cw
             WHERE cw.parent_work_order_id = m.work_order_id
               AND cw.product_id = m.material_code
             ORDER BY cw.created_at LIMIT 1) AS child_status
    FROM work_order_materials m
    WHERE m.work_order_id = :wo_id
      AND COALESCE(m.required_qty, 0) > 0
    ORDER BY m.level NULLS LAST, m.material_code
""")

# 不凭印象写列名：SET 子句按 information_schema 过滤（这轮我已经两次猜错列，
# 一次 cancelled_by、一次 released_at —— 表里没有，靠运行期报错才发现）。
async def _release_columns(db: AsyncSession) -> Dict[str, str]:
    cols = {str(r[0]) for r in (await db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'work_orders'
    """)))}
    wanted = {
        "status": "'released'",
        "released_by": ":who",
        "current_stage": "'齐套放行：采购料与下层件均满足'",
        "updated_at": "NOW()",
    }
    return {k: v for k, v in wanted.items() if k in cols}


async def _release_one(db: AsyncSession, wo_id: str, who: str) -> int:
    columns = await _release_columns(db)
    if not columns:
        return 0
    sets = ", ".join(f"{col} = {expr}" for col, expr in columns.items())
    result = await db.execute(text(
        f"UPDATE work_orders SET {sets} WHERE id = :id AND status = 'pending'"
    ), {"id": wo_id, "who": who})
    return int(result.rowcount or 0)


RELEASED_BY = "component_kit"
BATCH = max(1, int(os.getenv("COMPONENT_RELEASE_BATCH", "40")))


async def release_kitted_child_orders(
    db: AsyncSession, *, factory_id: str | None = None, limit: int = BATCH,
    apply: bool = True,
) -> Dict[str, Any]:
    """逐单判齐套并放行；返回可对账的凭据（放行几张、各卡在哪）。"""
    sql = CANDIDATES_SQL.text
    params: Dict[str, Any] = {"limit": limit}
    if factory_id:
        sql = sql.replace("WHERE wo.wo_type = 'component'",
                          "WHERE wo.factory_id = :factory_id AND wo.wo_type = 'component'")
        params["factory_id"] = factory_id

    candidates = (await db.execute(text(sql), params)).mappings().all()
    receipt: Dict[str, Any] = {
        "candidates": len(candidates),
        "released": 0,
        "held": {},
        "held_examples": [],
        "scope": factory_id or "全部厂区",
    }
    # 未分配剩余量：跨工单共用一份供应，判过就扣，绝不每单都看全量
    pool: Dict[tuple, float] = {}

    for cand in candidates:
        fid = str(cand["factory_id"])
        lines: List[Any] = (await db.execute(
            text(LINES_SQL.text), {"wo_id": cand["id"], "fid": fid}
        )).mappings().all()
        blocker = None
        # 一行带需求量的料都没有 = 没有任何领料依据。以前这算"没有缺口→齐套"，
        # 于是拆单时抄了 0 需求的子单被成批放行（实测 120 张）：
        # "没人缺货"和"知道要发什么料"是两件事，判不齐就宁可压住。
        if not lines:
            receipt["held"]["no_kit_evidence"] = \
                receipt["held"].get("no_kit_evidence", 0) + 1
            if len(receipt["held_examples"]) < 5:
                receipt["held_examples"].append({
                    "work_order_code": str(cand["work_order_code"]),
                    "blocker": "no_kit_evidence",
                })
            continue
        # 先算到影子账上：本单被压住时不能已经把匹配到的行从公共池扣掉了，
        # 否则后面的单会以为料被占走，明明能齐却放不了行
        taken: Dict[tuple, float] = {}
        for line in lines:
            code = str(line["material_code"])
            need = int(line["required_qty"] or 0)
            key = (fid, code)
            left = pool.get(key, float(line["on_hand"] or 0)) - taken.get(key, 0.0)
            if left >= need:
                taken[key] = taken.get(key, 0.0) + need
                continue
            # 库存不够：自制件如果有已完工的子工单，说明产出会入库，按"由下层供货"通过
            if str(line["item_type"]) == "make" and str(line["child_status"] or "") == "completed":
                continue
            if str(line["item_type"]) == "make":
                blocker = blocker or f"waiting_on_child:{line['child_status'] or 'no_order'}"
            else:
                blocker = blocker or "purchased_short"
        if blocker:
            receipt["held"][blocker] = receipt["held"].get(blocker, 0) + 1
            if len(receipt["held_examples"]) < 5:
                receipt["held_examples"].append({
                    "work_order_code": str(cand["work_order_code"]),
                    "blocker": blocker,
                })
            continue

        # 放行了才把影子账落到公共池上
        on_hand_by_code = {str(l["material_code"]): float(l["on_hand"] or 0) for l in lines}
        for key, qty in taken.items():
            pool[key] = pool.get(key, on_hand_by_code.get(key[1], 0.0)) - qty
        if apply:
            receipt["released"] += await _release_one(db, str(cand["id"]), RELEASED_BY)
        else:
            receipt["released"] += 1

    if apply:
        await db.commit()
    else:
        await db.rollback()
    receipt["dry_run"] = not apply
    receipt["status"] = "ok"
    return receipt
