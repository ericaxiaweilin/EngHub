"""
多智能体并行编排路由
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/orchestrator", tags=["多智能体编排"])


class OrchestrationRequest(BaseModel):
    intent: Optional[str] = None
    message: Optional[str] = None
    factory_id: Optional[str] = None
    context: Dict[str, Any] = {}


@router.post("/execute")
async def execute_orchestration(
    req: OrchestrationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行多智能体并行编排"""
    from api.services.parallel_orchestrator import ParallelOrchestrator
    orchestrator = ParallelOrchestrator(db)

    factory_id = req.factory_id or getattr(current_user, "active_factory_id", None) or "FAC_MECH_001"

    # 如果没指定 intent，从 message 中识别
    intent = req.intent
    if not intent and req.message:
        intent = orchestrator.resolve_intent(req.message)
    if not intent:
        return {"error": "未识别到编排意图，请指定 intent 或输入包含关键词的 message", "available_intents": orchestrator.list_intents()}

    result = await orchestrator.execute(
        intent=intent,
        factory_id=factory_id,
        context=req.context or {"user_message": req.message or ""},
        user_message=req.message or "",
    )
    return result.to_dict()


@router.get("/intents")
async def list_intents(
    current_user: User = Depends(get_current_user),
):
    """列出所有可用的并行编排意图"""
    from api.services.parallel_orchestrator import ParallelOrchestrator
    orchestrator = ParallelOrchestrator(None)
    return orchestrator.list_intents()


@router.get("/agents")
async def list_all_agents(
    current_user: User = Depends(get_current_user),
):
    """列出所有注册的智能体（含岗位级+功能级）"""
    from api.services.parallel_orchestrator import ParallelOrchestrator
    orchestrator = ParallelOrchestrator(None)
    return orchestrator.list_agents()


@router.get("/history")
async def orchestration_history(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """获取编排执行历史"""
    from api.services.parallel_orchestrator import ParallelOrchestrator
    orchestrator = ParallelOrchestrator(None)
    return orchestrator.get_history(limit)
