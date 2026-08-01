"""
Chatbot 快速命令 + 智能体调度路由
- /api/v1/chat/agents          可选智能体列表（供 chatbot 页面 agent 选择器）
- /api/v1/chat/quick-commands  快速命令 CRUD（新增后立即自动归类到对应智能体）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/chat", tags=["ai-assistant"])


def _resolve_factory(request: Request, user: User) -> str:
    return (
        request.headers.get("x-factory-id")
        or getattr(user, "active_factory_id", None)
        or user.factory_id
        or "FAC_MECH_001"
    )


class QuickCommandCreate(BaseModel):
    command_text: str = Field(..., min_length=1, max_length=500)
    agent_key: Optional[str] = None  # 不传则自动归类


class QuickCommandUpdate(BaseModel):
    command_text: Optional[str] = Field(None, max_length=500)
    agent_key: Optional[str] = None  # 传空字符串 = 清除归类（通用）


@router.get("/agents")
async def list_chat_agents(
    current_user: User = Depends(get_current_user),
):
    """chatbot 可调度的智能体列表（含'自动调度'由前端自行渲染）。"""
    from api.services.agent_supervisor_service import AGENTS
    return {
        "agents": [
            {
                "key": k,
                "name": v["name"],
                "description": v["description"],
                "trigger": v["trigger"],
            }
            for k, v in AGENTS.items()
        ],
    }


@router.get("/quick-commands")
async def list_quick_commands(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """快速命令列表（全局预置 + 当前工厂自定义）。"""
    from api.services import quick_command_service as svc
    factory_id = _resolve_factory(request, current_user)
    return {"commands": await svc.list_quick_commands(db, factory_id)}


@router.post("/quick-commands", status_code=201)
async def create_quick_command(
    payload: QuickCommandCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新增快速命令：未指定 agent_key 时，立即自动归类到对应智能体。"""
    from api.services import quick_command_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.create_quick_command(
        db, factory_id,
        created_by=current_user.username or current_user.id,
        command_text=payload.command_text,
        agent_key=payload.agent_key,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/quick-commands/{command_id}")
async def update_quick_command(
    command_id: str,
    payload: QuickCommandUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新快速命令：修改文本且未指定 agent 时自动重新归类。"""
    from api.services import quick_command_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.update_quick_command(
        db, factory_id, command_id,
        command_text=payload.command_text,
        agent_key=payload.agent_key,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/quick-commands/{command_id}")
async def delete_quick_command(
    command_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除快速命令（系统预置不可删）。"""
    from api.services import quick_command_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.delete_quick_command(db, factory_id, command_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


__all__ = ["router"]
