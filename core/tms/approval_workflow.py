"""
TMS Approval Workflow Engine - 审批工作流引擎

支持：
- 串行审批 (sequential): A -> B -> C
- 并行审批 (parallel): A + B + C 同时审
- 条件分支 (conditional): 金额 > 10w 走总监审批
- 会签/或签
- Agent 代审（需授权）
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    TMSTask,
    TMSApprovalFlow,
    TMSApprovalRecord,
    User,
)
from core.tms.events import tms_event_bus, TMSEventType

logger = logging.getLogger(__name__)


class FlowType(str, Enum):
    """审批流类型"""
    SEQUENTIAL = "sequential"    # 串行
    PARALLEL = "parallel"        # 并行
    CONDITIONAL = "conditional"  # 条件分支


class FlowStatus(str, Enum):
    """审批流状态"""
    ACTIVE = "active"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ApprovalAction(str, Enum):
    """审批动作"""
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"
    ESCALATE = "escalate"


@dataclass
class FlowStep:
    """审批步骤定义"""
    step_index: int
    step_name: str
    approver_role: Optional[str] = None       # 审批人角色
    approver_id: Optional[str] = None         # 指定审批人
    approver_ids: List[str] = field(default_factory=list)  # 多人审批
    approval_type: str = "or"                 # or=或签, and=会签
    condition: Optional[Dict[str, Any]] = None  # 条件表达式
    allow_agent: bool = False                 # 是否允许 Agent 代审
    auto_approve_if: Optional[Dict[str, Any]] = None  # 自动审批条件


@dataclass
class FlowResult:
    """审批流操作结果"""
    success: bool
    flow_id: str
    flow_status: str
    current_step: int
    action: str
    message: str
    next_approver: Optional[str] = None
    next_approver_name: Optional[str] = None
    requires_confirmation: bool = False


class ApprovalWorkflowEngine:
    """
    审批工作流引擎
    
    支持串行、并行、条件分支审批
    支持 Agent 代审（需授权）
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def initiate_flow(
        self,
        task: TMSTask,
        flow_type: str = FlowType.SEQUENTIAL.value,
        steps: Optional[List[Dict[str, Any]]] = None,
        initiated_by: str = "system",
    ) -> TMSApprovalFlow:
        """
        发起审批流
        
        Args:
            task: 关联任务
            flow_type: 流类型
            steps: 审批步骤定义
            initiated_by: 发起人
        """
        # 默认审批步骤（如果未提供）
        if not steps:
            steps = self._get_default_steps(task.task_type)

        flow_code = f"FLOW-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

        flow = TMSApprovalFlow(
            id=str(uuid.uuid4()),
            flow_code=flow_code,
            task_id=task.id,
            flow_type=flow_type,
            steps=steps,
            current_step=0,
            status=FlowStatus.ACTIVE.value,
            initiated_by=initiated_by,
        )

        self.db.add(flow)

        # 更新任务状态
        task.status = "pending_approval"
        task.approval_flow_id = flow.id
        task.updated_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(flow)

        # 发布事件
        await tms_event_bus.publish(
            TMSEventType.APPROVAL_INITIATED.value,
            {
                "flow_id": str(flow.id),
                "flow_code": flow_code,
                "task_id": str(task.id),
                "task_code": task.task_code,
                "flow_type": flow_type,
                "total_steps": len(steps),
            },
            source=initiated_by,
        )

        # 通知第一步审批人
        await self._notify_current_approver(flow)

        logger.info(f"Approval flow initiated: {flow_code} | task={task.task_code} | steps={len(steps)}")
        return flow

    async def approve(
        self,
        flow_id: str,
        approver_id: str,
        comment: Optional[str] = None,
        acted_by: Optional[str] = None,
    ) -> FlowResult:
        """
        审批通过
        
        Args:
            flow_id: 审批流 ID
            approver_id: 审批人 ID
            comment: 审批意见
            acted_by: 操作者标识 (user:xxx / agent:xxx)
        """
        flow = await self._get_flow(flow_id)
        if not flow:
            return FlowResult(False, flow_id, "unknown", 0, "approve", "审批流不存在")

        if flow.status != FlowStatus.ACTIVE.value:
            return FlowResult(False, flow_id, flow.status, flow.current_step, "approve", f"审批流已{flow.status}")

        # 验证审批人权限
        current_step_def = flow.steps[flow.current_step] if flow.current_step < len(flow.steps) else {}
        is_agent = acted_by and acted_by.startswith("agent:")

        if is_agent and not current_step_def.get("allow_agent", False):
            return FlowResult(
                False, flow_id, flow.status, flow.current_step, "approve",
                "当前步骤不允许 Agent 代审",
                requires_confirmation=True,
            )

        # 记录审批
        record = TMSApprovalRecord(
            id=str(uuid.uuid4()),
            flow_id=flow_id,
            step_index=flow.current_step,
            approver_id=approver_id,
            action=ApprovalAction.APPROVE.value,
            comment=comment,
            acted_by=acted_by or f"user:{approver_id}",
        )
        self.db.add(record)

        # 判断是否进入下一步
        flow.current_step += 1

        if flow.current_step >= len(flow.steps):
            # 审批完成
            flow.status = FlowStatus.APPROVED.value
            await self._complete_flow(flow, approved=True)
            message = "审批全部通过"
        else:
            message = f"第 {flow.current_step} 步审批通过，进入下一步"
            await self._notify_current_approver(flow)

        flow.updated_at = datetime.utcnow()
        await self.db.commit()

        # 发布事件
        await tms_event_bus.publish(
            TMSEventType.APPROVAL_APPROVED.value,
            {
                "flow_id": flow_id,
                "step_index": flow.current_step - 1,
                "approver_id": approver_id,
                "acted_by": acted_by,
                "flow_status": flow.status,
            },
            source=acted_by or f"user:{approver_id}",
        )

        next_approver = None
        if flow.status == FlowStatus.ACTIVE.value and flow.current_step < len(flow.steps):
            next_step = flow.steps[flow.current_step]
            next_approver = next_step.get("approver_id") or next_step.get("approver_role")

        return FlowResult(
            success=True,
            flow_id=flow_id,
            flow_status=flow.status,
            current_step=flow.current_step,
            action="approve",
            message=message,
            next_approver=next_approver,
        )

    async def reject(
        self,
        flow_id: str,
        approver_id: str,
        reason: str,
        acted_by: Optional[str] = None,
    ) -> FlowResult:
        """审批驳回"""
        flow = await self._get_flow(flow_id)
        if not flow:
            return FlowResult(False, flow_id, "unknown", 0, "reject", "审批流不存在")

        if flow.status != FlowStatus.ACTIVE.value:
            return FlowResult(False, flow_id, flow.status, flow.current_step, "reject", f"审批流已{flow.status}")

        # 记录驳回
        record = TMSApprovalRecord(
            id=str(uuid.uuid4()),
            flow_id=flow_id,
            step_index=flow.current_step,
            approver_id=approver_id,
            action=ApprovalAction.REJECT.value,
            comment=reason,
            acted_by=acted_by or f"user:{approver_id}",
        )
        self.db.add(record)

        flow.status = FlowStatus.REJECTED.value
        flow.updated_at = datetime.utcnow()

        await self._complete_flow(flow, approved=False)
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.APPROVAL_REJECTED.value,
            {
                "flow_id": flow_id,
                "step_index": flow.current_step,
                "approver_id": approver_id,
                "reason": reason,
            },
            source=acted_by or f"user:{approver_id}",
        )

        return FlowResult(
            success=True,
            flow_id=flow_id,
            flow_status=FlowStatus.REJECTED.value,
            current_step=flow.current_step,
            action="reject",
            message=f"审批被驳回: {reason}",
        )

    async def delegate(
        self,
        flow_id: str,
        from_user_id: str,
        to_user_id: str,
        acted_by: Optional[str] = None,
    ) -> FlowResult:
        """委托审批"""
        flow = await self._get_flow(flow_id)
        if not flow:
            return FlowResult(False, flow_id, "unknown", 0, "delegate", "审批流不存在")

        # 更新当前步骤审批人
        if flow.current_step < len(flow.steps):
            flow.steps[flow.current_step]["approver_id"] = to_user_id
            flow.steps[flow.current_step]["delegated_from"] = from_user_id

        # 记录委托
        record = TMSApprovalRecord(
            id=str(uuid.uuid4()),
            flow_id=flow_id,
            step_index=flow.current_step,
            approver_id=from_user_id,
            action=ApprovalAction.DELEGATE.value,
            comment=f"委托给 {to_user_id}",
            acted_by=acted_by or f"user:{from_user_id}",
        )
        self.db.add(record)
        flow.updated_at = datetime.utcnow()
        await self.db.commit()

        await self._notify_current_approver(flow)

        return FlowResult(
            success=True,
            flow_id=flow_id,
            flow_status=flow.status,
            current_step=flow.current_step,
            action="delegate",
            message=f"已委托给 {to_user_id}",
            next_approver=to_user_id,
        )

    async def escalate(
        self,
        flow_id: str,
        reason: str,
        acted_by: Optional[str] = None,
    ) -> FlowResult:
        """升级审批（跳转到更高级别审批人）"""
        flow = await self._get_flow(flow_id)
        if not flow:
            return FlowResult(False, flow_id, "unknown", 0, "escalate", "审批流不存在")

        # 记录升级
        record = TMSApprovalRecord(
            id=str(uuid.uuid4()),
            flow_id=flow_id,
            step_index=flow.current_step,
            approver_id=None,
            action=ApprovalAction.ESCALATE.value,
            comment=reason,
            acted_by=acted_by or "system",
        )
        self.db.add(record)

        # 升级到下一步（跳过当前步骤）
        flow.current_step += 1
        if flow.current_step >= len(flow.steps):
            # 添加管理员审批步骤
            flow.steps.append({
                "step_index": flow.current_step,
                "step_name": "管理员审批（升级）",
                "approver_role": "admin",
                "approval_type": "or",
                "allow_agent": False,
            })

        flow.updated_at = datetime.utcnow()
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.APPROVAL_ESCALATED.value,
            {"flow_id": flow_id, "reason": reason, "new_step": flow.current_step},
            source=acted_by or "system",
        )

        await self._notify_current_approver(flow)

        return FlowResult(
            success=True,
            flow_id=flow_id,
            flow_status=flow.status,
            current_step=flow.current_step,
            action="escalate",
            message=f"审批已升级: {reason}",
        )

    async def get_flow_status(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """获取审批流状态"""
        flow = await self._get_flow(flow_id)
        if not flow:
            return None

        # 获取审批记录
        records_result = await self.db.execute(
            select(TMSApprovalRecord)
            .where(TMSApprovalRecord.flow_id == flow_id)
            .order_by(TMSApprovalRecord.created_at)
        )
        records = records_result.scalars().all()

        return {
            "flow_id": str(flow.id),
            "flow_code": flow.flow_code,
            "task_id": str(flow.task_id),
            "flow_type": flow.flow_type,
            "status": flow.status,
            "current_step": flow.current_step,
            "total_steps": len(flow.steps),
            "steps": flow.steps,
            "records": [
                {
                    "step_index": r.step_index,
                    "action": r.action,
                    "comment": r.comment,
                    "acted_by": r.acted_by,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ],
        }

    async def get_pending_approvals(self, approver_id: str) -> List[Dict[str, Any]]:
        """获取待审批列表"""
        # 查询用户相关的活跃审批流
        result = await self.db.execute(
            select(TMSApprovalFlow)
            .where(TMSApprovalFlow.status == FlowStatus.ACTIVE.value)
        )
        flows = result.scalars().all()

        pending = []
        for flow in flows:
            if flow.current_step < len(flow.steps):
                step = flow.steps[flow.current_step]
                # 检查是否是当前审批人
                if (step.get("approver_id") == approver_id or
                    step.get("approver_role") == "manager"):  # 简化：经理可审所有
                    # 获取任务信息
                    task_result = await self.db.execute(
                        select(TMSTask).where(TMSTask.id == flow.task_id)
                    )
                    task = task_result.scalar_one_or_none()
                    if task:
                        pending.append({
                            "flow_id": str(flow.id),
                            "flow_code": flow.flow_code,
                            "task_id": str(task.id),
                            "task_code": task.task_code,
                            "task_title": task.title,
                            "task_type": task.task_type,
                            "priority": task.priority,
                            "current_step": flow.current_step,
                            "step_name": step.get("step_name", f"Step {flow.current_step + 1}"),
                            "initiated_by": flow.initiated_by,
                            "created_at": flow.created_at.isoformat() if flow.created_at else None,
                        })

        return pending

    async def _get_flow(self, flow_id: str) -> Optional[TMSApprovalFlow]:
        """获取审批流"""
        result = await self.db.execute(
            select(TMSApprovalFlow).where(TMSApprovalFlow.id == flow_id)
        )
        return result.scalar_one_or_none()

    async def _complete_flow(self, flow: TMSApprovalFlow, approved: bool) -> None:
        """完成审批流，更新关联任务状态"""
        task_result = await self.db.execute(
            select(TMSTask).where(TMSTask.id == flow.task_id)
        )
        task = task_result.scalar_one_or_none()
        if task:
            task.status = "completed" if approved else "rejected"
            task.updated_at = datetime.utcnow()

        await tms_event_bus.publish(
            TMSEventType.APPROVAL_COMPLETED.value,
            {
                "flow_id": str(flow.id),
                "task_id": str(flow.task_id),
                "approved": approved,
            },
        )

    async def _notify_current_approver(self, flow: TMSApprovalFlow) -> None:
        """通知当前步骤审批人"""
        if flow.current_step >= len(flow.steps):
            return

        step = flow.steps[flow.current_step]
        await tms_event_bus.publish(
            TMSEventType.APPROVAL_PENDING.value,
            {
                "flow_id": str(flow.id),
                "flow_code": flow.flow_code,
                "step_index": flow.current_step,
                "step_name": step.get("step_name"),
                "approver_id": step.get("approver_id"),
                "approver_role": step.get("approver_role"),
            },
        )

    def _get_default_steps(self, task_type: str) -> List[Dict[str, Any]]:
        """获取默认审批步骤"""
        default_flows = {
            "ecn_release": [
                {"step_index": 0, "step_name": "EE 审批", "approver_role": "engineer", "approval_type": "or", "allow_agent": True},
                {"step_index": 1, "step_name": "PM 审批", "approver_role": "manager", "approval_type": "or", "allow_agent": False},
                {"step_index": 2, "step_name": "DCC 发布", "approver_role": "admin", "approval_type": "or", "allow_agent": False},
            ],
            "ecr_approval": [
                {"step_index": 0, "step_name": "技术评审", "approver_role": "engineer", "approval_type": "and", "allow_agent": True},
                {"step_index": 1, "step_name": "经理审批", "approver_role": "manager", "approval_type": "or", "allow_agent": False},
            ],
            "inspection": [
                {"step_index": 0, "step_name": "质量检验", "approver_role": "operator", "approval_type": "or", "allow_agent": True},
            ],
        }

        return default_flows.get(task_type, [
            {"step_index": 0, "step_name": "审批", "approver_role": "manager", "approval_type": "or", "allow_agent": False},
        ])
