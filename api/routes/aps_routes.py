"""
APS 排程引擎 API Routes
高级计划排程：生成/确认/下达/插单/甘特图/产能负荷
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, time as dtime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User, ApsSchedule, ApsScheduleTask, ApsWorkCalendar
from api.services.aps_service import ApsService

router = APIRouter(prefix="/api/v1/aps", tags=["aps"])


# ============== Request Schemas ==============


class GenerateRequest(BaseModel):
    factory_id: str
    mode: str = "hybrid"  # forward/backward/hybrid
    horizon_days: int = 7
    optimize_for: str = "delivery"  # delivery/efficiency/cost


class RescheduleRequest(BaseModel):
    factory_id: str
    insert_wo_id: Optional[str] = None


class CalendarCreate(BaseModel):
    factory_id: str
    resource_id: str
    resource_type: str = "station"
    shift_name: str = "标准班"
    day_of_week: int  # 0=Mon ... 6=Sun
    start_time: str  # "08:00"
    end_time: str    # "20:00"
    is_active: bool = True
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


# ============== 排程方案 ==============


@router.post("/generate")
async def generate_schedule(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成排程方案"""
    svc = ApsService(db)
    result = await svc.generate_schedule(
        factory_id=req.factory_id,
        mode=req.mode,
        horizon_days=req.horizon_days,
        optimize_for=req.optimize_for,
        created_by=current_user.username,
    )
    if not result.get("success") and not result.get("schedule_id"):
        raise HTTPException(status_code=400, detail=result.get("message", "排程失败"))
    return result


@router.get("/schedules")
async def list_schedules(
    factory_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排程方案列表"""
    query = select(ApsSchedule).where(ApsSchedule.factory_id == factory_id)
    if status:
        query = query.where(ApsSchedule.status == status)
    query = query.order_by(ApsSchedule.created_at.desc())

    # 总数
    from sqlalchemy import func
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    schedules = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": s.id,
                "schedule_code": s.schedule_code,
                "factory_id": s.factory_id,
                "mode": s.mode,
                "optimize_for": s.optimize_for,
                "status": s.status,
                "horizon_start": s.horizon_start.isoformat() if s.horizon_start else None,
                "horizon_end": s.horizon_end.isoformat() if s.horizon_end else None,
                "on_time_rate": s.on_time_rate,
                "avg_utilization": s.avg_utilization,
                "total_setup_minutes": s.total_setup_minutes,
                "avg_cycle_hours": s.avg_cycle_hours,
                "total_tasks": s.total_tasks,
                "unscheduled_count": s.unscheduled_count,
                "created_by": s.created_by,
                "confirmed_by": s.confirmed_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in schedules
        ],
    }


@router.get("/schedules/{schedule_id}")
async def get_schedule_detail(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """方案详情（含任务明细）"""
    schedule = await db.get(ApsSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="排程方案不存在")

    tasks_stmt = select(ApsScheduleTask).where(
        ApsScheduleTask.schedule_id == schedule_id
    ).order_by(ApsScheduleTask.planned_start)
    tasks_result = await db.execute(tasks_stmt)
    tasks = tasks_result.scalars().all()

    return {
        "id": schedule.id,
        "schedule_code": schedule.schedule_code,
        "factory_id": schedule.factory_id,
        "mode": schedule.mode,
        "optimize_for": schedule.optimize_for,
        "status": schedule.status,
        "horizon_start": schedule.horizon_start.isoformat() if schedule.horizon_start else None,
        "horizon_end": schedule.horizon_end.isoformat() if schedule.horizon_end else None,
        "on_time_rate": schedule.on_time_rate,
        "avg_utilization": schedule.avg_utilization,
        "total_setup_minutes": schedule.total_setup_minutes,
        "avg_cycle_hours": schedule.avg_cycle_hours,
        "total_tasks": schedule.total_tasks,
        "unscheduled_count": schedule.unscheduled_count,
        "created_by": schedule.created_by,
        "confirmed_by": schedule.confirmed_by,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        "tasks": [
            {
                "id": t.id,
                "work_order_id": t.work_order_id,
                "order_code": t.order_code,
                "product_code": t.product_code,
                "operation_seq": t.operation_seq,
                "operation_name": t.operation_name,
                "station_id": t.station_id,
                "planned_start": t.planned_start.isoformat() if t.planned_start else None,
                "planned_end": t.planned_end.isoformat() if t.planned_end else None,
                "setup_seconds": t.setup_seconds,
                "run_seconds": t.run_seconds,
                "quantity": t.quantity,
                "status": t.status,
                "is_locked": t.is_locked,
                "priority": t.priority,
            }
            for t in tasks
        ],
    }


@router.post("/schedules/{schedule_id}/confirm")
async def confirm_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认排程方案 → 回写工单计划时间"""
    svc = ApsService(db)
    result = await svc.confirm_schedule(schedule_id, confirmed_by=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "确认失败"))
    return result


@router.post("/schedules/{schedule_id}/release")
async def release_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下达排程 → 工单状态 released"""
    svc = ApsService(db)
    result = await svc.release_schedule(schedule_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "下达失败"))
    return result


@router.post("/reschedule")
async def reschedule(
    req: RescheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """插单/急单重排"""
    svc = ApsService(db)
    result = await svc.reschedule(
        factory_id=req.factory_id,
        insert_wo_id=req.insert_wo_id,
        created_by=current_user.username,
    )
    if not result.get("success") and not result.get("schedule_id"):
        raise HTTPException(status_code=400, detail=result.get("message", "重排失败"))
    return result


# ============== 甘特图 + KPI ==============


@router.get("/gantt/{schedule_id}")
async def get_gantt_data(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """甘特图数据（按工位分组）"""
    svc = ApsService(db)
    result = await svc.get_gantt_data(schedule_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/kpi/{schedule_id}")
async def get_schedule_kpi(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排程 KPI 指标"""
    schedule = await db.get(ApsSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="排程方案不存在")

    return {
        "schedule_id": schedule_id,
        "schedule_code": schedule.schedule_code,
        "status": schedule.status,
        "kpi": {
            "on_time_rate": schedule.on_time_rate,
            "avg_utilization": schedule.avg_utilization,
            "total_setup_minutes": schedule.total_setup_minutes,
            "avg_cycle_hours": schedule.avg_cycle_hours,
            "total_tasks": schedule.total_tasks,
            "unscheduled_count": schedule.unscheduled_count,
        },
    }


# ============== 工作日历 ==============


@router.get("/calendars")
async def list_calendars(
    factory_id: str,
    resource_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工作日历列表"""
    query = select(ApsWorkCalendar).where(ApsWorkCalendar.factory_id == factory_id)
    if resource_id:
        query = query.where(ApsWorkCalendar.resource_id == resource_id)
    query = query.order_by(ApsWorkCalendar.resource_id, ApsWorkCalendar.day_of_week)

    result = await db.execute(query)
    calendars = result.scalars().all()

    return {
        "items": [
            {
                "id": c.id,
                "factory_id": c.factory_id,
                "resource_id": c.resource_id,
                "resource_type": c.resource_type,
                "shift_name": c.shift_name,
                "day_of_week": c.day_of_week,
                "start_time": c.start_time.strftime("%H:%M") if c.start_time else None,
                "end_time": c.end_time.strftime("%H:%M") if c.end_time else None,
                "is_active": c.is_active,
                "effective_from": str(c.effective_from) if c.effective_from else None,
                "effective_to": str(c.effective_to) if c.effective_to else None,
            }
            for c in calendars
        ]
    }


@router.post("/calendars")
async def create_calendar(
    req: CalendarCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """维护工作日历"""
    import uuid
    from datetime import date as ddate

    # 解析时间
    try:
        start_parts = req.start_time.split(":")
        end_parts = req.end_time.split(":")
        start_t = dtime(int(start_parts[0]), int(start_parts[1]))
        end_t = dtime(int(end_parts[0]), int(end_parts[1]))
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="时间格式错误，应为 HH:MM")

    cal = ApsWorkCalendar(
        id=str(uuid.uuid4()),
        factory_id=req.factory_id,
        resource_id=req.resource_id,
        resource_type=req.resource_type,
        shift_name=req.shift_name,
        day_of_week=req.day_of_week,
        start_time=start_t,
        end_time=end_t,
        is_active=req.is_active,
        effective_from=ddate.fromisoformat(req.effective_from) if req.effective_from else None,
        effective_to=ddate.fromisoformat(req.effective_to) if req.effective_to else None,
    )
    db.add(cal)
    await db.commit()

    return {"success": True, "id": cal.id, "message": "工作日历已创建"}


# ============== 产能负荷 ==============


@router.get("/capacity-load")
async def get_capacity_load(
    factory_id: str,
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """产能负荷分析（真实排程数据）"""
    svc = ApsService(db)
    return await svc.get_capacity_load(factory_id, days=days)


# ============== 交期回复 + 插单影响评估 ==============


class DeliveryPromiseRequest(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    work_order_id: Optional[str] = None


@router.post("/delivery-promise")
async def delivery_promise(
    req: DeliveryPromiseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交期回复：基于当前产能负荷，估算新订单最早可交付日期。

    生产计划员核心能力：客户问“这批货什么时候能交？”→ 系统自动计算。
    算法：当前待排工单负荷 + 新单加工时间 → 最早完工日期。
    """
    from sqlalchemy import func as sa_func, and_
    from database.models import WorkOrder, Station
    from datetime import timedelta

    now = datetime.utcnow()

    # 1. 获取当前待排工单总负荷（小时）
    pending_stmt = select(
        sa_func.coalesce(sa_func.sum(WorkOrder.planned_qty), 0)
    ).where(and_(
        WorkOrder.factory_id == req.factory_id,
        WorkOrder.status.in_(["released", "pending", "in_progress"]),
        WorkOrder.wo_type == "master",
    ))
    pending_qty = (await db.execute(pending_stmt)).scalar() or 0

    # 2. 获取工位数量和效率
    station_stmt = select(sa_func.count(Station.id)).where(Station.factory_id == req.factory_id)
    station_count = (await db.execute(station_stmt)).scalar() or 1

    # 3. 计算加工时间（简化模型：每件 0.5h，效率 0.85，每天 16h 可用）
    efficiency = 0.85
    available_hours_per_day = 16.0
    hours_per_unit = 0.5 / efficiency

    # 当前负荷占用天数
    current_load_hours = pending_qty * hours_per_unit
    current_load_days = current_load_hours / (station_count * available_hours_per_day)

    # 新单加工时间
    new_order_hours = req.quantity * hours_per_unit
    new_order_days = new_order_hours / (station_count * available_hours_per_day)

    # 最早完工 = 当前负荷消化 + 新单加工
    total_days = current_load_days + new_order_days
    earliest_end = now + timedelta(days=max(total_days, 0.5))

    # 4. 判断是否可行（30天内）
    feasible = total_days <= 30
    confidence = "high" if total_days <= 7 else ("medium" if total_days <= 14 else "low")

    return {
        "product_id": req.product_id,
        "quantity": req.quantity,
        "current_load": {
            "pending_qty": int(pending_qty),
            "load_days": round(current_load_days, 1),
            "station_count": station_count,
        },
        "new_order": {
            "process_days": round(new_order_days, 1),
            "process_hours": round(new_order_hours, 1),
        },
        "promise": {
            "earliest_delivery": earliest_end.strftime("%Y-%m-%d"),
            "total_lead_days": round(total_days, 1),
            "feasible": feasible,
            "confidence": confidence,
        },
        "calculated_at": now.isoformat(),
    }


class RushOrderImpactRequest(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    due_date: Optional[str] = None  # ISO date
    priority: str = "urgent"


@router.post("/rush-order-impact")
async def rush_order_impact(
    req: RushOrderImpactRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """插单影响评估：模拟插入紧急单，评估对现有工单的影响。

    生产计划员核心能力：“插这单会延迟哪些订单？”
    """
    from sqlalchemy import and_
    from database.models import WorkOrder
    from datetime import timedelta

    now = datetime.utcnow()
    efficiency = 0.85
    hours_per_unit = 0.5 / efficiency

    # 插单加工时间
    rush_hours = req.quantity * hours_per_unit
    rush_days = rush_hours / 16.0  # 单工位

    # 获取当前待排工单（按交期排序）
    wo_stmt = select(WorkOrder).where(and_(
        WorkOrder.factory_id == req.factory_id,
        WorkOrder.status.in_(["released", "pending"]),
        WorkOrder.wo_type == "master",
    )).order_by(WorkOrder.planned_due.asc())
    wo_result = await db.execute(wo_stmt)
    existing_orders = list(wo_result.scalars().all())

    # 模拟：插单占用产能后，现有工单延迟
    delayed_orders = []
    cumulative_delay_hours = rush_hours  # 插单占用的时间

    for wo in existing_orders:
        if not wo.planned_due:
            continue
        wo_hours = (wo.planned_qty or 0) * hours_per_unit
        # 简化：插单后的新完工时间 = 原计划 + 累计延迟
        original_due = wo.planned_due
        new_end = original_due + timedelta(hours=cumulative_delay_hours)

        if new_end > original_due:
            delay_h = (new_end - original_due).total_seconds() / 3600
            delayed_orders.append({
                "work_order_code": wo.work_order_code,
                "product_id": wo.product_id,
                "planned_qty": wo.planned_qty,
                "original_due": original_due.strftime("%Y-%m-%d") if original_due else None,
                "new_estimated_end": new_end.strftime("%Y-%m-%d"),
                "delay_hours": round(delay_h, 1),
                "delay_days": round(delay_h / 24, 1),
                "priority": wo.priority,
            })

    # 插单本身能否满足交期
    rush_end = now + timedelta(hours=rush_hours)
    rush_feasible = True
    if req.due_date:
        from datetime import date as ddate2
        due = ddate2.fromisoformat(req.due_date)
        rush_feasible = rush_end.date() <= due

    return {
        "rush_order": {
            "product_id": req.product_id,
            "quantity": req.quantity,
            "priority": req.priority,
            "process_hours": round(rush_hours, 1),
            "estimated_end": rush_end.strftime("%Y-%m-%d %H:%M"),
            "due_date": req.due_date,
            "due_feasible": rush_feasible,
        },
        "impact": {
            "affected_orders": len(delayed_orders),
            "total_existing_orders": len(existing_orders),
            "max_delay_hours": max((d["delay_hours"] for d in delayed_orders), default=0),
            "delayed_orders": delayed_orders[:10],  # 最多返回10条
        },
        "recommendation": _rush_recommendation(delayed_orders, rush_feasible),
        "calculated_at": now.isoformat(),
    }


def _rush_recommendation(delayed: list, feasible: bool) -> str:
    """生成插单建议"""
    if not delayed:
        return "✅ 可以插单，不影响现有订单交期"
    if not feasible:
        return "❌ 插单本身无法按期交付，建议与客户协商延期或拆分批次"
    max_delay = max(d["delay_hours"] for d in delayed)
    if max_delay <= 24:
        return f"⚠️ 可插单，{len(delayed)} 个订单延迟≤ 1天，影响可控"
    elif max_delay <= 72:
        return f"⚠️ 插单将导致 {len(delayed)} 个订单延迟 1-3 天，建议调整低优先级工单"
    else:
        return f"🚨 插单影响严重：{len(delayed)} 个订单延迟超过 3 天，建议拒绝或分批交付"


# ============== 前端兼容接口 (Phase 2) ==============


class ScheduleWithAlgorithmRequest(BaseModel):
    factory_id: str
    algorithm: str = "EDD"  # EDD/SPT/CR/PRIORITY
    horizon_days: int = 7


@router.post("/schedule")
async def schedule_with_algorithm(
    req: ScheduleWithAlgorithmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """有限产能排程（算法选择）- 前端 SchedulingCenter 调用"""
    svc = ApsService(db)
    # 算法映射到 optimize_for
    algo_map = {
        "EDD": "delivery",
        "SPT": "efficiency",
        "CR": "delivery",
        "PRIORITY": "delivery",
    }
    optimize_for = algo_map.get(req.algorithm, "delivery")
    result = await svc.generate_schedule(
        factory_id=req.factory_id,
        mode="hybrid",
        horizon_days=req.horizon_days,
        optimize_for=optimize_for,
        created_by=current_user.username,
    )
    if not result.get("success") and not result.get("schedule_id"):
        raise HTTPException(status_code=400, detail=result.get("message", "排程失败"))
    # 添加算法信息
    result["algorithm"] = req.algorithm
    result["conflict_count"] = result.get("unscheduled_count", 0)
    return result


@router.get("/conflicts")
async def detect_conflicts(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冲突检测 - 前端 SchedulingCenter 调用"""
    from sqlalchemy import and_
    from database.models import WorkOrder
    from datetime import timedelta

    now = datetime.utcnow()
    conflicts = []

    # 1. 交期风险检测：已下达工单中，计划完成时间已过期但未完成的
    overdue_stmt = select(WorkOrder).where(and_(
        WorkOrder.factory_id == factory_id,
        WorkOrder.status.in_(["released", "in_progress"]),
        WorkOrder.planned_due < now,
    ))
    overdue_result = await db.execute(overdue_stmt)
    overdue_orders = overdue_result.scalars().all()

    for wo in overdue_orders:
        delay_hours = (now - wo.planned_due).total_seconds() / 3600 if wo.planned_due else 0
        conflicts.append({
            "type": "delivery_risk",
            "work_order": wo.work_order_code,
            "delay_hours": round(delay_hours, 1),
            "message": f"工单 {wo.work_order_code} 已延期 {round(delay_hours/24, 1)} 天",
        })

    # 2. 无BOM工单检测
    no_bom_stmt = select(WorkOrder).where(and_(
        WorkOrder.factory_id == factory_id,
        WorkOrder.status.in_(["released", "pending"]),
        WorkOrder.product_id.isnot(None),
    ))
    no_bom_result = await db.execute(no_bom_stmt)
    # 简化：假设所有工单都有BOM（实际需要查询BOM表）

    return {
        "factory_id": factory_id,
        "conflicts": conflicts[:20],  # 最多返回20条
        "total": len(conflicts),
        "checked_at": now.isoformat(),
    }
