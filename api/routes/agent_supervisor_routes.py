"""
智能体监督路由 - 长任务追踪/卡住检测/预测/闭环验证
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/agent-supervisor", tags=["智能体监督"])


@router.get("/agents")
async def list_agents(
    current_user: User = Depends(get_current_user),
):
    """获取所有智能体定义（6个Agent+架构说明）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(None)
    return await svc.list_agents()


@router.get("/dashboard")
async def supervisor_dashboard(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """智能体监督看板（所有Agent状态+最近任务+健康度）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.supervisor_dashboard(factory_id)


@router.get("/predict")
async def predict_issues(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预测性问题发现（不是出了问题才动，是预判要出问题）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.predict_issues(factory_id)


@router.get("/stalled")
async def check_stalled(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检测卡住的任务（超时无进展）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.check_stalled(factory_id)


@router.post("/task/start")
async def start_task(
    factory_id: str = Query(...),
    agent_key: str = Query(...),
    task_type: str = Query(...),
    task_desc: str = Query(""),
    total_steps: int = Query(1, ge=1),
    timeout_minutes: int = Query(30, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启动长任务（智能体开始多步骤工作）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.start_task(factory_id, agent_key, task_type, task_desc, total_steps, timeout_minutes)


@router.post("/task/progress")
async def update_progress(
    task_id: str = Query(...),
    completed_steps: int = Query(..., ge=0),
    note: str = Query(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新任务进度"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.update_progress(task_id, completed_steps, note)


@router.post("/task/complete")
async def complete_task(
    task_id: str = Query(...),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成任务"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.complete_task(task_id, error=error)


@router.post("/task/verify")
async def verify_task(
    task_id: str = Query(...),
    verify_result: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """闭环验证（确认执行结果）"""
    from api.services.agent_supervisor_service import AgentSupervisor
    svc = AgentSupervisor(db)
    return await svc.verify_task(task_id, verify_result)
