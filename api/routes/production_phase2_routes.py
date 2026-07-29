"""
岗位替代 Phase 2 路由 - 订单管理 / APS 排程增强
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.order_decomposition_service import OrderDecompositionService
from api.services.aps_engine import ApsEngine

router = APIRouter(prefix="/api/v1", tags=["production-phase2"])


# ==================== Request Models ====================

class SalesOrderCreate(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    product_name: Optional[str] = None
    delivery_date: Optional[str] = None
    priority: str = "medium"
    unit_price: Optional[float] = None
    remark: Optional[str] = None


class ScheduleRequest(BaseModel):
    factory_id: str
    algorithm: str = "EDD"
    horizon_days: int = 7


class RescheduleRequest(BaseModel):
    factory_id: str
    insert_wo_id: Optional[str] = None
    algorithm: str = "EDD"


# ==================== 销售订单 ====================

@router.post("/orders")
async def create_sales_order(
    req: SalesOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建销售订单"""
    svc = OrderDecompositionService(db)
    result = await svc.create_sales_order(
        factory_id=req.factory_id,
        product_id=req.product_id,
        quantity=req.quantity,
        customer_name=req.customer_name,
        customer_code=req.customer_code,
        product_name=req.product_name,
        delivery_date=req.delivery_date,
        priority=req.priority,
        unit_price=req.unit_price,
        remark=req.remark,
        created_by=current_user.username,
    )
    return result


@router.get("/orders")
async def list_sales_orders(
    factory_id: str = Query(...),
    status: Optional[str] = None,
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """销售订单列表"""
    svc = OrderDecompositionService(db)
    return await svc.list_sales_orders(factory_id, status, limit)


@router.post("/orders/{order_id}/decompose")
async def decompose_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单 → 工单拆分"""
    svc = OrderDecompositionService(db)
    result = await svc.decompose_order(order_id, operator=current_user.username)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/orders/{order_id}/material-check")
async def material_check(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """物料齐套检查"""
    svc = OrderDecompositionService(db)
    result = await svc.material_check(order_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/orders/delivery-estimate")
async def delivery_estimate(
    factory_id: str = Query(...),
    product_id: str = Query(...),
    quantity: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交期评估"""
    svc = OrderDecompositionService(db)
    return await svc.estimate_delivery(factory_id, product_id, quantity)


# ==================== APS 排程增强 ====================

@router.post("/aps/schedule")
async def run_schedule(
    req: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行有限产能排程"""
    engine = ApsEngine(db)
    result = await engine.schedule(
        factory_id=req.factory_id,
        algorithm=req.algorithm,
        horizon_days=req.horizon_days,
        created_by=current_user.username,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/aps/reschedule")
async def run_reschedule(
    req: RescheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """插单重排（锁定在制工单）"""
    engine = ApsEngine(db)
    result = await engine.reschedule(
        factory_id=req.factory_id,
        insert_wo_id=req.insert_wo_id,
        algorithm=req.algorithm,
        created_by=current_user.username,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/aps/gantt")
async def gantt_data(
    factory_id: str = Query(...),
    schedule_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """甘特图数据"""
    engine = ApsEngine(db)
    return await engine.get_gantt_data(factory_id, schedule_id)


@router.get("/aps/conflicts")
async def detect_conflicts(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冲突检测"""
    engine = ApsEngine(db)
    return await engine.detect_conflicts(factory_id)
