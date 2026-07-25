

"""
v2.6 - RCC Service Layer
资源控制中心服务 — 调度、审批、参数调整、工单路由
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func


class RCCTaskService:
    """RCC 任务服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_task(
        self,
        task_type: str,
        title: str,
        org_unit_id: str,
        affected_params: List[Dict[str, Any]],
        affected_entities: List[Dict[str, Any]],
        expected_impact_summary: str = "",
        requested_by: str = "system",
        request_context: Optional[Dict[str, Any]] = None,
        source_ticket_id: Optional[str] = None,
    ) -> Any:
        """创建 RCC 调度任务"""
        from core.rcc.models import RCCTask
        
        task_code = f"RCC-{org_unit_id[:8].upper()}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        
        task = RCCTask(
            task_code=task_code,
            org_unit_id=org_unit_id,
            task_type=task_type,
            title=title,
            affected_params=affected_params,
            affected_entities=affected_entities,
            expected_impact_summary=expected_impact_summary,
            status="pending",
            requested_by=requested_by,
            request_context=request_context or {},
            source_ticket_id=source_ticket_id,
        )
        
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def approve_task(self, task_id: str, approver_id: str, comment: str = "") -> Any:
        """审批通过任务"""
        from core.rcc.models import RCCTask, RccApprovalRecord
        
        task = await self._get_task(task_id)
        if task.status != "pending":
            raise ValueError(f"任务状态不允许审批: {task.status}")
        
        task.status = "approved"
        task.approved_by = approver_id
        task.approved_at = datetime.now(timezone.utc)
        
        # 创建审批记录
        record = RccApprovalRecord(
            rcc_task_id=task.id,
            approver_role=approver_id,
            decision="approve",
            comment=comment,
        )
        self.db.add(record)
        await task.approval_records.append(record) if hasattr(task, 'approval_records') else None
        
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def reject_task(self, task_id: str, approver_id: str, reason: str) -> Any:
        """拒绝任务"""
        from core.rcc.models import RCCTask, RccApprovalRecord
        
        task = await self._get_task(task_id)
        if task.status != "pending":
            raise ValueError(f"任务状态不允许审批: {task.status}")
        
        task.status = "rejected"
        task.rejected_by = approver_id
        task.rejection_reason = reason
        
        record = RccApprovalRecord(
            rcc_task_id=task.id,
            approver_role=approver_id,
            decision="reject",
            comment=reason,
        )
        self.db.add(record)
        await task.approval_records.append(record) if hasattr(task, 'approval_records') else None
        
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        org_unit_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Any]:
        """查询 RCC 任务列表"""
        from core.rcc.models import RCCTask
        
        query = select(RCCTask)
        if status:
            query = query.where(RCCTask.status == status)
        if org_unit_id:
            query = query.where(RCCTask.org_unit_id == org_unit_id)
        query = query.order_by(RCCTask.created_at.desc()).offset((page-1)*page_size).limit(page_size)
        
        return list((await self.db.execute(query)).scalars().all())
    
    async def _get_task(self, task_id: str) -> Any:
        """获取单个任务"""
        from core.rcc.models import RCCTask
        
        result = await self.db.execute(select(RCCTask).where(RCCTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise ValueError("RCC任务不存在")
        return task


class ParamAdjustmentService:
    """参数调整服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def adjust_parameter(
        self,
        param_id: str,
        new_value: str,
        changed_by: str,
        reason: str = "",
        source: str = "panel",
    ) -> Dict[str, Any]:
        """
        调整参数：
        - low: 直接生效 + 静默同步RCC基线
        - normal: 直接生效 + 需RCC审批
        - high: 需要RCC调整
        - strategic: 仅RCC可调整
        """
        from core.rcc.models import GlobalAdjustableParam, ParameterChangeAudit, RCCOrganization
        
        param = await self._get_param(param_id)
        old_value = param.current_value
        
        # 检查敏感度
        sensitivity = param.sensitivity
        if sensitivity == "strategic":
            raise ValueError("该参数仅限 RCC 调整，请通过 RCC 调度任务修改")
        
        # 更新当前值
        param.current_value = new_value
        param.previous_value = old_value
        param.changed_by = changed_by
        param.change_reason = reason
        
        # 创建审计记录
        audit = ParameterChangeAudit(
            param_id=param_id,
            from_value=old_value,
            to_value=new_value,
            changed_by=changed_by,
            source=source,
            reason=reason,
        )
        
        # 根据敏感度决定是否需要审批
        if sensitivity in ("normal", "high"):
            audit.approval_required = True
            audit.approval_status = "pending_rcc"
        else:
            audit.approval_status = "auto_approved"
        
        self.db.add(audit)
        
        # 如果正常级别需要自动同步到RCC基线（低敏感度直接同步）
        if sensitivity in ("low", "normal"):
            await self._sync_to_rcc_baseline(param, old_value, new_value, reason)
        
        await self.db.commit()
        await self.db.refresh(param)
        
        return {
            "success": True,
            "param_id": param_id,
            "from_value": old_value,
            "to_value": new_value,
            "approval_status": audit.approval_status,
            "rcc_synced": sensitivity in ("low", "normal"),
            "audit_id": audit.id,
        }
    
    async def _get_param(self, param_id: str) -> Any:
        """获取参数"""
        from core.rcc.models import GlobalAdjustableParam
        
        result = await self.db.execute(select(GlobalAdjustableParam).where(GlobalAdjustableParam.id == param_id))
        param = result.scalar_one_or_none()
        if not param:
            raise ValueError("参数不存在")
        return param
    
    async def _sync_to_rcc_baseline(self, param: Any, old_value: str, new_value: str, reason: str):
        """同步参数到RCC基线"""
        # 这里只是占位逻辑，实际应该更新RCC的resource_pool或capacity_model
        # 完整实现需要考虑资源池的一致性
        pass
    
    async def list_params(
        self,
        org_unit_id: Optional[str] = None,
        category: Optional[str] = None,
        sensitivity: Optional[str] = None,
    ) -> List[Any]:
        """查询可调参数"""
        from core.rcc.models import GlobalAdjustableParam
        
        query = select(GlobalAdjustableParam)
        if org_unit_id:
            query = query.where(GlobalAdjustableParam.org_unit_id == org_unit_id)
        if category:
            query = query.where(GlobalAdjustableParam.category == category)
        if sensitivity:
            query = query.where(GlobalAdjustableParam.sensitivity == sensitivity)
        
        return list((await self.db.execute(query)).scalars().all())
    
    async def analyze_impact(self, param_id: str, new_value: str) -> Dict[str, Any]:
        """分析参数变更影响"""
        from core.rcc.models import GlobalAdjustableParam
        
        param = await self._get_param(param_id)
        affected_logic_chains = []
        affected_tasks = []
        affected_entities = []
        
        # 检查受影响的逻辑链
        for chain_id in param.affects_logic_chains or []:
            # 简化处理，实际应该查询逻辑链表
            pass
        
        # 检查相关任务和实体
        # 根据参数类别和影响范围查询
        
        return {
            "param_id": param_id,
            "current_value": param.current_value,
            "new_value": new_value,
            "affected_logic_chains": affected_logic_chains,
            "affected_tasks": affected_tasks,
            "affected_entities": affected_entities,
            "risk_level": "high" if len(affected_tasks) > 5 else "medium" if len(affected_tasks) > 0 else "low",
        }


class LogicChainEngine:
    """确定性逻辑链执行引擎"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def evaluate(self, event: Dict[str, Any], context_org_unit: str) -> List[Dict[str, Any]]:
        """
        评估并执行匹配的逻辑链
        """
        from core.rcc.models import DeterministicLogicChain, LogicChainExecutionLog
        
        results = []
        
        # 获取该组织单元下所有激活的逻辑链
        query = select(DeterministicLogicChain).where(
            DeterministicLogicChain.enabled == True,
            DeterministicLogicChain.org_unit_id == context_org_unit,
        ).order_by(DeterministicLogicChain.execution_order)
        
        chains = (await self.db.execute(query)).scalars().all()
        
        for chain in chains:
            if self._matches_trigger(chain, event):
                conditions_met = await self._check_conditions(chain, event)
                if conditions_met:
                    result = await self._execute_actions(chain, event)
                    results.append(result)
        
        return results
    
    async def _matches_trigger(self, chain: Any, event: Dict[str, Any]) -> bool:
        """检查触发事件是否匹配"""
        return chain.trigger_event == event.get("event_type")
    
    async def _check_conditions(self, chain: Any, event: Dict[str, Any]) -> bool:
        """检查条件表达式是否满足"""
        from core.logic_chain.conditions import ConditionEvaluator
        
        evaluator = ConditionEvaluator(self.db)
        return await evaluator.evaluate_conditions(chain.conditions, event)
    
    async def _execute_actions(self, chain: Any, event: Dict[str, Any]) -> Dict[str, Any]:
        """执行动作序列"""
        from core.rcc.models import LogicChainExecutionLog
        
        execution_results = []
        
        for action in chain.action_sequence or []:
            result = await self._run_action(action, event)
            execution_results.append(result)
            
            # 如果动作产生了新事件，可能需要递归评估
            if result.get("generated_event"):
                nested_results = await self.evaluate(result["generated_event"], chain.org_unit_id)
                execution_results.extend(nested_results)
        
        # 记录执行日志
        log_entry = LogicChainExecutionLog(
            chain_id=chain.id,
            triggered_by=event.get("triggered_by", "unknown"),
            trigger_payload=event,
            conditions_matched=True,
            actions_executed=[a.get("type") for a in chain.action_sequence or []],
            action_results=execution_results,
        )
        self.db.add(log_entry)
        await self.db.commit()
        
        return {
            "chain_id": chain.id,
            "chain_name": chain.chain_name,
            "execution_results": execution_results,
            "success": True,
        }
    
    async def _run_action(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个动作"""
        action_type = action.get("type")
        
        if action_type == "update_param":
            return await self._action_update_param(action, event)
        elif action_type == "create_chatbot_ticket":
            return await self._action_create_ticket(action, event)
        elif action_type == "notify_org_unit":
            return await self._action_notify(action, event)
        elif action_type == "log_audit":
            return await self._action_log_audit(action, event)
        elif action_type == "escalate_rcc":
            return await self._action_escalate(action, event)
        else:
            return {"type": action_type, "status": "unsupported"}
    
    async def _action_update_param(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """更新参数动作"""
        param_code = action.get("param_code")
        new_value = action.get("value")
        
        # 查找参数ID
        from core.rcc.models import GlobalAdjustableParam
        query = select(GlobalAdjustableParam).where(GlobalAdjustableParam.param_code == param_code)
        param = (await self.db.execute(query)).scalar_one_or_none()
        
        if param:
            param.current_value = str(new_value)
            param.previous_value = param.current_value
            await self.db.commit()
            return {"type": "update_param", "param_id": param.id, "status": "updated"}
        
        return {"type": "update_param", "param_code": param_code, "status": "not_found"}
    
    async def _action_create_ticket(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """创建Chatbot工单动作"""
        from core.rcc.services import ChatbotTicketService
        
        service = ChatbotTicketService(self.db)
        ticket = await service.create_ticket(
            message=action.get("message", ""),
            requester_id=action.get("requester_id", "logic_chain_auto"),
            ticket_type=action.get("ticket_type", "process_change"),
        )
        return {"type": "create_ticket", "ticket_id": ticket.id, "status": "created"}
    
    async def _action_notify(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """通知动作（占位）"""
        return {"type": "notify", "target": action.get("target_org_unit"), "status": "sent"}
    
    async def _action_log_audit(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """审计日志动作（占位）"""
        return {"type": "log_audit", "status": "logged"}
    
    async def _action_escalate(self, action: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """升级动作（占位）"""
        return {"type": "escalate", "to_level": action.get("level"), "status": "escalated"}


class ChatbotTicketService:
    """Chatbot 工单服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_ticket(
        self,
        message: str,
        requester_id: str,
        ticket_type: str = "support_request",
        parsed_intents: Optional[Dict[str, Any]] = None,
        parsed_slots: Optional[Dict[str, Any]] = None,
        related_param_id: Optional[str] = None,
        related_rcc_task_id: Optional[str] = None,
        related_work_order_id: Optional[str] = None,
        requested_resource: Optional[Dict[str, Any]] = None,
        requested_time_window: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """创建Chatbot工单"""
        from core.rcc.models import ChatbotTicket
        
        ticket_code = f"CBT-{requester_id[:6].upper()}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        
        ticket = ChatbotTicket(
            ticket_code=ticket_code,
            requester_id=requester_id,
            ticket_type=ticket_type,
            raw_message=message,
            parsed_intents=parsed_intents or {},
            parsed_slots=parsed_slots or {},
            related_param_id=related_param_id,
            related_rcc_task_id=related_rcc_task_id,
            related_work_order_id=related_work_order_id,
            requested_resource=requested_resource or {},
            requested_time_window=requested_time_window or {},
            status="open",
        )
        
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket
    
    async def route_ticket(self, ticket_id: str, target_org_unit: str, target_position: str) -> Any:
        """路由工单到指定组织和职位"""
        from core.rcc.models import ChatbotTicket
        
        ticket = await self._get_ticket(ticket_id)
        ticket.routed_to_org_unit = target_org_unit
        ticket.routed_to_position = target_position
        ticket.status = "routed"
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket
    
    async def resolve_ticket(self, ticket_id: str, resolution: str, resolved_by: str) -> Any:
        """解决工单"""
        from core.rcc.models import ChatbotTicket
        
        ticket = await self._get_ticket(ticket_id)
        ticket.status = "resolved"
        ticket.resolved_by = resolved_by
        ticket.resolution = resolution
        ticket.resolved_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket
    
    async def list_tickets(
        self,
        requester_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Any]:
        """查询工单列表"""
        from core.rcc.models import ChatbotTicket
        
        query = select(ChatbotTicket)
        if requester_id:
            query = query.where(ChatbotTicket.requester_id == requester_id)
        if status:
            query = query.where(ChatbotTicket.status == status)
        query = query.order_by(ChatbotTicket.created_at.desc()).offset((page-1)*page_size).limit(page_size)
        
        return list((await self.db.execute(query)).scalars().all())
    
    async def _get_ticket(self, ticket_id: str) -> Any:
        """获取单个工单"""
        from core.rcc.models import ChatbotTicket
        
        result = await self.db.execute(select(ChatbotTicket).where(ChatbotTicket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise ValueError("工单不存在")
        return ticket

