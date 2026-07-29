
"""
Andon 2.0 Service Layer
智能工单服务 — 创建/派单/抢单/提醒/升级/TMS联动
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import (
    WorkOrder,
    DefectRecord,
)
from core.andon.models import AndonTicket, AndonEscalationLog


class AndonService:
    """安灯小工单服务"""

    # 类别定义
    CATEGORIES = {
        "equipment_repair": {
            "name": "设备维修",
            "priority_hint": "high",
            "timeout_minutes": 30,
        },
        "material_call": {
            "name": "物料呼叫",
            "priority_hint": "medium",
            "timeout_minutes": 20,
        },
        "quality_issue": {
            "name": "质量异常",
            "priority_hint": "urgent",
            "timeout_minutes": 15,
        },
        "tech_support": {
            "name": "技术支持",
            "priority_hint": "high",
            "timeout_minutes": 45,
        },
        "admin_matter": {
            "name": "行政事务",
            "priority_hint": "low",
            "timeout_minutes": 60,
        },
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_ticket(
        self,
        factory_id: str,
        category_code: str,
        title: str,
        description: Optional[str] = None,
        location_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        created_by: Optional[str] = None,
        priority: Optional[str] = None,
        metadata_: Optional[Dict[str, Any]] = None,
    ) -> AndonTicket:
        """创建安灯工单"""
        if category_code not in self.CATEGORIES:
            raise ValueError(f"未知的安灯类别: {category_code}")

        cat = self.CATEGORIES[category_code]
        ticket_code = f"AND-{factory_id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

        ticket = AndonTicket(
            ticket_code=ticket_code,
            factory_id=factory_id,
            category_code=category_code,
            title=title,
            description=description,
            location_id=location_id,
            location_name=metadata_["location_name"] if metadata_ and "location_name" in metadata_ else None,
            equipment_id=equipment_id,
            work_order_id=work_order_id,
            priority=priority or cat["priority_hint"],
            timeout_minutes_no_response=cat["timeout_minutes"],
            metadata_=metadata_ or {},
        )

        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)

        # 自动转TMS任务（如果类别配置了auto_route）
        if category_code == "equipment_repair":
            await self._auto_convert_to_tms(ticket, "maintenance_task")
        elif category_code == "quality_issue":
            await self._auto_convert_to_tms(ticket, "quality_investigation")

        return ticket

    async def assign_ticket(self, ticket_id: str, target_user_id: str, reason: Optional[str] = None) -> AndonTicket:
        """指定派单"""
        ticket = await self._get_ticket(ticket_id)
        ticket.status = "assigned"
        ticket.assigned_to = target_user_id
        ticket.assigned_by = reason or "api_user"
        await self.db.commit()
        await self.db.refresh(ticket)

        # 记录日志
        await self._log_event(ticket_id, "reminder", message=f"已指派给 {target_user_id}: {reason or ''}")
        return ticket

    async def claim_ticket(self, ticket_id: str, user_id: str) -> AndonTicket:
        """抢单模式 - 员工自主认领"""
        ticket = await self._get_ticket(ticket_id)
        if ticket.status != "open":
            raise ValueError("只有开放状态的工单可被抢单")
        ticket.status = "claimed"
        ticket.assigned_to = user_id
        ticket.claimed_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def resolve_ticket(self, ticket_id: str, resolution: str, resolved_by: Optional[str] = None) -> AndonTicket:
        """解决工单"""
        ticket = await self._get_ticket(ticket_id)
        ticket.status = "resolved"
        ticket.resolved_at = datetime.utcnow()
        ticket.metadata_["resolution"] = resolution
        await self.db.commit()
        await self.db.refresh(ticket)

        await self._log_event(ticket_id, "resolved_closed", message=f"已解决: {resolution}")
        return ticket

    async def escalate_ticket(self, ticket_id: str, level: int, note: Optional[str] = None) -> AndonTicket:
        """手动升级"""
        ticket = await self._get_ticket(ticket_id)
        ticket.escalation_level = level
        ticket.escalator_note = note
        if level == 1:
            ticket.escalated_to = "team_leader"
        elif level == 2:
            ticket.escalated_to = "factory_manager"
        await self.db.commit()
        await self.db.refresh(ticket)
        await self._log_event(ticket_id, "escalated", to_role=ticket.escalated_to, message=note or "")
        return ticket

    async def process_timeout_escalations(self) -> List[Dict[str, Any]]:
        """处理超时未响应/未解决的升级（定时任务调用）"""
        now = datetime.utcnow()
        result = []

        # 查所有 open/assigned/claimed 工单
        stmt = select(AndonTicket).where(
            AndonTicket.status.in_(["open", "assigned", "claimed"]),
            AndonTicket.created_at < now - timedelta(minutes=15),
        )
        pending_tickets = (await self.db.execute(stmt)).scalars().all()

        for ticket in pending_tickets:
            # 无响应升级
            last_activity = max(ticket.created_at, ticket.last_reminder_at or ticket.created_at)
            minutes_since_last = (now - last_activity).total_seconds() / 60

            if minutes_since_last >= ticket.timeout_minutes_no_response and ticket.status == "open":
                ticket.escalation_level = max(ticket.escalation_level, 1)
                ticket.escalated_to = "team_leader"
                ticket.status = "upgrading"
                await self._log_event(ticket.id, "escalated", to_role="team_leader", message=f"超时15分钟无响应，自动升级至组长")
                result.append({"ticket_id": ticket.id, "action": "timeout_escalation", "to": "team_leader"})

            # 未解决升级
            elif minutes_since_last >= ticket.timeout_minutes_resolve:
                ticket.escalation_level = max(ticket.escalation_level, 2)
                ticket.escalated_to = "factory_manager"
                await self._log_event(ticket.id, "escalated", to_role="factory_manager", message=f"超时{ticket.timeout_minutes_resolve}分钟未解决，升级至厂长")
                result.append({"ticket_id": ticket.id, "action": "resolve_timeout", "to": "factory_manager"})

        if result:
            await self.db.commit()

        return result

    async def process_timed_reminders(self) -> List[Dict[str, Any]]:
        """处理定时提醒推送"""
        now = datetime.utcnow()
        result = []

        stmt = select(AndonTicket).where(
            AndonTicket.status.in_(["open", "assigned", "claimed"]),
            AndonTicket.last_reminder_at.is_(None),
        )
        tickets = (await self.db.execute(stmt)).scalars().all()

        for ticket in tickets:
            minutes_since_create = (now - ticket.created_at).total_seconds() / 60
            interval = ticket.reminder_interval_minutes or 5

            if minutes_since_create >= interval:
                ticket.last_reminder_at = now
                await self._log_event(
                    ticket.id, "reminder",
                    message=f"第{int(minutes_since_create // interval)}次提醒：{ticket.title}",
                    from_role=ticket.assigned_to,
                )
                result.append({
                    "ticket_id": ticket.id,
                    "event_type": "reminder",
                    "assigned_to": ticket.assigned_to,
                    "message": f"请处理工单 #{ticket.ticket_code}: {ticket.title}",
                })

        if result:
            await self.db.commit()

        return result

    async def list_tickets(
        self,
        factory_id: str,
        status: Optional[str] = None,
        category_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[AndonTicket]:
        """列表查询"""
        query = select(AndonTicket).where(AndonTicket.factory_id == factory_id)
        if status:
            query = query.where(AndonTicket.status == status)
        if category_code:
            query = query.where(AndonTicket.category_code == category_code)
        query = query.order_by(AndonTicket.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        return list((await self.db.execute(query)).scalars().all())

    async def get_ticket(self, ticket_id: str) -> Optional[AndonTicket]:
        return await self._get_ticket(ticket_id)

    async def _get_ticket(self, ticket_id: str) -> AndonTicket:
        result = await self.db.execute(select(AndonTicket).where(AndonTicket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise ValueError("工单不存在")
        return ticket

    async def _log_event(self, ticket_id, event_type: str, message: str,
                         from_role: Optional[str] = None, to_role: Optional[str] = None) -> None:
        import uuid as uuid_module
        # 确保 ticket_id 是 UUID 对象以匹配数据库列类型
        if isinstance(ticket_id, str):
            try:
                ticket_id = uuid_module.UUID(ticket_id)
            except ValueError:
                pass  # 保持原值
        log = AndonEscalationLog(
            ticket_id=ticket_id,
            event_type=event_type,
            from_role=from_role,
            to_role=to_role,
            message=message,
            triggered_by="system",
        )
        self.db.add(log)

    async def _auto_convert_to_tms(self, ticket: AndonTicket, task_type: str) -> None:
        """小工单自动转化为TMS标准任务（占位，实际需引入 TMS 集成）"""
        # 此处仅记录元数据，TMS任务创建由 TMS service 统一处理
        ticket.metadata_["tms_conversion_status"] = "pending"
        ticket.metadata_["tms_task_type"] = task_type
