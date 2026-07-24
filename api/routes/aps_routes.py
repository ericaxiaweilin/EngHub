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
