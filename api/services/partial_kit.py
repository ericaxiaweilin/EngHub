"""部分齐套投产：一单缺一种料不等于这单停工，先算清"现在能开几台"。

用户给的工厂常识是这句话：工厂不会因为一个料缺就停产，而是迅速调整方案尽量不停产。
就绪门原来是二值的 —— 有缺口就整单压住，于是 68 台的单明明还能开 21 台，
账面写的是"整单停工"，车间看到的是 47 个人等着一种料。

只算库里有的东西：
- `work_order_materials`：每行是这台单的一个料，`required_qty` 是这张单按 `planned_qty`
  的毛需求，`available_qty` 是当前台账可用（报工已经真扣过），`shortage_qty` 是净缺口；
- 单件用量 = required_qty ÷ planned_qty，所以"可用量能顶几台"是除出来的，不是猜的；
- 上限是这张单还欠几台（planned − completed），不然会报出"能开 1,085 万台"这种数
  —— 那正是我第一版按每行可用量取最小值时算出来的，因为分母是 1/3 台。

写动作只有一个：`followup_task_service.create_task`。引擎不自动拆单、不改 planned_qty：
拆不拆、拆多少是 PMC 与车间的决定，这里只把台数、覆盖率、卡在哪个料摆出来。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 一张单至少能先开这么多台才值得报（默认 1，开发尺度可按环境变量抬高）
MIN_STARTABLE_UNITS = max(1, int(os.getenv("PARTIAL_KIT_MIN_UNITS", "1")))
LIMIT_OPPORTUNITIES = max(1, int(os.getenv("PARTIAL_KIT_MAX_ITEMS", "20")))

STARTABLE_SQL = text("""
    WITH kit AS (
        SELECT m.work_order_id,
               m.material_code,
               COALESCE(m.material_name, m.material_code) AS material_name,
               m.required_qty::numeric AS required_qty,
               COALESCE(m.available_qty, 0)::numeric AS available_qty,
               COALESCE(m.shortage_qty, 0)::numeric AS shortage_qty,
               wo.planned_qty::numeric AS planned_qty,
               GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0)::numeric AS remaining_qty
        FROM work_order_materials m
        JOIN work_orders wo ON wo.id = m.work_order_id
        WHERE wo.factory_id = :fid
          AND COALESCE(m.required_qty, 0) > 0
          AND wo.status IN ('pending', 'released', 'in_progress')
    ),
    per_order AS (
        SELECT work_order_id,
               MIN(planned_qty) AS planned_qty,
               MIN(remaining_qty) AS remaining_qty,
               -- 短板料能顶几台：可用量 ÷ 单件用量，封顶在这张单还欠几台
               MIN(LEAST(remaining_qty,
                         FLOOR(available_qty / GREATEST(required_qty / NULLIF(planned_qty, 0), 1e-9))))
                   AS startable_units,
               SUM(required_qty) AS required_total,
               SUM(LEAST(available_qty, required_qty)) AS covered_total,
               COUNT(*) FILTER (WHERE shortage_qty > 0) AS short_lines,
               COUNT(*) AS kit_lines
        FROM kit
        GROUP BY work_order_id
    )
    SELECT p.work_order_id, wo.work_order_code, wo.wo_type, wo.product_id,
           wo.planned_qty, p.remaining_qty, p.startable_units, p.short_lines, p.kit_lines,
           ROUND(p.covered_total / GREATEST(p.required_total, 1e-9), 4) AS coverage,
           k.material_code AS blocker_code, k.material_name AS blocker_name,
           k.shortage_qty AS blocker_shortage
    FROM per_order p
    JOIN work_orders wo ON wo.id = p.work_order_id
    LEFT JOIN LATERAL (
        SELECT material_code, material_name, shortage_qty
        FROM kit s
        WHERE s.work_order_id = p.work_order_id AND s.shortage_qty > 0
        ORDER BY shortage_qty DESC NULLS LAST, material_code
        LIMIT 1
    ) k ON TRUE
    WHERE p.short_lines > 0
      AND COALESCE(p.startable_units, 0) >= :min_units
      AND p.startable_units < p.remaining_qty
    ORDER BY p.startable_units DESC, p.remaining_qty DESC
    LIMIT :lim
""")


def summarize(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把明细压成能进心跳/接口的读数；没有机会时也要说清数了几张单。"""
    startable_units = sum(float(o["startable_units"] or 0) for o in orders)
    waiting_units = sum(float(o["remaining_qty"] or 0) - float(o["startable_units"] or 0) for o in orders)
    return {
        "orders_with_partial_option": len(orders),
        "units_startable_now": round(startable_units, 1),
        "units_still_waiting": round(max(0.0, waiting_units), 1),
    }


# 单件用量自己打自己：领料行是按快照写的，qty_per_unit 是主档声明，两边对不上时
# "能开几台"取决于信哪一条 —— 所以两个数都要报，不能默默只用其中一个。
PER_UNIT_CONFLICT_SQL = text("""
    SELECT COUNT(*) AS conflicting_lines,
           COUNT(DISTINCT m.work_order_id) AS conflicting_orders
    FROM work_order_materials m
    JOIN work_orders wo ON wo.id = m.work_order_id
    WHERE wo.factory_id = :fid
      AND COALESCE(m.required_qty, 0) > 0
      AND COALESCE(m.qty_per_unit, 0) > 0
      AND wo.planned_qty > 0
      AND ABS(m.qty_per_unit - m.required_qty / wo.planned_qty::numeric) > 0.001
""")


async def partial_kit_opportunities(
    db: AsyncSession, factory_id: str, *, min_units: int = MIN_STARTABLE_UNITS,
    limit: int = LIMIT_OPPORTUNITIES,
) -> Dict[str, Any]:
    """只读：现在有哪些单"料没齐但已经能先开一批"。"""
    rows = [dict(r) for r in (await db.execute(
        STARTABLE_SQL, {"fid": factory_id, "min_units": float(min_units), "lim": int(limit)}
    )).mappings().all()]
    for row in rows:
        for key in ("startable_units", "remaining_qty", "planned_qty", "coverage", "blocker_shortage"):
            if row.get(key) is not None:
                row[key] = float(row[key])
        row["waiting_units"] = max(0.0, row["remaining_qty"] - row["startable_units"])
    conflicts = (await db.execute(PER_UNIT_CONFLICT_SQL, {"fid": factory_id})).mappings().first()
    return {
        "status": "ok",
        "factory_id": factory_id,
        "min_units": min_units,
        "rule": ("能开几台 = min over 领料行 (可用量 ÷ 单件用量)，封顶在'这张单还欠几台'；"
                 "单件用量取 领料行毛需求 ÷ 计划台数（qty_per_unit 主档只有 49/4110 行有值，"
                 "不做主依据），但对不上的行数一并报出来"),
        "opportunities": rows,
        "per_unit_conflicts": {
            "lines": int(conflicts["conflicting_lines"] or 0) if conflicts else 0,
            "orders": int(conflicts["conflicting_orders"] or 0) if conflicts else 0,
        },
        **summarize(rows),
    }


async def report_partial_kit_splits(
    db: AsyncSession, factory_id: str, *, apply: bool = True,
    min_units: int = MIN_STARTABLE_UNITS, limit: int = 5,
) -> Dict[str, Any]:
    """把"先开一批"发成 PMC 的一条待办；判重按单号，一轮最多 limit 条。

    不自动拆单：拆多少台、要不要拆，取决于车间能不能临时腾出人力和工位，
    引擎没有这个信息，编出来就是替车间做决定。
    """
    from api.services.followup_task_service import create_task

    found = await partial_kit_opportunities(db, factory_id, min_units=min_units, limit=limit * 4)
    opportunities = found["opportunities"][:limit]
    if not apply or not opportunities:
        return {**found, "tasks_created": 0}

    created = 0
    for row in opportunities:
        existing = (await db.execute(text("""
            SELECT 1 FROM followup_tasks
            WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
              AND payload->>'category' = 'partial_kit'
              AND payload->>'work_order_code' = :code
            LIMIT 1
        """), {"fid": factory_id, "code": row["work_order_code"]})).first()
        if existing:
            continue
        evidence = {"category": "partial_kit", **row}
        await create_task(
            db, factory_id, created_by="partial_kit_advisor",
            title=(f"[分批] {row['work_order_code']}：齐套率 {row['coverage'] * 100:.0f}%，"
                   f"现在能先开 {row['startable_units']:g} 台（还欠 {row['waiting_units']:g} 台）"),
            description=(
                f"这张单还欠 {row['remaining_qty']:g} 台，被 {row['kit_lines']} 行领料里的 "
                f"{row['short_lines']} 个缺口压着，整单判成了停工。\n"
                f"· 台账可用量已经够先开 {row['startable_units']:g} 台（短板料口径）\n"
                f"· 最卡的料：{row.get('blocker_name') or row.get('blocker_code')}"
                f"（缺 {row.get('blocker_shortage') or 0:g}）\n"
                "引擎不自动拆单、不改 planned_qty —— 拆多少、车间腾不腾得出人力是现场决定。\n"
                "拍板后走正常拆单/下达，下一轮齐套快照会自己跟上。"
            ),
            agent_key="pmc_agent", item_type="followup", source="partial_kit_advisor",
            follow_interval_minutes=480,
            payload=json.dumps(evidence, ensure_ascii=False),
        )
        created += 1

    return {**found, "tasks_created": created}
