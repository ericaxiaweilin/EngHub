"""
智能体事件总线（Agent Event Bus）
================================
参考 Pi Agent 的事件模型：10种标准事件覆盖全生命周期。
前端通过 SSE 订阅，实时看到每个智能体的执行状态。

事件类型：
- agent_start / agent_end：智能体任务开始/结束
- turn_start / turn_end：每轮决策循环
- action_start / action_update / action_end：具体动作执行
- steer_injected：中途纠偏指令注入
- hook_blocked：钩子拦截了某个动作
- error：执行异常
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional
from collections import defaultdict
import logging

_logger = logging.getLogger("agent_event_bus")


class EventType(str, Enum):
    """智能体事件类型（对标 Pi Agent 的 10 种事件）"""
    # 任务级
    AGENT_START = "agent_start"          # 智能体开始处理任务
    AGENT_END = "agent_end"              # 智能体任务完成
    # 决策轮次级
    TURN_START = "turn_start"            # 新一轮决策开始
    TURN_END = "turn_end"                # 本轮决策结束
    # 动作执行级
    ACTION_START = "action_start"        # 具体动作开始执行
    ACTION_UPDATE = "action_update"      # 动作进度更新（流式）
    ACTION_END = "action_end"            # 动作执行结束
    # 控制级
    STEER_INJECTED = "steer_injected"    # 中途纠偏指令注入
    HOOK_BLOCKED = "hook_blocked"        # 钩子拦截了动作
    ERROR = "error"                      # 执行异常


@dataclass
class AgentEvent:
    """智能体事件（不可变，发出后即入审计链）"""
    type: EventType
    agent_key: str
    factory_id: str
    task_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    def to_sse(self) -> str:
        """SSE 格式输出"""
        return f"event: {self.type.value}\ndata: {json.dumps(self.to_dict(), ensure_ascii=False, default=str)}\n\n"


# 订阅者类型：async callback(event)
Subscriber = Callable[[AgentEvent], Coroutine[Any, Any, None]]


class AgentEventBus:
    """
    智能体事件总线（单例）
    
    用法：
        bus = AgentEventBus.get_instance()
        
        # 发布事件
        await bus.emit(EventType.ACTION_START, agent_key="scheduling_agent", 
                       factory_id="F01", data={"step": "计算产能"})
        
        # 订阅（SSE endpoint 用）
        sub_id = bus.subscribe("F01", callback)
        bus.unsubscribe(sub_id)
    """
    _instance: Optional["AgentEventBus"] = None

    def __init__(self):
        # factory_id -> list of (sub_id, callback)
        self._subscribers: Dict[str, List[tuple]] = defaultdict(list)
        # 全局订阅（监督看板用）
        self._global_subscribers: List[tuple] = []
        # 事件环形缓冲（最近500条，供回放）
        self._ring_buffer: List[AgentEvent] = []
        self._ring_max = 500
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "AgentEventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def emit(
        self,
        event_type: EventType,
        agent_key: str,
        factory_id: str,
        task_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> AgentEvent:
        """发布事件 → 通知所有订阅者 + 入环形缓冲"""
        event = AgentEvent(
            type=event_type,
            agent_key=agent_key,
            factory_id=factory_id,
            task_id=task_id,
            data=data or {},
        )

        # 入环形缓冲
        async with self._lock:
            self._ring_buffer.append(event)
            if len(self._ring_buffer) > self._ring_max:
                self._ring_buffer = self._ring_buffer[-self._ring_max:]

        # 通知工厂级订阅者
        targets = self._subscribers.get(factory_id, []) + self._global_subscribers
        for sub_id, callback in targets:
            try:
                await callback(event)
            except Exception as e:
                _logger.warning(f"[EventBus] subscriber {sub_id} error: {e}")

        return event

    def subscribe(self, factory_id: str, callback: Subscriber) -> str:
        """订阅某工厂的事件流，返回订阅ID"""
        sub_id = str(uuid.uuid4())
        self._subscribers[factory_id].append((sub_id, callback))
        return sub_id

    def subscribe_global(self, callback: Subscriber) -> str:
        """全局订阅（监督看板）"""
        sub_id = str(uuid.uuid4())
        self._global_subscribers.append((sub_id, callback))
        return sub_id

    def unsubscribe(self, sub_id: str):
        """取消订阅"""
        for fid in list(self._subscribers.keys()):
            self._subscribers[fid] = [
                (sid, cb) for sid, cb in self._subscribers[fid] if sid != sub_id
            ]
        self._global_subscribers = [
            (sid, cb) for sid, cb in self._global_subscribers if sid != sub_id
        ]

    def get_recent_events(self, factory_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """获取最近事件（回放用）"""
        events = self._ring_buffer
        if factory_id:
            events = [e for e in events if e.factory_id == factory_id]
        return [e.to_dict() for e in events[-limit:]]

    @property
    def subscriber_count(self) -> int:
        return sum(len(v) for v in self._subscribers.values()) + len(self._global_subscribers)
