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
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/ie", tags=["ie"])


# ============================================================
# 响应模型 (Pydantic Response Models)
# ============================================================

class StandardTimeCreate(BaseModel):
    """创建标准工时请求体"""
    factory_id: str
    product_id: str
    routing_step: str
    operation_name: str
    station_id: Optional[str] = None
    standard_time_min: float
    setup_time_min: float = 0.0
    batch_size: int = 1
    rating_factor: float = 1.0
    allowance_rate: float = 0.15
    validity_start: datetime
    validity_end: Optional[datetime] = None

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

# ============================================================
# 标准工时端点 (Standard Time Endpoints)
# ============================================================

@router.post("/standard-times", status_code=201)
async def create_standard_time(
    sot_data: StandardTimeCreate,
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

@router.get("/standard-times", response_model=List[Dict[str, Any]])
async def list_standard_times(
    factory_id: str,
    product_id: Optional[str] = None,
    station_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
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

# ============================================================
# 时间研究端点 (Time Study Endpoints)
# ============================================================

@router.post("/time-studies", status_code=201)
async def create_time_study(
    ts_data: TimeStudyCreate,
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

@router.get("/time-studies", response_model=List[Dict[str, Any]])
async def list_time_studies(
    factory_id: str,
    product_id: Optional[str] = None,
    station_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
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
