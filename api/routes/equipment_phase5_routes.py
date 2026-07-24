"""
岗位替代 Phase 5 路由 - 维保终端 / OEE / 故障预测
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.maintenance_service import MaintenanceService
from api.services.oee_service import OeeService

router = APIRouter(prefix="/api/v1/equip-maint", tags=["equipment-phase5"])


# ==================== Request Models ====================

class MaintenanceCreate(BaseModel):
    factory_id: str
    task_type: str
    equipment_id: str
    equipment_name: Optional[str] = None
    station_id: Optional[str] = None
    planned_date: Optional[str] = None
    planned_duration_minutes: int = 60
    priority: str = "medium"
    assigned_to: Optional[str] = None
    remark: Optional[str] = None


class ChecklistAdd(BaseModel):
    task_id: str
    items: List[dict]


class ChecklistSubmit(BaseModel):
    task_id: str
    item_id: str
    measured_value: str
    is_normal: bool
    remark: Optional[str] = None


class TaskComplete(BaseModel):
    task_id: str
    result: str
    findings: Optional[str] = None
    parts_used: Optional[str] = None
    cost: float = 0


class OeeCalculate(BaseModel):
    factory_id: str
    equipment_id: str
    snapshot_date: Optional[str] = None
    planned_minutes: float = 960
    actual_output: int = 0
    good_output: int = 0
    ideal_cycle_minutes: float = 1.0


class ReadingRecord(BaseModel):
    factory_id: str
    equipment_id: str
    metric_type: str
    metric_value: float
    unit: Optional[str] = None
    warning_threshold: Optional[float] = None
    alarm_threshold: Optional[float] = None


# ==================== 维保任务 ====================

@router.post("/task")
async def create_maintenance(
    req: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建维保任务"""
    svc = MaintenanceService(db)
    return await svc.create_task(
        factory_id=req.factory_id, task_type=req.task_type,
        equipment_id=req.equipment_id, equipment_name=req.equipment_name,
        station_id=req.station_id, planned_date=req.planned_date,
        planned_duration_minutes=req.planned_duration_minutes,
        priority=req.priority, assigned_to=req.assigned_to,
        remark=req.remark, created_by=current_user.username,
    )


@router.post("/checklist")
async def add_checklist(
    req: ChecklistAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加点检项"""
    svc = MaintenanceService(db)
    return await svc.add_checklist(req.task_id, req.items)


@router.post("/{task_id}/start")
async def start_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始执行"""
    svc = MaintenanceService(db)
    return await svc.start_task(task_id, current_user.username)


@router.post("/checklist/submit")
async def submit_checklist(
    req: ChecklistSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交点检结果"""
    svc = MaintenanceService(db)
    return await svc.submit_checklist_item(req.task_id, req.item_id, req.measured_value, req.is_normal, req.remark)


@router.post("/complete")
async def complete_task(
    req: TaskComplete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成维保"""
    svc = MaintenanceService(db)
    return await svc.complete_task(req.task_id, req.result, req.findings, req.parts_used, req.cost)


@router.get("/tasks")
async def list_tasks(
    factory_id: str = Query(...),
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    equipment_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """维保任务列表"""
    svc = MaintenanceService(db)
    return await svc.list_tasks(factory_id, task_type, status, equipment_id)


@router.post("/auto-schedule")
async def auto_schedule(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动保养排程"""
    svc = MaintenanceService(db)
    return await svc.auto_schedule_pm(factory_id, current_user.username)


@router.get("/fault-prediction")
async def fault_prediction(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """故障预测"""
    svc = MaintenanceService(db)
    return await svc.predict_faults(factory_id)


@router.get("/{task_id}")
async def get_task_detail(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """任务详情"""
    svc = MaintenanceService(db)
    return await svc.get_task_detail(task_id)


@router.post("/readings")
async def record_reading(
    req: ReadingRecord,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录设备读数"""
    svc = MaintenanceService(db)
    return await svc.record_reading(
        factory_id=req.factory_id, equipment_id=req.equipment_id,
        metric_type=req.metric_type, metric_value=req.metric_value,
        unit=req.unit, warning_threshold=req.warning_threshold,
        alarm_threshold=req.alarm_threshold, recorded_by=current_user.username,
    )


# ==================== OEE ====================

@router.post("/oee/calculate")
async def calculate_oee(
    req: OeeCalculate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """计算日 OEE"""
    svc = OeeService(db)
    return await svc.calculate_daily_oee(
        factory_id=req.factory_id, equipment_id=req.equipment_id,
        snapshot_date=req.snapshot_date, planned_minutes=req.planned_minutes,
        actual_output=req.actual_output, good_output=req.good_output,
        ideal_cycle_minutes=req.ideal_cycle_minutes,
    )


@router.get("/oee/trend")
async def oee_trend(
    factory_id: str = Query(...),
    equipment_id: Optional[str] = None,
    days: int = Query(default=7),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """OEE 趋势"""
    svc = OeeService(db)
    return await svc.get_oee_trend(factory_id, equipment_id, days)


@router.get("/oee/summary")
async def oee_summary(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工厂 OEE 概览"""
    svc = OeeService(db)
    return await svc.get_factory_oee_summary(factory_id)
