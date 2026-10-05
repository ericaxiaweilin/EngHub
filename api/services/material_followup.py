"""缺料催办：把"哪张单因哪些料不齐停下、该哪个岗位去追"变成任务中心里的一条待办。

这是虚拟引擎 + 岗位 agent 的接点。引擎已经能挡住不齐套的单（`plan_commit_gate` 与
虚拟工厂的材料门），但**挡住只是第一步**：谁都不知道的话，工厂就是静止地卡着。
所以每一次"因缺料不能执行"都要落一条带证据、有责任人、会自己跟进的待办。

三条硬要求，都写进代码而不是靠人记：

1. **证据不能丢**：待办的 payload 里带机种、工单、每一行缺什么（料号/品名/单位/需求/已收/可用/缺口、
   层级与父件、自制还是外购、有没有对应的下级工单、卡在哪个门）——
   拿到这条任务的人不需要再问"缺哪个、缺多少、是我来做还是要去买"。
2. **责任人从 HR 映射来，不编名字**：
   - 外购缺料 → 采购部/采购员（agent=采购智能体）；
   - 自制缺下层 → 该单首道工序工位（路线 → stations → 工位中文名）对应班组的**组长**，
     没有组长再退技术员/主管（agent=PMC 智能体）；
   - 映射不到在岗人选时，任务照样开但**不指派**，并把"HR 里找不到该工位在岗人员"写进受阻原因，
     交回人事/组织去补，绝不抓一个名字填上。
3. **不许灌行**：同一张工单在任务中心里最多一条未关闭的缺料催办（按 payload 里的工单号判重），
   跟进节奏交给 followup 机制自己走。历史上仓储智能体每轮给同一批低库存物料重复插申请，
   41 天灌了 890 万行，这条教训就落在这个判重上。

写入口只有 `followup_task_service.create_task` 一个：通知、跟进日志、状态机都在那里，
这里不再自己 INSERT 一次。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CHASE_LIMIT = max(1, int(os.getenv("MATERIAL_CHASE_LIMIT", "20")))

# 每单取前几行明细进 payload：一条任务要能看懂，又不能把 5 千行塞进 jsonb
EVIDENCE_LINES_PER_ORDER = 8

# 一张单缺什么：齐套快照 + 有没有对应的下级工单（自制件的"在等谁"要说清）
SHORTAGE_SQL = text("""
    SELECT w.id AS work_order_id, w.work_order_code, w.product_id AS model_code,
           w.planned_qty, w.wo_type, w.status AS wo_status,
           m.material_code, m.material_name, m.unit,
           m.qty_per_unit, m.required_qty, m.received_qty, m.available_qty, m.shortage_qty,
           m.level, m.parent_code, m.item_type,
           (SELECT string_agg(c.work_order_code || ':' || c.status, ', ' ORDER BY c.status)
              FROM work_orders c
             WHERE c.parent_work_order_id = w.id AND c.product_id = m.material_code
               AND COALESCE(c.status, '') <> 'cancelled') AS child_orders
    FROM work_orders w
    JOIN work_order_materials m ON m.work_order_id = w.id
    WHERE w.factory_id = :fid
      AND w.status IN ('pending', 'released', 'in_progress')
      AND GREATEST(COALESCE(m.shortage_qty, 0), 0) > 0
      AND (CAST(:only_models AS text[]) IS NULL OR w.product_id = ANY(CAST(:only_models AS text[])))
    ORDER BY w.product_id NULLS LAST, w.work_order_code,
             GREATEST(COALESCE(m.shortage_qty, 0), 0) DESC
""")

# 首道工序工位 → 工位中文名（HR 的 station 存的是中文车间/工位名）
STATION_NAME_SQL = text("""
    SELECT station_name FROM stations
    WHERE factory_id = :fid AND station_code = :code
""")

OWNER_SQL = text("""
    SELECT name, employee_code, position, department
    FROM hr_employees
    WHERE factory_id = :fid AND status = 'active'
      AND (
            (:role = 'purchase'
               AND (position IN ('采购员', '采购专员', '物控员') OR department = '采购部'))
         OR (:role = 'make'
               -- 工位名两边写法不一致：stations 是"涂装车间"，HR 的 station 存"涂装"，
               -- 所以去尾字再比一次，而不是要求各系统字段一模一样
               AND (station = :station_name OR station = ANY(:station_aliases))
                    AND position IN ('组长', '主管', '经理', '技术员'))
          )
    ORDER BY CASE position
               WHEN '组长' THEN 0 WHEN '主管' THEN 1 WHEN '经理' THEN 2
               WHEN '采购员' THEN 0 WHEN '采购专员' THEN 1 WHEN '物控员' THEN 2
               ELSE 3 END,
             name
    LIMIT 1
""")


def _station_aliases(station_name: Optional[str]) -> List[str]:
    import re

    if not station_name:
        return []
    return [station_name, re.sub(r"(车间|工位|生产线|线)$", "", station_name)]


async def _owner(db: AsyncSession, factory_id: str, role: str,
                 station_name: Optional[str]) -> Dict[str, Any]:
    """从 HR 找该由谁催；找不到就说找不到（不编人名）。"""
    if role == "make" and not station_name:
        return {"assigned_to": None, "owner_basis": "自制缺料但这张单没有可映射的首道工位"}
    rows = (await db.execute(OWNER_SQL, {
        "fid": factory_id, "role": role, "station_name": station_name or "",
        "station_aliases": _station_aliases(station_name),
    })).mappings().all()
    if not rows:
        return {
            "assigned_to": None,
            "owner_basis": (
                f"HR 里没有{'采购部/采购员' if role == 'purchase' else f'工位「{station_name}」的组长/技术员'}在岗人员"
            ),
        }
    person = rows[0]
    return {
        "assigned_to": str(person["name"]),
        "owner_basis": f"{person['department']}／{person['position']}（{person['employee_code']}）",
    }


def _evidence(order: Dict[str, Any], lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把"缺什么、在等谁、归谁"压成一段能核对的证据，字段名与库里一致。"""
    return {
        "category": "material_shortage",
        "factory_id": order["factory_id"],
        "work_order_id": order["work_order_id"],
        "work_order_code": order["work_order_code"],
        "model_code": order["model_code"],
        "wo_type": order["wo_type"],
        "planned_qty": order["planned_qty"],
        "blocked_by": "齐套快照有缺口 → 材料门与下达门都不放行",
        "shortage_total": order["shortage_total"],
        "purchase_lines": order["purchase_lines"],
        "make_lines": order["make_lines"],
        "lines": lines,
        "evidence_note": (
            "缺口来自 work_order_materials（齐套快照，按当前台账刷新）；"
            "make 行的 child_orders 给出对应下级工单与状态，没有就是还没拆单"
        ),
    }


async def _group_per_order(db: AsyncSession, factory_id: str, models: Optional[List[str]],
                           limit: int) -> List[Dict[str, Any]]:
    rows = (await db.execute(SHORTAGE_SQL, {
        "fid": factory_id, "only_models": models if models else None,
    })).mappings().all()
    orders: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = str(r["work_order_id"])
        o = orders.setdefault(key, {
            "factory_id": factory_id,
            "work_order_id": key,
            "work_order_code": r["work_order_code"],
            "model_code": r["model_code"],
            "wo_type": r["wo_type"],
            "planned_qty": r["planned_qty"],
            "wo_status": r["wo_status"],
            "lines": [],
            "shortage_total": 0.0,
            "purchase_lines": 0,
            "make_lines": 0,
        })
        short = float(r["shortage_qty"] or 0)
        item = str(r["item_type"] or "")
        if item == "buy":
            o["purchase_lines"] += 1
        elif item == "make":
            o["make_lines"] += 1
        o["shortage_total"] += short
        if len(o["lines"]) < EVIDENCE_LINES_PER_ORDER:
            o["lines"].append({
                "material_code": r["material_code"],
                "material_name": r["material_name"],
                "unit": r["unit"],
                "required": float(r["required_qty"] or 0),
                "received": float(r["received_qty"] or 0),
                "available": float(r["available_qty"] or 0),
                "shortage": short,
                "level": r["level"],
                "parent_code": r["parent_code"],
                "item_type": item or "unknown",
                "child_orders": r["child_orders"],
            })
    picked = list(orders.values())[:limit]
    for o in picked:
        o["shortage_total"] = round(o["shortage_total"], 3)
    return picked


async def chase_material_shortages(
    db: AsyncSession, factory_id: str, *, limit: int = CHASE_LIMIT,
    models: Optional[List[str]] = None, apply: bool = True,
    created_by: str = "virtual_factory",
) -> Dict[str, Any]:
    """把"因缺料不能执行"的单开成催料待办，责任人从 HR 岗位映射来。"""
    from api.services.followup_task_service import create_task

    receipt: Dict[str, Any] = {
        "factory_id": factory_id, "limit": limit, "dry_run": not apply,
        "orders_short": 0, "created": 0, "skipped_open": 0, "unassigned": 0,
        "no_purchase_owner": 0, "created_examples": [],
    }
    orders = await _group_per_order(db, factory_id, models, limit)
    receipt["orders_short"] = len(orders)
    if not orders:
        receipt["status"] = "nothing_to_chase"
        receipt["message"] = "本厂没有因缺料停着的工单，不需要催办"
        return receipt

    # 一张单只留一条未关闭的催办：曾经每轮重复插申请灌出过 890 万行，这条不许退
    existing = {str(row) for row in (await db.execute(text("""
        SELECT payload->>'work_order_id' FROM followup_tasks
        WHERE factory_id = :fid AND status NOT IN ('closed', 'done', 'cancelled')
          AND payload->>'category' = 'material_shortage'
    """), {"fid": factory_id})).scalars().all() if row}
    receipt["open_already"] = len(existing)

    caps = await _primary_stations(db, factory_id, [o["work_order_id"] for o in orders])
    for order in orders:
        wo_id = order["work_order_id"]
        if wo_id in existing:
            receipt["skipped_open"] += 1
            continue
        role = "purchase" if order["purchase_lines"] >= order["make_lines"] else "make"
        station_code = caps.get(wo_id)
        station_name = None
        if station_code:
            station_name = (await db.execute(STATION_NAME_SQL, {
                "fid": factory_id, "code": station_code,
            })).scalar()
        owner = await _owner(db, factory_id, role, station_name)
        if not owner["assigned_to"]:
            receipt["unassigned"] += 1
            if role == "purchase":
                receipt["no_purchase_owner"] += 1
        agent_key = "procurement_agent" if role == "purchase" else "pmc_agent"
        evidence = _evidence(order, order["lines"])
        title = (
            f"催料｜{order['work_order_code']}（机种 {order['model_code'] or '-'}）"
            f"缺 {order['purchase_lines']} 行外购 / {order['make_lines']} 行自制"
        )[:200]
        description = (
            f"工单 {order['work_order_code']}（{order['wo_status']}）合计缺 "
            f"{order['shortage_total']:g} 件，已挡在齐套门外不能投产。"
            f"归口：{owner['owner_basis']}。明细见任务附件（料号/需求/已收/可用/缺口/层级/父件/下级工单）。"
        )
        if not apply:
            receipt["created_examples"].append({
                "title": title, "assigned_to": owner["assigned_to"],
                "role": role, "station": station_code,
                "shortage_total": order["shortage_total"],
            })
            continue
        await create_task(
            db, factory_id, created_by, title,
            description=description,
            agent_key=agent_key,
            item_type="assigned" if owner["assigned_to"] else "followup",
            assigned_to=owner["assigned_to"],
            block_reason=f"缺料不能执行：{owner['owner_basis']}",
            source="virtual_factory",
            conversation_hint="这批料什么时候能到？到了引擎会自动放行这张单继续生产。",
            payload=json.dumps(evidence, ensure_ascii=False),
            follow_interval_minutes=240,
        )
        receipt["created"] += 1
        receipt["created_examples"].append({
            "title": title, "assigned_to": owner["assigned_to"], "role": role,
        })
        receipt["created_examples"] = receipt["created_examples"][:5]
    receipt["status"] = "ok"
    receipt["message"] = (
        f"因缺料停着的工单 {receipt['orders_short']} 张：新开催办 {receipt['created']} 条、"
        f"已有未关闭催办 {receipt['skipped_open']} 条不再重复挂；"
        f"其中 {receipt['unassigned']} 条在 HR 里映射不到在岗责任人（不编名字，见受阻原因）"
    )
    return receipt


async def _primary_stations(db: AsyncSession, factory_id: str,
                            order_ids: List[str]) -> Dict[str, str]:
    """每张单的首道工序工位（沿用虚拟工厂的路线映射口径，不在这里另算一份规则）。"""
    if not order_ids:
        return {}
    rows = (await db.execute(text("""
        WITH route_station AS (
            SELECT w.id AS work_order_id, st.work_center AS station_code, st.seq::int AS step_seq
            FROM work_orders w
            JOIN routing_template_steps st ON st.template_id::text = w.routing_template_id::text
            WHERE w.id = ANY(CAST(:ids AS text[])) AND COALESCE(st.work_center, '') <> ''
            UNION ALL
            SELECT w.id, COALESCE(s->>'station', s->>'work_center'),
                   COALESCE((s->>'sequence')::int, (s->>'seq')::int, 0)
            FROM work_orders w
            JOIN routings r ON r.id = w.routing_id, jsonb_array_elements(r.steps::jsonb) AS s
            WHERE w.id = ANY(CAST(:ids AS text[]))
              AND COALESCE(s->>'station', s->>'work_center', '') <> ''
        )
        SELECT DISTINCT ON (work_order_id) work_order_id, station_code
        FROM route_station ORDER BY work_order_id, step_seq
    """), {"ids": order_ids})).all()
    return {str(row[0]): str(row[1]) for row in rows}
