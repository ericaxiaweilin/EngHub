"""
Equipment and TPM API Routes
Handles REST API endpoints for equipment management and TPM modules
"""

from typing import Optional, List
import uuid
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime, date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_async_session
from database.models import Equipment
from core.auth.security import enforce_tenant, get_current_user

router = APIRouter(prefix="/api/v1/equipment", tags=["Equipment & TPM"], dependencies=[Depends(enforce_tenant)])


# ==================== OEE Endpoints ====================

class OEEStats(BaseModel):
    factory_id: str = Field(..., description="Factory ID")
    date_from: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    equipment_id: Optional[str] = Field(None, description="Specific equipment ID")


@router.get("/oee/stats", summary="Get OEE statistics")
async def get_oee_stats(
    factory_id: str = Query(..., description="Factory ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    equipment_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get OEE statistics for equipment"""
    
    # TODO: Implement OEE calculation logic
    # For now, return mock data
    return {
        "overall_oee": 78.5,
        "availability": 87.5,
        "performance": 92.3,
        "quality": 97.2,
        "downtime_loss": 12.5,
        "speed_loss": 7.7,
        "quality_loss": 2.8
    }


@router.get("/oee/equipment-list", summary="Get equipment list with OEE")
async def get_equipment_oee_list(
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get list of equipment with their OEE scores"""
    
    # TODO: Query equipment and calculate OEE
    return {
        "equipment": [
            {
                "id": "eq-001",
                "name": "CNC Machine A",
                "oee": 82.5,
                "availability": 90.0,
                "performance": 91.5,
                "quality": 99.5
            },
            {
                "id": "eq-002",
                "name": "Injection Molder B",
                "oee": 75.2,
                "availability": 85.0,
                "performance": 88.5,
                "quality": 96.0
            }
        ]
    }


# ==================== Downtime Endpoints ====================

class DowntimeRecord(BaseModel):
    equipment_id: str
    category: str  # BREAKDOWN, SETUP, MAINTENANCE, MATERIAL, QUALITY, OTHER
    reason: str
    reported_by: str
    downtime_start: Optional[str] = None
    downtime_end: Optional[str] = None


@router.post("/downtime", summary="Report downtime")
async def report_downtime(
    payload: DowntimeRecord,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Report equipment downtime"""
    
    # TODO: Implement downtime recording logic
    return {
        "success": True,
        "message": "Downtime reported successfully",
        "record_id": "dt-001"
    }


@router.get("/downtime", summary="List downtime records")
async def list_downtime(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """List downtime records with filtering"""
    
    # TODO: Query downtime records from database
    return {
        "total": 0,
        "limit": limit,
        "offset": offset,
        "records": []
    }


@router.get("/downtime/stats", summary="Get downtime statistics")
async def get_downtime_stats(
    factory_id: str = Query(..., description="Factory ID"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get downtime statistics"""
    
    # TODO: Calculate downtime statistics
    return {
        "total_downtime_minutes": 0,
        "total_records": 0,
        "by_category": {},
        "by_equipment": []
    }


@router.post("/downtime/{record_id}/resolve", summary="Resolve downtime")
async def resolve_downtime(
    record_id: str,
    resolution_notes: str = Body(..., embed=True, description="Resolution notes"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Mark downtime record as resolved"""
    
    # TODO: Implement downtime resolution logic
    return {
        "success": True,
        "message": "Downtime resolved successfully"
    }


# ==================== Preventive Maintenance Endpoints ====================

class MaintenanceTask(BaseModel):
    equipment_id: str
    task_type: str  # inspection / lubrication / calibration / repair / preventive
    equipment_name: Optional[str] = None
    priority: Optional[str] = "medium"
    planned_date: Optional[str] = None  # YYYY-MM-DD
    planned_duration_minutes: Optional[int] = 60
    assigned_to: Optional[str] = None
    remark: Optional[str] = None


@router.post("/maintenance", summary="Create maintenance task")
async def create_maintenance_task(
    payload: MaintenanceTask,
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """创建维保任务（真实落库 maintenance_tasks）"""
    fid = factory_id or getattr(current_user, "factory_id", None) or "FAC_MECH_001"
    task_id = str(uuid.uuid4())
    prefix = {"inspection": "INS", "lubrication": "LUB", "calibration": "CAL",
              "repair": "REP", "preventive": "PM"}.get(payload.task_type.lower(), "MT")
    task_code = f"{prefix}-{fid[-6:] if fid else 'F00'}-{datetime.now().strftime('%m%d%H%M')}-{task_id[:4]}"
    planned = date.fromisoformat(payload.planned_date) if payload.planned_date else date.today()
    # 设备名回查（未传时用设备表补齐）
    eq_name = payload.equipment_name
    if not eq_name:
        r = await db.execute(text("SELECT equipment_name FROM equipment WHERE id=:e OR equipment_code=:e LIMIT 1"), {"e": payload.equipment_id})
        eq_name = r.scalar() or payload.equipment_id
    await db.execute(text(
        "INSERT INTO maintenance_tasks (id, factory_id, task_code, task_type, priority, equipment_id, "
        "equipment_name, planned_date, planned_duration_minutes, status, assigned_to, source, created_by) "
        "VALUES (:id,:fid,:code,:tt,:pri,:eid,:ename,:pd,:dur,'pending',:assign,'manual',:cb)"
    ), {
        "id": task_id, "fid": fid, "code": task_code,
        "tt": payload.task_type.lower(), "pri": (payload.priority or "medium").lower(),
        "eid": payload.equipment_id, "ename": eq_name, "pd": planned,
        "dur": payload.planned_duration_minutes, "assign": payload.assigned_to,
        "cb": getattr(current_user, "username", None),
    })
    await db.commit()
    return {"success": True, "task_id": task_id, "task_code": task_code}


@router.get("/maintenance", summary="List maintenance tasks")
async def list_maintenance_tasks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """维保任务列表（真实查询 maintenance_tasks）"""
    fid = factory_id or getattr(current_user, "factory_id", None)
    cond, params = ["1=1"], {}
    if fid:
        cond.append("factory_id = :fid"); params["fid"] = fid
    if status:
        cond.append("LOWER(status) = :st"); params["st"] = status.lower()
    if task_type:
        cond.append("LOWER(task_type) = :tt"); params["tt"] = task_type.lower()
    if date_from:
        cond.append("planned_date >= :df"); params["df"] = date.fromisoformat(date_from)
    if date_to:
        cond.append("planned_date <= :dt"); params["dt"] = date.fromisoformat(date_to)
    where = " AND ".join(cond)
    total = (await db.execute(text(f"SELECT COUNT(*) FROM maintenance_tasks WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(
        f"SELECT id, task_code, task_type, priority, equipment_id, equipment_name, planned_date, "
        f"status, assigned_to, result, remark, started_at, completed_at, created_at "
        f"FROM maintenance_tasks WHERE {where} ORDER BY planned_date DESC, created_at DESC "
        f"LIMIT :lim OFFSET :off"
    ), {**params, "lim": limit, "off": offset})).mappings().all()
    tasks = []
    for r in rows:
        d = dict(r)
        for k in ("planned_date",):
            if d.get(k):
                d[k] = d[k].isoformat()
        for k in ("started_at", "completed_at", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        tasks.append(d)
    return {"total": int(total or 0), "limit": limit, "offset": offset, "tasks": tasks}


@router.get("/maintenance/stats", summary="Get maintenance statistics")
async def get_maintenance_stats(
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """维保统计（总数/待办/进行中/已完成/逾期/完成率）"""
    fid = factory_id or getattr(current_user, "factory_id", None)
    cond, params = "", {}
    if fid:
        cond, params = "WHERE factory_id = :fid", {"fid": fid}
    rows = (await db.execute(text(
        f"SELECT LOWER(status) st, COUNT(*)::int cnt FROM maintenance_tasks {cond} GROUP BY 1"
    ), params)).all()
    stats = {r[0]: r[1] for r in rows}
    total = sum(stats.values())
    completed = stats.get("completed", 0)
    overdue = (await db.execute(text(
        f"SELECT COUNT(*) FROM maintenance_tasks {('WHERE ' + cond[6:]) if cond else 'WHERE 1=1'} "
        f"AND LOWER(status) NOT IN ('completed') AND planned_date < CURRENT_DATE"
    ), params)).scalar() or 0
    return {
        "total_tasks": total,
        "pending": stats.get("pending", 0),
        "in_progress": stats.get("in_progress", 0),
        "completed": completed,
        "overdue": int(overdue),
        "completion_rate": round(completed / total * 100, 1) if total else 0,
    }


@router.post("/maintenance/{task_id}/complete", summary="Complete maintenance task")
async def complete_maintenance_task(
    task_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """完成维保任务：状态→completed，记录完成时间与耗时"""
    r = await db.execute(text("SELECT status FROM maintenance_tasks WHERE id=:i"), {"i": task_id})
    row = r.first()
    if not row:
        raise HTTPException(404, detail="维保任务不存在")
    if row[0] == "completed":
        raise HTTPException(400, detail="任务已完成，勿重复操作")
    started = (await db.execute(text("SELECT started_at FROM maintenance_tasks WHERE id=:i"), {"i": task_id})).scalar()
    actual_min = int((datetime.now() - started).total_seconds() // 60) if started else None
    await db.execute(text(
        "UPDATE maintenance_tasks SET status='completed', completed_at=NOW(), "
        "actual_duration_minutes=COALESCE(:am, actual_duration_minutes), "
        "result=COALESCE(result,'normal'), updated_at=NOW() WHERE id=:i"
    ), {"am": actual_min, "i": task_id})
    await db.commit()
    return {"success": True, "message": "Maintenance task completed"}


@router.post("/maintenance/{task_id}/start", summary="Start maintenance task")
async def start_maintenance_task(
    task_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """开始维保任务：pending/assigned → in_progress"""
    r = await db.execute(text("UPDATE maintenance_tasks SET status='in_progress', started_at=COALESCE(started_at,NOW()), updated_at=NOW() WHERE id=:i AND LOWER(status) IN ('pending','assigned') RETURNING id"), {"i": task_id})
    if not r.first():
        raise HTTPException(400, detail="任务不存在或状态不允许开始")
    await db.commit()
    return {"success": True, "message": "Maintenance started"}


# ==================== Autonomous Maintenance Endpoints ====================

class AutonomousTask(BaseModel):
    equipment_id: str
    task_name: str
    performed_by: str
    checklist_items: Optional[List[dict]] = None
    notes: Optional[str] = None
    photos: Optional[List[str]] = None


@router.post("/autonomous-maintenance", summary="Create autonomous maintenance task")
async def create_autonomous_task(
    payload: AutonomousTask,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Create an autonomous maintenance task"""
    
    # TODO: Implement autonomous maintenance task creation
    return {
        "success": True,
        "message": "Autonomous maintenance task created successfully",
        "task_id": "am-001"
    }


@router.get("/autonomous-maintenance", summary="List autonomous maintenance tasks")
async def list_autonomous_tasks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """List autonomous maintenance tasks"""
    
    # TODO: Query autonomous maintenance tasks
    return {
        "total": 0,
        "limit": limit,
        "offset": offset,
        "tasks": []
    }


@router.get("/autonomous-maintenance/stats", summary="Get autonomous maintenance statistics")
async def get_autonomous_stats(
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get autonomous maintenance statistics"""
    
    # TODO: Calculate autonomous maintenance statistics
    return {
        "total_tasks": 0,
        "completed": 0,
        "issues_found": 0,
        "completion_rate": 0
    }


# ==================== 5S Audit Endpoints ====================

class FiveSAudit(BaseModel):
    audit_name: str
    area: str
    auditor: str
    audit_date: str
    items: List[dict]
    overall_notes: Optional[str] = None
    score: Optional[int] = None


@router.post("/five-s-audits", summary="Create 5S audit")
async def create_five_s_audit(
    payload: FiveSAudit,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Create a 5S audit record"""
    
    # TODO: Implement 5S audit creation
    return {
        "success": True,
        "message": "5S audit created successfully",
        "audit_id": "5s-001"
    }


@router.get("/five-s-audits", summary="List 5S audits")
async def list_five_s_audits(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """List 5S audits"""
    
    # TODO: Query 5S audits from database
    return {
        "total": 0,
        "limit": limit,
        "offset": offset,
        "audits": []
    }


@router.get("/five-s-audits/stats", summary="Get 5S audit statistics")
async def get_five_s_stats(
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get 5S audit statistics"""
    
    # TODO: Calculate 5S statistics
    return {
        "total_audits": 0,
        "average_score": 0,
        "completed": 0,
        "pending": 0
    }


# ==================== Equipment Endpoints ====================

@router.get("/", summary="List equipment")
async def list_equipment(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """设备列表（真实查询 equipment 表）"""
    cond, params = ["factory_id = :fid"], {"fid": factory_id}
    if status:
        cond.append("LOWER(status) = :st"); params["st"] = status.lower()
    where = " AND ".join(cond)
    total = (await db.execute(text(f"SELECT COUNT(*) FROM equipment WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(
        f"SELECT id, equipment_code, equipment_name, equipment_type, status, station_id, "
        f"last_maintenance_date, next_maintenance_date "
        f"FROM equipment WHERE {where} ORDER BY equipment_code LIMIT :lim OFFSET :off"
    ), {**params, "lim": limit, "off": offset})).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        for k in ("last_maintenance_date", "next_maintenance_date"):
            if d.get(k):
                d[k] = d[k].isoformat()
        items.append(d)
    return {
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "equipment": items
    }


@router.get("/{equipment_id}", summary="Get equipment details")
async def get_equipment(
    equipment_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get equipment details"""
    
    # TODO: Query equipment by ID
    return {
        "id": equipment_id,
        "name": "Equipment Name",
        "status": "OPERATIONAL"
    }
