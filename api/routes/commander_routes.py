"""
工厂指挥官路由
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/commander", tags=["工厂指挥官"])


class CommanderCycleRequest(BaseModel):
    factory_id: Optional[str] = None
    force_mode: Optional[str] = None  # surplus / normal / deficit
    auto_execute: bool = True


class ModeOverrideRequest(BaseModel):
    factory_id: Optional[str] = None
    mode: Optional[str] = None  # surplus / normal / deficit / null(自动)


class CommanderToggleRequest(BaseModel):
    enabled: bool = True
    factory_id: Optional[str] = None
    scope: Optional[dict] = None  # {departments, role, stations}


@router.post("/cycle")
async def run_commander_cycle(
    req: CommanderCycleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行一轮指挥官决策循环（感知→决策→执行→汇报）"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(db)
    factory_id = req.factory_id or getattr(current_user, "active_factory_id", None) or "FAC_MECH_001"
    report = await commander.run_cycle(factory_id, force_mode=req.force_mode, auto_execute=req.auto_execute, created_by=current_user.username or str(current_user.id))
    return report.to_dict()


@router.get("/status")
async def commander_status(
    factory_id: str = Query(default="FAC_MECH_001"),
    current_user: User = Depends(get_current_user),
):
    """获取指挥官当前状态"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(None)
    return await commander.get_status(factory_id)


@router.get("/history")
async def commander_history(
    factory_id: str = Query(default="FAC_MECH_001"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """获取指挥官决策历史"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(None)
    return await commander.get_history(factory_id, limit)


@router.post("/mode")
async def set_commander_mode(
    req: ModeOverrideRequest,
    current_user: User = Depends(get_current_user),
):
    """手动设置订单模式（override自动判断）"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(None)
    factory_id = req.factory_id or getattr(current_user, "active_factory_id", None) or "FAC_MECH_001"
    commander.set_mode(factory_id, req.mode)
    return {"factory_id": factory_id, "mode_override": req.mode, "message": f"模式已设置为: {req.mode or '自动'}"}


@router.post("/toggle")
async def toggle_commander(
    req: CommanderToggleRequest,
    current_user: User = Depends(get_current_user),
):
    """开启/关闭当前用户的指挥官（开启后自动接管工作范围内事务）"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(None)
    user_id = str(current_user.id)
    factory_id = req.factory_id or getattr(current_user, "active_factory_id", None) or "FAC_MECH_001"

    if req.enabled:
        await commander.enable_for_user(user_id, factory_id, req.scope, username=current_user.username)
        return {"enabled": True, "user_id": user_id, "factory_id": factory_id, "message": "指挥官已开启，将自动接管您工作范围内的生产调度、接单、排产、交期管理"}
    else:
        await commander.disable_for_user(user_id)
        return {"enabled": False, "user_id": user_id, "message": "指挥官已关闭，恢复手动模式"}


@router.get("/my-status")
async def my_commander_status(
    current_user: User = Depends(get_current_user),
):
    """获取我的指挥官状态"""
    from api.services.factory_commander import FactoryCommander
    commander = FactoryCommander(None)
    return await commander.get_user_status(str(current_user.id))
