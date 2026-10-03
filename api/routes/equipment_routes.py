"""设备与 TPM 的对外接口。

这个文件原先 18 个端点全是 `# TODO: return mock data`：设备台账返回空列表、
任意 equipment_id 都返回 status=OPERATIONAL、POST 声称创建成功但一行都不写、
OEE 返回写死的 78.5/87.5/92.3/97.2。真实的查询与写入逻辑本来就在
`api/services/equipment_service.py`（EquipmentTpmService）和各张实表里，只是没被接上。
现在这里只做"接线"，算不出来的（比如没有对应台账表的自主维护）明确返回 501，
不再用假成功糊界面。
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.equipment_service import EquipmentTpmService
from core.auth.security import get_current_user
from database.db_config import get_async_session
from database.models import Equipment, EquipmentDowntime, MaintenanceOrder, MaintenancePlan

router = APIRouter(prefix="/api/v1/equipment", tags=["Equipment & TPM"])


def _parse_day(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"日期格式应为 YYYY-MM-DD，收到 {value}")
    return datetime.combine(day, datetime.max.time() if end_of_day else datetime.min.time())


def _window_days(date_from: Optional[str], date_to: Optional[str], default: int = 7) -> int:
    """把日期区间换算成 OEE 统计天数（服务按天回溯）。"""
    start = _parse_day(date_from)
    if not start:
        return default
    end = _parse_day(date_to, end_of_day=True) or datetime.utcnow()
    return max(1, min(366, int((end - start).total_seconds() // 86400) + 1))


def _as_dt(value):
    """next_due_at 是 timestamp、next_run_date 是 date，比较前统一成 datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time())


async def _equipment_names(db: AsyncSession, ids: List[str]) -> Dict[str, str]:
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    rows = (await db.execute(
        select(Equipment.id, Equipment.equipment_name, Equipment.equipment_code).where(
            or_(Equipment.id.in_(ids), Equipment.equipment_code.in_(ids))
        )
    )).all()
    names: Dict[str, str] = {}
    for rid, name, code in rows:
        label = str(name or code or rid)
        names[str(rid)] = label
        names[str(code)] = label
    return names


# ==================== 设备台账 ====================

@router.get("/", summary="List equipment")
@router.get("", summary="List equipment", include_in_schema=False)
async def list_equipment(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="按设备编码或名称模糊匹配"),
    equipment_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """设备台账：直接查 equipment 表。"""
    conditions = [Equipment.factory_id == factory_id]
    if status:
        conditions.append(Equipment.status == status)
    if equipment_type:
        conditions.append(func.lower(Equipment.equipment_type) == equipment_type.lower())
    if search:
        like = f"%{search.strip()}%"
        conditions.append(or_(Equipment.equipment_code.ilike(like), Equipment.equipment_name.ilike(like)))

    total = (await db.execute(
        select(func.count()).select_from(Equipment).where(*conditions)
    )).scalar() or 0
    rows = (await db.execute(
        select(Equipment).where(*conditions)
        .order_by(Equipment.equipment_code)
        .offset(offset).limit(limit)
    )).scalars().all()

    # 状态分布按整个工厂算，不按当前页算 —— 否则"运行中"会在翻页时变数字
    status_counts = {
        str(st or "unknown"): int(n)
        for st, n in (await db.execute(
            select(Equipment.status, func.count()).select_from(Equipment)
            .where(Equipment.factory_id == factory_id).group_by(Equipment.status)
        )).all()
    }

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "equipment": [
            {
                "id": str(eq.id),
                "equipment_code": eq.equipment_code,
                "name": eq.equipment_name,
                "equipment_name": eq.equipment_name,
                "status": eq.status,
                "station_id": eq.station_id,
                "equipment_type": eq.equipment_type,
                "last_maintenance_date": eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
                "next_maintenance_date": eq.next_maintenance_date.isoformat() if eq.next_maintenance_date else None,
                "next_maintenance": eq.next_maintenance_date.isoformat() if eq.next_maintenance_date else None,
                "model": eq.manufacturer_model,
                # 单台 OEE 需要按报工归属逐台折算，列表里不顺手编一个数，页面显示 -
                "oee": None,
            }
            for eq in rows
        ],
        "status_counts": status_counts,
    }


# ==================== OEE ====================

async def _oee_payload(db: AsyncSession, factory_id: str, equipment_id: Optional[str], days: int) -> Dict[str, Any]:
    result = await EquipmentTpmService(db).calculate_oee(factory_id, equipment_id=equipment_id, days=days)
    availability = result.get("availability")
    performance = result.get("performance")
    quality = result.get("quality")
    overall = result.get("oee")
    return {
        "overall_oee": overall,
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "downtime_loss": round(100 - availability, 1) if availability is not None else None,
        "speed_loss": round(max(0.0, 100 - performance), 1) if performance is not None else None,
        "quality_loss": round(100 - quality, 1) if quality is not None else None,
        "period_days": days,
        "planned_minutes": result.get("planned_minutes"),
        "downtime_minutes": result.get("downtime_minutes"),
        "total_produced": result.get("total_produced"),
        "total_defects": result.get("total_defects"),
        "expected_pieces": result.get("expected_pieces"),
        "basis": result.get("oee_basis"),
    }


@router.get("/oee/stats", summary="Get OEE statistics")
@router.get("/oee/", summary="Get OEE statistics", include_in_schema=False)
@router.get("/oee", summary="Get OEE statistics", include_in_schema=False)
async def get_oee_stats(
    factory_id: str = Query(..., description="Factory ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    equipment_id: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=366),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """OEE：计划时间按工厂日历、性能率按工位配置的日可完成件数折算，不再返回写死的百分比。"""
    window = days or _window_days(date_from, date_to)
    return await _oee_payload(db, factory_id, equipment_id, window)


@router.get("/oee/equipment-list", summary="Get equipment list with OEE")
async def get_equipment_oee_list(
    factory_id: str = Query(..., description="Factory ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=366),
    limit: int = Query(20, ge=1, le=100, description="逐台计算的台份上限（每台都要算一遍日历与报工）"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """逐台设备的 OEE。算不出来的项返回 null，不补数。"""
    window = days or _window_days(date_from, date_to)
    machines = list((await db.execute(
        select(Equipment).where(Equipment.factory_id == factory_id)
        .order_by(Equipment.equipment_code).limit(limit)
    )).scalars().all())

    items = []
    for eq in machines:
        oee = await _oee_payload(db, factory_id, str(eq.id), window)
        items.append({
            "id": str(eq.id),
            "equipment_code": eq.equipment_code,
            "name": eq.equipment_name,
            "status": eq.status,
            "oee": oee["overall_oee"],
            "availability": oee["availability"],
            "performance": oee["performance"],
            "quality": oee["quality"],
        })
    return {"equipment": items, "period_days": window}


# ==================== 停机 ====================

class DowntimeRecord(BaseModel):
    equipment_id: str
    category: str = Field(..., description="breakdown/setup/maintenance/material/quality/other")
    reason: str
    reported_by: str
    downtime_start: Optional[str] = None
    downtime_end: Optional[str] = None


@router.post("/downtime", summary="Report downtime")
@router.post("/downtime/", summary="Report downtime", include_in_schema=False)
async def report_downtime(
    payload: DowntimeRecord,
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """报停：真的写进 equipment_downtime，并回真实主键。"""
    eq = (await db.execute(
        select(Equipment).where(or_(Equipment.id == payload.equipment_id, Equipment.equipment_code == payload.equipment_id))
    )).scalars().first()
    if not eq:
        raise HTTPException(status_code=404, detail=f"设备 {payload.equipment_id} 不存在，停机记录未写入")

    start = _parse_day(payload.downtime_start) if payload.downtime_start else datetime.utcnow()
    if payload.downtime_start and start is None:
        start = datetime.utcnow()
    end = _parse_day(payload.downtime_end, end_of_day=True) if payload.downtime_end else None

    result = await EquipmentTpmService(db).record_downtime(
        equipment_id=str(eq.id),
        factory_id=factory_id,
        start_time=start,
        downtime_category=payload.category,
        reason_code=payload.category,
        description=payload.reason,
        reported_by=payload.reported_by,
        end_time=end,
    )
    if not result.get("success", True):
        raise HTTPException(status_code=500, detail=result.get("message", "停机记录写入失败"))
    return result


@router.get("/downtime", summary="List downtime records")
@router.get("/downtime/", summary="List downtime records", include_in_schema=False)
async def list_downtime(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    conditions = [EquipmentDowntime.factory_id == factory_id]
    if category:
        conditions.append(EquipmentDowntime.downtime_category == category)
    start = _parse_day(date_from)
    end = _parse_day(date_to, end_of_day=True)
    if start:
        conditions.append(EquipmentDowntime.start_time >= start)
    if end:
        conditions.append(EquipmentDowntime.start_time <= end)

    total = (await db.execute(
        select(func.count()).select_from(EquipmentDowntime).where(*conditions)
    )).scalar() or 0
    rows = (await db.execute(
        select(EquipmentDowntime).where(*conditions)
        .order_by(EquipmentDowntime.start_time.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    names = await _equipment_names(db, [str(r.equipment_id) for r in rows])

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "records": [
            {
                "id": str(r.id),
                "equipment_id": r.equipment_id,
                "equipment_name": names.get(str(r.equipment_id), r.equipment_id),
                "downtime_start": r.start_time.isoformat() if r.start_time else None,
                "downtime_end": r.end_time.isoformat() if r.end_time else None,
                "duration_minutes": round(float(r.duration_minutes), 1) if r.duration_minutes is not None else None,
                "reason": r.description or r.reason_code,
                "category": r.downtime_category,
                "reported_by": r.reported_by,
                "open": r.end_time is None,
            }
            for r in rows
        ],
    }


@router.get("/downtime/stats", summary="Get downtime statistics")
@router.get("/downtime/stats/", summary="Get downtime statistics", include_in_schema=False)
async def get_downtime_stats(
    factory_id: str = Query(..., description="Factory ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    conditions = [EquipmentDowntime.factory_id == factory_id]
    start = _parse_day(date_from)
    end = _parse_day(date_to, end_of_day=True)
    if start:
        conditions.append(EquipmentDowntime.start_time >= start)
    if end:
        conditions.append(EquipmentDowntime.start_time <= end)

    rows = (await db.execute(
        select(
            EquipmentDowntime.downtime_category,
            EquipmentDowntime.equipment_id,
            func.coalesce(func.sum(EquipmentDowntime.duration_minutes), 0).label("minutes"),
            func.count().label("records"),
        ).where(*conditions).group_by(EquipmentDowntime.downtime_category, EquipmentDowntime.equipment_id)
    )).mappings().all()
    names = await _equipment_names(db, [str(r["equipment_id"]) for r in rows])

    by_category: Dict[str, float] = {}
    by_equipment: List[Dict[str, Any]] = []
    for r in rows:
        minutes = round(float(r["minutes"]), 1)
        key = str(r["downtime_category"] or "uncategorized")
        by_category[key] = round(by_category.get(key, 0) + minutes, 1)
        by_equipment.append({
            "equipment_id": r["equipment_id"],
            "equipment_name": names.get(str(r["equipment_id"]), str(r["equipment_id"])),
            "downtime_minutes": minutes,
            "records": int(r["records"]),
        })
    by_equipment.sort(key=lambda x: -x["downtime_minutes"])

    return {
        "total_downtime_minutes": round(sum(by_category.values()), 1),
        "total_records": int(sum(int(r["records"]) for r in rows)),
        "by_category": by_category,
        "by_equipment": by_equipment,
    }


@router.post("/downtime/{record_id}/resolve", summary="Resolve downtime")
async def resolve_downtime(
    record_id: str,
    resolution_notes: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """结案：写入 end_time 与实际停机时长（原来只回一句成功，什么都没改）。"""
    record = await db.get(EquipmentDowntime, record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"停机记录 {record_id} 不存在")
    result = await EquipmentTpmService(db).end_downtime(record_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "结案失败"))
    record.description = (f"{record.description or ''}\n[处理说明] {resolution_notes}").strip()
    await db.commit()
    return {
        "success": True,
        "record_id": record_id,
        "duration_minutes": result.get("duration_minutes"),
        "message": "停机已结案并记录实际时长",
    }


# ==================== 预防维护计划 ====================

class MaintenanceTask(BaseModel):
    equipment_id: str
    plan_name: str
    frequency_days: int = Field(..., ge=1, le=365)
    description: Optional[str] = None
    checklist: Optional[List[dict]] = None


@router.post("/maintenance", summary="Create maintenance plan")
@router.post("/maintenance/", summary="Create maintenance plan", include_in_schema=False)
async def create_maintenance_task(
    payload: MaintenanceTask,
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    eq = (await db.execute(
        select(Equipment).where(or_(Equipment.id == payload.equipment_id, Equipment.equipment_code == payload.equipment_id))
    )).scalars().first()
    if not eq:
        raise HTTPException(status_code=404, detail=f"设备 {payload.equipment_id} 不存在，计划未创建")

    result = await EquipmentTpmService(db).create_maintenance_plan(
        factory_id=factory_id,
        equipment_id=str(eq.id),
        plan_name=payload.plan_name,
        frequency_days=payload.frequency_days,
        checklist=payload.description,
    )
    return {"success": True, "message": "预防维护计划已创建", **result}


@router.get("/maintenance", summary="List maintenance plans")
@router.get("/maintenance/", summary="List maintenance plans", include_in_schema=False)
async def list_maintenance_tasks(
    factory_id: Optional[str] = Query(None, description="Factory ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """预防维护计划清单。status 由 next_run/next_due 与今天的关系推出，不编状态。"""
    conditions = []
    if factory_id:
        conditions.append(MaintenancePlan.factory_id == factory_id)
    total = (await db.execute(
        select(func.count()).select_from(MaintenancePlan).where(*conditions)
    )).scalar() or 0
    rows = (await db.execute(
        select(MaintenancePlan).where(*conditions)
        .order_by(MaintenancePlan.next_due_at.asc().nullslast())
        .offset(offset).limit(limit)
    )).scalars().all()
    names = await _equipment_names(db, [str(r.equipment_id) for r in rows])

    today = datetime.utcnow()
    tasks = []
    for plan in rows:
        due = _as_dt(plan.next_due_at) or _as_dt(plan.next_run_date)
        if not plan.is_active:
            state = "disabled"
        elif due is None:
            state = "unscheduled"
        elif due < today:
            state = "overdue"
        elif due <= today + timedelta(days=3):
            state = "due_soon"
        else:
            state = "scheduled"
        if status and state != status:
            continue
        tasks.append({
            "id": str(plan.id),
            "plan_code": plan.plan_code,
            "equipment_id": plan.equipment_id,
            "equipment_name": names.get(str(plan.equipment_id), str(plan.equipment_id)),
            "task_name": plan.plan_name,
            "task_type": plan.plan_type,
            "frequency": plan.frequency or (f"每{plan.frequency_days}天" if plan.frequency_days else None),
            "next_due": due.isoformat() if due else None,
            "last_run": _as_dt(plan.last_executed_at or plan.last_run_date).isoformat() if (plan.last_executed_at or plan.last_run_date) else None,
            "status": state,
            "duration_minutes": None,
        })

    return {"total": int(total), "limit": limit, "offset": offset, "tasks": tasks,
            "status_definitions": "overdue=到期已过, due_soon=3天内, scheduled=已排期, unscheduled=没有下次时间, disabled=已停用"}


@router.get("/maintenance/stats", summary="Get maintenance plan statistics")
@router.get("/maintenance/stats/", summary="Get maintenance plan statistics", include_in_schema=False)
async def get_maintenance_stats(
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    conditions = []
    if factory_id:
        conditions.append(MaintenancePlan.factory_id == factory_id)
    rows = (await db.execute(select(MaintenancePlan).where(*conditions))).scalars().all()
    today = datetime.utcnow()

    total = len(rows)
    overdue = sum(1 for p in rows if p.is_active and _as_dt(p.next_due_at or p.next_run_date)
                  and _as_dt(p.next_due_at or p.next_run_date) < today)
    executed = sum(1 for p in rows if p.last_executed_at or p.last_run_date)
    active = sum(1 for p in rows if p.is_active)

    return {
        "total_tasks": total,
        "active_plans": active,
        "overdue": overdue,
        "executed_at_least_once": executed,
        "never_executed": active - executed,
        "completion_rate": round(executed / total * 100, 1) if total else 0,
        "definitions": "completion_rate = 至少执行过一次的计划数 ÷ 全部计划数；这不是按期完成率，只是执行覆盖度",
    }


@router.post("/maintenance/{task_id}/complete", summary="Record a maintenance plan execution")
async def complete_maintenance_task(
    task_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """把一次执行落到计划上：更新 last_executed_at 并按周期推出下次到期。"""
    plan = await db.get(MaintenancePlan, task_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"维护计划 {task_id} 不存在")
    now = datetime.utcnow()
    plan.last_executed_at = now
    plan.last_run_date = now
    if plan.frequency_days:
        plan.next_due_at = now + timedelta(days=int(plan.frequency_days))
        plan.next_run_date = plan.next_due_at
    plan.updated_at = now
    plan.updated_by = str(current_user.get("username") if isinstance(current_user, dict) else "") or None
    await db.commit()
    return {
        "success": True,
        "task_id": task_id,
        "executed_at": now.isoformat(),
        "next_due": plan.next_due_at.isoformat() if plan.next_due_at else None,
    }


# ==================== 维护工单（维护中心页面） ====================

class MaintenanceOrderCreate(BaseModel):
    equipment_id: str
    maintenance_type: str = "corrective"
    priority: str = "medium"
    description: Optional[str] = None
    planned_date: Optional[str] = None
    assigned_to: Optional[str] = None


@router.get("/maintenance-orders", summary="List maintenance orders")
@router.get("/maintenance-orders/", summary="List maintenance orders", include_in_schema=False)
async def list_maintenance_orders(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    conditions = [MaintenanceOrder.factory_id == factory_id]
    if status:
        conditions.append(MaintenanceOrder.status == status)
    if order_type:
        conditions.append(or_(MaintenanceOrder.order_type == order_type, MaintenanceOrder.maintenance_type == order_type))
    start = _parse_day(date_from)
    end = _parse_day(date_to, end_of_day=True)
    if start:
        conditions.append(MaintenanceOrder.created_at >= start)
    if end:
        conditions.append(MaintenanceOrder.created_at <= end)

    total = (await db.execute(
        select(func.count()).select_from(MaintenanceOrder).where(*conditions)
    )).scalar() or 0
    rows = (await db.execute(
        select(MaintenanceOrder).where(*conditions)
        .order_by(MaintenanceOrder.created_at.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    names = await _equipment_names(db, [str(r.equipment_id) for r in rows])

    def _hours(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
        if not a or not b:
            return None
        return round((b - a).total_seconds() / 3600, 2)

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "orders": [
            {
                "id": str(o.id),
                "order_code": o.order_code,
                "equipment_id": o.equipment_id,
                "equipment_name": names.get(str(o.equipment_id), str(o.equipment_id)),
                "order_type": o.order_type or o.maintenance_type,
                "priority": o.priority,
                "description": o.description,
                "status": o.status,
                "assigned_to": o.assigned_to,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "scheduled_start": (o.scheduled_start or o.planned_date).isoformat() if (o.scheduled_start or o.planned_date) else None,
                "scheduled_end": o.scheduled_end.isoformat() if o.scheduled_end else None,
                "actual_start": (o.actual_start or o.started_at).isoformat() if (o.actual_start or o.started_at) else None,
                "actual_end": (o.actual_end or o.completed_at).isoformat() if (o.actual_end or o.completed_at) else None,
                "duration_hours": _hours(o.actual_start or o.started_at, o.actual_end or o.completed_at),
                "downtime_minutes": round(float(o.downtime_minutes), 1) if o.downtime_minutes is not None else None,
                "parts_used": o.parts_used or [],
                "notes": o.result_summary,
            }
            for o in rows
        ],
    }


@router.get("/maintenance-orders/stats", summary="Maintenance order statistics")
@router.get("/maintenance-orders/stats/", summary="Maintenance order statistics", include_in_schema=False)
async def maintenance_order_stats(
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    rows = (await db.execute(
        select(MaintenanceOrder.status, func.count().label("n"),
               func.coalesce(func.sum(MaintenanceOrder.downtime_minutes), 0).label("minutes"))
        .where(MaintenanceOrder.factory_id == factory_id)
        .group_by(MaintenanceOrder.status)
    )).mappings().all()
    by_status = {str(r["status"]): int(r["n"]) for r in rows}
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    overdue = (await db.execute(
        select(func.count()).select_from(MaintenanceOrder).where(
            MaintenanceOrder.factory_id == factory_id,
            MaintenanceOrder.status.in_(["open", "in_progress"]),
            MaintenanceOrder.planned_date.isnot(None),
            MaintenanceOrder.planned_date < datetime.utcnow(),
        )
    )).scalar() or 0

    return {
        "total": total,
        "by_status": by_status,
        "open": by_status.get("open", 0),
        "in_progress": by_status.get("in_progress", 0),
        "completed": completed,
        "overdue": int(overdue),
        "completion_rate": round(completed / total * 100, 1) if total else 0,
        "total_downtime_minutes": round(float(sum(r["minutes"] for r in rows)), 1),
    }


@router.post("/maintenance-orders", summary="Create maintenance order")
@router.post("/maintenance-orders/", summary="Create maintenance order", include_in_schema=False)
async def create_maintenance_order(
    payload: MaintenanceOrderCreate,
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    eq = (await db.execute(
        select(Equipment).where(or_(Equipment.id == payload.equipment_id, Equipment.equipment_code == payload.equipment_id))
    )).scalars().first()
    if not eq:
        raise HTTPException(status_code=404, detail=f"设备 {payload.equipment_id} 不存在，工单未创建")

    result = await EquipmentTpmService(db).create_maintenance_order(
        factory_id=factory_id,
        equipment_id=str(eq.id),
        maintenance_type=payload.maintenance_type,
        priority=payload.priority,
        description=payload.description,
        planned_date=_parse_day(payload.planned_date),
        assigned_to=payload.assigned_to,
        created_by=str(current_user.get("username") if isinstance(current_user, dict) else "") or None,
    )
    return result


@router.post("/maintenance-orders/{order_id}/assign", summary="Assign a maintenance order")
async def assign_maintenance_order(
    order_id: str,
    assigned_to: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    order = await db.get(MaintenanceOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"维护工单 {order_id} 不存在")
    order.assigned_to = assigned_to
    order.updated_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "order_id": order_id, "assigned_to": assigned_to, "status": order.status}


@router.post("/maintenance-orders/{order_id}/start", summary="Start a maintenance order")
async def start_maintenance_order(
    order_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    order = await db.get(MaintenanceOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"维护工单 {order_id} 不存在")
    if order.status == "completed":
        raise HTTPException(status_code=400, detail="工单已完成，不能重新开始")
    result = await EquipmentTpmService(db).update_maintenance_order(order_id, status="in_progress")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "开工失败"))
    return {"success": True, "order_id": order_id, "status": "in_progress"}


@router.post("/maintenance-orders/{order_id}/complete", summary="Complete a maintenance order")
async def complete_maintenance_order(
    order_id: str,
    result_summary: Optional[str] = Body(None, embed=True),
    downtime_minutes: Optional[float] = Body(None, embed=True),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    order = await db.get(MaintenanceOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"维护工单 {order_id} 不存在")
    result = await EquipmentTpmService(db).update_maintenance_order(
        order_id, status="completed", result_summary=result_summary, downtime_minutes=downtime_minutes
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "完工失败"))
    return {"success": True, "order_id": order_id, "status": "completed",
            "completed_at": order.completed_at.isoformat() if order.completed_at else None}


# ==================== 5S 审核 ====================

class FiveSAudit(BaseModel):
    audit_name: str
    area: str
    auditor: str
    audit_date: str
    items: List[dict] = Field(default_factory=list)
    overall_notes: Optional[str] = None
    score: Optional[int] = None
    factory_id: Optional[str] = None


@router.post("/five-s-audits", summary="Create 5S audit")
@router.post("/five-s-audits/", summary="Create 5S audit", include_in_schema=False)
async def create_five_s_audit(
    payload: FiveSAudit,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """5S 审核写入 five_s_audits；五项分数从 items 里按 SEIRI..SHITSUKE 取。"""
    factory_id = payload.factory_id or str(current_user.get("factory_id") if isinstance(current_user, dict) else "") or ""
    if not factory_id:
        raise HTTPException(status_code=422, detail="缺少 factory_id，5S 审核未写入")

    keys = {"seiri": "seiri_score", "seiton": "seiton_score", "seiso": "seiso_score",
            "seiketsu": "seiketsu_score", "shitsuke": "shitsuke_score"}
    scores: Dict[str, Any] = {}
    for item in payload.items:
        name = str((item or {}).get("name") or (item or {}).get("category") or "").lower()
        for prefix, column in keys.items():
            if name.startswith(prefix):
                value = (item or {}).get("score")
                if value is not None:
                    scores[column] = float(value)

    total_score = payload.score if payload.score is not None else (
        sum(v for v in scores.values()) if scores else None
    )
    audit_id = str(__import__("uuid").uuid4())
    await db.execute(text("""
        INSERT INTO five_s_audits (id, factory_id, work_center_id, audit_date, auditor_id,
                                  seiri_score, seiton_score, seiso_score, seiketsu_score, shitsuke_score,
                                  improvement_items, total_score, created_by, created_at)
        VALUES (:id, :fid, :area, :audit_date, :auditor,
                :seiri, :seiton, :seiso, :seiketsu, :shitsuke,
                :improvement, :total, :created_by, NOW())
    """), {
        "id": audit_id, "fid": factory_id, "area": payload.area,
        "audit_date": _parse_day(payload.audit_date), "auditor": payload.auditor,
        "seiri": scores.get("seiri_score"), "seiton": scores.get("seiton_score"),
        "seiso": scores.get("seiso_score"), "seiketsu": scores.get("seiketsu_score"),
        "shitsuke": scores.get("shitsuke_score"),
        "improvement": payload.overall_notes or "", "total": total_score,
        "created_by": str(current_user.get("username") if isinstance(current_user, dict) else "") or None,
    })
    await db.commit()
    return {"success": True, "audit_id": audit_id, "total_score": total_score}


@router.get("/five-s-audits", summary="List 5S audits")
@router.get("/five-s-audits/", summary="List 5S audits", include_in_schema=False)
async def list_five_s_audits(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    rows = (await db.execute(text("""
        SELECT id, work_center_id AS area, audit_date, auditor_id AS auditor,
               seiri_score, seiton_score, seiso_score, seiketsu_score, shitsuke_score,
               total_score, improvement_items
        FROM five_s_audits WHERE factory_id = :fid
        ORDER BY audit_date DESC LIMIT :limit OFFSET :offset
    """), {"fid": factory_id, "limit": limit, "offset": offset})).mappings().all()
    total = (await db.execute(text(
        "SELECT count(*) FROM five_s_audits WHERE factory_id = :fid"
    ), {"fid": factory_id})).scalar() or 0
    return {
        "total": int(total), "limit": limit, "offset": offset,
        "audits": [
            {**dict(r), "audit_date": r["audit_date"].isoformat() if r["audit_date"] else None}
            for r in rows
        ],
    }


@router.get("/five-s-audits/stats", summary="Get 5S audit statistics")
@router.get("/five-s-audits/stats/", summary="Get 5S audit statistics", include_in_schema=False)
async def get_five_s_stats(
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    row = (await db.execute(text("""
        SELECT count(*) AS total_audits, AVG(total_score) AS average_score,
               MAX(audit_date) AS last_audit_date
        FROM five_s_audits WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().first() or {}
    total_audits = int(row.get("total_audits") or 0)
    return {
        "total_audits": total_audits,
        "average_score": round(float(row["average_score"]), 1) if row.get("average_score") is not None else None,
        "last_audit_date": row["last_audit_date"].isoformat() if row.get("last_audit_date") else None,
        "completed": total_audits,
        "pending": 0,
        "note": "five_s_audits 表没有状态列，completed 即已存在的审核记录数，pending 恒为 0",
    }


# ==================== 自主维护（没有台账表，明确不实现） ====================

AM_UNIMPLEMENTED = HTTPException(
    status_code=501,
    detail="自主维护（AM）没有对应的台账表，接口未实现；需要先确定数据模型，不会返回假成功或空列表",
)


@router.post("/autonomous-maintenance", summary="Create autonomous maintenance task")
async def create_autonomous_task():
    raise AM_UNIMPLEMENTED


@router.get("/autonomous-maintenance", summary="List autonomous maintenance tasks")
async def list_autonomous_tasks():
    raise AM_UNIMPLEMENTED


@router.get("/autonomous-maintenance/stats", summary="Get autonomous maintenance statistics")
async def get_autonomous_stats():
    raise AM_UNIMPLEMENTED


class EquipmentCreate(BaseModel):
    factory_id: str
    equipment_name: str
    equipment_type: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = Field(None, description="工位编码，必须是本厂 stations 里已登记的工位")
    responsible_engineer_id: Optional[str] = None


@router.post("/", summary="Create equipment")
@router.post("", summary="Create equipment", include_in_schema=False)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """新建设备。location 只有能对上本厂台账工位才会写入 station_id ——
    否则宁可 422，也不让一个不存在的工位编码进入排程（那正是跨厂借用那类问题的来源）。"""
    name = (payload.equipment_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="设备名称不能为空")

    station_id = None
    if payload.location and payload.location.strip():
        location = payload.location.strip()
        station = (await db.execute(text("""
            SELECT station_code FROM stations
            WHERE factory_id = :fid AND (station_code = :loc OR station_name = :loc)
            LIMIT 1
        """), {"fid": payload.factory_id, "loc": location})).scalar()
        if not station:
            raise HTTPException(
                status_code=422,
                detail=f"工位 {location} 不在工厂 {payload.factory_id} 的台账里；先在 stations 登记，再绑定设备",
            )
        station_id = str(station)

    seq = (await db.execute(
        select(func.count()).select_from(Equipment).where(Equipment.factory_id == payload.factory_id)
    )).scalar() or 0
    code = f"EQ-{payload.factory_id[-4:]}-{int(seq) + 1:03d}"
    while (await db.execute(
        select(func.count()).select_from(Equipment).where(Equipment.equipment_code == code)
    )).scalar():
        seq += 1
        code = f"EQ-{payload.factory_id[-4:]}-{seq + 1:03d}"

    eq = Equipment(
        equipment_code=code,
        factory_id=payload.factory_id,
        station_id=station_id,
        equipment_name=name,
        equipment_type=(payload.equipment_type or "").lower() or None,
        manufacturer_model=payload.model,
        serial_number=payload.serial_number,
        # 台账里实际用到的状态只有 running/maintenance/idle/broken，
        # 新设备未开机就是 idle，不要造一个字典外的 "available"
        status="idle",
        responsible_engineer_id=payload.responsible_engineer_id,
    )
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    return {
        "success": True,
        "id": str(eq.id),
        "equipment_code": eq.equipment_code,
        "equipment_name": eq.equipment_name,
        "station_id": eq.station_id,
        "status": eq.status,
    }


@router.get("/{equipment_id}", summary="Get equipment details")
async def get_equipment(
    equipment_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
):
    """设备详情。查不到就 404 —— 原来这里对任意 ID 都返回 OPERATIONAL。"""
    eq = (await db.execute(
        select(Equipment).where(or_(Equipment.id == equipment_id, Equipment.equipment_code == equipment_id))
    )).scalars().first()
    if not eq:
        raise HTTPException(status_code=404, detail=f"设备 {equipment_id} 不存在")

    downtime_minutes = (await db.execute(
        select(func.coalesce(func.sum(EquipmentDowntime.duration_minutes), 0)).where(
            EquipmentDowntime.equipment_id == eq.id
        )
    )).scalar() or 0
    open_orders = (await db.execute(
        select(func.count()).select_from(MaintenanceOrder).where(
            MaintenanceOrder.equipment_id == eq.id,
            MaintenanceOrder.status.in_(["open", "in_progress"]),
        )
    )).scalar() or 0

    return {
        "id": str(eq.id),
        "equipment_code": eq.equipment_code,
        "name": eq.equipment_name,
        "factory_id": eq.factory_id,
        "station_id": eq.station_id,
        "equipment_type": eq.equipment_type,
        "status": eq.status,
        "manufacturer_model": eq.manufacturer_model,
        "serial_number": eq.serial_number,
        "spec": eq.spec,
        "last_maintenance_date": eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
        "next_maintenance_date": eq.next_maintenance_date.isoformat() if eq.next_maintenance_date else None,
        "total_downtime_minutes": round(float(downtime_minutes), 1),
        "open_maintenance_orders": int(open_orders),
    }

__all__ = ["router"]
