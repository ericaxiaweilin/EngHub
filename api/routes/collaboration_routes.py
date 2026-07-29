"""
岗位协同网络路由 - 跨岗位信息流+决策边界
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/collaboration", tags=["岗位协同网络"])


@router.get("/network")
async def get_network(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取完整协同网络（岗位+事件+边界全景）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(db)
    return await svc.get_network(factory_id)


@router.get("/event-rule")
async def query_event_rule(
    event_key: str = Query(..., description="事件标识"),
    current_user: User = Depends(get_current_user),
):
    """查询单个事件的协同规则（通知谁/谁决策/边界）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.query_event_rule(event_key)


@router.get("/check-permission")
async def check_permission(
    role_key: str = Query(..., description="岗位标识"),
    action: str = Query(..., description="要执行的动作"),
    current_user: User = Depends(get_current_user),
):
    """检查某岗位是否有权执行某动作（边界检查）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.check_permission(role_key, action)


@router.get("/role-boundaries")
async def get_role_boundaries(
    role_key: str = Query(..., description="岗位标识"),
    current_user: User = Depends(get_current_user),
):
    """获取某岗位的完整权限边界（能做/不能做/协同连接）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.get_role_boundaries(role_key)


@router.post("/simulate-event")
async def simulate_event(
    factory_id: str = Query(...),
    event_key: str = Query(..., description="事件标识"),
    context: Dict[str, Any] = {},
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """模拟事件触发：展示协同流程（谁通知/谁决策/当前level下系统做什么）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(db)
    return await svc.simulate_event(factory_id, event_key, context)


@router.get("/chatbot-rules")
async def chatbot_rules(
    current_user: User = Depends(get_current_user),
):
    """给chatbot的协同规则（用于AI助手的边界判断）"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(None)
    return await svc.chatbot_rules()
