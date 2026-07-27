"""
IE Module Extended API Routes - Advanced Lean Features
精益生产IE模块扩展API：动作研究、方法研究、Kanban看板、5S审计等高级功能
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import (
    ActionStudy, MethodStudy, WorkCellLayout, KanbanSystem, FiveSAudit, Product
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/ie-advanced", tags=["ie-advanced"])


# ============================================================
# 请求/响应模型 (Request/Response Models)
# ============================================================

class ActionStudyCreate(BaseModel):
    """创建动作研究记录请求体"""
    factory_id: str
    product_id: str
    operation_name: str
    station_id: Optional[str] = None
    operator_id: str
    method_type: str = "mtm"
    recorded_by: str
    study_date: datetime
    motions: List[Dict] = []
    total_time_cycles: float

class ActionStudyResponse(BaseModel):
    """动作研究响应体"""
    id: str
    factory_id: str
    product_id: str
    operation_name: str
    station_id: Optional[str]
    operator_id: str
    method_type: str
    recorded_by: str
    study_date: datetime
    created_at: datetime


class MethodStudyCreate(BaseModel):
    """创建方法研究方案请求体"""
    factory_id: str
    product_id: str
    original_operation: str
    version: str = "v1"
    is_basement_method: bool = False
    is_optimal_method: bool = False
    description: str = ""
    action_sequence: List[Dict] = []
    setup_time_min: float = 0.0
    cycle_time_min: float = 0.0
    total_standard_time_min: float = 0.0
    validity_start: datetime
    validity_end: Optional[datetime] = None
    created_by: str

class MethodStudyResponse(BaseModel):
    """方法研究响应体"""
    id: str
    factory_id: str
    product_id: str
    original_operation: str
    version: str
    is_basement_method: bool
    is_optimal_method: bool
    created_at: datetime


class WorkCellLayoutInput(BaseModel):
    """工站布局输入"""
    factory_id: str
    work_cell_id: str
    product_family_id: str
    material_flow_path: List[str] = []
    operator_movement_path: List[str] = []
    takt_time_alignment: str = "aligned"

class WorkCellLayoutResponse(BaseModel):
    """工站布局响应体"""
    id: str
    factory_id: str
    work_cell_id: str
    product_family_id: str
    last_updated: datetime


class KanbanCreate(BaseModel):
    """看板创建请求体"""
    factory_id: str
    kanban_id: str
    kanban_type: str = "continuous"
    upstream_station: Optional[str] = None
    downstream_station: Optional[str] = None
    product_id: str
    part_number: Optional[str] = None
    max_card_count: int = 5

class KanbanResponse(BaseModel):
    """看板响应体"""
    id: str
    factory_id: str
    kanban_id: str
    card_status: str
    current_card_count: int


class FiveSAuditInput(BaseModel):
    """5S审计输入"""
    factory_id: str
    work_center_id: str
    audit_date: datetime
    auditor_id: str
    seiri_score: int
    seiton_score: int
    seiso_score: int
    seiketsu_score: int
    shitsuke_score: int

class FiveSAuditResponse(BaseModel):
    """5S审计响应体"""
    id: str
    work_center_id: str
    audit_date: datetime
    total_score: int
    score_percentage: float


# ============================================================
# 动作研究端点 (Action Study Endpoints)
# ============================================================

@router.post("/action-studies", status_code=201)
async def create_action_study(
    as_data: ActionStudyCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建动作研究记录"""
    from database.models import ActionStudy
    action_study = ActionStudy(
        factory_id=as_data.factory_id,
        product_id=as_data.product_id,
        operation_name=as_data.operation_name,
        station_id=as_data.station_id,
        operator_id=as_data.operator_id,
        method_type=as_data.method_type,
        recorded_by=as_data.recorded_by,
        study_date=as_data.study_date,
        motions=as_data.motions,
        total_time_cycles=as_data.total_time_cycles,
        created_by=current_user.username
    )
    db.add(action_study)
    await db.commit()
    await db.refresh(action_study)
    return {"id": action_study.id, "factory_id": action_study.factory_id, "status": "created"}


@router.get("/action-studies", response_model=List[Dict[str, Any]])
async def list_action_studies(
    factory_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询动作研究记录列表"""
    query = select(ActionStudy).where(ActionStudy.factory_id == factory_id)
    query = query.order_by(ActionStudy.study_date.desc()).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [{"id": r.id, "factory_id": r.factory_id, "operation_name": r.operation_name, "station_id": r.station_id, "method_type": r.method_type, "study_date": str(r.study_date)} for r in rows]


# ============================================================
# 方法研究端点 (Method Study Endpoints)
# ============================================================

@router.post("/method-studies", status_code=201)
async def create_method_study(
    ms_data: MethodStudyCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建方法研究方案"""
    from database.models import MethodStudy
    method_study = MethodStudy(
        factory_id=ms_data.factory_id,
        product_id=ms_data.product_id,
        original_operation=ms_data.original_operation,
        version=ms_data.version,
        is_basement_method=ms_data.is_basement_method,
        is_optimal_method=ms_data.is_optimal_method,
        description=ms_data.description,
        action_sequence=ms_data.action_sequence,
        required_resources=ms_data.required_resources if hasattr(ms_data, 'required_resources') else [],
        setup_time_min=ms_data.setup_time_min,
        cycle_time_min=ms_data.cycle_time_min,
        total_standard_time_min=ms_data.total_standard_time_min,
        validity_start=ms_data.validity_start,
        validity_end=ms_data.validity_end,
        created_by=ms_data.created_by
    )
    db.add(method_study)
    await db.commit()
    await db.refresh(method_study)
    return {"id": method_study.id, "factory_id": method_study.factory_id, "status": "created"}


# ============================================================
# 工站布局端点 (Work Cell Layout Endpoints)
# ============================================================

@router.post("/work-cells", status_code=201)
async def create_work_cell_layout(
    cell_data: WorkCellLayoutInput,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建工站布局设计"""
    from database.models import WorkCellLayout
    layout = WorkCellLayout(
        factory_id=cell_data.factory_id,
        work_cell_id=cell_data.work_cell_id,
        product_family_id=cell_data.product_family_id,
        material_flow_path=cell_data.material_flow_path,
        operator_movement_path=cell_data.operator_movement_path,
        takt_time_alignment=cell_data.takt_time_alignment,
        created_by=current_user.username
    )
    db.add(layout)
    await db.commit()
    await db.refresh(layout)
    return {"id": layout.id, "factory_id": layout.factory_id, "work_cell_id": layout.work_cell_id, "status": "created"}


# ============================================================
# Kanban端点 (Kanban Endpoints)
# ============================================================

@router.post("/kanbans", status_code=201)
async def create_kanban(
    kanban_data: KanbanCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建Kanban卡片"""
    from database.models import KanbanSystem
    kanban = KanbanSystem(
        factory_id=kanban_data.factory_id,
        kanban_id=kanban_data.kanban_id,
        kanban_type=kanban_data.kanban_type,
        upstream_station=kanban_data.upstream_station,
        downstream_station=kanban_data.downstream_station,
        product_id=kanban_data.product_id,
        part_number=kanban_data.part_number,
        max_card_count=kanban_data.max_card_count,
        created_by=current_user.username
    )
    db.add(kanban)
    await db.commit()
    await db.refresh(kanban)
    return {"id": kanban.id, "factory_id": kanban.factory_id, "kanban_id": kanban.kanban_id, "status": "created"}


# ============================================================
# 5S审计端点 (5S Audit Endpoints)
# ============================================================

@router.post("/5s-audits", status_code=201)
async def create_five_s_audit(
    audit_data: FiveSAuditInput,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """执行5S审计"""
    from database.models import FiveSAudit
    
    # Calculate total score and percentage
    total_score = (audit_data.seiri_score + audit_data.seiton_score + 
                   audit_data.seiso_score + audit_data.seiketsu_score + 
                   audit_data.shitsuke_score)
    score_percentage = round(total_score / 25 * 100, 1)
    
    five_s_audit = FiveSAudit(
        factory_id=audit_data.factory_id,
        work_center_id=audit_data.work_center_id,
        audit_date=audit_data.audit_date,
        auditor_id=audit_data.auditor_id,
        seiri_score=audit_data.seiri_score,
        seiton_score=audit_data.seiton_score,
        seiso_score=audit_data.seiso_score,
        seiketsu_score=audit_data.seiketsu_score,
        shitsuke_score=audit_data.shitsuke_score,
        total_score=total_score,
        score_percentage=score_percentage,
        created_by=current_user.username
    )
    
    db.add(five_s_audit)
    await db.commit()
    await db.refresh(five_s_audit)
    return {"id": five_s_audit.id, "work_center_id": five_s_audit.work_center_id, "total_score": total_score, "score_percentage": score_percentage}


@router.get("/5s-audits/work-centers/{work_center_id}", response_model=List[Dict[str, Any]])
async def list_five_s_audits_by_workcenter(
    work_center_id: str,
    factory_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """按工站查询5S审计历史记录"""
    query = select(FiveSAudit).where(FiveSAudit.work_center_id == work_center_id)
    if factory_id:
        query = query.where(FiveSAudit.factory_id == factory_id)
    query = query.order_by(FiveSAudit.audit_date.desc()).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [{"id": r.id, "work_center_id": r.work_center_id, "audit_date": str(r.audit_date), "total_score": r.total_score, "score_percentage": r.score_percentage} for r in rows]
