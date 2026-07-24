"""
工序派工与流转引擎（016）

核心职责：
- dispatch_operations: 主工单下达时，按工艺路线模板自动生成工序工单
- advance_flow: 工序工单完工时，自动释放下一道工序
- 支持串行/并行工序、QC 品质门

岗位替代（调度员/车间主任）：
- auto_dispatch_station: 事件驱动自派发（工位空闲→自动分配最高优先级工单）
- exception_reschedule: 设备异常→自动转移受影响工单
- shift_handover_report: 交接班自动报告
- line_balance: 产线平衡分析
"""

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import WorkOrder, RoutingTemplate, RoutingTemplateStep, WoStatusLog


async def dispatch_operations(
    db: AsyncSession,
    master_wo: WorkOrder,
    template_steps: List[RoutingTemplateStep],
    operator: str,
) -> List[WorkOrder]:
    """
    主工单下达时调用：按工艺路线模板生成工序工单。

    规则：
    1. 遍历 template_steps，为每步创建 wo_type=operation 子工单
    2. 编码：{master_code}-{seq:02d}-{process_code}
    3. 首道工序（seq 最小且非并行）status=released；并行步骤也 released；其余 pending
    4. work_center = step.work_center or step.process_code
    5. parent_work_order_id = master_wo.id
    """
    if not template_steps:
        return []

    # 按 seq 排序
    sorted_steps = sorted(template_steps, key=lambda s: s.seq)

    # 确定首批释放的工序：第一道 + 所有标记 is_parallel 的连续步骤
    first_seq = sorted_steps[0].seq
    release_seqs = {first_seq}
    for step in sorted_steps[1:]:
        if step.is_parallel:
            release_seqs.add(step.seq)
        else:
            break  # 遇到非并行步骤停止

    created_ops: List[WorkOrder] = []
    now = datetime.utcnow()

    for step in sorted_steps:
        op_code = f"{master_wo.work_order_code}-{step.seq:02d}-{step.process_code}"
        wc = step.work_center or step.process_code
        status = "released" if step.seq in release_seqs else "pending"

        op_wo = WorkOrder(
            id=str(uuid.uuid4()),
            work_order_code=op_code,
            factory_id=master_wo.factory_id,
            sales_order_id=master_wo.sales_order_id,
            product_id=master_wo.product_id,
            routing_id=master_wo.routing_id,
            planned_qty=master_wo.planned_qty,
            unit=master_wo.unit,
            completed_qty=0,
            good_qty=0,
            defect_qty=0,
            scrap_qty=0,
            status=status,
            priority=master_wo.priority,
            planned_start=master_wo.planned_start,
            planned_due=master_wo.planned_due,
            assigned_station_id=None,
            current_routing_step=0,
            bom_version=master_wo.bom_version,
            parent_work_order_id=master_wo.id,
            wo_type="operation",
            process_code=step.process_code,
            operation_seq=step.seq,
            work_center=wc,
            routing_template_id=master_wo.routing_template_id,
            created_by=operator,
            updated_by=operator,
            released_by=operator if status == "released" else None,
            remark=f"工序{step.seq}: {step.operation_name}",
            created_at=now,
            updated_at=now,
        )
        db.add(op_wo)
        created_ops.append(op_wo)

    # 先 flush 工序工单，确保 FK 约束满足后再写日志
    await db.flush()

    # 记录状态日志（首道/并行工序的释放记录）
    for op_wo, step in zip(created_ops, sorted_steps):
        if op_wo.status == "released":
            log = WoStatusLog(
                id=str(uuid.uuid4()),
                work_order_id=op_wo.id,
                action="release",
                from_status="pending",
                to_status="released",
                operator=operator,
                comment=f"派工自动释放（工序{step.seq}: {step.operation_name}）",
                created_at=now,
            )
            db.add(log)

    await db.flush()
    return created_ops


async def advance_flow(
    db: AsyncSession,
    completed_op: WorkOrder,
    operator: str,
) -> Dict[str, Any]:
    """
    工序工单完工时调用：释放下一道工序。

    规则：
    1. 找同 parent 下 seq = current.seq + 1 的工序工单
    2. 如果下一步 is_parallel=True，继续释放后续并行步骤
    3. 如果当前步 is_qc_gate=True，需品质确认后才释放（暂不自动释放后道）
    4. 所有工序完工 → 主工单自动标记 completed

    返回：{"released_ops": [...], "master_completed": bool, "qc_pending": bool}
    """
    result = {"released_ops": [], "master_completed": False, "qc_pending": False}

    if not completed_op.parent_work_order_id:
        return result

    # 检查当前工序是否为 QC 门 — 如果是，后道不自动释放
    if completed_op.remark and "QC_GATE" in (completed_op.remark or ""):
        result["qc_pending"] = True
        # 仍然检查是否全部完工
        await _check_master_completion(db, completed_op, operator)
        return result

    # 查找当前工序的 seq
    current_seq = completed_op.operation_seq or 0

    # 查找同 parent 下所有工序工单
    siblings_result = await db.execute(
        select(WorkOrder)
        .where(
            WorkOrder.parent_work_order_id == completed_op.parent_work_order_id,
            WorkOrder.wo_type == "operation",
        )
        .order_by(WorkOrder.operation_seq)
    )
    siblings = siblings_result.scalars().all()

    # 找下一道待释放的工序
    next_seq = current_seq + 1
    released_any = False

    for sib in siblings:
        if sib.operation_seq == next_seq and sib.status == "pending":
            # 释放
            sib.status = "released"
            sib.released_by = operator
            sib.updated_by = operator
            sib.updated_at = datetime.utcnow()
            result["released_ops"].append(sib.work_order_code)
            released_any = True

            # 记录日志
            log = WoStatusLog(
                id=str(uuid.uuid4()),
                work_order_id=sib.id,
                action="release",
                from_status="pending",
                to_status="released",
                operator=operator,
                comment="前道工序完工自动释放",
                created_at=datetime.utcnow(),
            )
            db.add(log)

            # 如果下一步也是并行的，继续释放后续
            next_seq += 1
        elif sib.operation_seq == next_seq and sib.status != "pending":
            # 已释放/进行中，跳过继续看后续并行
            next_seq += 1
        elif released_any and sib.operation_seq == next_seq and sib.status == "pending":
            # 并行步骤
            sib.status = "released"
            sib.released_by = operator
            sib.updated_by = operator
            sib.updated_at = datetime.utcnow()
            result["released_ops"].append(sib.work_order_code)
            next_seq += 1

    await db.flush()

    # 检查主工单是否所有工序完工
    result["master_completed"] = await _check_master_completion(db, completed_op, operator)

    return result


async def confirm_qc_gate(
    db: AsyncSession,
    qc_op: WorkOrder,
    operator: str,
) -> Dict[str, Any]:
    """
    品质确认 QC 门工序后，释放后道工序。
    """
    result = {"released_ops": [], "master_completed": False}

    if not qc_op.parent_work_order_id:
        return result

    current_seq = qc_op.operation_seq or 0

    siblings_result = await db.execute(
        select(WorkOrder)
        .where(
            WorkOrder.parent_work_order_id == qc_op.parent_work_order_id,
            WorkOrder.wo_type == "operation",
            WorkOrder.operation_seq > current_seq,
            WorkOrder.status == "pending",
        )
        .order_by(WorkOrder.operation_seq)
    )
    pending_next = siblings_result.scalars().all()

    # 释放紧邻的下一道（及并行步骤）
    next_seq = current_seq + 1
    for sib in pending_next:
        if sib.operation_seq == next_seq:
            sib.status = "released"
            sib.released_by = operator
            sib.updated_by = operator
            sib.updated_at = datetime.utcnow()
            result["released_ops"].append(sib.work_order_code)

            log = WoStatusLog(
                id=str(uuid.uuid4()),
                work_order_id=sib.id,
                action="release",
                from_status="pending",
                to_status="released",
                operator=operator,
                comment="QC门品质确认后释放",
                created_at=datetime.utcnow(),
            )
            db.add(log)
            next_seq += 1
        else:
            break

    await db.flush()
    result["master_completed"] = await _check_master_completion(db, qc_op, operator)
    return result


async def _check_master_completion(
    db: AsyncSession,
    op_wo: WorkOrder,
    operator: str,
) -> bool:
    """检查主工单下所有工序是否完工，如果是则自动完成主工单。"""
    if not op_wo.parent_work_order_id:
        return False

    # 统计未完工工序数
    not_done = await db.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.parent_work_order_id == op_wo.parent_work_order_id,
            WorkOrder.wo_type == "operation",
            WorkOrder.status.notin_(["completed", "closed", "cancelled"]),
        )
    )
    remaining = not_done.scalar() or 0

    if remaining == 0:
        # 所有工序完工 → 主工单自动完成
        master_result = await db.execute(
            select(WorkOrder).where(WorkOrder.id == op_wo.parent_work_order_id)
        )
        master = master_result.scalar_one_or_none()
        if master and master.status not in ("completed", "closed", "cancelled"):
            master.status = "completed"
            master.completed_by = operator
            master.updated_by = operator
            master.updated_at = datetime.utcnow()
            master.actual_complete = datetime.utcnow()

            log = WoStatusLog(
                id=str(uuid.uuid4()),
                work_order_id=master.id,
                action="complete",
                from_status=master.status,
                to_status="completed",
                operator=operator,
                comment="所有工序完工，主工单自动完成",
                created_at=datetime.utcnow(),
            )
            db.add(log)
            await db.flush()
            return True

    return False


# ==================== 调度员岗位替代：事件驱动自派发 ====================


async def auto_dispatch_station(
    db: AsyncSession,
    factory_id: str,
    station_id: Optional[str] = None,
) -> Dict[str, Any]:
    """事件驱动自派发：工位空闲 → 自动分配最高优先级工单。

    调度员替代逻辑：不需要人盯着看哪个工位空了，系统自动派。
    规则：优先级 > 交期紧迫度 > 等待时间
    """
    from sqlalchemy import text as sql_text

    # 查找空闲工位（无在制工单的工位）
    if station_id:
        free_stations = [station_id]
    else:
        # 查找所有有 released 工单等待分配的工位
        result = await db.execute(sql_text("""
            SELECT DISTINCT work_center
            FROM work_orders
            WHERE factory_id = :fid AND status = 'released' AND wo_type = 'operation'
              AND assigned_station_id IS NULL
        """), {"fid": factory_id})
        free_stations = [r[0] for r in result.fetchall() if r[0]]

    dispatched = []
    for station in free_stations:
        # 找该工位等待中优先级最高的工单
        wo_result = await db.execute(sql_text("""
            SELECT id, work_order_code, priority, planned_due, work_center
            FROM work_orders
            WHERE factory_id = :fid AND status = 'released' AND wo_type = 'operation'
              AND (work_center = :wc OR assigned_station_id IS NULL)
            ORDER BY priority DESC, planned_due ASC, created_at ASC
            LIMIT 1
        """), {"fid": factory_id, "wc": station})
        wo = wo_result.mappings().first()

        if wo:
            # 自动分配
            await db.execute(sql_text("""
                UPDATE work_orders
                SET assigned_station_id = :sid, status = 'in_progress',
                    actual_start = NOW(), updated_at = NOW()
                WHERE id = :id
            """), {"sid": station, "id": wo["id"]})

            log = WoStatusLog(
                id=str(uuid.uuid4()),
                work_order_id=wo["id"],
                action="auto_dispatch",
                from_status="released",
                to_status="in_progress",
                operator="system",
                comment=f"事件驱动自派发到工位 {station}",
                created_at=datetime.utcnow(),
            )
            db.add(log)
            dispatched.append({"wo_code": wo["work_order_code"], "station": station})

    if dispatched:
        await db.flush()

    return {
        "dispatched_count": len(dispatched),
        "dispatched": dispatched,
        "mode": "event_driven",
        "message": f"✅ 自动派发 {len(dispatched)} 个工单" if dispatched else "无待派发工单",
    }


async def exception_reschedule(
    db: AsyncSession,
    factory_id: str,
    equipment_id: str,
    reason: str = "设备故障",
) -> Dict[str, Any]:
    """设备异常 → 自动转移受影响工单到其他可用工位。

    调度员替代逻辑：设备坏了不需要人打电话调单，系统自动转移。
    """
    from sqlalchemy import text as sql_text

    # 查找该设备上所有在制工单
    result = await db.execute(sql_text("""
        SELECT id, work_order_code, work_center, operation_seq, planned_qty
        FROM work_orders
        WHERE factory_id = :fid AND assigned_station_id = :eid
          AND status IN ('in_progress', 'released')
    """), {"fid": factory_id, "eid": equipment_id})
    affected = [dict(r) for r in result.mappings().all()]

    if not affected:
        return {"affected_count": 0, "message": "该设备无在制工单"}

    reassigned = []
    for wo in affected:
        # 释放回待派状态
        await db.execute(sql_text("""
            UPDATE work_orders
            SET assigned_station_id = NULL, status = 'released',
                remark = COALESCE(remark,'') || :tag, updated_at = NOW()
            WHERE id = :id
        """), {"tag": f" [{reason}:原工位{equipment_id}→待重派]", "id": wo["id"]})
        reassigned.append(wo["work_order_code"])

    await db.flush()

    # 触发重新派发
    redispatch = await auto_dispatch_station(db, factory_id)

    return {
        "equipment_id": equipment_id,
        "reason": reason,
        "affected_count": len(affected),
        "released_orders": reassigned,
        "redispatched": redispatch["dispatched_count"],
        "message": f"🚨 {reason}: {len(affected)} 个工单已释放并重新派发",
    }


async def shift_handover_report(
    db: AsyncSession,
    factory_id: str,
    shift: str = "day",
) -> Dict[str, Any]:
    """交接班自动报告：当前产线状态一览。

    调度员替代逻辑：不需要人写交接记录，系统自动生成。
    """
    from sqlalchemy import text as sql_text

    # 在制工单
    wip_result = await db.execute(sql_text("""
        SELECT work_order_code, product_id, planned_qty, completed_qty, good_qty,
               work_center, assigned_station_id, priority, planned_due
        FROM work_orders
        WHERE factory_id = :fid AND status = 'in_progress' AND wo_type = 'operation'
        ORDER BY priority DESC, planned_due ASC
    """), {"fid": factory_id})
    wip = [dict(r) for r in wip_result.mappings().all()]

    # 等待派发
    queue_result = await db.execute(sql_text("""
        SELECT COUNT(*) as cnt FROM work_orders
        WHERE factory_id = :fid AND status = 'released' AND wo_type = 'operation'
    """), {"fid": factory_id})
    queue_count = queue_result.scalar() or 0

    # 今日完工
    done_result = await db.execute(sql_text("""
        SELECT COUNT(*) as cnt, COALESCE(SUM(good_qty), 0) as total_good
        FROM work_orders
        WHERE factory_id = :fid AND status = 'completed'
          AND actual_complete >= CURRENT_DATE
    """), {"fid": factory_id})
    done_row = done_result.mappings().first()

    # 异常工单（超期）
    overdue_result = await db.execute(sql_text("""
        SELECT work_order_code, planned_due, work_center
        FROM work_orders
        WHERE factory_id = :fid AND status IN ('in_progress', 'released')
          AND planned_due < NOW()
    """), {"fid": factory_id})
    overdue = [dict(r) for r in overdue_result.mappings().all()]

    return {
        "shift": shift,
        "generated_at": datetime.utcnow().isoformat(),
        "wip_count": len(wip),
        "wip_orders": wip[:20],
        "queue_count": queue_count,
        "today_completed": done_row["cnt"] if done_row else 0,
        "today_good_qty": int(done_row["total_good"]) if done_row else 0,
        "overdue_count": len(overdue),
        "overdue_orders": overdue,
        "handover_notes": f"在制{len(wip)}单，排队{queue_count}单，今日完工{done_row['cnt'] if done_row else 0}单，超期{len(overdue)}单",
    }


async def line_balance(
    db: AsyncSession,
    factory_id: str,
) -> Dict[str, Any]:
    """产线平衡分析：各工位负荷率。

    调度员替代逻辑：不需要人看哪个工位忙/闲，系统自动算平衡率。
    """
    from sqlalchemy import text as sql_text

    result = await db.execute(sql_text("""
        SELECT work_center,
               COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as active_count,
               COUNT(CASE WHEN status = 'released' THEN 1 END) as queue_count,
               COUNT(*) as total_count
        FROM work_orders
        WHERE factory_id = :fid AND wo_type = 'operation'
          AND status IN ('in_progress', 'released')
        GROUP BY work_center
        ORDER BY total_count DESC
    """), {"fid": factory_id})
    stations = [dict(r) for r in result.mappings().all()]

    if not stations:
        return {"stations": [], "balance_rate": 0, "bottleneck": None}

    loads = [s["total_count"] for s in stations]
    max_load = max(loads) if loads else 1
    avg_load = sum(loads) / len(loads) if loads else 0

    # 平衡率 = 平均负荷 / 最大负荷 × 100%
    balance_rate = round((avg_load / max_load * 100) if max_load > 0 else 0, 1)
    bottleneck = max(stations, key=lambda s: s["total_count"]) if stations else None

    return {
        "stations": stations,
        "balance_rate": balance_rate,
        "avg_load": round(avg_load, 1),
        "max_load": max_load,
        "bottleneck": bottleneck["work_center"] if bottleneck else None,
        "suggestion": "产线平衡" if balance_rate >= 80 else f"瓶颈工位: {bottleneck['work_center']}，建议分流" if bottleneck else "",
    }
