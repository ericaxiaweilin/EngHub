"""
岗位替代 Phase 3 路由 - 仓管操作终端 / 库存预警 / 盘点
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.wms_operation_service import WmsOperationService
from api.services.stock_alert_service import StockAlertService

router = APIRouter(prefix="/api/v1", tags=["wms-phase3"])


# ==================== Request Models ====================

class InboundRequest(BaseModel):
    factory_id: str
    material_id: str
    material_code: str
    quantity: int
    warehouse_id: str
    location_id: Optional[str] = None
    batch_code: Optional[str] = None
    material_name: Optional[str] = None
    unit: str = "pcs"
    remark: Optional[str] = None


class OutboundRequest(BaseModel):
    factory_id: str
    material_id: str
    quantity: int
    warehouse_id: Optional[str] = None
    batch_code: Optional[str] = None
    remark: Optional[str] = None


class TransferRequest(BaseModel):
    factory_id: str
    material_id: str
    quantity: int
    from_warehouse_id: str
    to_warehouse_id: str
    to_location_id: Optional[str] = None
    remark: Optional[str] = None


class CycleCountCreate(BaseModel):
    factory_id: str
    warehouse_id: Optional[str] = None
    count_type: str = "cycle"
    assigned_to: Optional[str] = None


class CountSubmit(BaseModel):
    task_id: str
    item_id: str
    counted_qty: int


class SafetyConfigUpsert(BaseModel):
    factory_id: str
    material_id: str
    material_code: str = ""
    material_name: str = ""
    safety_stock: int = 0
    reorder_point: int = 0
    max_stock: int = 0
    dead_stock_days: int = 90


# ==================== 仓管操作终端 ====================

@router.post("/wms/inbound")
async def quick_inbound(
    req: InboundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """快速入库"""
    svc = WmsOperationService(db)
    result = await svc.quick_inbound(
        factory_id=req.factory_id,
        material_id=req.material_id,
        material_code=req.material_code,
        quantity=req.quantity,
        warehouse_id=req.warehouse_id,
        location_id=req.location_id,
        batch_code=req.batch_code,
        material_name=req.material_name,
        unit=req.unit,
        operator=current_user.username,
        remark=req.remark,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/wms/outbound")
async def quick_outbound(
    req: OutboundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """快速出库"""
    svc = WmsOperationService(db)
    result = await svc.quick_outbound(
        factory_id=req.factory_id,
        material_id=req.material_id,
        quantity=req.quantity,
        warehouse_id=req.warehouse_id,
        batch_code=req.batch_code,
        operator=current_user.username,
        remark=req.remark,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/wms/transfer")
async def transfer_stock(
    req: TransferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移库"""
    svc = WmsOperationService(db)
    result = await svc.transfer(
        factory_id=req.factory_id,
        material_id=req.material_id,
        quantity=req.quantity,
        from_warehouse_id=req.from_warehouse_id,
        to_warehouse_id=req.to_warehouse_id,
        to_location_id=req.to_location_id,
        operator=current_user.username,
        remark=req.remark,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/wms/search")
async def search_inventory(
    factory_id: str = Query(...),
    keyword: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """库存搜索"""
    svc = WmsOperationService(db)
    return await svc.search_inventory(factory_id, keyword, warehouse_id)


@router.get("/wms/recent-operations")
async def recent_operations(
    factory_id: str = Query(...),
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """最近操作流水"""
    svc = WmsOperationService(db)
    return await svc.recent_transactions(factory_id, limit)


# ==================== 盘点 ====================

@router.post("/wms/cycle-count")
async def create_cycle_count(
    req: CycleCountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建盘点任务"""
    svc = WmsOperationService(db)
    result = await svc.create_cycle_count(
        factory_id=req.factory_id,
        warehouse_id=req.warehouse_id,
        count_type=req.count_type,
        assigned_to=req.assigned_to,
        created_by=current_user.username,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/wms/cycle-count/submit")
async def submit_count(
    req: CountSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交盘点数量"""
    svc = WmsOperationService(db)
    result = await svc.submit_count(req.task_id, req.item_id, req.counted_qty, current_user.username)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/wms/cycle-count/tasks")
async def list_count_tasks(
    factory_id: str = Query(...),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """盘点任务列表"""
    svc = WmsOperationService(db)
    return await svc.list_count_tasks(factory_id, status)


# ==================== 库存预警 ====================

@router.post("/wms/alerts/check")
async def run_alert_check(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行库存预警检查"""
    svc = StockAlertService(db)
    return await svc.run_alert_check(factory_id)


@router.get("/wms/alerts")
async def get_alerts(
    factory_id: str = Query(...),
    status: Optional[str] = None,
    alert_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预警列表"""
    svc = StockAlertService(db)
    return await svc.get_alerts(factory_id, status, alert_type)


@router.post("/wms/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """解决预警"""
    svc = StockAlertService(db)
    return await svc.resolve_alert(alert_id, current_user.username)


@router.post("/wms/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认预警"""
    svc = StockAlertService(db)
    return await svc.acknowledge_alert(alert_id)


@router.get("/wms/safety-config")
async def get_safety_configs(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """安全库存配置"""
    svc = StockAlertService(db)
    return await svc.get_safety_configs(factory_id)


@router.post("/wms/safety-config")
async def upsert_safety_config(
    req: SafetyConfigUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新增/更新安全库存配置"""
    svc = StockAlertService(db)
    return await svc.upsert_safety_config(
        factory_id=req.factory_id,
        material_id=req.material_id,
        material_code=req.material_code,
        material_name=req.material_name,
        safety_stock=req.safety_stock,
        reorder_point=req.reorder_point,
        max_stock=req.max_stock,
        dead_stock_days=req.dead_stock_days,
    )


@router.get("/wms/health")
async def stock_health(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """库存健康度概览"""
    svc = StockAlertService(db)
    return await svc.stock_health_summary(factory_id)
