"""
APS 排程引擎 API Routes
高级计划排程：生成/确认/下达/插单/甘特图/产能负荷
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta, time as dtime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user, require_permission
from database.models import (
    User, ApsSchedule, ApsScheduleTask, ApsWorkCalendar, ApsHoliday,
    ApsCoordinationMeeting, ApsPlannerActivity, ApsPlanEvent,
)
from api.services.aps_service import ApsService

router = APIRouter(prefix="/api/v1/aps", tags=["aps"])


# ============== Request Schemas ==============


class GenerateRequest(BaseModel):
    factory_id: str
    mode: str = "hybrid"  # forward/backward/hybrid
    horizon_days: int = 7
    optimize_for: str = "delivery"  # delivery/efficiency/cost
    reason: Optional[str] = None


class RescheduleRequest(BaseModel):
    factory_id: str
    insert_wo_id: Optional[str] = None
    reason: Optional[str] = None
    approval_id: Optional[str] = None  # 插单审批单ID（Q4：要求已批准）


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


class HolidayCalendarItem(BaseModel):
    holiday_date: str
    holiday_name: str
    holiday_type: str = "legal"  # legal/compensatory/company
    is_working_day: bool = False  # 周末补班/调休上班日


class HolidayCalendarUpsert(BaseModel):
    """通过接口批量维护一个或多个工厂的日期级日历。"""

    factory_ids: List[str]
    year: int
    calendar_code: str
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    items: List[HolidayCalendarItem]


class CoordinationMeetingCreate(BaseModel):
    factory_id: str
    meeting_date: str
    meeting_type: str = "production_coordination"
    plan_version: Optional[str] = None
    attendees: List[str] = []
    decisions: List[Dict[str, Any]] = []
    action_items: List[Dict[str, Any]] = []


class PlannerActivityCreate(BaseModel):
    factory_id: str
    activity_type: str
    source: str = "aps_ui"  # aps_ui / excel / meeting / email
    plan_version: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    duration_minutes: Optional[float] = None
    metadata: Dict[str, Any] = {}


# ============== 排程方案 ==============


@router.post("/generate")
async def generate_schedule(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "create")),
):
    """生成排程方案"""
    svc = ApsService(db)
    result = await svc.generate_schedule(
        factory_id=req.factory_id,
        mode=req.mode,
        horizon_days=req.horizon_days,
        optimize_for=req.optimize_for,
        created_by=current_user.username,
        change_reason=req.reason or "manual_generation",
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
    current_user: User = Depends(require_permission("pp", "view")),
):
    """排程方案列表"""
    query = select(ApsSchedule).where(ApsSchedule.factory_id == factory_id)
    if status:
        query = query.where(ApsSchedule.status == status)
    query = query.order_by(ApsSchedule.is_current.desc(), ApsSchedule.created_at.desc())

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
                "version_number": s.version_number,
                "is_current": s.is_current,
                "supersedes_schedule_id": s.supersedes_schedule_id,
                "change_reason": s.change_reason,
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
    current_user: User = Depends(require_permission("pp", "view")),
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
        "version_number": schedule.version_number,
        "is_current": schedule.is_current,
        "supersedes_schedule_id": schedule.supersedes_schedule_id,
        "change_reason": schedule.change_reason,
        "approved_by": schedule.approved_by,
        "released_by": schedule.released_by,
        "released_at": schedule.released_at.isoformat() if schedule.released_at else None,
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
                "material_ready": t.material_ready,
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
    current_user: User = Depends(require_permission("pp", "approve")),
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
    current_user: User = Depends(require_permission("pp", "release")),
):
    """下达排程 → 工单状态 released"""
    svc = ApsService(db)
    result = await svc.release_schedule(schedule_id, released_by=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "下达失败"))
    return result


@router.post("/reschedule")
async def reschedule(
    req: RescheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "edit")),
):
    """插单/急单重排"""
    from core.pp.rush_approval_service import RushApprovalService

    if not req.approval_id:
        raise HTTPException(
            status_code=403,
            detail="Q4 插单审批流：重排必须携带已批准的插单审批单 approval_id，请先走 rush-order-impact 评估并审批",
        )

    appr_svc = RushApprovalService(db)
    approval = await appr_svc.get(req.approval_id)
    if not approval or approval.status != "executed":
        raise HTTPException(
            status_code=403,
            detail=f"插单审批单 {req.approval_id} 状态为 {getattr(approval, 'status', '不存在')}，仅 executed 可触发重排",
        )

    svc = ApsService(db)
    result = await svc.reschedule(
        factory_id=req.factory_id,
        insert_wo_id=req.insert_wo_id or approval.target_wo_id,
        created_by=current_user.username,
        change_reason=req.reason or f"插单审批 {approval.approval_code} 执行",
    )
    if not result.get("success") and not result.get("schedule_id"):
        raise HTTPException(status_code=400, detail=result.get("message", "重排失败"))
    return result


# ============== 甘特图 + KPI ==============


@router.get("/gantt/{schedule_id}")
async def get_gantt_data(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
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
    current_user: User = Depends(require_permission("pp", "view")),
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
    current_user: User = Depends(require_permission("pp", "view")),
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
    current_user: User = Depends(require_permission("pp", "manage")),
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


@router.get("/holiday-calendars")
async def list_holiday_calendars(
    factory_id: str,
    year: int = Query(..., ge=2020, le=2100),
    calendar_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """读取工厂某年度的日期级法定假期/补班配置。PMC 只依赖此接口对应的数据。"""
    query = select(ApsHoliday).where(
        ApsHoliday.factory_id == factory_id,
        ApsHoliday.year == year,
        ApsHoliday.is_active.is_(True),
    )
    if calendar_code:
        query = query.where(ApsHoliday.calendar_code == calendar_code)
    result = await db.execute(query.order_by(ApsHoliday.holiday_date))
    items = result.scalars().all()
    return {
        "factory_id": factory_id,
        "year": year,
        "calendar_code": items[0].calendar_code if items else calendar_code,
        "configured": bool(items),
        "items": [
            {
                "id": item.id,
                "holiday_date": item.holiday_date.isoformat(),
                "holiday_name": item.holiday_name,
                "holiday_type": item.holiday_type,
                "is_working_day": item.is_working_day,
                "calendar_code": item.calendar_code,
                "source_name": item.source_name,
                "source_url": item.source_url,
            }
            for item in items
        ],
    }


@router.post("/holiday-calendars/bulk")
async def upsert_holiday_calendars(
    req: HolidayCalendarUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "manage")),
):
    """通过接口把年度日历应用到一个或多个工厂；不会把日期写进 PMC 代码。"""
    from datetime import date as ddate
    import uuid

    if not req.factory_ids:
        raise HTTPException(status_code=400, detail="factory_ids 不能为空")
    parsed_items = []
    for item in req.items:
        try:
            parsed_date = ddate.fromisoformat(item.holiday_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"日期格式错误：{item.holiday_date}") from exc
        if parsed_date.year != req.year:
            raise HTTPException(status_code=400, detail=f"日期 {item.holiday_date} 不属于 {req.year} 年")
        if item.holiday_type not in {"legal", "compensatory", "company"}:
            raise HTTPException(status_code=400, detail=f"holiday_type 不支持：{item.holiday_type}")
        parsed_items.append((parsed_date, item))

    saved = 0
    for factory_id in sorted(set(req.factory_ids)):
        for parsed_date, item in parsed_items:
            existing_result = await db.execute(
                select(ApsHoliday).where(
                    ApsHoliday.factory_id == factory_id,
                    ApsHoliday.holiday_date == parsed_date,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.calendar_code = req.calendar_code
                existing.year = req.year
                existing.holiday_name = item.holiday_name
                existing.holiday_type = item.holiday_type
                existing.is_working_day = item.is_working_day
                existing.source_name = req.source_name
                existing.source_url = req.source_url
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
            else:
                db.add(ApsHoliday(
                    id=str(uuid.uuid4()),
                    factory_id=factory_id,
                    calendar_code=req.calendar_code,
                    year=req.year,
                    holiday_date=parsed_date,
                    holiday_name=item.holiday_name,
                    holiday_type=item.holiday_type,
                    is_working_day=item.is_working_day,
                    source_name=req.source_name,
                    source_url=req.source_url,
                    created_by=current_user.username or current_user.id,
                ))
            saved += 1
    await db.commit()
    return {
        "success": True,
        "calendar_code": req.calendar_code,
        "year": req.year,
        "factory_ids": sorted(set(req.factory_ids)),
        "items_per_factory": len(parsed_items),
        "saved": saved,
        "message": "日期级工作日历已通过接口保存；PMC 将在下一次矩阵计算时读取。",
    }


# ============== 产能负荷 ==============


@router.get("/capacity-load")
async def get_capacity_load(
    factory_id: str,
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """产能负荷分析（真实排程数据）"""
    svc = ApsService(db)
    return await svc.get_capacity_load(factory_id, days=days)


# ============== 计划协同与计划员活动审计 ==============


@router.post("/coordination-meetings")
async def create_coordination_meeting(
    req: CoordinationMeetingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "manage")),
):
    from datetime import date as ddate

    try:
        meeting_date = ddate.fromisoformat(req.meeting_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="meeting_date 应为 YYYY-MM-DD") from exc
    meeting = ApsCoordinationMeeting(
        factory_id=req.factory_id,
        meeting_date=meeting_date,
        meeting_type=req.meeting_type,
        plan_version=req.plan_version,
        attendees=req.attendees,
        decisions=req.decisions,
        action_items=req.action_items,
        created_by=current_user.username,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return {"success": True, "id": meeting.id, "meeting_date": meeting.meeting_date.isoformat()}


@router.get("/coordination-meetings")
async def list_coordination_meetings(
    factory_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    from datetime import date as ddate

    query = select(ApsCoordinationMeeting).where(ApsCoordinationMeeting.factory_id == factory_id)
    if from_date:
        query = query.where(ApsCoordinationMeeting.meeting_date >= ddate.fromisoformat(from_date))
    if to_date:
        query = query.where(ApsCoordinationMeeting.meeting_date <= ddate.fromisoformat(to_date))
    rows = (await db.execute(query.order_by(ApsCoordinationMeeting.meeting_date.desc()))).scalars().all()
    return {
        "factory_id": factory_id,
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "meeting_date": row.meeting_date.isoformat(),
                "meeting_type": row.meeting_type,
                "plan_version": row.plan_version,
                "attendees": row.attendees or [],
                "decisions": row.decisions or [],
                "action_items": row.action_items or [],
                "created_by": row.created_by,
            }
            for row in rows
        ],
    }


@router.get("/coordination-meetings/summary")
async def coordination_meeting_summary(
    factory_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    result = await list_coordination_meetings(
        factory_id=factory_id,
        from_date=from_date,
        to_date=to_date,
        db=db,
        current_user=current_user,
    )
    by_type: Dict[str, int] = {}
    for item in result["items"]:
        by_type[item["meeting_type"]] = by_type.get(item["meeting_type"], 0) + 1
    return {"factory_id": factory_id, "meeting_count": result["count"], "by_type": by_type}


@router.post("/planner-activities")
async def create_planner_activity(
    req: PlannerActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "edit")),
):
    started_at = datetime.fromisoformat(req.started_at)
    ended_at = datetime.fromisoformat(req.ended_at) if req.ended_at else None
    duration = req.duration_minutes
    if duration is None and ended_at:
        duration = max(0.0, (ended_at - started_at).total_seconds() / 60)
    activity = ApsPlannerActivity(
        factory_id=req.factory_id,
        user_id=current_user.username,
        activity_type=req.activity_type,
        source=req.source,
        plan_version=req.plan_version,
        started_at=started_at,
        ended_at=ended_at,
        duration_minutes=duration,
        activity_metadata=req.metadata,
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    return {"success": True, "id": activity.id, "duration_minutes": float(duration or 0)}


@router.get("/planner-activities/summary")
async def planner_activity_summary(
    factory_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    query = select(ApsPlannerActivity).where(ApsPlannerActivity.factory_id == factory_id)
    if from_date:
        query = query.where(ApsPlannerActivity.started_at >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.where(ApsPlannerActivity.started_at < datetime.fromisoformat(to_date) + timedelta(days=1))
    rows = (await db.execute(query)).scalars().all()
    by_source: Dict[str, float] = {}
    by_type: Dict[str, float] = {}
    for row in rows:
        minutes = float(row.duration_minutes or 0)
        by_source[row.source] = by_source.get(row.source, 0) + minutes
        by_type[row.activity_type] = by_type.get(row.activity_type, 0) + minutes
    return {
        "factory_id": factory_id,
        "total_minutes": round(sum(by_source.values()), 2),
        "by_source": {key: round(value, 2) for key, value in by_source.items()},
        "by_activity_type": {key: round(value, 2) for key, value in by_type.items()},
        "sample_count": len(rows),
    }


@router.get("/plan-events")
async def list_plan_events(
    factory_id: str,
    schedule_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    query = select(ApsPlanEvent).where(ApsPlanEvent.factory_id == factory_id)
    if schedule_id:
        query = query.where(ApsPlanEvent.schedule_id == schedule_id)
    if event_type:
        query = query.where(ApsPlanEvent.event_type == event_type)
    rows = (await db.execute(query.order_by(ApsPlanEvent.created_at.desc()).limit(limit))).scalars().all()
    return {
        "factory_id": factory_id,
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "actor": row.actor,
                "schedule_id": row.schedule_id,
                "plan_id": row.plan_id,
                "work_order_id": row.work_order_id,
                "reason": row.reason,
                "payload": row.payload or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ============== 交期回复 + 插单影响评估 ==============


class DeliveryPromiseRequest(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    work_order_id: Optional[str] = None
    due_date: Optional[str] = None


@router.post("/delivery-promise")
async def delivery_promise(
    req: DeliveryPromiseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """交期回复：基于当前产能负荷，估算新订单最早可交付日期。

    生产计划员核心能力：客户问“这批货什么时候能交？”→ 系统自动计算。
    算法：当前待排工单负荷 + 新单加工时间 → 最早完工日期。
    """
    from sqlalchemy import func as sa_func, and_, or_
    from database.models import WorkOrder, Product, Routing, RoutingTemplateStep
    from datetime import timedelta

    now = datetime.utcnow()
    product_result = await db.execute(select(Product).where(
        or_(Product.id == req.product_id, Product.product_code == req.product_id),
        Product.factory_id == req.factory_id,
    ))
    product = product_result.scalar_one_or_none()

    route_id = None
    if req.work_order_id:
        wo = await db.get(WorkOrder, req.work_order_id)
        if wo and wo.factory_id == req.factory_id:
            route_id = wo.routing_template_id or wo.routing_id
    if not route_id and product:
        route_id = product.current_routing_id

    standard_hours = 0.0
    route_source = None
    if route_id:
        step_result = await db.execute(
            select(RoutingTemplateStep).where(RoutingTemplateStep.template_id == str(route_id))
        )
        template_steps = list(step_result.scalars().all())
        if template_steps:
            standard_hours = sum(float(step.standard_hours or 0) for step in template_steps)
            route_source = "routing_template_steps"
        else:
            routing = await db.get(Routing, str(route_id))
            if routing and isinstance(routing.steps, list):
                standard_hours = sum(
                    ApsService._routing_step_seconds(step) / 3600
                    for step in routing.steps
                )
                route_source = "routing.steps"

    capacity_result = await db.execute(text("""
        SELECT station_id, available_hours_per_day, efficiency_rate
        FROM station_capacity
        WHERE factory_id = :factory_id AND is_active = TRUE
    """), {"factory_id": req.factory_id})
    capacities = list(capacity_result.mappings().all())
    effective_hours_per_day = sum(
        float(row["available_hours_per_day"] or 0) * float(row["efficiency_rate"] or 0)
        for row in capacities
    )

    current_end = (await db.execute(
        select(sa_func.max(ApsScheduleTask.planned_end))
        .join(ApsSchedule, ApsSchedule.id == ApsScheduleTask.schedule_id)
        .where(
            ApsSchedule.factory_id == req.factory_id,
            ApsSchedule.is_current.is_(True),
            ApsScheduleTask.status.in_(["planned", "confirmed", "released"]),
        )
    )).scalar_one_or_none()
    baseline_end = max(now, current_end) if current_end else now

    missing_inputs = []
    if not route_source or standard_hours <= 0:
        missing_inputs.append("产品工艺路线标准工时")
    if not capacities or effective_hours_per_day <= 0:
        missing_inputs.append("工厂/工位产能参数")

    if missing_inputs:
        return {
            "product_id": req.product_id,
            "quantity": req.quantity,
            "promise": {
                "earliest_delivery": None,
                "total_lead_days": None,
                "feasible": None,
                "confidence": "insufficient",
            },
            "assumptions": {"missing_inputs": missing_inputs, "route_source": route_source},
            "message": "缺少真实工艺路线或产能参数，不能生成可信交期；请先补齐基础数据。",
            "calculated_at": now.isoformat(),
        }

    current_load_hours = 0.0
    load_result = await db.execute(
        select(ApsScheduleTask.planned_start, ApsScheduleTask.planned_end)
        .join(ApsSchedule, ApsSchedule.id == ApsScheduleTask.schedule_id)
        .where(
            ApsSchedule.factory_id == req.factory_id,
            ApsSchedule.is_current.is_(True),
            ApsScheduleTask.status.in_(["planned", "confirmed", "released"]),
        )
    )
    for start, end in load_result.all():
        if start and end:
            current_load_hours += (end - start).total_seconds() / 3600

    new_order_hours = req.quantity * standard_hours
    new_order_days = new_order_hours / effective_hours_per_day
    earliest_end = baseline_end + timedelta(days=max(new_order_days, 0.0))
    requested_due = datetime.fromisoformat(req.due_date) if req.due_date else None
    feasible = earliest_end <= requested_due if requested_due else None
    confidence = "medium" if not requested_due else ("high" if feasible else "low")

    return {
        "product_id": req.product_id,
        "quantity": req.quantity,
        "current_load": {
            "load_hours": round(current_load_hours, 1),
            "capacity_hours_per_day": round(effective_hours_per_day, 2),
            "station_count": len(capacities),
        },
        "new_order": {
            "process_days": round(new_order_days, 1),
            "process_hours": round(new_order_hours, 1),
        },
        "promise": {
            "earliest_delivery": earliest_end.strftime("%Y-%m-%d"),
            "total_lead_days": round((earliest_end - now).total_seconds() / 86400, 1),
            "feasible": feasible,
            "confidence": confidence,
        },
        "assumptions": {
            "route_source": route_source,
            "standard_hours_per_unit": round(standard_hours, 4),
            "capacity_source": "station_capacity",
            "calendar_source": "aps_work_calendars/aps_holidays",
            "material_readiness": "not_evaluated_for_new_order",
        },
        "calculated_at": now.isoformat(),
    }


class RushOrderImpactRequest(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    due_date: Optional[str] = None  # ISO date
    priority: str = "urgent"
    persist: bool = True  # 是否落库为审批单草稿（默认落库）


@router.post("/rush-order-impact")
async def rush_order_impact(
    req: RushOrderImpactRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """插单影响评估：模拟插入紧急单，评估对现有工单的影响。

    生产计划员核心能力：“插这单会延迟哪些订单？”
    """
    from sqlalchemy import and_
    from database.models import WorkOrder
    from datetime import timedelta

    now = datetime.utcnow()
    promise = await delivery_promise(
        DeliveryPromiseRequest(
            factory_id=req.factory_id,
            product_id=req.product_id,
            quantity=req.quantity,
            due_date=req.due_date,
        ),
        db=db,
        current_user=current_user,
    )
    if promise["promise"]["earliest_delivery"] is None:
        return {
            "rush_order": {"product_id": req.product_id, "quantity": req.quantity, "priority": req.priority},
            "impact": {"affected_orders": 0, "total_existing_orders": 0, "delayed_orders": []},
            "recommendation": promise.get("message", "缺少真实产能/工艺数据，不能评估插单"),
            "decision_required_by": "生产经理/厂长",
            "approval_action": "pp.approve",
            "calculated_at": now.isoformat(),
        }

    rush_hours = float(promise["new_order"]["process_hours"])

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

    result = {
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
        "decision_required_by": "生产经理/厂长",
        "approval_action": "pp.approve",
        "mutation": "仅评估，未修改当前计划；通过审批单批准后才执行重排",
        "calculated_at": now.isoformat(),
    }

    if req.persist:
        from core.pp.rush_approval_service import RushApprovalService

        svc = RushApprovalService(db)
        draft = await svc.create_from_eval(
            factory_id=req.factory_id,
            product_id=req.product_id,
            quantity=req.quantity,
            due_date=req.due_date,
            rush_priority=req.priority,
            impact=result["impact"],
            rush=result["rush_order"],
            recommendation=result["recommendation"],
            applicant=current_user.username if current_user else "system",
        )
        result["approval"] = {
            "id": draft["id"],
            "approval_code": draft["approval_code"],
            "status": draft["status"],
            "level": draft["approval_level"],
            "required_role": draft["required_role"],
            "max_delay_days": str(draft["max_delay_days"]),
        }

    return result


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
    current_user: User = Depends(require_permission("pp", "create")),
):
    """有限产能排程（算法选择）- 前端 SchedulingCenter 调用"""
    svc = ApsService(db)
    # 算法映射到 optimize_for
    algo_map = {
        "EDD": "delivery",
        "SPT": "efficiency",
        "CR": "critical_ratio",
        "PRIORITY": "priority",
    }
    algorithm_names = {
        "EDD": "EDD 最早交期优先",
        "SPT": "SPT 最短加工优先",
        "CR": "CR 关键比率优先",
        "PRIORITY": "优先级优先",
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
    result["algorithm_name"] = algorithm_names.get(req.algorithm, req.algorithm)
    result["optimize_for"] = optimize_for
    result["conflict_count"] = result.get("constraint_violation_count", 0)
    return result


@router.get("/conflicts")
async def detect_conflicts(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
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


# ============== 插单审批流 (审计 Q4) ==============


class RushApprovalAction(BaseModel):
    comment: Optional[str] = None
    reason: Optional[str] = None  # reject 必填


@router.get("/rush-order/approvals")
async def list_rush_approvals(
    factory_id: str = Query(..., description="工厂ID"),
    status: Optional[str] = Query(None, description="draft/submitted/approved/executed/rejected/cancelled"),
    mine: bool = Query(False, description="只看我申请的"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """插单审批单列表（Q4）"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    items = await svc.list_by(
        factory_id=factory_id,
        status=status,
        applicant=current_user.username if mine else None,
    )
    return {
        "success": True,
        "total": len(items),
        "items": [i.to_dict() for i in items],
    }


@router.get("/rush-order/approvals/{approval_id}")
async def get_rush_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "view")),
):
    """插单审批单详情（含受影响订单全量 + 审批日志）"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    approval = await svc.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批单不存在")
    data = approval.to_dict()
    data["logs"] = await svc._logs_dict(approval_id)
    return {"success": True, "data": data}


@router.post("/rush-order/approvals/{approval_id}/submit")
async def submit_rush_approval(
    approval_id: str,
    body: RushApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "create")),
):
    """计划员提报插单审批单"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    result = await svc.submit(approval_id, current_user.username, body.comment)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/rush-order/approvals/{approval_id}/approve")
async def approve_rush_approval(
    approval_id: str,
    body: RushApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "approve")),
):
    """审批通过 → 触发调度重排"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    result = await svc.approve(
        approval_id,
        current_user.username,
        current_user,
        comment=body.comment,
    )
    if not result.get("success"):
        raise HTTPException(status_code=403, detail=result["message"])
    return result


@router.post("/rush-order/approvals/{approval_id}/reject")
async def reject_rush_approval(
    approval_id: str,
    body: RushApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "approve")),
):
    """驳回插单审批单"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    result = await svc.reject(approval_id, current_user.username, current_user, body.reason or "")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/rush-order/approvals/{approval_id}/cancel")
async def cancel_rush_approval(
    approval_id: str,
    body: RushApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("pp", "edit")),
):
    """申请人撤销插单审批单"""
    from core.pp.rush_approval_service import RushApprovalService

    svc = RushApprovalService(db)
    result = await svc.cancel(approval_id, current_user.username, current_user)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result
