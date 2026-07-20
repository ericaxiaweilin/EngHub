"""
TMS Event Bus - 事件驱动架构
轻量级事件总线（进程内 + Webhook 外推）

用途：
- 任务创建后自动触发分发引擎
- 审批完成后通知相关方
- 超期任务自动升级
- Agent 实时感知任务变化
"""

import asyncio
import logging
import hashlib
import hmac
import json
from datetime import datetime
from typing import Callable, Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class TMSEventType(str, Enum):
    """TMS 事件类型"""
    # 任务生命周期
    TASK_CREATED = "task.created"
    TASK_DISTRIBUTED = "task.distributed"
    TASK_CLAIMED = "task.claimed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_REJECTED = "task.rejected"
    TASK_OVERDUE = "task.overdue"
    TASK_REASSIGNED = "task.reassigned"

    # 审批事件
    APPROVAL_INITIATED = "approval.initiated"
    APPROVAL_PENDING = "approval.pending"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_ESCALATED = "approval.escalated"
    APPROVAL_COMPLETED = "approval.completed"

    # Agent 事件
    AGENT_COMMAND_RECEIVED = "agent.command_received"
    AGENT_ACTION_COMPLETED = "agent.action_completed"
    AGENT_CONFIRMATION_REQUIRED = "agent.confirmation_required"


@dataclass
class TMSEvent:
    """TMS 事件对象"""
    event_type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "system"
    event_id: str = field(default_factory=lambda: hashlib.md5(
        f"{datetime.utcnow().isoformat()}{id(object())}".encode()
    ).hexdigest()[:16])


@dataclass
class WebhookSubscription:
    """Webhook 订阅"""
    agent_id: str
    event_types: List[str]
    webhook_url: str
    secret: Optional[str] = None
    is_active: bool = True


class TMSEventBus:
    """
    TMS 事件总线
    
    支持：
    - 进程内事件订阅/发布
    - Webhook 外部推送（Agent 订阅）
    - 异步非阻塞处理
    """

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._webhook_subscriptions: List[WebhookSubscription] = []
        self._event_history: List[TMSEvent] = []
        self._max_history = 1000

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """订阅事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info(f"Event handler subscribed: {event_type} -> {handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """取消订阅"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    async def publish(self, event_type: str, payload: Dict[str, Any], source: str = "system") -> TMSEvent:
        """
        发布事件
        
        1. 创建事件对象
        2. 调用进程内 handlers
        3. 推送 Webhook
        4. 记录事件历史
        """
        event = TMSEvent(event_type=event_type, payload=payload, source=source)
        
        # 记录历史
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        logger.info(f"Event published: {event_type} | source={source} | id={event.event_id}")

        # 进程内处理
        await self._dispatch_local(event)

        # Webhook 外推
        await self._dispatch_webhooks(event)

        return event

    async def _dispatch_local(self, event: TMSEvent) -> None:
        """进程内事件分发"""
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {event.event_type} -> {handler.__name__}: {e}")

    async def _dispatch_webhooks(self, event: TMSEvent) -> None:
        """Webhook 外推"""
        active_subscriptions = [
            sub for sub in self._webhook_subscriptions
            if sub.is_active and event.event_type in sub.event_types
        ]

        if not active_subscriptions:
            return

        async with httpx.AsyncClient(timeout=10.0) as client:
            for sub in active_subscriptions:
                try:
                    headers = {"Content-Type": "application/json"}
                    body = json.dumps({
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "timestamp": event.timestamp,
                        "source": event.source,
                        "payload": event.payload,
                    })

                    # 签名
                    if sub.secret:
                        signature = hmac.new(
                            sub.secret.encode(), body.encode(), hashlib.sha256
                        ).hexdigest()
                        headers["X-TMS-Signature"] = f"sha256={signature}"

                    await client.post(sub.webhook_url, content=body, headers=headers)
                    logger.info(f"Webhook delivered: {sub.agent_id} <- {event.event_type}")
                except Exception as e:
                    logger.error(f"Webhook delivery failed: {sub.agent_id} @ {sub.webhook_url}: {e}")

    def register_webhook(
        self,
        agent_id: str,
        event_types: List[str],
        webhook_url: str,
        secret: Optional[str] = None,
    ) -> WebhookSubscription:
        """注册 Webhook 订阅"""
        subscription = WebhookSubscription(
            agent_id=agent_id,
            event_types=event_types,
            webhook_url=webhook_url,
            secret=secret,
        )
        self._webhook_subscriptions.append(subscription)
        logger.info(f"Webhook registered: {agent_id} -> {webhook_url} | events={event_types}")
        return subscription

    def unregister_webhook(self, agent_id: str) -> int:
        """注销 Webhook 订阅"""
        before = len(self._webhook_subscriptions)
        self._webhook_subscriptions = [
            sub for sub in self._webhook_subscriptions if sub.agent_id != agent_id
        ]
        removed = before - len(self._webhook_subscriptions)
        logger.info(f"Webhook unregistered: {agent_id} | removed={removed}")
        return removed

    def get_event_history(self, event_type: Optional[str] = None, limit: int = 50) -> List[TMSEvent]:
        """获取事件历史"""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]


# 全局事件总线单例
tms_event_bus = TMSEventBus()
