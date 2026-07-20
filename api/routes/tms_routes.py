"""
TMS API Routes - 任务管理系统路由

包含：
- 任务 CRUD
- 任务分发
- 审批工作流
- Agent/Chatbot 开放 API
- 仪表盘统计
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.tms import (
    TaskCreate,
    TaskUpdate,
    TaskDistributeRequest,
    TaskClaimRequest,
    ApprovalFlowCreate,
    ApprovalActionRequest,
    ApprovalDelegateRequest,
    ApprovalEscalateRequest,
    AgentCommandRequest,
    AgentConfirmRequest,
    AgentRegisterRequest,
    WebhookRegisterRequest,
)
from api.services.tms_service import TMSService

router = APIRouter(prefix="/api/v1/tms", tags=["TMS - 任务管理系统"])


# ========== 依赖注入 ==========

async def get_tms_service() -> TMSService:
    """获取 TMS 服务（简化版，生产环境应使用真正的 DB session）"""
    from database.db_config import get_async_session
    async for session in get_async_session():
        yield TMSService(session)


# ========== Task Routes ==========

@router.post("/tasks", summary="创建任务")
async def create_task(
    payload: TaskCreate,
    service: TMSService = Depends(get_tms_service),
):
    """创建新任务"""
    result = await service.create_task(
        title=payload.title,
        task_type=payload.task_type,
        description=payload.description,
        priority=payload.priority,
        points=payload.points,
        required_skills=payload.required_skills,
        required_roles=payload.required_roles,
        deadline=payload.deadline,
        distribution_strategy=payload.distribution_strategy,
        related_work_order_id=payload.related_work_order_id,
        metadata=payload.metadata,
        created_by="api_user",
    )
    return {"success": True, "data": result}


@router.get("/tasks", summary="任务列表")
async def list_tasks(
    status: Optional[str] = Query(None, description="状态过滤"),
    task_type: Optional[str] = Query(None, description="类型过滤"),
    priority: Optional[str] = Query(None, description="优先级过滤"),
    assigned_to: Optional[str] = Query(None, description="负责人过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: TMSService = Depends(get_tms_service),
):
    """获取任务列表"""
    result = await service.list_tasks(
        status=status,
        task_type=task_type,
        priority=priority,
        assigned_to=assigned_to,
        page=page,
        page_size=page_size,
    )
    return result


@router.get("/tasks/{task_id}", summary="任务详情")
async def get_task(
    task_id: str,
    service: TMSService = Depends(get_tms_service),
):
    """获取任务详情"""
    result = await service.get_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.put("/tasks/{task_id}", summary="更新任务")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    service: TMSService = Depends(get_tms_service),
):
    """更新任务"""
    result = await service.update_task(
        task_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        points=payload.points,
        required_skills=payload.required_skills,
        deadline=payload.deadline,
        metadata_=payload.metadata,
    )
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "data": result}


# ========== Distribution Routes ==========

@router.post("/tasks/{task_id}/distribute", summary="分发任务")
async def distribute_task(
    task_id: str,
    payload: TaskDistributeRequest,
    service: TMSService = Depends(get_tms_service),
):
    """分发任务（核心接口）"""
    result = await service.distribute_task(
        task_id=task_id,
        strategy=payload.strategy,
        mode=payload.mode,
        target_user_id=payload.target_user_id,
        triggered_by="api_user",
    )
    return result


@router.post("/tasks/{task_id}/claim", summary="认领任务")
async def claim_task(
    task_id: str,
    payload: TaskClaimRequest,
    service: TMSService = Depends(get_tms_service),
):
    """认领任务（候选池抢单）"""
    result = await service.claim_task(task_id, payload.user_id)
    return result


@router.get("/distribution/stats", summary="分发统计")
async def get_distribution_stats(
    service: TMSService = Depends(get_tms_service),
):
    """获取分发统计信息"""
    return await service.get_distribution_stats()


# ========== Approval Routes ==========

@router.post("/approvals", summary="发起审批")
async def initiate_approval(
    payload: ApprovalFlowCreate,
    service: TMSService = Depends(get_tms_service),
):
    """发起审批流"""
    result = await service.initiate_approval(
        task_id=payload.task_id,
        flow_type=payload.flow_type,
        steps=payload.steps,
        initiated_by="api_user",
    )
    return result


@router.post("/approvals/{flow_id}/approve", summary="审批通过")
async def approve_task(
    flow_id: str,
    payload: ApprovalActionRequest,
    service: TMSService = Depends(get_tms_service),
):
    """审批通过"""
    result = await service.approve_task(
        flow_id=flow_id,
        approver_id=payload.approver_id,
        comment=payload.comment,
    )
    return result


@router.post("/approvals/{flow_id}/reject", summary="审批驳回")
async def reject_task(
    flow_id: str,
    payload: ApprovalActionRequest,
    service: TMSService = Depends(get_tms_service),
):
    """审批驳回"""
    result = await service.reject_task(
        flow_id=flow_id,
        approver_id=payload.approver_id,
        reason=payload.comment or "驳回",
    )
    return result


@router.post("/approvals/{flow_id}/delegate", summary="委托审批")
async def delegate_approval(
    flow_id: str,
    payload: ApprovalDelegateRequest,
    service: TMSService = Depends(get_tms_service),
):
    """委托审批"""
    result = await service.delegate_approval(flow_id, payload.from_user_id, payload.to_user_id)
    return result


@router.post("/approvals/{flow_id}/escalate", summary="升级审批")
async def escalate_approval(
    flow_id: str,
    payload: ApprovalEscalateRequest,
    service: TMSService = Depends(get_tms_service),
):
    """升级审批"""
    result = await service.escalate_approval(flow_id, payload.reason)
    return result


@router.get("/approvals/pending", summary="待审批列表")
async def get_pending_approvals(
    approver_id: str = Query(..., description="审批人ID"),
    service: TMSService = Depends(get_tms_service),
):
    """获取待审批列表"""
    result = await service.get_pending_approvals(approver_id)
    return {"items": result, "total": len(result)}


@router.get("/approvals/{flow_id}", summary="审批流状态")
async def get_approval_flow(
    flow_id: str,
    service: TMSService = Depends(get_tms_service),
):
    """获取审批流状态"""
    result = await service.get_approval_flow_status(flow_id)
    if not result:
        raise HTTPException(status_code=404, detail="审批流不存在")
    return result


# ========== Agent Routes (开放 API) ==========

@router.post("/agent/command", summary="Agent 命令入口")
async def agent_command(
    payload: AgentCommandRequest,
    service: TMSService = Depends(get_tms_service),
):
    """
    Agent/Chatbot 统一命令入口
    
    支持命令：
    - query_tasks: 查询任务
    - get_recommendation: 获取分发建议
    - assign_task: 分配任务
    - create_task: 创建任务
    - approve_task: 代审批（需确认）
    - reject_task: 驳回（需确认）
    - escalate_task: 升级审批
    - batch_distribute: 批量分发（需确认）
    """
    result = await service.execute_agent_command(
        agent_id=payload.agent_id,
        command=payload.command,
        params=payload.params,
        idempotency_key=payload.idempotency_key,
    )
    return result


@router.post("/agent/confirm", summary="确认 Agent 操作")
async def confirm_agent_action(
    payload: AgentConfirmRequest,
    service: TMSService = Depends(get_tms_service),
):
    """人工确认 Agent 高危操作"""
    result = await service.confirm_agent_action(
        action_id=payload.action_id,
        confirmed_by=payload.confirmed_by,
        approved=payload.approved,
    )
    return result


@router.post("/agent/register", summary="注册 Agent")
async def register_agent(
    payload: AgentRegisterRequest,
    service: TMSService = Depends(get_tms_service),
):
    """注册 Agent（设置权限等级）"""
    result = await service.register_agent(
        agent_id=payload.agent_id,
        permission_level=payload.permission_level,
        whitelisted=payload.whitelisted,
    )
    return result


@router.post("/agent/webhook", summary="注册 Webhook")
async def register_webhook(
    payload: WebhookRegisterRequest,
    service: TMSService = Depends(get_tms_service),
):
    """注册 Webhook 订阅（Agent 事件推送）"""
    result = await service.register_webhook(
        agent_id=payload.agent_id,
        event_types=payload.event_types,
        webhook_url=payload.webhook_url,
        secret=payload.secret,
    )
    return result


@router.get("/agent/context/{task_id}", summary="获取任务 Agent 上下文")
async def get_agent_context(
    task_id: str,
    service: TMSService = Depends(get_tms_service),
):
    """获取任务的 Agent 上下文（供 Chatbot 使用）"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task["id"],
        "task_code": task["task_code"],
        "title": task["title"],
        "description": task["description"],
        "status": task["status"],
        "priority": task["priority"],
        "required_skills": task["required_skills"],
        "candidate_pool": task["candidate_pool"],
        "agent_context": task["agent_context"],
        "metadata": task["metadata"],
    }


# ========== Dashboard Routes ==========

@router.get("/dashboard/stats", summary="仪表盘统计")
async def get_dashboard_stats(
    service: TMSService = Depends(get_tms_service),
):
    """获取 TMS 仪表盘统计数据"""
    return await service.get_dashboard_stats()


@router.get("/dashboard/recommended", summary="推荐任务")
async def get_recommended_tasks(
    user_id: str = Query(..., description="用户ID"),
    limit: int = Query(10, ge=1, le=50),
    service: TMSService = Depends(get_tms_service),
):
    """获取推荐任务（基于技能匹配）"""
    result = await service.get_recommended_tasks(user_id, limit)
    return {"items": result, "total": len(result)}
