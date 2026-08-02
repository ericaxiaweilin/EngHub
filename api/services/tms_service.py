"""
TMS Service - 应用服务层
协调核心模块，提供业务逻辑封装
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TMSTask, TMSApprovalFlow, TMSDistributionLog, User
from core.tms.distribution_engine import DistributionEngine, DistributionStrategy, DistributionMode
from core.tms.approval_workflow import ApprovalWorkflowEngine, FlowType
from core.tms.agent_interface import AgentInterface, AgentCommandRequest
from core.tms.events import tms_event_bus, TMSEventType

logger = logging.getLogger(__name__)


class TMSService:
    """TMS 应用服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.distribution_engine = DistributionEngine(db)
        self.approval_engine = ApprovalWorkflowEngine(db)
        self.agent_interface = AgentInterface(db)

    # ========== Task CRUD ==========

    async def create_task(
        self,
        title: str,
        task_type: str = "custom",
        description: Optional[str] = None,
        priority: str = "medium",
        points: int = 0,
        required_skills: Optional[List[str]] = None,
        required_roles: Optional[List[str]] = None,
        deadline: Optional[datetime] = None,
        distribution_strategy: Optional[str] = None,
        related_work_order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_by: str = "system",
        auto_distribute: bool = False,
    ) -> Dict[str, Any]:
        """创建任务"""
        task_code = f"TASK-{datetime.now().strftime('%Y')}-{str(uuid.uuid4())[:5].upper()}"

        task = TMSTask(
            id=str(uuid.uuid4()),
            task_code=task_code,
            title=title,
            description=description,
            task_type=task_type,
            source="manual" if created_by != "system" else "system",
            priority=priority,
            points=points,
            status="pending_distribution",
            distribution_strategy=distribution_strategy,
            required_skills=required_skills or [],
            required_roles=required_roles or [],
            deadline=deadline,
            related_work_order_id=related_work_order_id,
            metadata_=metadata or {},
            created_by=created_by,
        )

        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)

        # 发布事件
        await tms_event_bus.publish(
            TMSEventType.TASK_CREATED.value,
            {"task_id": str(task.id), "task_code": task_code, "task_type": task_type},
            source=created_by,
        )

        # 自动分发
        if auto_distribute and distribution_strategy:
            await self.distribution_engine.distribute(
                task, strategy=distribution_strategy, triggered_by=created_by
            )

        return self._task_to_dict(task)

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        return self._task_to_dict(task) if task else None

    async def get_task_by_code(self, task_code: str) -> Optional[Dict[str, Any]]:
        """根据任务编号获取"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.task_code == task_code))
        task = result.scalar_one_or_none()
        return self._task_to_dict(task) if task else None

    async def list_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """任务列表"""
        query = select(TMSTask)
        count_query = select(func.count(TMSTask.id))

        if status:
            query = query.where(TMSTask.status == status)
            count_query = count_query.where(TMSTask.status == status)
        if task_type:
            query = query.where(TMSTask.task_type == task_type)
            count_query = count_query.where(TMSTask.task_type == task_type)
        if priority:
            query = query.where(TMSTask.priority == priority)
            count_query = count_query.where(TMSTask.priority == priority)
        if assigned_to:
            query = query.where(TMSTask.assigned_to == assigned_to)
            count_query = count_query.where(TMSTask.assigned_to == assigned_to)

        total = (await self.db.execute(count_query)).scalar() or 0
        offset = (page - 1) * page_size
        query = query.order_by(TMSTask.created_at.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        tasks = result.scalars().all()

        return {
            "items": [self._task_to_dict(t) for t in tasks],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def update_task(self, task_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """更新任务"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return None

        allowed_fields = ["title", "description", "priority", "points", "required_skills", "deadline", "metadata_"]
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None:
                setattr(task, field, kwargs[field])

        task.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(task)
        return self._task_to_dict(task)

    # ========== Distribution ==========

    async def distribute_task(
        self,
        task_id: str,
        strategy: str = "skill_match",
        mode: str = "direct",
        target_user_id: Optional[str] = None,
        triggered_by: str = "system",
    ) -> Dict[str, Any]:
        """分发任务"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"success": False, "message": "任务不存在"}

        if task.status not in ["pending_distribution", "distributed"]:
            return {"success": False, "message": f"任务状态 {task.status} 不可分发"}

        dist_result = await self.distribution_engine.distribute(
            task, strategy=strategy, mode=mode, triggered_by=triggered_by, target_user_id=target_user_id
        )

        return {
            "success": dist_result.success,
            "message": dist_result.message,
            "task_id": dist_result.task_id,
            "strategy": dist_result.strategy,
            "mode": dist_result.mode,
            "assigned_to": dist_result.assigned_to,
            "assigned_to_name": dist_result.assigned_to_name,
            "candidate_pool": dist_result.candidate_pool,
            "candidate_scores": dist_result.candidate_scores,
        }

    async def claim_task(self, task_id: str, user_id: str) -> Dict[str, Any]:
        """认领任务"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"success": False, "message": "任务不存在"}

        claim_result = await self.distribution_engine.claim_task(task, user_id)
        return {"success": claim_result.success, "message": claim_result.message}

    async def get_distribution_stats(self) -> Dict[str, Any]:
        """获取分发统计"""
        return await self.distribution_engine.get_distribution_stats()

    # ========== Approval ==========

    async def initiate_approval(
        self,
        task_id: str,
        flow_type: str = "sequential",
        steps: Optional[List[Dict[str, Any]]] = None,
        initiated_by: str = "system",
    ) -> Dict[str, Any]:
        """发起审批"""
        result = await self.db.execute(select(TMSTask).where(TMSTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return {"success": False, "message": "任务不存在"}

        flow = await self.approval_engine.initiate_flow(
            task, flow_type=flow_type, steps=steps, initiated_by=initiated_by
        )

        return {
            "success": True,
            "message": "审批流已发起",
            "flow_id": str(flow.id),
            "flow_code": flow.flow_code,
            "total_steps": len(flow.steps),
        }

    async def approve_task(self, flow_id: str, approver_id: str, comment: Optional[str] = None, acted_by: Optional[str] = None) -> Dict[str, Any]:
        """审批通过"""
        result = await self.approval_engine.approve(flow_id, approver_id, comment, acted_by)
        return {
            "success": result.success,
            "message": result.message,
            "flow_status": result.flow_status,
            "current_step": result.current_step,
            "next_approver": result.next_approver,
        }

    async def reject_task(self, flow_id: str, approver_id: str, reason: str, acted_by: Optional[str] = None) -> Dict[str, Any]:
        """审批驳回"""
        result = await self.approval_engine.reject(flow_id, approver_id, reason, acted_by)
        return {"success": result.success, "message": result.message, "flow_status": result.flow_status}

    async def delegate_approval(self, flow_id: str, from_user_id: str, to_user_id: str) -> Dict[str, Any]:
        """委托审批"""
        result = await self.approval_engine.delegate(flow_id, from_user_id, to_user_id)
        return {"success": result.success, "message": result.message}

    async def escalate_approval(self, flow_id: str, reason: str, acted_by: Optional[str] = None) -> Dict[str, Any]:
        """升级审批"""
        result = await self.approval_engine.escalate(flow_id, reason, acted_by)
        return {"success": result.success, "message": result.message}

    async def get_pending_approvals(self, approver_id: str) -> List[Dict[str, Any]]:
        """获取待审批列表"""
        return await self.approval_engine.get_pending_approvals(approver_id)

    async def get_approval_flow_status(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """获取审批流状态"""
        return await self.approval_engine.get_flow_status(flow_id)

    # ========== Agent ==========

    async def execute_agent_command(
        self,
        agent_id: str,
        command: str,
        params: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行 Agent 命令"""
        request = AgentCommandRequest(
            agent_id=agent_id,
            command=command,
            params=params,
            idempotency_key=idempotency_key,
        )
        response = await self.agent_interface.execute_command(request)
        return {
            "success": response.success,
            "command": response.command,
            "data": response.data,
            "message": response.message,
            "requires_confirmation": response.requires_confirmation,
            "confirmation_id": response.confirmation_id,
            "action_id": response.action_id,
        }

    async def confirm_agent_action(self, action_id: str, confirmed_by: str, approved: bool = True) -> Dict[str, Any]:
        """确认 Agent 操作"""
        response = await self.agent_interface.confirm_action(action_id, confirmed_by, approved)
        return {
            "success": response.success,
            "message": response.message,
            "data": response.data,
        }

    async def register_agent(self, agent_id: str, permission_level: int = 1, whitelisted: bool = False) -> Dict[str, Any]:
        """注册 Agent"""
        self.agent_interface.register_agent(agent_id, permission_level, whitelisted)
        return {"success": True, "message": f"Agent {agent_id} 注册成功", "permission_level": permission_level}

    async def register_webhook(self, agent_id: str, event_types: List[str], webhook_url: str, secret: Optional[str] = None) -> Dict[str, Any]:
        """注册 Webhook"""
        return await self.agent_interface.register_webhook(agent_id, event_types, webhook_url, secret)

    # ========== Dashboard ==========

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        """获取仪表盘统计"""
        # 各状态任务数
        status_result = await self.db.execute(
            select(TMSTask.status, func.count(TMSTask.id)).group_by(TMSTask.status)
        )
        status_counts = {row[0]: row[1] for row in status_result.all()}

        # 本周积分
        week_start = datetime.utcnow() - timedelta(days=7)
        points_result = await self.db.execute(
            select(func.sum(TMSTask.points)).where(
                and_(
                    TMSTask.status == "completed",
                    TMSTask.updated_at >= week_start,
                )
            )
        )
        weekly_points = points_result.scalar() or 0

        # SLA 达标率（简化：按时完成率）
        total_completed = status_counts.get("completed", 0)
        on_time_result = await self.db.execute(
            select(func.count(TMSTask.id)).where(
                and_(
                    TMSTask.status == "completed",
                    TMSTask.deadline.isnot(None),
                    TMSTask.updated_at <= TMSTask.deadline,
                )
            )
        )
        on_time_count = on_time_result.scalar() or 0
        sla_rate = (on_time_count / total_completed * 100) if total_completed > 0 else 100.0

        return {
            "pending_distribution": status_counts.get("pending_distribution", 0),
            "distributed": status_counts.get("distributed", 0),
            "claimed": status_counts.get("claimed", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "pending_approval": status_counts.get("pending_approval", 0),
            "completed": status_counts.get("completed", 0),
            "rejected": status_counts.get("rejected", 0),
            "total": sum(status_counts.values()),
            "weekly_points": weekly_points,
            "sla_rate": round(sla_rate, 1),
        }

    async def get_recommended_tasks(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取推荐任务（基于技能匹配）"""
        # 获取用户技能
        from database.models import EmployeeSkill, Skill
        skill_result = await self.db.execute(
            select(Skill.code).join(EmployeeSkill, EmployeeSkill.skill_id == Skill.id)
            .where(cast(EmployeeSkill.user_id, String(36)) == str(user_id))
        )
        user_skills = {row[0] for row in skill_result.all()}

        # 获取待分发/已分发任务
        result = await self.db.execute(
            select(TMSTask).where(
                TMSTask.status.in_(["pending_distribution", "distributed"])
            ).order_by(TMSTask.priority.desc(), TMSTask.points.desc()).limit(limit * 2)
        )
        tasks = result.scalars().all()

        # 计算匹配度
        recommended = []
        for task in tasks:
            required = set(task.required_skills or [])
            if not required or required & user_skills:
                match_rate = len(required & user_skills) / len(required) if required else 0.7
                recommended.append({
                    **self._task_to_dict(task),
                    "match_rate": round(match_rate, 2),
                    "ai_recommendation": f"技能匹配度 {match_rate:.0%}" if required else "通用任务",
                })

        recommended.sort(key=lambda x: (-x.get("match_rate", 0), -x.get("points", 0)))
        return recommended[:limit]

    # ========== Helper ==========

    def _task_to_dict(self, task: TMSTask) -> Dict[str, Any]:
        """任务模型转字典"""
        return {
            "id": str(task.id),
            "task_code": task.task_code,
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "source": task.source,
            "priority": task.priority,
            "points": task.points,
            "status": task.status,
            "distribution_strategy": task.distribution_strategy,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "assigned_by": task.assigned_by,
            "candidate_pool": task.candidate_pool or [],
            "required_skills": task.required_skills or [],
            "required_roles": task.required_roles or [],
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "approval_flow_id": str(task.approval_flow_id) if task.approval_flow_id else None,
            "agent_context": task.agent_context or {},
            "metadata": task.metadata_ or {},
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
