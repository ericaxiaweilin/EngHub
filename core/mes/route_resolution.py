"""产品 → 工艺路线的唯一解析口径。

排程、ATP/交期评估、what-if 模拟必须用同一套解析结果，否则会出现"排程排得出 7 道工序、
交期评估却说没有路线"这种自相矛盾（这套系统历史上真发生过）。

优先级与排程实际取路线的方式一致：
1. 该厂该产品**工单**上挂的 `routing_template_id`（排程就是按它排产的，最可信）；
2. 旧版 `routings.steps` JSON（历史工单没有模板绑定时用）；
3. 都没有 → 返回空，由调用方**明确拒绝**给数字，而不是退回"全厂最慢工位"编一个。
"""

from typing import Any, Dict, List

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Routing, RoutingTemplateStep


async def route_ops_for_product(
    db: AsyncSession, factory_id: str, product_id: str
) -> List[Dict[str, Any]]:
    """按工序顺序返回 [{operation_name, work_center, standard_hours}]；解析不出就是 []。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return []

    template_id = (await db.execute(text("""
        SELECT w.routing_template_id
        FROM work_orders w
        WHERE w.factory_id = :fid AND w.product_id = :pid AND w.routing_template_id IS NOT NULL
        GROUP BY w.routing_template_id
        ORDER BY count(*) DESC, max(w.priority) DESC NULLS LAST
        LIMIT 1
    """), {"fid": factory_id, "pid": product_id})).scalar()
    if template_id:
        steps = list((await db.execute(
            select(RoutingTemplateStep)
            .where(RoutingTemplateStep.template_id == str(template_id))
            .order_by(RoutingTemplateStep.seq)
        )).scalars().all())
        if steps:
            return [
                {
                    "operation_name": s.operation_name,
                    "work_center": str(s.work_center) if s.work_center else None,
                    "standard_hours": float(s.standard_hours or 0),
                }
                for s in steps
            ]

    routing = (await db.execute(
        select(Routing).where(Routing.factory_id == factory_id, Routing.product_id == product_id)
    )).scalars().first()
    if routing and isinstance(routing.steps, list):
        return [
            {
                "operation_name": step.get("name") or step.get("operation_name"),
                "work_center": str(step.get("station") or step.get("work_center") or "") or None,
                "standard_hours": float(step.get("standard_hours") or step.get("time_min") or 0),
            }
            for step in sorted(routing.steps, key=lambda s: s.get("sequence") or s.get("seq") or 0)
        ]

    return []


async def route_stations_for_product(
    db: AsyncSession, factory_id: str, product_id: str
) -> List[str]:
    """路线上依次用到的工位编码（去重保序）。"""
    codes = [op["work_center"] for op in await route_ops_for_product(db, factory_id, product_id)]
    return list(dict.fromkeys([c for c in codes if c]))
