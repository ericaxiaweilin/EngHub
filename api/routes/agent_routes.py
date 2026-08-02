"""
智能体路由 - 排产智能体 + 仓储智能体
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
from pydantic import BaseModel

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/agents", tags=["智能体"])


# ═══════════════════════════════════════════════════════════
# 排产智能体
# ═══════════════════════════════════════════════════════════

@router.post("/scheduling/auto-schedule")
async def scheduling_auto(
    factory_id: str = Query(...),
    algorithm: str = Query("EDD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体：自动排程"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.auto_schedule(factory_id, algorithm)


@router.post("/scheduling/auto-reschedule")
async def scheduling_reschedule(
    factory_id: str = Query(...),
    reason: str = Query("手动触发重排"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体：自动重排（插单/故障后）"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.auto_reschedule(factory_id, reason)


@router.post("/scheduling/what-if")
async def scheduling_what_if(
    factory_id: str = Query(...),
    planned_qty: int = Query(100),
    product_id: str = Query(""),
    priority: str = Query("medium"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体：What-if模拟（加入新工单的影响）"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.what_if(factory_id, {
        "planned_qty": planned_qty,
        "product_id": product_id,
        "priority": priority,
    })


@router.get("/scheduling/capacity-balance")
async def scheduling_balance(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体：产能平衡检查"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.capacity_balance(factory_id)


@router.post("/scheduling/event/order-released")
async def scheduling_event_order(
    factory_id: str = Query(...),
    wo_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体事件：新工单下达"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.on_work_order_released(factory_id, wo_id)


@router.post("/scheduling/event/equipment-breakdown")
async def scheduling_event_breakdown(
    factory_id: str = Query(...),
    equipment_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """排产智能体事件：设备故障→工单迁移"""
    from api.services.scheduling_agent_service import SchedulingAgent
    agent = SchedulingAgent(db)
    return await agent.on_equipment_breakdown(factory_id, equipment_id)


# ═══════════════════════════════════════════════════════════
# 仓储智能体
# ═══════════════════════════════════════════════════════════

@router.post("/warehouse/check-replenishment")
async def warehouse_replenish(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仓储智能体：检查补货需求（低于安全线→自动创建采购申请）"""
    from api.services.warehouse_agent_service import WarehouseAgent
    agent = WarehouseAgent(db)
    return await agent.on_stock_below_safety(factory_id)


@router.post("/warehouse/kit-check")
async def warehouse_kit_check(
    factory_id: str = Query(...),
    wo_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仓储智能体：齐套检查（工单物料够不够）"""
    from api.services.warehouse_agent_service import WarehouseAgent
    agent = WarehouseAgent(db)
    return await agent.on_work_order_released(factory_id, wo_id)


@router.get("/warehouse/dead-stock")
async def warehouse_dead_stock(
    factory_id: str = Query(...),
    days: int = Query(90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仓储智能体：呆滞料预警"""
    from api.services.warehouse_agent_service import WarehouseAgent
    agent = WarehouseAgent(db)
    return await agent.daily_dead_stock_check(factory_id, days)


@router.get("/warehouse/location-optimization")
async def warehouse_location(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仓储智能体：库位优化建议"""
    from api.services.warehouse_agent_service import WarehouseAgent
    agent = WarehouseAgent(db)
    return await agent.location_optimization(factory_id)


@router.get("/warehouse/health")
async def warehouse_health(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仓储智能体：库存健康度总览"""
    from api.services.warehouse_agent_service import WarehouseAgent
    agent = WarehouseAgent(db)
    return await agent.inventory_health(factory_id)
