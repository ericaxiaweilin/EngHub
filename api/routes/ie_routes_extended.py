"""
IE Module Extended API Routes - Advanced Lean Features
精益生产IE模块扩展：动作研究、方法研究、工站布局、看板系统、5S审计等高级功能
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database.db_config import get_db
from database.models import (
    ActionStudy, MethodStudy, WorkCellLayout, KanbanSystem, FiveSAudit, Product
)
from api.services.ie_service_extended import (
    ExtendedTimeStudyService, AdvancedLineBalanceService,
    ComprehensiveProcessAnalysisService, PerformanceRatingService, ReportExportService
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/ie", tags=["ie-advanced"])


# ============================================================
# 请求/响应模型 (Request/Response Models)
# ============================================================

class ActionStudyCreate(BaseModel):
    """创建动作研究请求体"""
    factory_id: str
    product_id: str
    operation_name: str
    station_id: Optional[str] = None
    operator_id: str
    method_type: str = "mtm"
    recorded_by: str
    study_date: str  # ISO format
    motions: List[Dict] = []  # [{"motion": "reach", "time_units": 2}]
    total_time_cycles: float = 0.0
    analysis_result: Dict[str, Any] = {}


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
    study_date: str
    motions: List[Dict]
    total_time_cycles: float
    created_at: str


class MethodStudyCreate(BaseModel):
    """创建方法研究请求体"""
    factory_id: str
    product_id: str
    original_operation: str
    version: str = "v1"
    is_basement_method: bool = False
    is_optimal_method: bool = False
    description: str = ""
    action_sequence: List[Dict] = []
    required_resources: List[Dict] = []
    setup_time_min: float = 0.0
    cycle_time_min: float = 0.0
    total_standard_time_min: float = 0.0
    validity_start: str
    validity_end: Optional[str] = None
    created_by: str
    approved_by: Optional[str] = None
    status: str = "draft"


class MethodStudyResponse(BaseModel):
    """方法研究响应体"""
    id: str
    factory_id: str
    product_id: str
    original_operation: str
    version: str
    is_basement_method: bool
    is_optimal_method: bool
    description: str
    action_sequence: List[Dict]
    required_resources: List[Dict]
    setup_time_min: float
    cycle_time_min: float
    total_standard_time_min: float
    validity_start: str
    validity_end: Optional[str]
    created_by: str
    approved_by: Optional[str]
    status: str
    created_at: str


class WorkCellLayoutInput(BaseModel):
    """工站布局输入"""
    factory_id: str
    work_cell_id: str
    product_family_id: str
    layout_diagram_url: Optional[str] = None
    material_flow_path: List[str] = []
    operator_movement_path: List[str] = []
    takt_time_alignment: str = "aligned"
    storage_location_type: str = "in_process"


class WorkCellLayoutResponse(BaseModel):
    """工站布局响应体"""
    id: str
    factory_id: str
    work_cell_id: str
    product_family_id: str
    layout_diagram_url: Optional[str]
    material_flow_path: List[str]
    operator_movement_path: List[str]
    takt_time_alignment: str
    storage_location_type: str
    last_updated: str


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
    current_card_count: int = 0
    safety_stock_level: int = 2
    card_status: str = "available"


class KanbanResponse(BaseModel):
    """看板响应体"""
    id: str
    factory_id: str
    kanban_id: str
    kanban_type: str
    upstream_station: Optional[str]
    downstream_station: Optional[str]
    product_id: str
    part_number: Optional[str]
    max_card_count: int
    current_card_count: int
    safety_stock_level: int
    card_status: str
    last_used_at: Optional[str]


class FiveSAuditInput(BaseModel):
    """5S审计输入"""
    factory_id: str
    work_center_id: str
    audit_date: str
    auditor_id: str
    seiri_score: int
    seiton_score: int
    seiso_score: int
    seiketsu_score: int
    shitsuke_score: int
    improvement_items: List[str] = []
    next_audit_date: Optional[str] = None


class FiveSAuditResponse(BaseModel):
    """5S审计响应体"""
    id: str
    factory_id: str
    work_center_id: str
    audit_date: str
    auditor_id: str
    seiri_score: int
    seiton_score: int
    seiso_score: int
    seiketsu_score: int
    shitsuke_score: int
    total_score: int
    score_percentage: float
    improvement_items: List[str]
    next_audit_date: Optional[str]


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
    study_date = datetime.fromisoformat(as_data.study_date.replace('Z', '+00:00'))
    
    # 简化实现 - 实际应调用服务层
    from database.models import ActionStudy
    action_study = ActionStudy(
        factory_id=as_data.factory_id,
        product_id=as_data.product_id,
        operation_name=as_data.operation_name,
        station_id=as_data.station_id,
        operator_id=as_data.operator_id,
        method_type=as_data.method_type,
        recorded_by=as_data.recorded_by,
        study_date=study_date,
        motions=as_data.motions,
        total_time_cycles=as_data.total_time_cycles,
        analysis_result=as_data.analysis_result,
        created_by=current_user.username
    )
    
    db.add(action_study)
    await db.commit()
    await db.refresh(action_study)
    
    return ActionStudyResponse.from_pydict(action_study.to_dict())


@router.get("/action-studies", response_model=List[Dict[str, Any]])
async def list_action_studies(
    factory_id: str,
    product_id: Optional[str] = None,
    operator_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询动作研究记录列表"""
    query = select(ActionStudy).where(ActionStudy.factory_id == factory_id)
    
    if product_id:
        query = query.where(ActionStudy.product_id == product_id)
    if operator_id:
        query = query.where(ActionStudy.operator_id == operator_id)
    
    result = await db.execute(query.order_by(ActionStudy.study_date.desc()).limit(limit))
    return [row.to_dict() for row in result.scalars().all()]


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
    validity_start = datetime.fromisoformat(ms_data.validity_start.replace('Z', '+00:00'))
    validity_end = None
    if ms_data.validity_end:
        validity_end = datetime.fromisoformat(ms_data.validity_end.replace('Z', '+00:00'))
    
    method_study = MethodStudy(
        factory_id=ms_data.factory_id,
        product_id=ms_data.product_id,
        original_operation=ms_data.original_operation,
        version=ms_data.version,
        is_basement_method=ms_data.is_basement_method,
        is_optimal_method=ms_data.is_optimal_method,
        description=ms_data.description,
        action_sequence=ms_data.action_sequence,
        required_resources=ms_data.required_resources,
        setup_time_min=ms_data.setup_time_min,
        cycle_time_min=ms_data.cycle_time_min,
        total_standard_time_min=ms_data.total_standard_time_min,
        validity_start=validity_start,
        validity_end=validity_end,
        created_by=ms_data.created_by,
        approved_by=ms_data.approved_by,
        status=ms_data.status
    )
    
    db.add(method_study)
    await db.commit()
    await db.refresh(method_study)
    
    return MethodStudyResponse.from_pydict(method_study.to_dict())


@router.put("/method-studies/{ms_id}/approve")
async def approve_method_study(
    ms_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """批准方法研究（设为最优方法）"""
    method_study = await db.execute(select(MethodStudy).where(MethodStudy.id == ms_id))
    method_study = method_study.scalar_one_or_none()
    if not method_study:
        raise HTTPException(status_code=404, detail="Method study not found")
    
    method_study.is_optimal_method = True
    method_study.approved_by = current_user.username
    method_study.status = "approved"
    method_study.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(method_study)
    
    return {"status": "success", "message": "Method study approved"}


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
    layout = WorkCellLayout(
        factory_id=cell_data.factory_id,
        work_cell_id=cell_data.work_cell_id,
        product_family_id=cell_data.product_family_id,
        layout_diagram_url=cell_data.layout_diagram_url,
        material_flow_path=cell_data.material_flow_path,
        operator_movement_path=cell_data.operator_movement_path,
        takt_time_alignment=cell_data.takt_time_alignment,
        storage_location_type=cell_data.storage_location_type,
        created_by=current_user.username
    )
    
    db.add(layout)
    await db.commit()
    await db.refresh(layout)
    
    return WorkCellLayoutResponse.from_pydict(layout.to_dict())


@router.get("/work-cells/{work_cell_id}", response_model=WorkCellLayoutResponse)
async def get_work_cell_layout(
    work_cell_id: str,
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取工站布局详情"""
    query = select(WorkCellLayout).where(WorkCellLayout.work_cell_id == work_cell_id)
    if factory_id:
        query = query.where(WorkCellLayout.factory_id == factory_id)
    
    result = await query
    layout = result.scalar_one_or_none()
    if not layout:
        raise HTTPException(status_code=404, detail="Work cell layout not found")
    return WorkCellLayoutResponse.from_pydict(layout.to_dict())


# ============================================================
# 看板系统端点 (Kanban System Endpoints)
# ============================================================

@router.post("/kanbans", status_code=201)
async def create_kanban(
    kanban_data: KanbanCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建看板卡片"""
    kanban = KanbanSystem(
        factory_id=kanban_data.factory_id,
        kanban_id=kanban_data.kanban_id,
        kanban_type=kanban_data.kanban_type,
        upstream_station=kanban_data.upstream_station,
        downstream_station=kanban_data.downstream_station,
        product_id=kanban_data.product_id,
        part_number=kanban_data.part_number,
        max_card_count=kanban_data.max_card_count,
        current_card_count=kanban_data.current_card_count,
        safety_stock_level=kanban_data.safety_stock_level,
        card_status=kanban_data.card_status,
        created_by=current_user.username
    )
    
    db.add(kanban)
    await db.commit()
    await db.refresh(kanban)
    
    return KanbanResponse.from_pydict(kanban.to_dict())


@router.put("/kanbans/{kanban_id}/update-card-count")
async def update_kanban_card_count(
    kanban_id: str,
    new_count: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """更新看板卡片数量（使用或归还卡片）"""
    kanban = await db.execute(select(KanbanSystem).where(KanbanSystem.kanban_id == kanban_id))
    kanban = kanban.scalar_one_or_none()
    if not kanban:
        raise HTTPException(status_code=404, detail="Kanban not found")
    
    kanban.current_card_count = new_count
    kanban.last_used_at = datetime.utcnow()
    kanban.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(kanban)
    
    return KanbanResponse.from_pydict(kanban.to_dict())


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
    audit_date = datetime.fromisoformat(audit_data.audit_date.replace('Z', '+00:00'))
    next_audit_date = None
    if audit_data.next_audit_date:
        next_audit_date = datetime.fromisoformat(audit_data.next_audit_date.replace('Z', '+00:00'))
    
    # 计算总分和百分比
    total_score = (audit_data.seiri_score + audit_data.seiton_score + 
                   audit_data.seiso_score + audit_data.seiketsu_score + 
                   audit_data.shitsuke_score)
    score_percentage = round(total_score / 25 * 100, 1)  # 满分25分
    
    five_s_audit = FiveSAudit(
        factory_id=audit_data.factory_id,
        work_center_id=audit_data.work_center_id,
        audit_date=audit_date,
        auditor_id=audit_data.auditor_id,
        seiri_score=audit_data.seiri_score,
        seiton_score=audit_data.seiton_score,
        seiso_score=audit_data.seiso_score,
        seiketsu_score=audit_data.seiketsu_score,
        shitsuke_score=audit_data.shitsuke_score,
        total_score=total_score,
        score_percentage=score_percentage,
        improvement_items=audit_data.improvement_items,
        next_audit_date=next_audit_date,
        created_by=current_user.username
    )
    
    db.add(five_s_audit)
    await db.commit()
    await db.refresh(five_s_audit)
    
    return FiveSAuditResponse.from_pydict(five_s_audit.to_dict())


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
    result = await query
    return [r.to_dict() for r in result.scalars().all()]


# ============================================================
# 辅助端点：精益绩效分析
# ============================================================

@router.get("/performance/rating", response_model=Dict[str, Any])
async def calculate_operator_performance_rating(
    operator_id: str,
    station_id: str,
    product_id: str,
    start_date: str,
    end_date: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """计算操作员绩效评级（基于标准工时）"""
    from services.ie_service_extended import PerformanceRatingService
    
    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    
    service = PerformanceRatingService(db)
    try:
        result = await service.calculate_operator_performance(
            operator_id=operator_id,
            station_id=station_id,
            product_id=product_id,
            start_date=start_dt,
            end_date=end_dt
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/value-stream-mapping", response_model=Dict[str, Any])
async def value_stream_mapping(
    factory_id: str,
    product_id: str,
    include_inventory: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """价值流映射（VSM）分析"""
    from services.ie_service_extended import ComprehensiveProcessAnalysisService
    
    service = ComprehensiveProcessAnalysisService(db)
    try:
        vsm = await service.value_stream_mapping(
            factory_id=factory_id,
            product_id=product_id,
            include_inventory=include_inventory
        )
        return vsm
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# 报告导出端点（简化版，实际实现需调用 ReportExportService）
# ============================================================

@router.get("/reports/standard-times-export", response_model=Dict[str, Any])
async def export_standard_times_report(
    factory_id: str,
    product_id: Optional[str] = None,
    format: str = Query("xlsx", enum=["xlsx", "csv", "pdf"]),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """导出标准工时报表（API触发后台生成任务）"""
    # 返回文件下载链接或在异步任务完成后返回
    return {
        "status": "processing",
        "request_id": f"export_{datetime.utcnow().timestamp()}",
        "message": "Report generation initiated. Check status later.",
    }
