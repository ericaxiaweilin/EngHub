"""计划下达的逐单就绪门：把"这一版计划里到底哪些单能开工"算清楚，再决定动不动。

无人链条缺的是最后一格：APS 每轮都出草案（10-05 机械厂一份 961 行任务），但线上 314 份方案
**confirmed=0、released=0、is_current=0** —— 排了半天没有一版成为生效计划，ATP/产能负荷/控制塔
因此一直按"空车间"承诺。人工点不下去也有原因：`release_schedule` 是整版下达，一版里必然混着
缺料单和没排进的单，硬闸必然命中，计划员只能整版放着。

这里把粒度改成**按工单**。一张单要进"可下达"必须同时满足四条，判据全部来自库里的事实：

1. 它在这一版里排进了工序行（没排进 = 还在待排池，谈不上开工）；
2. 排进的工序行数 = 它自己工艺路线的工序数 —— 只排进一半的单不下，车间不该拿到残缺工艺；
3. 它所有任务行 `material_ready` 为真 —— 缺口由齐套快照按当前台账刷新，自制件的下层没完工
   就仍留缺口，所以这一条把层级依赖一起管住了；
4. 首道工序的工位编码在**本厂** stations 查得到（映射不到就写不进 assigned_station_id，
   等于把跨厂/未登记的工位当成派工结果）。

不满足的每一类都点名差什么（缺料几行、少几道工序、哪个工位映射不到），交回计划员/采购/工程；
门只放行该放的，不把剩下的当已下达。

落库按开发尺度限量（`PLAN_COMMIT_MAX_ORDERS`），且默认只预演：`PLAN_COMMIT_APPLY` 没打开时
一行都不改 —— "要不要让机器自己下达计划"是业务决定，不由代码顺手替工厂做。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PLAN_PICK_SQL = text("""
    SELECT id, schedule_code, version_number, input_fingerprint, unscheduled_count,
           status, is_current, created_at
    FROM aps_schedules
    WHERE factory_id = :fid AND status <> 'archived' AND input_fingerprint IS NOT NULL
      AND (CAST(:sid AS text) IS NULL OR id = CAST(:sid AS text))
    ORDER BY is_current DESC NULLS LAST, created_at DESC
    LIMIT 1
""")

# 注意 expected 用的是工单自己的路线绑定（模板路线看工步行数，旧版看 routings.steps JSON）：
# 子装配件工单同样有自己的路线，不按 wo_type 特判，否则"排齐"会被算松。
GATE_SQL = text("""
    WITH pool AS (
        SELECT wo.id, wo.work_order_code, wo.wo_type, wo.status, wo.product_id,
               wo.planned_qty, wo.planned_due, wo.planned_start, wo.assigned_station_id,
               wo.routing_template_id, wo.routing_id
        FROM work_orders wo
        WHERE wo.factory_id = :fid
          AND wo.wo_type IN ('master', 'component')
          AND wo.status IN ('released', 'in_progress', 'pending')
    ),
    expected AS (
        SELECT p.id AS work_order_id,
               CASE
                 WHEN p.routing_template_id IS NOT NULL THEN (
                     SELECT count(*) FROM routing_template_steps st
                     WHERE st.template_id::text = p.routing_template_id::text
                 )
                 ELSE COALESCE((
                     SELECT jsonb_array_length(r.steps::jsonb) FROM routings r WHERE r.id = p.routing_id
                 ), 0)
               END AS route_steps
        FROM pool p
    ),
    task AS (
        SELECT t.work_order_id,
               count(*) AS plan_rows,
               count(*) FILTER (WHERE COALESCE(t.material_ready, TRUE) = FALSE) AS short_rows
        FROM aps_schedule_tasks t
        WHERE t.schedule_id = :sid
        GROUP BY t.work_order_id
    ),
    first_step AS (
        SELECT DISTINCT ON (t.work_order_id) t.work_order_id, t.station_id, t.planned_start
        FROM aps_schedule_tasks t
        WHERE t.schedule_id = :sid
        ORDER BY t.work_order_id, t.operation_seq, t.planned_start
    ),
    kit AS (
        SELECT m.work_order_id,
               count(*) FILTER (WHERE COALESCE(m.required_qty, 0) > 0) AS kit_rows
        FROM work_order_materials m
        JOIN pool pp ON pp.id = m.work_order_id      -- 只数池子里这些单，不扫全表
        GROUP BY m.work_order_id
    )
    SELECT p.id AS work_order_id, p.work_order_code, p.wo_type, p.status, p.product_id,
           p.planned_qty, p.planned_due, p.planned_start,
           COALESCE(e.route_steps, 0) AS route_steps,
           COALESCE(t.plan_rows, 0) AS plan_rows,
           COALESCE(t.short_rows, 0) AS short_rows,
           COALESCE(k.kit_rows, 0) AS kit_rows,
           f.station_id AS first_station_code,
           f.planned_start AS first_start,
           CASE WHEN f.station_id IS NULL THEN TRUE ELSE (s.id IS NOT NULL) END AS station_mapped
    FROM pool p
    LEFT JOIN expected e ON e.work_order_id = p.id
    LEFT JOIN task t ON t.work_order_id = p.id
    LEFT JOIN kit k ON k.work_order_id = p.id
    LEFT JOIN first_step f ON f.work_order_id = p.id
    LEFT JOIN stations s ON s.station_code = f.station_id AND s.factory_id = :fid
    ORDER BY p.planned_due NULLS LAST, p.work_order_code
""")

HOLD_REASONS = {
    "not_scheduled": "这一版里没有它的任何工序行（仍在待排池）",
    "partial_steps": "只排进了一部分工序：车间不该拿到残缺工艺",
    "shortage": "有物料缺口未齐套（含下层自制件没完工）",
    "no_kit_evidence": "齐套表里没有任何带需求量的物料行：不知道要发什么料就不算齐套，不许下达",
    "station_unmapped": "首道工序的工位编码在本厂 stations 查不到，无法回写派工工位",
}

PREVIEW_LIMIT = 20

# 已经下达过的单不再参与判定：released/in_progress 表示这张单早被放行（人或门），
# 每轮再"放行"一次只是重复写状态和事件；数量对账要靠 already_released_count。
ALREADY_ACTED = ("released", "in_progress")


def _verdict(row: Any) -> Dict[str, Any]:
    """一张单的判定：能下就说能下，不能下要点名差什么。"""
    steps = int(row["route_steps"] or 0)
    plan_rows = int(row["plan_rows"] or 0)
    short_rows = int(row["short_rows"] or 0)
    kit_rows = int(row.get("kit_rows") or 0)
    reasons: List[str] = []
    if plan_rows == 0:
        reasons.append("not_scheduled")
    else:
        if steps and plan_rows < steps:
            reasons.append("partial_steps")
        if short_rows > 0:
            reasons.append("shortage")
    if kit_rows == 0:
        # 没有一行领料需求 = 没有依据说这单能开工。缺料和"根本不知道缺什么"
        # 是两种不齐套，后者更危险：它会被前一种判据当成"没缺口"直接放行。
        reasons.append("no_kit_evidence")
    if not row["station_mapped"]:
        reasons.append("station_unmapped")
    already = str(row["status"] or "") in ALREADY_ACTED
    return {
        "already_released": already,
        "work_order_id": str(row["work_order_id"]),
        "work_order_code": row["work_order_code"],
        "wo_type": row["wo_type"],
        "status": row["status"],
        "product_id": row["product_id"],
        "planned_qty": row["planned_qty"],
        "planned_due": row["planned_due"].isoformat() if row["planned_due"] else None,
        "route_steps": steps,
        "plan_rows": plan_rows,
        "short_rows": short_rows,
        "first_station_code": row["first_station_code"],
        "first_start": row["first_start"],
        "station_mapped": bool(row["station_mapped"]),
        "ready": bool(not reasons and not already),
        "hold_reasons": [] if already else reasons,
    }


async def _latest_draft(db: AsyncSession, factory_id: str,
                        schedule_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """取"这版"或"最新版"。点名某版是给人用的：下达第 340 版就得按第 340 版判，
    不能拿库里最新的那版替它决定谁能开工。"""
    row = (await db.execute(PLAN_PICK_SQL, {"fid": factory_id, "sid": schedule_id})).mappings().first()
    if row is None:
        return None
    return {
        "schedule_id": str(row["id"]),
        "schedule_code": row["schedule_code"],
        "version_number": row["version_number"],
        "input_fingerprint": row["input_fingerprint"],
        "plan_status": row["status"],
        "is_current": bool(row["is_current"]),
        "generated_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def evaluate_commit_gate(
    db: AsyncSession, factory_id: str, *, full: bool = False,
    schedule_id: Optional[str] = None,
) -> Dict[str, Any]:
    """只读预演：这一版草案里哪些单可以下达、哪些卡在哪一条门上。

    默认只回前 PREVIEW_LIMIT 条明细（心跳和界面用），`full=True` 才带回全部 id ——
    下达那一步需要完整清单，回执里则只放限量样本，否则心跳 JSON 会胀到没人看。
    """
    plan = await _latest_draft(db, factory_id, schedule_id)
    if plan is None:
        return {
            "factory_id": factory_id, "plan": None,
            "evaluated_orders": 0, "ready_count": 0, "held_count": 0,
            "already_released_count": 0,
            "hold_reason_counts": {key: 0 for key in HOLD_REASONS},
            "ready": [], "held": [], "ready_ids": [],
            "status": "no_current_draft",
            "reason": "本厂没有带输入指纹的方案：先跑一次排程（/api/v1/aps/schedule）",
            "gate_rules": {"requires": ["排进本版本", "工序排齐（任务行数=路线工序数）",
                                        "全部任务行齐套", "齐套表里有带需求量的领料行",
                                        "首道工序工位可在本厂映射到 stations.id"],
                           "hold_reason_definitions": HOLD_REASONS},
        }
    rows = (await db.execute(GATE_SQL, {"fid": factory_id, "sid": plan["schedule_id"]})).mappings().all()
    verdicts = [_verdict(r) for r in rows]
    already = [v for v in verdicts if v["already_released"]]
    rest = [v for v in verdicts if not v["already_released"]]
    ready = [v for v in rest if v["ready"]]
    held = [v for v in rest if not v["ready"]]
    counts: Dict[str, int] = {key: 0 for key in HOLD_REASONS}
    for v in held:
        for reason in v["hold_reasons"]:
            counts[reason] += 1
    out = {
        "factory_id": factory_id,
        "plan": plan,
        "evaluated_orders": len(verdicts),
        "ready_count": len(ready),
        "held_count": len(held),
        "already_released_count": len(already),
        "hold_reason_counts": counts,
        "ready": [dict(v, first_start=str(v["first_start"])) for v in ready][:PREVIEW_LIMIT],
        "held": held[:PREVIEW_LIMIT],
        "ready_ids": [v["work_order_id"] for v in ready],
        "gate_rules": {
            "requires": ["排进本版本", "工序排齐（任务行数=路线工序数）", "全部任务行齐套",
                         "齐套表里有带需求量的领料行",
                         "首道工序工位可在本厂映射到 stations.id"],
            "hold_reason_definitions": HOLD_REASONS,
            "route_step_source": "工单自己的绑定：模板看 routing_template_steps 行数，旧版看 routings.steps",
        },
        "status": "ok",
    }
    if full:
        out["ready_full"] = ready
    return out


def _event(*, factory_id: str, event_type: str, actor: str, schedule_id: str,
           work_order_id: Optional[str], reason: str, payload: Dict[str, Any]):
    from database.models import ApsPlanEvent

    return ApsPlanEvent(
        id=str(uuid.uuid4()),
        factory_id=factory_id,
        event_type=event_type,
        actor=actor,
        schedule_id=schedule_id,
        work_order_id=work_order_id,
        reason=reason,
        payload=payload,
    )


async def commit_ready_orders(
    db: AsyncSession,
    factory_id: str,
    *,
    apply: bool,
    actor: str = "plan-commit-gate",
    max_orders: int = 5,
) -> Dict[str, Any]:
    """把通过就绪门的单下达，并让这一版成为生效计划（is_current）。

    只动该动的：held 的单状态不变；任务行也只把放行那几张的置为 released，其余留在 planned ——
    否则界面会把"没齐套"读成"已下达"。
    """
    from database.models import ApsSchedule, WorkOrder

    gate = await evaluate_commit_gate(db, factory_id, full=True)
    plan = gate["plan"]
    receipt: Dict[str, Any] = {
        "factory_id": factory_id,
        "schedule_code": plan["schedule_code"] if plan else None,
        "version_number": plan["version_number"] if plan else None,
        "evaluated_orders": gate["evaluated_orders"],
        "ready_count": gate["ready_count"],
        "held_count": gate["held_count"],
        "already_released_count": gate["already_released_count"],
        "hold_reason_counts": gate["hold_reason_counts"],
        "batch_limit": max_orders,
        "released_orders": 0,
        "released_tasks": 0,
        "plan_is_current": False,
        "dry_run": not apply,
    }
    if plan is None:
        receipt["status"] = gate["status"]
        receipt["reason"] = gate["reason"]
        return receipt

    schedule_id = plan["schedule_id"]
    receipt["plan_status"] = plan["plan_status"]
    batch_ids = gate["ready_ids"][:max_orders]
    if apply and not batch_ids:
        # 一张都不该动：不落任何状态，把"为什么全被压住"原样交回（心跳里也是这句）
        await db.rollback()
        receipt["status"] = "nothing_ready"
        receipt["reason"] = (
            f"{receipt['held_count']} 张单全部卡在就绪门上，原因分布 {receipt['hold_reason_counts']}"
        )
        return receipt
    ready_by_id = {v["work_order_id"]: v for v in gate.get("ready_full", gate["ready"])}

    for wo_id in batch_ids:
        item = ready_by_id.get(wo_id) or {}
        wo = await db.get(WorkOrder, wo_id)
        if wo is None:
            continue
        if not apply:
            continue
        # 只翻状态：开工时刻与派工工位留在方案任务行里，由人工确认（confirm_schedule）回写。
        # 回写 planned_start/assigned_station_id 会改动排程自己的输入，逐单门就成了自激环。
        wo.status = "released"
        wo.released_by = actor
        wo.updated_at = datetime.utcnow()
        receipt["released_orders"] += 1
        updated = await db.execute(text("""
            UPDATE aps_schedule_tasks SET status = 'released'
            WHERE schedule_id = :sid AND work_order_id = :wid
              AND COALESCE(status, '') NOT IN ('completed', 'cancelled')
        """), {"sid": schedule_id, "wid": wo_id})
        receipt["released_tasks"] += int(updated.rowcount or 0)
        db.add(_event(
            factory_id=factory_id, event_type="order_released_by_gate", actor=actor,
            schedule_id=schedule_id, work_order_id=wo_id,
            reason=f"逐单就绪门放行：{item.get('plan_rows')}/{item.get('route_steps')} 道工序排齐且齐套",
            payload={"work_order_code": item.get("work_order_code"),
                     "route_steps": item.get("route_steps"),
                     "plan_rows": item.get("plan_rows"),
                     "basis": "scheduled_all_steps + material_ready + station_mapped"},
        ))

    if not apply:
        await db.rollback()
        receipt["status"] = "dry_run"
        receipt["would_release"] = len(batch_ids)
        receipt["message"] = (
            f"预演：{receipt['ready_count']}/{receipt['evaluated_orders']} 张可下达"
            f"（本轮上限 {max_orders} 张 → 实取 {len(batch_ids)} 张），"
            f"{receipt['held_count']} 张卡在门上，原因分布 {receipt['hold_reason_counts']}"
        )
        return receipt

    row = await db.get(ApsSchedule, schedule_id)
    # 一张都没放行就不动方案状态：否则"空批次"会把草案悄悄变成生效计划
    if row is not None and receipt["released_orders"] > 0:
        await db.execute(text("""
            UPDATE aps_schedules SET is_current = FALSE, status = 'archived', updated_at = NOW()
            WHERE factory_id = :fid AND is_current = TRUE AND id <> :sid
        """), {"fid": factory_id, "sid": schedule_id})
        row.status = "released"
        row.is_current = True
        row.released_by = actor
        row.released_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        receipt["plan_is_current"] = True
        db.add(_event(
            factory_id=factory_id, event_type="plan_committed_by_gate", actor=actor,
            schedule_id=schedule_id, work_order_id=None,
            reason=f"逐单就绪门：{receipt['released_orders']} 张下达、"
                   f"{receipt['held_count']} 张留在待排池",
            payload={"released_orders": receipt["released_orders"],
                     "released_tasks": receipt["released_tasks"],
                     "held_count": receipt["held_count"],
                     "hold_reason_counts": receipt["hold_reason_counts"],
                     "input_fingerprint": plan["input_fingerprint"]},
        ))
    await db.commit()
    receipt["status"] = "ok"
    receipt["message"] = (
        f"已下达 {receipt['released_orders']} 张（{receipt['released_tasks']} 道工序行），"
        f"{receipt['held_count']} 张卡在就绪门上留在池子里；"
        f"方案 {receipt['schedule_code']} 现为生效计划"
    )
    return receipt


APPLY_ENABLED = os.getenv("PLAN_COMMIT_APPLY", "false").strip().lower() in ("1", "true", "yes", "on")
MAX_ORDERS = max(1, int(os.getenv("PLAN_COMMIT_MAX_ORDERS", "5")))

# 撤销机制自己声明过的放行 = 承认之前放错了，是在改状态不是在删数据，
# 但同样要显式开：默认只把"哪些单被放错了"报出来。
RECONCILE_APPLY = os.getenv("ENGINE_RECONCILE_APPLY", "false").strip().lower() in ("1", "true", "yes", "on")


FALSE_RELEASES_SQL = text("""
    SELECT wo.id AS work_order_id, wo.work_order_code, wo.wo_type, wo.status,
           wo.released_by, wo.product_id, wo.planned_qty,
           count(m.id) FILTER (WHERE COALESCE(m.required_qty, 0) > 0) AS kit_rows
    FROM work_orders wo
    LEFT JOIN work_order_materials m ON m.work_order_id = wo.id
    WHERE wo.factory_id = :fid
      AND wo.wo_type <> 'operation'                    -- 仿真自己的工序单没有领料概念
      AND wo.status IN ('released', 'in_progress')
      AND wo.released_by IN ('plan-commit-gate', 'component_kit')
      AND COALESCE(wo.completed_qty, 0) = 0            -- 有产出的不动，那是另一条账
      AND NOT EXISTS (SELECT 1 FROM production_reports pr WHERE pr.work_order_id = wo.id)
    GROUP BY wo.id, wo.work_order_code, wo.wo_type, wo.status,
             wo.released_by, wo.product_id, wo.planned_qty
    HAVING count(m.id) FILTER (WHERE COALESCE(m.required_qty, 0) > 0) = 0
    ORDER BY wo.work_order_code
""")


async def audit_false_releases(
    db: AsyncSession, factory_id: str, *,
    apply: Optional[bool] = None, actor: str = "plan-commit-gate",
    limit: int = 200,
) -> Dict[str, Any]:
    """把"被机制放行、但齐套表里一行领料需求都没有"的单收回待开工。

    只撤销机制自己声明的放行（`released_by` 是这两个机制名），人工下达的一律不碰；
    有报工或有产出的不碰（那是既成事实，要按虚假产出那条账处理）。
    收回时连带把这一版里它的工序行从 released 退回 planned —— 否则界面仍是"已下达"。
    """
    if apply is None:
        apply = RECONCILE_APPLY
    rows = (await db.execute(
        FALSE_RELEASES_SQL, {"fid": factory_id}
    )).mappings().all()
    plan = await _latest_draft(db, factory_id)
    schedule_id = plan["schedule_id"] if plan else None
    receipt: Dict[str, Any] = {
        "factory_id": factory_id, "apply": apply, "dry_run": not apply,
        "false_releases_found": len(rows), "revoked": 0, "tasks_reset": 0,
        "examples": [dict(r) for r in rows[:5]],
    }
    if not rows:
        receipt["status"] = "nothing_to_revoke"
        return receipt
    if not apply:
        receipt["status"] = "dry_run"
        receipt["message"] = (f"预演：{len(rows)} 张单被机制放行但没有任何领料需求行，"
                             "可收回待开工；开 ENGINE_RECONCILE_APPLY=true 才真收回")
        return receipt

    for row in list(rows)[:limit]:
        wo_id = str(row["work_order_id"])
        updated = await db.execute(text("""
            UPDATE work_orders
            SET status = 'pending', released_by = NULL,
                remark = COALESCE(remark, '') || :note,
                updated_at = NOW()
            WHERE id = :wid AND status IN ('released', 'in_progress')
              AND COALESCE(completed_qty, 0) = 0
              AND released_by IN ('plan-commit-gate', 'component_kit')
        """), {
            "wid": wo_id,
            "note": (f"；就绪门收回：放行时齐套表里没有任何领料需求行"
                     f"（放行方 {row['released_by']}），不能算齐套"),
        })
        receipt["revoked"] += int(updated.rowcount or 0)
        reset = await db.execute(text("""
            UPDATE aps_schedule_tasks SET status = 'planned'
            WHERE work_order_id = :wid AND schedule_id = :sid AND status = 'released'
        """), {"wid": wo_id, "sid": schedule_id})
        receipt["tasks_reset"] += int(reset.rowcount or 0)
        if schedule_id:
            db.add(_event(
                factory_id=factory_id, event_type="order_release_revoked", actor=actor,
                schedule_id=schedule_id, work_order_id=wo_id,
                reason=f"就绪门收回误放行：{row['work_order_code']} 没有领料依据",
                payload={"released_by": str(row["released_by"] or ""),
                         "wo_type": str(row["wo_type"] or ""),
                         "kit_rows": int(row["kit_rows"] or 0)},
            ))
    await db.commit()
    receipt["status"] = "ok"
    receipt["message"] = (f"收回 {receipt['revoked']} 张没有领料依据的放行，"
                          f"退回 {receipt['tasks_reset']} 道工序行")
    return receipt
