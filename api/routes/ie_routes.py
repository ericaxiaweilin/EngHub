"""
IE Module - Basic API Routes
精益生产基础IE模块API路由：标准工时、时间研究、产线平衡、工序价值分析
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession 

from database.db_config import get_db
from database.models import (
    StandardOperationTime,
    TimeStudyRecord,
    LineBalanceAnalysis,
    ProcessAnalysis,
    Product,
)
from api.services.ie_service import (
    StandardTimeService,
    TimeStudyService,
    LineBalanceService,
    ProcessAnalysisService,
IE Module API Routes - Industrial Engineering Module
精益生产IE模块 API：标准工时、时间研究、线平衡分析、工序价值分析
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, BaseModel as PydanticModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database.db_config import get_db
from database.models import (
    StandardOperationTime, TimeStudyRecord, LineBalanceAnalysis, ProcessAnalysis, Product
)
from api.services.ie_service import (
    StandardTimeService, TimeStudyService, LineBalanceService, ProcessAnalysisService
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/ie", tags=["ie"])


# ============================================================
# 响应模型 (Pydantic Response Models)
# 请求/响应模型 (Request/Response Models)
# ============================================================

class StandardTimeCreate(BaseModel):
    """创建标准工时请求体"""
    factory_id: str
    product_id: str
    routing_step: str
    operation_name: str
    station_id: Optional[str] = None
    standard_time_min: float
    work_center: Optional[str] = None
    standard_time_min: float = 0.0
    unit_time_type: str = "per_piece"  # per_piece / per_batch / setup
    setup_time_min: float = 0.0
    batch_size: int = 1
    rating_factor: float = 1.0
    allowance_rate: float = 0.15
    validity_start: datetime
    validity_end: Optional[datetime] = None
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    version: str = "v1"


class StandardTimeUpdate(BaseModel):
    """更新标准工时请求体"""
    standard_time_min: Optional[float] = None
    setup_time_min: Optional[float] = None
    batch_size: Optional[int] = None
    rating_factor: Optional[float] = None
    allowance_rate: Optional[float] = None
    validity_end: Optional[str] = None
    is_active: Optional[bool] = None


class StandardTimeResponse(BaseModel):
    """标准工时响应体"""
    id: str
    factory_id: str
    product_id: str
    routing_step: str
    operation_name: str
    station_id: Optional[str]
    standard_time_min: float
    effective_standard_time: float
    version: str
    is_active: bool
    validity_start: datetime
    created_at: datetime
    work_center: Optional[str]
    standard_time_min: float
    unit_time_type: str
    setup_time_min: float
    batch_size: int
    rating_factor: float
    allowance_rate: float
    effective_standard_time: float
    version: str
    is_active: bool
    validity_start: str
    validity_end: Optional[str]
    created_by: str
    updated_by: str


class TimeStudyCreate(BaseModel):
    """创建时间研究记录请求体"""
    factory_id: str
    product_id: str
    station_id: str
    operation_name: str
    operator_id: str
    observer_id: str
    observation_date: datetime
    observed_cycles: List[float]
    rating_factor: float = 1.0
    method: str = "direct"

class TimeStudyResponse(BaseModel):
    """时间研究响应体"""
    id: str
    factory_id: str
    station_id: str
    operation_name: str
    operator_id: str
    average_time: float
    normal_time: float
    allowed_time: float
    status: str
    created_at: datetime
    observed_cycles: List[float]
    observation_date: Optional[str] = None
    rating_factor: float = 1.0
    method: str = "stopwatch"
    created_by: Optional[str] = None


class TimeStudyResponse(BaseModel):
    """时间研究记录响应体"""
    id: str
    factory_id: str
    product_id: str
    station_id: str
    operation_name: str
    operator_id: str
    observer_id: str
    observation_date: str
    observed_cycles: List[float]
    cycle_count: int
    average_time: float
    rating_factor: float
    normal_time: float
    allowed_time: float
    allowance_rate: float
    method: str
    status: str
    created_by: str
    approved_by: Optional[str]


class LineBalanceInput(BaseModel):
    """产线平衡分析输入"""
    factory_id: str
    line_id: str
    product_id: str
    takt_time: Optional[float] = None  # 可选，如不传入则自动计算


class LineBalanceResponse(BaseModel):
    """产线平衡分析报告"""
    id: str
    factory_id: str
    product_id: str
    line_id: str
    analysis_date: str
    takt_time_min: float
    cycle_time_max: float
    cycle_time_avg: float
    balance_rate: float
    idle_time_total: float
    workstation_count: int
    is_balanced: bool
    station_details: List[Dict[str, Any]]
    bottleneck_station: Optional[str]
    bottleneck_time: Optional[float]
    recommendations: List[str]
    created_by: str


class ProcessAnalysisInput(BaseModel):
    """工序价值分析输入"""
    factory_id: str
    product_id: str
    operation_code: str
    va_time: float
    nva_time: float
    wait_time: float
    move_time: float
    inspect_time: float
    lead_time: float


class ProcessAnalysisResponse(BaseModel):
    """工序价值分析报告"""
    id: str
    factory_id: str
    product_id: str
    operation_code: str
    analysis_date: str
    total_process_time_min: float
    va_time_min: float
    nva_time_min: float
    wait_time_min: float
    move_time_min: float
    inspect_time_min: float
    va_ratio: float
    lead_time: float
    efficiency_score: float
    created_by: str


# ============================================================
# 标准工时端点 (Standard Time Endpoints)
# ============================================================

@router.post("/standard-times", status_code=201)
async def create_standard_time(
    sot_data: StandardTimeCreate,
    st: StandardTimeCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建标准工时记录"""
    service = StandardTimeService(db)
    try:
        sot = await service.create_standard_time(
            factory_id=sot_data.factory_id,
            product_id=sot_data.product_id,
            routing_step=sot_data.routing_step,
            operation_name=sot_data.operation_name,
            station_id=sot_data.station_id,
            standard_time_min=sot_data.standard_time_min,
            setup_time_min=sot_data.setup_time_min,
            batch_size=sot_data.batch_size,
            rating_factor=sot_data.rating_factor,
            allowance_rate=sot_data.allowance_rate,
            validity_start=sot_data.validity_start,
            validity_end=sot_data.validity_end,
            created_by=current_user.username
        )
        return sot.to_dict() if hasattr(sot, 'to_dict') else {"id": sot.id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not st.validity_start:
        validity_start = datetime.utcnow()
    else:
        validity_start = datetime.fromisoformat(st.validity_start.replace('Z', '+00:00'))
    
    validity_end = None
    if st.validity_end:
        validity_end = datetime.fromisoformat(st.validity_end.replace('Z', '+00:00'))
    
    service = StandardTimeService(db)
    try:
        sot = await service.create_standard_time(
            factory_id=st.factory_id,
            product_id=st.product_id,
            routing_step=st.routing_step,
            operation_name=st.operation_name,
            station_id=st.station_id,
            work_center=st.work_center,
            standard_time_min=st.standard_time_min,
            unit_time_type=st.unit_time_type,
            setup_time_min=st.setup_time_min,
            batch_size=st.batch_size,
            rating_factor=st.rating_factor,
            allowance_rate=st.allowance_rate,
            validity_start=validity_start,
            validity_end=validity_end,
            created_by=current_user.username,
            version=st.version
        )
        return StandardTimeResponse.model_validate(sot.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/standard-times", response_model=List[Dict[str, Any]])
async def list_standard_times(
    factory_id: str,
    product_id: Optional[str] = None,
    station_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="active/pending"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询标准工时列表"""
    service = StandardTimeService(db)
    sots = await service.list_standard_times(
        factory_id=factory_id,
        product_id=product_id,
        station_id=station_id,
        limit=limit
    )
    return [s.to_dict() for s in sots]

@router.get("/standard-times/{id}", response_model=StandardTimeResponse)
    
    try:
        sots = await service.get_active_sots(
            factory_id=factory_id,
            product_id=product_id,
            station_id=station_id,
            include_expired=status != "active"
        )
        return [sot.to_dict() for sot in sots]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/standard-times/{sot_id}", response_model=StandardTimeResponse)
async def get_standard_time(
    sot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取单个标准工时记录"""
    service = StandardTimeService(db)
    sot = await service.get_standard_time(sot_id)
    if not sot:
        raise HTTPException(status_code=404, detail="Standard time not found")
    return sot.to_dict() if hasattr(sot, 'to_dict') else {"id": sot.id}

@router.put("/standard-times/{id}")
async def update_standard_time(
    sot_id: str,
    sot_data: StandardTimeCreate,
    """根据ID获取标准工时详情"""
    service = StandardTimeService(db)
    sot = await service.get_sot_by_id(sot_id)
    if not sot:
        raise HTTPException(status_code=404, detail="Standard time record not found")
    return StandardTimeResponse.model_validate(sot.to_dict())


@router.put("/standard-times/{sot_id}", response_model=StandardTimeResponse)
async def update_standard_time(
    sot_id: str,
    st: StandardTimeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """更新标准工时记录"""
    service = StandardTimeService(db)
    updated = await service.update_standard_time(
        sot_id=sot_id,
        factory_id=sot_data.factory_id,
        product_id=sot_data.product_id,
        routing_step=sot_data.routing_step,
        operation_name=sot_data.operation_name,
        station_id=sot_data.station_id,
        standard_time_min=sot_data.standard_time_min,
        setup_time_min=sot_data.setup_time_min,
        batch_size=sot_data.batch_size,
        rating_factor=sot_data.rating_factor,
        allowance_rate=sot_data.allowance_rate,
        validity_start=sot_data.validity_start,
        validity_end=sot_data.validity_end,
        updated_by=current_user.username
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Standard time not found")
    return {"status": "updated", "id": sot_id}

@router.delete("/standard-times/{id}")
    sot = await service.update_standard_time(
        sot_id=sot_id,
        **st.dict(exclude_unset=True),
        updated_by=current_user.username
    )
    if not sot:
        raise HTTPException(status_code=404, detail="Standard time record not found")
    return StandardTimeResponse.model_validate(sot.to_dict())


@router.delete("/standard-times/{sot_id}")
async def delete_standard_time(
    sot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """删除标准工时记录（逻辑删除）"""
    service = StandardTimeService(db)
    result = await service.delete_standard_time(sot_id)
    if not result:
        raise HTTPException(status_code=404, detail="Standard time not found")
    return {"status": "deleted", "id": sot_id}

@router.get("/products/{product_id}/standard-times")
async def get_standard_times_by_product(
    product_id: str,
    factory_id: str,
    db: AsyncSession = Depends(get_db)
):
    """按产品查询标准工时"""
    service = StandardTimeService(db)
    sots = await service.get_sots_by_product(factory_id=factory_id, product_id=product_id)
    return [s.to_dict() for s in sots]
    """逻辑删除标准工时（置为不生效）"""
    service = StandardTimeService(db)
    sot = await service.get_sot_by_id(sot_id)
    if not sot:
        raise HTTPException(status_code=404, detail="Standard time record not found")
    
    await service.update_standard_time(
        sot_id=sot_id,
        is_active=False,
        updated_by=current_user.username
    )
    return {"status": "success", "message": "Standard time deactivated"}


# ============================================================
# 时间研究端点 (Time Study Endpoints)
# ============================================================

@router.post("/time-studies", status_code=201)
async def create_time_study(
    ts_data: TimeStudyCreate,
    ts: TimeStudyCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建时间研究记录"""
    service = TimeStudyService(db)
    try:
        ts = await service.create_time_study(
            factory_id=ts_data.factory_id,
            product_id=ts_data.product_id,
            station_id=ts_data.station_id,
            operation_name=ts_data.operation_name,
            operator_id=ts_data.operator_id,
            observer_id=ts_data.observer_id,
            observation_date=ts_data.observation_date,
            observed_cycles=ts_data.observed_cycles,
            rating_factor=ts_data.rating_factor,
            method=ts_data.method,
            created_by=current_user.username
        )
        # Create a simplified response
        return {
            "id": ts.id,
            "factory_id": ts.factory_id,
            "station_id": ts.station_id,
            "operation_name": ts.operation_name,
            "operator_id": ts.operator_id,
            "average_time": ts.average_time,
            "normal_time": ts.normal_time,
            "allowed_time": ts.allowed_time,
            "status": ts.status,
            "created_at": ts.created_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ts.observation_date:
        observation_date = datetime.utcnow()
    else:
        observation_date = datetime.fromisoformat(ts.observation_date.replace('Z', '+00:00'))
    
    service = TimeStudyService(db)
    try:
        record = await service.create_time_study_record(
            factory_id=ts.factory_id,
            product_id=ts.product_id,
            station_id=ts.station_id,
            operation_name=ts.operation_name,
            operator_id=ts.operator_id,
            observer_id=ts.observer_id,
            observed_cycles=ts.observed_cycles,
            observation_date=observation_date,
            rating_factor=ts.rating_factor,
            method=ts.method,
            created_by=current_user.username
        )
        return TimeStudyResponse.model_validate(record.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/time-studies", response_model=List[Dict[str, Any]])
async def list_time_studies(
    factory_id: str,
    product_id: Optional[str] = None,
    station_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询时间研究记录列表"""
    service = TimeStudyService(db)
    records = await service.list_time_studies(
        factory_id=factory_id,
        product_id=product_id,
        station_id=station_id,
        status=status,
        limit=limit
    )
    return [{
        "id": r.id,
        "factory_id": r.factory_id,
        "station_id": r.station_id,
        "operation_name": r.operation_name,
        "operator_id": r.operator_id,
        "average_time": r.average_time,
        "normal_time": r.normal_time,
        "allowed_time": r.allowed_time,
        "status": r.status,
        "created_at": r.created_at.isoformat()
    } for r in records]

# ============================================================
# 产线平衡端点 (Line Balance Endpoints)
# ============================================================

@router.post("/line-balance-analyses", status_code=201)
async def analyze_line_balance(
    analysis_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """执行产线平衡分析"""
    factory_id = analysis_data.get("factory_id", "")
    line_id = analysis_data.get("line_id", "")
    product_id = analysis_data.get("product_id", "")
    
    service = LineBalanceService(db)
    try:
        lba = await service.analyze_line_balance(
            factory_id=factory_id,
            line_id=line_id,
            product_id=product_id,
            analysis_date=datetime.utcnow(),
            created_by=current_user.username
        )
        return {
            "id": lba.id,
            "factory_id": lba.factory_id,
            "line_id": lba.line_id,
            "product_id": lba.product_id,
            "balance_rate": lba.balance_rate,
            "takt_time_min": lba.takt_time_min,
            "bottleneck_station": lba.bottleneck_station,
            "recommendations": lba.recommendations,
            "created_at": lba.created_at.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return [r.to_dict() for r in records]


@router.get("/time-studies/{ts_id}/analysis", response_model=Dict[str, Any])
async def get_time_study_analysis(
    ts_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取时间研究的详细分析报告"""
    service = TimeStudyService(db)
    analysis = await service.get_ts_analysis(ts_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Time study record not found")
    return analysis


@router.post("/time-studies/{ts_id}/approve")
async def approve_time_study(
    ts_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """批准时间研究记录（生成对应的标准工时）"""
    service = TimeStudyService(db)
    try:
        record = await service.approve_time_study(
            ts_id=ts_id,
            approved_by=current_user.username
        )
        return {
            "status": "success",
            "message": "Time study approved and standard time created",
            "time_study_id": ts_id
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 产线平衡分析端点 (Line Balance Analysis Endpoints)
# ============================================================

@router.post("/line-balance-analyses", status_code=201)
async def create_line_balance_analysis(
    input_data: LineBalanceInput,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """执行产线平衡分析并保存报告"""
    service = LineBalanceService(db)
    
    try:
        takt_time = input_data.takt_time
        if input_data.takt_time is not None:
            takt_time = float(input_data.takt_time)
        
        lba = await service.analyze_line_balance(
            factory_id=input_data.factory_id,
            line_id=input_data.line_id,
            product_id=input_data.product_id,
            analysis_date=datetime.utcnow(),
            takt_time=takt_time
        )
        return LineBalanceResponse.model_validate(lba.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/line-balance-analyses", response_model=List[Dict[str, Any]])
async def list_line_balance_analyses(
    factory_id: str,
    product_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询产线平衡分析报告列表"""
    service = LineBalanceService(db)
    analyses = await service.list_line_balance_analyses(
        factory_id=factory_id,
        product_id=product_id,
        limit=limit
    )
    return [{
        "id": a.id,
        "factory_id": a.factory_id,
        "line_id": a.line_id,
        "product_id": a.product_id,
        "balance_rate": a.balance_rate,
        "takt_time_min": a.takt_time_min,
        "bottleneck_station": a.bottleneck_station,
        "created_at": a.created_at.isoformat()
    } for a in analyses]
    line_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询历史平衡分析报告"""
    service = LineBalanceService(db)
    reports = await service.list_line_balances(
        factory_id=factory_id,
        product_id=product_id,
        line_id=line_id,
        limit=limit
    )
    return [r.to_dict() for r in reports]


@router.get("/line-balance-analyses/{lba_id}", response_model=LineBalanceResponse)
async def get_line_balance_report(
    lba_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取平衡分析报告详情"""
    service = LineBalanceService(db)
    report = await service.get_line_balance_report(lba_id)
    if not report:
        raise HTTPException(status_code=404, detail="Line balance analysis not found")
    return LineBalanceResponse.model_validate(report.to_dict())


# ============================================================
# 工序价值分析端点 (Process Analysis Endpoints)
# ============================================================

@router.post("/process-analyses", status_code=201)
async def create_process_analysis(
    analysis_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建工序价值分析记录"""
    service = ProcessAnalysisService(db)
    try:
        pa = await service.create_process_analysis(
            factory_id=analysis_data["factory_id"],
            product_id=analysis_data["product_id"],
            operation_code=analysis_data["operation_code"],
            total_process_time_min=analysis_data["total_process_time_min"],
            va_time_min=analysis_data["va_time_min"],
            nva_time_min=analysis_data["nva_time_min"],
            wait_time_min=analysis_data.get("wait_time_min", 0),
            move_time_min=analysis_data.get("move_time_min", 0),
            inspect_time_min=analysis_data.get("inspect_time_min", 0),
            lead_time=analysis_data["lead_time"],
            efficiency_score=analysis_data["efficiency_score"],
            created_by=current_user.username
        )
        return {
            "id": pa.id,
            "factory_id": pa.factory_id,
            "operation_code": pa.operation_code,
            "va_ratio": pa.va_ratio,
            "efficiency_score": pa.efficiency_score,
            "created_at": pa.created_at.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    data: ProcessAnalysisInput,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """创建工序价值分析报告"""
    service = ProcessAnalysisService(db)
    
    try:
        pa = await service.create_process_analysis(
            factory_id=data.factory_id,
            product_id=data.product_id,
            operation_code=data.operation_code,
            va_time=data.va_time,
            nva_time=data.nva_time,
            wait_time=data.wait_time,
            move_time=data.move_time,
            inspect_time=data.inspect_time,
            lead_time=data.lead_time,
            created_by=current_user.username
        )
        return ProcessAnalysisResponse.model_validate(pa.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/process-analyses", response_model=List[Dict[str, Any]])
async def list_process_analyses(
    factory_id: str,
    product_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询工序价值分析列表"""
    service = ProcessAnalysisService(db)
    analyses = await service.list_process_analyses(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """查询工序价值分析记录"""
    service = ProcessAnalysisService(db)
    analyses = await service.get_process_flow_analysis(
        factory_id=factory_id,
        product_id=product_id,
        limit=limit
    )
    return [{
        "id": a.id,
        "factory_id": a.factory_id,
        "product_id": a.product_id,
        "operation_code": a.operation_code,
        "va_ratio": a.va_ratio,
        "efficiency_score": a.efficiency_score,
        "created_at": a.created_at.isoformat()
    } for a in analyses]

# ============================================================
# 精益指标端点 (Lean Metrics Endpoint)
# ============================================================

@router.get("/lean-metrics")
async def get_lean_metrics(
    factory_id: str,
    product_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取精益生产关键指标"""
    from api.services.ie_service import ProcessAnalysisService
    
    service = ProcessAnalysisService(db)
    
    # 从ProcessAnalysisService获取VA/NVA分析
    try:
        analyses = await service.get_process_flow_analysis(
            factory_id=factory_id,
            product_id=product_id
        )
        
        if not analyses:
            return {
                "message": "No process analysis data available yet",
                "data": []
            }
        
        total_va = sum(a.get("va_time_min", 0) for a in analyses)
        total_nva = sum(a.get("nva_time_min", 0) for a in analyses)
        total_time = total_va + total_nva
        
        return {
            "factory_id": factory_id,
            "product_id": product_id,
            "total_value_added_time": round(total_va, 2),
            "total_non_value_added_time": round(total_nva, 2),
            "overall_va_ratio": round(total_va / total_time, 4) if total_time > 0 else 0,
            "analysis_count": len(analyses),
            "processes": [
                {
                    "operation": a.get("operation_code", ""),
                    "va": a.get("va_time_min", 0),
                    "nva": a.get("nva_time_min", 0),
                    "ratio": a.get("va_ratio", 0),
                    "efficiency": a.get("efficiency_score", 0)
                } for a in analyses
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return analyses


@router.get("/process-analyses/{pa_id}", response_model=ProcessAnalysisResponse)
async def get_process_analysis(
    pa_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取工序价值分析报告详情"""
    service = ProcessAnalysisService(db)
    query = select(ProcessAnalysis).where(ProcessAnalysis.id == pa_id)
    result = await query
    pa = result.scalar_one_or_none()
    if not pa:
        raise HTTPException(status_code=404, detail="Process analysis not found")
    return ProcessAnalysisResponse.model_validate(pa.to_dict())


@router.get("/lean-metrics", response_model=Dict[str, Any])
async def calculate_lean_metrics(
    factory_id: str,
    product_id: str = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """计算精益生产关键指标（VA/NVA比率等）"""
    service = ProcessAnalysisService(db)
    metrics = await service.calculate_leaning_metrics(
        factory_id=factory_id,
        product_id=product_id
    )
    return metrics


# ============================================================
# 辅助端点：获取产品关联的标准工时
# ============================================================

@router.get("/products/{product_id}/standard-times", response_model=List[Dict[str, Any]])
async def get_product_standard_times(
    product_id: str,
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """获取产品的所有标准工时汇总"""
    service = StandardTimeService(db)
    
    query = select(
        StandardOperationTime.product_id,
        StandardOperationTime.routing_step,
        StandardOperationTime.operation_name,
        StandardOperationTime.station_id,
        StandardOperationTime.standard_time_min,
        StandardOperationTime.effective_standard_time,
        StandardOperationTime.version,
        StandardOperationTime.is_active
    ).where(StandardOperationTime.product_id == product_id)
    
    if factory_id:
        query = query.where(StandardOperationTime.factory_id == factory_id)
    
    query = query.order_by(StandardOperationTime.routing_step)
    result = await query.all()
    
    return [{
        "product_id": r.product_id,
        "routing_step": r.routing_step,
        "operation_name": r.operation_name,
        "station_id": r.station_id,
        "standard_time_min": r.standard_time_min,
        "effective_standard_time": r.effective_standard_time,
        "version": r.version,
        "is_active": r.is_active,
    } for r in result]
