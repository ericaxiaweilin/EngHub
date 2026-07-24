"""
岗位替代 Phase 4 路由 - 检验终端 / SPC 控制图 / 不良分析
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.inspection_service import InspectionService
from api.services.spc_service import SpcService

router = APIRouter(prefix="/api/v1", tags=["qms-phase4"])


# ==================== Request Models ====================

class InspectionCreate(BaseModel):
    factory_id: str
    inspect_type: str  # IQC/IPQC/FQC/OQC
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    product_id: Optional[str] = None
    work_order_id: Optional[str] = None
    station_id: Optional[str] = None
    batch_qty: int = 0
    sample_qty: int = 0
    source_type: Optional[str] = None
    source_code: Optional[str] = None


class InspectionItemsAdd(BaseModel):
    task_id: str
    items: List[dict]


class MeasurementSubmit(BaseModel):
    task_id: str
    item_id: str
    measured_value: float
    defect_type: Optional[str] = None
    severity: Optional[str] = None
    remark: Optional[str] = None


class InspectionComplete(BaseModel):
    task_id: str
    result: str  # PASS/FAIL/CONDITIONAL
    disposition: Optional[str] = None
    remark: Optional[str] = None


class SpcMeasurement(BaseModel):
    factory_id: str
    characteristic_code: str
    measured_value: float
    characteristic_name: Optional[str] = None
    work_order_id: Optional[str] = None
    station_id: Optional[str] = None
    sample_group: Optional[int] = None


class SpcConfigUpsert(BaseModel):
    factory_id: str
    characteristic_code: str
    characteristic_name: str = ""
    chart_type: str = "Xbar-R"
    ucl: Optional[float] = None
    cl: Optional[float] = None
    lcl: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    subgroup_size: int = 5


# ==================== 检验任务 ====================

@router.post("/qms/inspection")
async def create_inspection(
    req: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建检验任务"""
    svc = InspectionService(db)
    return await svc.create_task(
        factory_id=req.factory_id, inspect_type=req.inspect_type,
        material_code=req.material_code, material_name=req.material_name,
        product_id=req.product_id, work_order_id=req.work_order_id,
        station_id=req.station_id, batch_qty=req.batch_qty,
        sample_qty=req.sample_qty, source_type=req.source_type,
        source_code=req.source_code, created_by=current_user.username,
    )


@router.post("/qms/inspection/items")
async def add_inspection_items(
    req: InspectionItemsAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加检验项"""
    svc = InspectionService(db)
    return await svc.add_items(req.task_id, req.items)


@router.post("/qms/inspection/{task_id}/start")
async def start_inspection(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始检验"""
    svc = InspectionService(db)
    return await svc.start_inspection(task_id, current_user.username)


@router.post("/qms/inspection/measure")
async def submit_measurement(
    req: MeasurementSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交测量值"""
    svc = InspectionService(db)
    result = await svc.submit_measurement(
        req.task_id, req.item_id, req.measured_value,
        req.defect_type, req.severity, req.remark,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/qms/inspection/complete")
async def complete_inspection(
    req: InspectionComplete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成检验"""
    svc = InspectionService(db)
    return await svc.complete_inspection(req.task_id, req.result, req.disposition, req.remark)


@router.get("/qms/inspection/tasks")
async def list_inspections(
    factory_id: str = Query(...),
    inspect_type: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检验任务列表"""
    svc = InspectionService(db)
    return await svc.list_tasks(factory_id, inspect_type, status)


@router.get("/qms/inspection/{task_id}")
async def get_inspection_detail(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检验任务详情"""
    svc = InspectionService(db)
    return await svc.get_task_detail(task_id)


@router.get("/qms/defect-pareto")
async def defect_pareto(
    factory_id: str = Query(...),
    days: int = Query(default=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """不良 Pareto 分析"""
    svc = InspectionService(db)
    return await svc.defect_pareto(factory_id, days)


@router.get("/qms/quality-kpi")
async def quality_kpi(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """质量 KPI"""
    svc = InspectionService(db)
    return await svc.quality_kpi(factory_id)


# ==================== SPC ====================

@router.post("/qms/spc/measure")
async def spc_measure(
    req: SpcMeasurement,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录 SPC 测量"""
    svc = SpcService(db)
    return await svc.record_measurement(
        factory_id=req.factory_id, characteristic_code=req.characteristic_code,
        measured_value=req.measured_value, characteristic_name=req.characteristic_name,
        work_order_id=req.work_order_id, station_id=req.station_id,
        sample_group=req.sample_group, measured_by=current_user.username,
    )


@router.get("/qms/spc/chart")
async def spc_chart(
    factory_id: str = Query(...),
    characteristic_code: str = Query(...),
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """控制图数据"""
    svc = SpcService(db)
    return await svc.get_control_chart(factory_id, characteristic_code, limit)


@router.post("/qms/spc/calculate-limits")
async def calculate_limits(
    factory_id: str = Query(...),
    characteristic_code: str = Query(...),
    subgroup_size: int = Query(default=5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """计算控制限"""
    svc = SpcService(db)
    result = await svc.calculate_control_limits(factory_id, characteristic_code, subgroup_size)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/qms/spc/characteristics")
async def list_characteristics(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SPC 特性列表"""
    svc = SpcService(db)
    return await svc.list_characteristics(factory_id)


@router.post("/qms/spc/config")
async def upsert_spc_config(
    req: SpcConfigUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SPC 配置"""
    svc = SpcService(db)
    return await svc.upsert_config(
        factory_id=req.factory_id, characteristic_code=req.characteristic_code,
        characteristic_name=req.characteristic_name, chart_type=req.chart_type,
        ucl=req.ucl, cl=req.cl, lcl=req.lcl, usl=req.usl, lsl=req.lsl,
        subgroup_size=req.subgroup_size,
    )


# ==================== AQL + 检验计划 + 自动判定 ====================


@router.get("/qms/aql-sampling")
async def aql_sampling(
    batch_qty: int = Query(..., ge=1, description="批量"),
    aql: float = Query(1.0, description="AQL 值"),
    level: str = Query("II", description="检验水平"),
    current_user: User = Depends(get_current_user),
):
    """AQL 抽样方案（GB/T 2828.1）"""
    svc = InspectionService(None)
    return svc.get_aql_sampling_plan(batch_qty, aql, level)


@router.post("/qms/inspection/{task_id}/auto-plan")
async def auto_inspection_plan(
    task_id: str,
    inspect_type: str = Query("IQC", description="IQC/IPQC/FQC"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动生成检验计划（按检验类型生成标准检验项）"""
    svc = InspectionService(db)
    return await svc.generate_inspection_plan(task_id, inspect_type)


@router.post("/qms/inspection/{task_id}/auto-judge")
async def auto_judge(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动判定 + 生成检验报告"""
    svc = InspectionService(db)
    return await svc.auto_judge_and_report(task_id)
