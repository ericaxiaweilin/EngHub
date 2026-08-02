"""
TMS Agent Interface - Agent/Chatbot 命令接口层

开放 API 让 Chatbot/Agent 接入，支持命令级操作：
- 查询任务
- 分配/重新分配任务
- 代审批（需授权）
- 升级审批
- 创建任务
- 批量分发
- 获取 AI 分发建议

安全控制：
- Agent 权限分级 (LEVEL_1/2/3)
- 高危操作需人工确认
- 幂等性保证
- 全量审计日志
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    TMSTask,
    TMSAgentAction,
    TMSWebhookSubscription,
    User,
)
from core.tms.events import tms_event_bus, TMSEventType
from core.tms.distribution_engine import DistributionEngine, DistributionStrategy
from core.tms.approval_workflow import ApprovalWorkflowEngine

logger = logging.getLogger(__name__)


class AgentPermissionLevel(int, Enum):
    """Agent 权限等级"""
    LEVEL_1 = 1  # 只读
    LEVEL_2 = 2  # 写入
    LEVEL_3 = 3  # 高危操作


class AgentCommand(str, Enum):
    """Agent 支持的命令集"""
    # LEVEL_1 - 只读
    QUERY_TASKS = "query_tasks"
    GET_RECOMMENDATION = "get_recommendation"
    GET_TASK_CONTEXT = "get_task_context"
    GET_STATS = "get_stats"

    # LEVEL_2 - 写入
    ASSIGN_TASK = "assign_task"
    CREATE_TASK = "create_task"
    SET_DEADLINE = "set_deadline"
    CLAIM_TASK = "claim_task"

    # LEVEL_3 - 高危（需确认或白名单）
    REASSIGN_TASK = "reassign_task"
    APPROVE_TASK = "approve_task"
    REJECT_TASK = "reject_task"
    ESCALATE_TASK = "escalate_task"
    BATCH_DISTRIBUTE = "batch_distribute"


# 命令权限映射
COMMAND_PERMISSIONS = {
    AgentCommand.QUERY_TASKS: AgentPermissionLevel.LEVEL_1,
    AgentCommand.GET_RECOMMENDATION: AgentPermissionLevel.LEVEL_1,
    AgentCommand.GET_TASK_CONTEXT: AgentPermissionLevel.LEVEL_1,
    AgentCommand.GET_STATS: AgentPermissionLevel.LEVEL_1,
    AgentCommand.ASSIGN_TASK: AgentPermissionLevel.LEVEL_2,
    AgentCommand.CREATE_TASK: AgentPermissionLevel.LEVEL_2,
    AgentCommand.SET_DEADLINE: AgentPermissionLevel.LEVEL_2,
    AgentCommand.CLAIM_TASK: AgentPermissionLevel.LEVEL_2,
    AgentCommand.REASSIGN_TASK: AgentPermissionLevel.LEVEL_3,
    AgentCommand.APPROVE_TASK: AgentPermissionLevel.LEVEL_3,
    AgentCommand.REJECT_TASK: AgentPermissionLevel.LEVEL_3,
    AgentCommand.ESCALATE_TASK: AgentPermissionLevel.LEVEL_3,
    AgentCommand.BATCH_DISTRIBUTE: AgentPermissionLevel.LEVEL_3,
}

# 需要人工确认的命令
REQUIRES_CONFIRMATION = {
    AgentCommand.REASSIGN_TASK,
    AgentCommand.APPROVE_TASK,
    AgentCommand.REJECT_TASK,
    AgentCommand.BATCH_DISTRIBUTE,
}


@dataclass
class AgentCommandRequest:
    """Agent 命令请求"""
    agent_id: str
    command: str
    params: Dict[str, Any]
    idempotency_key: Optional[str] = None
    permission_level: int = 1


@dataclass
class AgentCommandResponse:
    """Agent 命令响应"""
    success: bool
    command: str
    data: Dict[str, Any]
    message: str
    requires_confirmation: bool = False
    confirmation_id: Optional[str] = None
    action_id: Optional[str] = None


class AgentInterface:
    """
    Agent/Chatbot 命令接口
    
    所有 Agent 操作通过此接口执行，确保：
    1. 权限验证
    2. 幂等性检查
    3. 全量审计
    4. 高危操作确认
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.distribution_engine = DistributionEngine(db)
        self.approval_engine = ApprovalWorkflowEngine(db)
        # Agent 权限配置（生产环境应从数据库/配置中心读取）
        self._agent_permissions: Dict[str, int] = {}
        # Agent 白名单（可执行高危操作无需确认）
        self._agent_whitelist: set = set()

    def register_agent(self, agent_id: str, permission_level: int = 1, whitelisted: bool = False) -> None:
        """注册 Agent"""
        self._agent_permissions[agent_id] = permission_level
        if whitelisted:
            self._agent_whitelist.add(agent_id)
        logger.info(f"Agent registered: {agent_id} | level={permission_level} | whitelisted={whitelisted}")

    def get_agent_permission(self, agent_id: str) -> int:
        """获取 Agent 权限等级"""
        return self._agent_permissions.get(agent_id, 1)

    async def execute_command(self, request: AgentCommandRequest) -> AgentCommandResponse:
        """
        执行 Agent 命令（统一入口）
        
        流程：
        1. 幂等性检查
        2. 权限验证
        3. 执行命令
        4. 记录审计日志
        5. 发布事件
        """
        command = request.command
        agent_id = request.agent_id

        logger.info(f"Agent command received: {agent_id} -> {command}")

        # 1. 幂等性检查
        if request.idempotency_key:
            existing = await self._check_idempotency(request.idempotency_key)
            if existing:
                return AgentCommandResponse(
                    success=True,
                    command=command,
                    data=existing.result or {},
                    message="命令已执行（幂等返回）",
                    action_id=str(existing.id),
                )

        # 2. 权限验证
        required_level = COMMAND_PERMISSIONS.get(AgentCommand(command), AgentPermissionLevel.LEVEL_3)
        agent_level = self.get_agent_permission(agent_id)

        if agent_level < required_level.value:
            await self._log_action(
                agent_id=agent_id,
                action_type=command,
                payload=request.params,
                result={"error": "permission_denied"},
                status="failed",
                idempotency_key=request.idempotency_key,
            )
            return AgentCommandResponse(
                success=False,
                command=command,
                data={},
                message=f"权限不足: 需要 LEVEL_{required_level.value}，当前 LEVEL_{agent_level}",
            )

        # 3. 高危操作确认检查
        needs_confirmation = (
            AgentCommand(command) in REQUIRES_CONFIRMATION
            and agent_id not in self._agent_whitelist
        )

        if needs_confirmation:
            # 创建待确认操作
            action = await self._log_action(
                agent_id=agent_id,
                action_type=command,
                target_task_id=request.params.get("task_id"),
                payload=request.params,
                result={},
                status="pending_confirmation",
                requires_confirmation=True,
                idempotency_key=request.idempotency_key,
            )

            await tms_event_bus.publish(
                TMSEventType.AGENT_CONFIRMATION_REQUIRED.value,
                {
                    "action_id": str(action.id),
                    "agent_id": agent_id,
                    "command": command,
                    "params": request.params,
                },
                source=f"agent:{agent_id}",
            )

            return AgentCommandResponse(
                success=True,
                command=command,
                data={"pending": True},
                message="操作需要人工确认",
                requires_confirmation=True,
                confirmation_id=str(action.id),
                action_id=str(action.id),
            )

        # 4. 执行命令
        try:
            result = await self._dispatch_command(command, request.params, agent_id)
            
            # 记录成功日志
            action = await self._log_action(
                agent_id=agent_id,
                action_type=command,
                target_task_id=request.params.get("task_id"),
                payload=request.params,
                result=result,
                status="success",
                idempotency_key=request.idempotency_key,
            )

            await tms_event_bus.publish(
                TMSEventType.AGENT_ACTION_COMPLETED.value,
                {"agent_id": agent_id, "command": command, "result": result},
                source=f"agent:{agent_id}",
            )

            return AgentCommandResponse(
                success=True,
                command=command,
                data=result,
                message=result.get("message", "命令执行成功"),
                action_id=str(action.id),
            )

        except Exception as e:
            logger.error(f"Agent command failed: {agent_id} -> {command}: {e}")
            await self._log_action(
                agent_id=agent_id,
                action_type=command,
                payload=request.params,
                result={"error": str(e)},
                status="failed",
                idempotency_key=request.idempotency_key,
            )
            return AgentCommandResponse(
                success=False,
                command=command,
                data={"error": str(e)},
                message=f"命令执行失败: {str(e)}",
            )

    async def confirm_action(self, action_id: str, confirmed_by: str, approved: bool = True) -> AgentCommandResponse:
        """人工确认 Agent 高危操作"""
        result = await self.db.execute(
            select(TMSAgentAction).where(TMSAgentAction.id == action_id)
        )
        action = result.scalar_one_or_none()

        if not action:
            return AgentCommandResponse(False, "confirm", {}, "操作不存在")

        if action.status != "pending_confirmation":
            return AgentCommandResponse(False, "confirm", {}, f"操作状态异常: {action.status}")

        if not approved:
            action.status = "failed"
            action.result = {"rejected_by": confirmed_by, "reason": "人工拒绝"}
            await self.db.commit()
            return AgentCommandResponse(True, "confirm", {"rejected": True}, "操作已被拒绝")

        # 执行原命令
        request = AgentCommandRequest(
            agent_id=action.agent_id,
            command=action.action_type,
            params=action.payload or {},
        )

        # 临时加入白名单执行
        self._agent_whitelist.add(action.agent_id)
        try:
            result_data = await self._dispatch_command(action.action_type, action.payload or {}, action.agent_id)
            action.status = "success"
            action.result = result_data
            action.requires_confirmation = False
            await self.db.commit()

            return AgentCommandResponse(
                True, action.action_type, result_data,
                f"操作已确认执行: {result_data.get('message', '成功')}",
                action_id=str(action.id),
            )
        finally:
            self._agent_whitelist.discard(action.agent_id)

    async def _dispatch_command(self, command: str, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """命令分发执行"""
        handlers = {
            AgentCommand.QUERY_TASKS.value: self._cmd_query_tasks,
            AgentCommand.GET_RECOMMENDATION.value: self._cmd_get_recommendation,
            AgentCommand.GET_TASK_CONTEXT.value: self._cmd_get_task_context,
            AgentCommand.GET_STATS.value: self._cmd_get_stats,
            AgentCommand.ASSIGN_TASK.value: self._cmd_assign_task,
            AgentCommand.CREATE_TASK.value: self._cmd_create_task,
            AgentCommand.SET_DEADLINE.value: self._cmd_set_deadline,
            AgentCommand.CLAIM_TASK.value: self._cmd_claim_task,
            AgentCommand.REASSIGN_TASK.value: self._cmd_reassign_task,
            AgentCommand.APPROVE_TASK.value: self._cmd_approve_task,
            AgentCommand.REJECT_TASK.value: self._cmd_reject_task,
            AgentCommand.ESCALATE_TASK.value: self._cmd_escalate_task,
            AgentCommand.BATCH_DISTRIBUTE.value: self._cmd_batch_distribute,
        }

        handler = handlers.get(command)
        if not handler:
            raise ValueError(f"未知命令: {command}")

        return await handler(params, agent_id)

    # ========== LEVEL 1 命令实现 ==========

    async def _cmd_query_tasks(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """查询任务列表"""
        status = params.get("status")
        task_type = params.get("task_type")
        assigned_to = params.get("assigned_to")
        limit = params.get("limit", 20)

        query = select(TMSTask)
        if status:
            query = query.where(TMSTask.status == status)
        if task_type:
            query = query.where(TMSTask.task_type == task_type)
        if assigned_to:
            query = query.where(TMSTask.assigned_to == assigned_to)

        query = query.order_by(TMSTask.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        tasks = result.scalars().all()

        return {
            "message": f"查询到 {len(tasks)} 个任务",
            "tasks": [
                {
                    "task_id": str(t.id),
                    "task_code": t.task_code,
                    "title": t.title,
                    "task_type": t.task_type,
                    "status": t.status,
                    "priority": t.priority,
                    "assigned_to": str(t.assigned_to) if t.assigned_to else None,
                    "deadline": t.deadline.isoformat() if t.deadline else None,
                }
                for t in tasks
            ],
            "count": len(tasks),
        }

    async def _cmd_get_recommendation(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """获取 AI 分发建议"""
        task_id = params.get("task_id")
        if not task_id:
            return {"message": "请提供 task_id", "recommendations": []}

        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"message": "任务不存在", "recommendations": []}

        # 使用分发引擎计算候选人评分
        candidates = await self.distribution_engine._get_candidates(task)
        scored = await self.distribution_engine._score_by_skill(task, candidates)
        scored.sort(key=lambda c: c.total_score, reverse=True)

        recommendations = [
            {
                "user_id": c.user_id,
                "username": c.username,
                "full_name": c.full_name,
                "score": round(c.total_score, 3),
                "reasons": c.reasons,
            }
            for c in scored[:5]
        ]

        return {
            "message": f"为任务 {task.task_code} 推荐 {len(recommendations)} 名候选人",
            "task_code": task.task_code,
            "recommendations": recommendations,
            "suggested_strategy": "skill_match",
        }

    async def _cmd_get_task_context(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """获取任务上下文（Agent 专用）"""
        task_id = params.get("task_id")
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"message": "任务不存在"}

        return {
            "task_id": str(task.id),
            "task_code": task.task_code,
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "required_skills": task.required_skills,
            "required_roles": task.required_roles,
            "candidate_pool": task.candidate_pool,
            "agent_context": task.agent_context,
            "metadata": task.metadata_,
            "deadline": task.deadline.isoformat() if task.deadline else None,
        }

    async def _cmd_get_stats(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """获取统计数据"""
        stats = await self.distribution_engine.get_distribution_stats()
        return {"message": "统计信息", **stats}

    # ========== LEVEL 2 命令实现 ==========

    async def _cmd_assign_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """分配任务"""
        task_code = params.get("task_code")
        task_id = params.get("task_id")
        assign_to = params.get("assign_to")
        reason = params.get("reason", "Agent 分配")

        task = await self._get_task(task_id=task_id, task_code=task_code)
        if not task:
            return {"message": "任务不存在"}

        # 解析 assign_to (支持 "user:xxx" 格式)
        user_id = assign_to.replace("user:", "") if assign_to.startswith("user:") else assign_to

        result = await self.distribution_engine._manual_distribute(
            task, user_id, f"agent:{agent_id}"
        )

        return {
            "message": result.message,
            "task_code": task.task_code,
            "assigned_to": result.assigned_to,
            "assigned_to_name": result.assigned_to_name,
        }

    async def _cmd_create_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """创建任务"""
        task_code = f"TASK-{datetime.now().strftime('%Y')}-{str(uuid.uuid4())[:5].upper()}"

        task = TMSTask(
            id=str(uuid.uuid4()),
            task_code=task_code,
            title=params.get("title", "Agent 创建的任务"),
            description=params.get("description"),
            task_type=params.get("task_type", "custom"),
            source="agent",
            priority=params.get("priority", "medium"),
            points=params.get("points", 0),
            status="pending_distribution",
            required_skills=params.get("required_skills", []),
            required_roles=params.get("required_roles", []),
            agent_context={"created_by_agent": agent_id},
            created_by=f"agent:{agent_id}",
        )

        self.db.add(task)
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.TASK_CREATED.value,
            {"task_id": str(task.id), "task_code": task_code, "source": "agent"},
            source=f"agent:{agent_id}",
        )

        return {
            "message": f"任务创建成功: {task_code}",
            "task_id": str(task.id),
            "task_code": task_code,
        }

    async def _cmd_set_deadline(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """设置截止日期"""
        task_id = params.get("task_id")
        deadline = params.get("deadline")

        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"message": "任务不存在"}

        task.deadline = datetime.fromisoformat(deadline) if isinstance(deadline, str) else deadline
        task.updated_at = datetime.utcnow()
        await self.db.commit()

        return {"message": f"截止日期已更新: {deadline}", "task_code": task.task_code}

    async def _cmd_claim_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """认领任务"""
        task_id = params.get("task_id")
        user_id = params.get("user_id")

        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"message": "任务不存在"}

        claim_result = await self.distribution_engine.claim_task(task, user_id)
        return {"message": claim_result.message, "success": claim_result.success}

    # ========== LEVEL 3 命令实现 ==========

    async def _cmd_reassign_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """重新分配任务"""
        task_id = params.get("task_id")
        new_assignee = params.get("new_assignee")
        reason = params.get("reason", "Agent 重新分配")

        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"message": "任务不存在"}

        old_assignee = str(task.assigned_to) if task.assigned_to else None
        user_id = new_assignee.replace("user:", "") if new_assignee.startswith("user:") else new_assignee

        task.assigned_to = user_id
        task.assigned_by = f"agent:{agent_id}"
        task.status = "distributed"
        task.updated_at = datetime.utcnow()
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.TASK_REASSIGNED.value,
            {"task_id": task_id, "old_assignee": old_assignee, "new_assignee": user_id},
            source=f"agent:{agent_id}",
        )

        return {"message": f"任务已重新分配给 {user_id}", "task_code": task.task_code}

    async def _cmd_approve_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """代审批通过"""
        flow_id = params.get("flow_id")
        approver_id = params.get("approver_id")
        comment = params.get("comment", "Agent 代审通过")

        result = await self.approval_engine.approve(
            flow_id=flow_id,
            approver_id=approver_id,
            comment=comment,
            acted_by=f"agent:{agent_id}",
        )

        return {"message": result.message, "flow_status": result.flow_status, "success": result.success}

    async def _cmd_reject_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """代审批驳回"""
        flow_id = params.get("flow_id")
        approver_id = params.get("approver_id")
        reason = params.get("reason", "Agent 代审驳回")

        result = await self.approval_engine.reject(
            flow_id=flow_id,
            approver_id=approver_id,
            reason=reason,
            acted_by=f"agent:{agent_id}",
        )

        return {"message": result.message, "flow_status": result.flow_status, "success": result.success}

    async def _cmd_escalate_task(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """升级审批"""
        flow_id = params.get("flow_id")
        reason = params.get("reason", "Agent 升级审批")

        result = await self.approval_engine.escalate(
            flow_id=flow_id,
            reason=reason,
            acted_by=f"agent:{agent_id}",
        )

        return {"message": result.message, "success": result.success}

    async def _cmd_batch_distribute(self, params: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        """批量分发"""
        task_ids = params.get("task_ids", [])
        strategy = params.get("strategy", "skill_match")

        results = []
        for task_id in task_ids:
            result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
            task = result.scalar_one_or_none()
            if task and task.status == "pending_distribution":
                dist_result = await self.distribution_engine.distribute(
                    task, strategy=strategy, triggered_by=f"agent:{agent_id}"
                )
                results.append({"task_code": task.task_code, "success": dist_result.success})

        return {
            "message": f"批量分发完成: {len([r for r in results if r['success']])}/{len(task_ids)} 成功",
            "results": results,
        }

    # ========== 辅助方法 ==========

    async def _get_task(self, task_id: Optional[str] = None, task_code: Optional[str] = None) -> Optional[TMSTask]:
        """获取任务"""
        if task_id:
            result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        elif task_code:
            result = await self.db.execute(select(TMSTask).where(TMSTask.task_code == task_code))
        else:
            return None
        return result.scalar_one_or_none()

    async def _check_idempotency(self, key: str) -> Optional[TMSAgentAction]:
        """幂等性检查"""
        result = await self.db.execute(
            select(TMSAgentAction).where(TMSAgentAction.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def _log_action(
        self,
        agent_id: str,
        action_type: str,
        payload: Dict[str, Any],
        result: Dict[str, Any],
        status: str = "success",
        target_task_id: Optional[str] = None,
        requires_confirmation: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> TMSAgentAction:
        """记录 Agent 操作日志"""
        action = TMSAgentAction(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            action_type=action_type,
            target_task_id=target_task_id,
            payload=payload,
            result=result,
            status=status,
            requires_confirmation=requires_confirmation,
            idempotency_key=idempotency_key,
        )
        self.db.add(action)
        await self.db.commit()
        await self.db.refresh(action)
        return action

    # ========== Webhook 管理 ==========

    async def register_webhook(
        self,
        agent_id: str,
        event_types: List[str],
        webhook_url: str,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """注册 Webhook"""
        subscription = TMSWebhookSubscription(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            event_types=event_types,
            webhook_url=webhook_url,
            secret=secret,
        )
        self.db.add(subscription)
        await self.db.commit()

        # 同时注册到事件总线
        tms_event_bus.register_webhook(agent_id, event_types, webhook_url, secret)

        return {"message": "Webhook 注册成功", "subscription_id": str(subscription.id)}

    async def unregister_webhook(self, agent_id: str) -> Dict[str, Any]:
        """注销 Webhook"""
        result = await self.db.execute(
            select(TMSWebhookSubscription).where(TMSWebhookSubscription.agent_id == agent_id)
        )
        subscriptions = result.scalars().all()
        for sub in subscriptions:
            await self.db.delete(sub)
        await self.db.commit()

        tms_event_bus.unregister_webhook(agent_id)
        return {"message": f"已注销 {len(subscriptions)} 个 Webhook 订阅"}
