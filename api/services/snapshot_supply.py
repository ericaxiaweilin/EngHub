"""齐套快照的供给刷新：让主工单的缺口跟着真实台账走，闭环才能自己转。

问题：`work_order_materials` 是**下达那一刻**的 MRP 快照。之后领料出库、收货入库、
下级工单完工入库都会改变库存，但快照里的 `shortage_qty` 不动 —— APS 的齐套门
（`material_ready = shortage_count == 0`）读的就是这一列，于是它判的是过期事实：
下级工单做好了，父层还显示缺料，永远放不了行。

口径（和 `bom_source.explode_requirement` 必须一致，否则等于把刚修完的 bug 请回来）：
- 供应 = 在库可用 + 已到承诺期且未收货的在途 PO；
- **一份供应只能被一条需求行冲抵**：同一个料号可能出现在多张工单/多个层级，
  如果每行都按全量库存去扣，缺口会被重复冲抵算小，齐套门就会**假放行**（这是我在
  MRP 多层展开里抓到并修掉的同一个错，实测当时净需求 11,177 → 修正后 11,270）；
- 冲抵顺序确定：计划交期 → 层级 → 料号 → 行 id，保证同样数据刷出来同样的结果；
- 只刷主工单快照；下级工单的行是执行明细，不参与需求总账（否则同一份需求数两遍）。

只改 `shortage_qty` 和 `remark`（记上刷新时间与依据），
`available_qty/received_qty` 保留为下达时的历史事实，不覆盖 —— 快照的取证价值比
"看起来同步"更重要。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_source import stock_and_supply

LIVE_LINES_SQL = text("""
    SELECT m.id, m.material_code, m.required_qty, m.shortage_qty, m.level,
           wo.factory_id, p.required_date
    FROM work_order_materials m
    JOIN work_orders wo ON wo.id = m.work_order_id
    LEFT JOIN pp_plans p ON p.id = wo.source_plan_id
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND m.material_code IS NOT NULL
    ORDER BY COALESCE(p.required_date, CURRENT_DATE), m.level NULLS LAST,
             m.material_code, m.id
""")

APPLY_SQL = text("""
    UPDATE work_order_materials
    SET shortage_qty = :shortage_qty,
        remark = :remark
    WHERE id = :id
""")


async def refresh_snapshot_supply(
    db: AsyncSession, *, factory_id: str | None = None, apply: bool = True
) -> Dict[str, Any]:
    """按当前台账重算主快照缺口（单份冲抵）。幂等：每次从现状重算，不累加。"""
    params = {"factory_id": factory_id} if factory_id else {}
    where = "AND wo.factory_id = :factory_id" if factory_id else ""
    rows = (await db.execute(text(LIVE_LINES_SQL.text.replace(
        "    ORDER BY", f"      {where}\n    ORDER BY"
    )), params)).mappings().all()

    receipt: Dict[str, Any] = {
        "lines": len(rows),
        "changed": 0,
        "cleared": 0,
        "shortage_before": 0,
        "shortage_after": 0,
        "factories": sorted({str(r["factory_id"]) for r in rows}),
    }
    if not rows:
        receipt["status"] = "no_lines"
        return receipt

    codes = sorted({str(r["material_code"]) for r in rows})
    supply: Dict[str, Dict[str, Dict[str, float]]] = {}
    for fid in receipt["factories"]:
        supply[fid] = await stock_and_supply(db, fid, codes)

    # 每个厂区每个料号一份剩余供应，边冲抵边扣，扣完为止
    remaining: Dict[tuple, float] = {
        (fid, code): float(v.get("on_hand", 0.0)) + float(v.get("on_order", 0.0))
        for fid, per_code in supply.items() for code, v in per_code.items()
    }
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    for row in rows:
        code = str(row["material_code"])
        fid = str(row["factory_id"])
        required = int(row["required_qty"] or 0)
        key = (fid, code)
        left = remaining.get(key, 0.0)
        used = min(required, max(0.0, left))
        remaining[key] = left - used
        shortage = required - int(used)
        receipt["shortage_before"] += int(row["shortage_qty"] or 0)
        receipt["shortage_after"] += shortage
        if shortage != int(row["shortage_qty"] or 0):
            receipt["changed"] += 1
            if shortage == 0 and int(row["shortage_qty"] or 0) > 0:
                receipt["cleared"] += 1
            if apply:
                await db.execute(APPLY_SQL, {
                    "id": row["id"],
                    "shortage_qty": shortage,
                    "remark": (
                        f"供给刷新 {stamp}：按当前在库+到期在途单份冲抵重算缺口"
                        f"（available/received 保留下达时快照值）"
                    ),
                })
    if apply:
        await db.commit()
    else:
        await db.rollback()
    receipt["status"] = "ok"
    receipt["dry_run"] = not apply
    return receipt
