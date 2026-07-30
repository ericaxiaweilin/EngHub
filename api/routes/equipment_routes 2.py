"""
设备 TPM API Routes
设备管理/OEE/停机/维护工单/预防维护
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User, Equipment, EquipmentDowntime, MaintenanceOrder, MaintenancePlan
from api.services.equipment_service import EquipmentTpmService

router = APIRouter(prefix="/api/v1/equipment", tags=["equipment"])


# ============== Schemas ==============


class DowntimeCreate(BaseModel):
    equipment_id: str
    factory_id: str
    start_time: str
    downtime_category: str = "breakdown"
    reason_code: Optional[str] = None
    description: Optional[str] = None
    end_time: Optional[str] = None


class MaintenanceCreate(BaseModel):
    factory_id: str
    equipment_id: str
    maintenance_type: str = "corrective"
    priority: str = "medium"
    description: Optional[str] = None
    planned_date: Optional[str] = None
    assigned_to: Optional[str] = None


class MaintenanceUpdate(BaseModel):
    status: Optional[str] = None
    result_summary: Optional[str] = None
    downtime_minutes: Optional[float] = None


class MaintenancePlanCreate(BaseModel):
    factory_id: str
    equipment_id: str
    plan_name: str
    frequency_days: int
    checklist: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str


# ============== 设备基础 ==============


@router.get("")
async def list_equipment(
    factory_id: str,
    status: Optional[str] = None,
    station_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设备列表"""
    query = select(Equipment).where(Equipment.factory_id == factory_id)
    if status:
        query = query.where(Equipment.status == status)
    if station_id:
        query = query.where(Equipment.station_id == station_id)
    query = query.order_by(Equipment.equipment_code)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": e.id, "equipment_code": e.equipment_code,
                "equipment_name": e.equipment_name, "factory_id": e.factory_id,
                "station_id": e.station_id, "equipment_type": e.equipment_type,
                "status": e.status,
                "last_maintenance_date": e.last_maintenance_date.isoformat() if e.last_maintenance_date else None,
                "next_maintenance_date": e.next_maintenance_date.isoformat() if e.next_maintenance_date else None,
            }
            for e in items
        ],
        "total": len(items),
    }


@router.get("/dashboard")
async def equipment_dashboard(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设备看板"""
    svc = EquipmentTpmService(db)
    return await svc.get_equipment_dashboard(factory_id)


@router.get("/oee")
async def get_oee(
    factory_id: str,
    equipment_id: Optional[str] = None,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """OEE 分析"""
    svc = EquipmentTpmService(db)
    return await svc.calculate_oee(factory_id, equipment_id, days)


@router.put("/{equipment_id}/status")
async def update_equipment_status(
    equipment_id: str,
    req: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新设备状态"""
    eq = await db.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    eq.status = req.status
    eq.updated_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "status": req.status}


# ============== 停机管理 ==============


@router.post("/downtime")
async def record_downtime(
    req: DowntimeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录停机"""
    svc = EquipmentTpmService(db)
    start = datetime.fromisoformat(req.start_time)
    end = datetime.fromisoformat(req.end_time) if req.end_time else None
    return await svc.record_downtime(
        equipment_id=req.equipment_id,
        factory_id=req.factory_id,
        start_time=start,
        downtime_category=req.downtime_category,
        reason_code=req.reason_code,
        description=req.description,
        reported_by=current_user.username,
        end_time=end,
    )


@router.get("/downtime")
async def list_downtime(
    factory_id: str,
    equipment_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停机记录列表"""
    query = select(EquipmentDowntime).where(EquipmentDowntime.factory_id == factory_id)
    if equipment_id:
        query = query.where(EquipmentDowntime.equipment_id == equipment_id)
    query = query.order_by(EquipmentDowntime.start_time.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": r.id, "equipment_id": r.equipment_id,
                "start_time": r.start_time.isoformat() if r.start_time else None,
                "end_time": r.end_time.isoformat() if r.end_time else None,
                "duration_minutes": r.duration_minutes,
                "downtime_category": r.downtime_category,
                "reason_code": r.reason_code,
                "description": r.description,
                "reported_by": r.reported_by,
            }
            for r in records
        ],
    }


@router.post("/downtime/{downtime_id}/end")
async def end_downtime(
    downtime_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """结束停机"""
    svc = EquipmentTpmService(db)
    result = await svc.end_downtime(downtime_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ============== 维护工单 ==============


@router.get("/maintenance")
async def list_maintenance_orders(
    factory_id: str,
    status: Optional[str] = None,
    equipment_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """维护工单列表"""
    query = select(MaintenanceOrder).where(MaintenanceOrder.factory_id == factory_id)
    if status:
        query = query.where(MaintenanceOrder.status == status)
    if equipment_id:
        query = query.where(MaintenanceOrder.equipment_id == equipment_id)
    query = query.order_by(MaintenanceOrder.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    orders = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": o.id, "order_code": o.order_code,
                "equipment_id": o.equipment_id,
                "maintenance_type": o.maintenance_type,
                "priority": o.priority, "status": o.status,
                "description": o.description,
                "planned_date": o.planned_date.isoformat() if o.planned_date else None,
                "started_at": o.started_at.isoformat() if o.started_at else None,
                "completed_at": o.completed_at.isoformat() if o.completed_at else None,
                "assigned_to": o.assigned_to,
                "result_summary": o.result_summary,
                "downtime_minutes": o.downtime_minutes,
                "created_by": o.created_by,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
    }


@router.post("/maintenance")
async def create_maintenance_order(
    req: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建维护工单"""
    svc = EquipmentTpmService(db)
    planned = datetime.fromisoformat(req.planned_date) if req.planned_date else None
    return await svc.create_maintenance_order(
        factory_id=req.factory_id,
        equipment_id=req.equipment_id,
        maintenance_type=req.maintenance_type,
        priority=req.priority,
        description=req.description,
        planned_date=planned,
        assigned_to=req.assigned_to,
        created_by=current_user.username,
    )


@router.put("/maintenance/{order_id}")
async def update_maintenance_order(
    order_id: str,
    req: MaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新维护工单"""
    svc = EquipmentTpmService(db)
    result = await svc.update_maintenance_order(
        order_id, status=req.status,
        result_summary=req.result_summary,
        downtime_minutes=req.downtime_minutes,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ============== 预防维护计划 ==============


@router.get("/maintenance-plans")
async def list_maintenance_plans(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预防维护计划"""
    svc = EquipmentTpmService(db)
    return await svc.get_maintenance_schedule(factory_id)


@router.post("/maintenance-plans")
async def create_maintenance_plan(
    req: MaintenancePlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建维护计划"""
    svc = EquipmentTpmService(db)
    return await svc.create_maintenance_plan(
        factory_id=req.factory_id,
        equipment_id=req.equipment_id,
        plan_name=req.plan_name,
        frequency_days=req.frequency_days,
        checklist=req.checklist,
    )
