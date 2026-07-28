"""
智能体运行时（Agent Runtime）
============================
参考 Pi Agent 的 pi-agent-core 设计，整合：
- 事件总线：所有动作以事件流暴露
- 钩子链：before/after 拦截
- 并行执行：无依赖任务并发
- Steer 纠偏：运行中注入修正
- 审计链：完整决策记录，可回放

这是监督引擎的"执行内核"，AgentSupervisor 通过它驱动所有智能体动作。
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional
from datetime import datetime
import logging

from .event_bus import AgentEventBus, EventType
from .hooks import HookChain, HookResult, ActionContext, create_default_hook_chain

_logger = logging.getLogger("agent_runtime")


@dataclass
class SteerMessage:
    """纠偏指令（运行中注入）"""
    content: str
    injected_by: str = "supervisor"
    timestamp: float = field(default_factory=time.time)
    priority: str = "normal"  # normal / urgent


@dataclass
class AuditEntry:
    """审计条目（每次决策/动作的完整记录）"""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    agent_key: str = ""
    factory_id: str = ""
    task_id: Optional[str] = None
    phase: str = ""           # decide / execute / verify / steer / block
    action: str = ""
    input_summary: str = ""
    output_summary: str = ""
    duration_ms: float = 0
    blocked: bool = False
    block_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "time_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "agent_key": self.agent_key,
            "factory_id": self.factory_id,
            "task_id": self.task_id,
            "phase": self.phase,
            "action": self.action,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "duration_ms": round(self.duration_ms, 1),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class AgentRuntime:
    """
    智能体运行时（单例）
    
    核心能力：
    1. execute_action：执行单个动作（经过钩子链 + 事件流）
    2. execute_parallel：并发执行多个无依赖动作
    3. steer：向运行中的任务注入纠偏指令
    4. get_audit_trail：获取审计链（回放用）
    
    用法：
        runtime = AgentRuntime.get_instance()
        
        # 执行动作（自动过钩子 + 发事件）
        result = await runtime.execute_action(
            agent_key="scheduling_agent",
            factory_id="F01",
            action_type="adjust_schedule",
            params={"work_order": "WO-001", "priority": "urgent"},
            executor=my_async_fn,  # 实际执行函数
        )
        
        # 并行执行
        results = await runtime.execute_parallel([
            {"agent_key": "warehouse_agent", "action_type": "check_stock", ...},
            {"agent_key": "scheduling_agent", "action_type": "check_capacity", ...},
        ])
    """
    _instance: Optional["AgentRuntime"] = None

    def __init__(self):
        self.event_bus = AgentEventBus.get_instance()
        self.hook_chain = create_default_hook_chain()
        # 审计链（环形缓冲，最近1000条）
        self._audit_trail: List[AuditEntry] = []
        self._audit_max = 1000
        # Steer 队列：task_id -> list of SteerMessage
        self._steer_queue: Dict[str, List[SteerMessage]] = {}
        # 运行中任务注册：task_id -> asyncio.Task
        self._running_tasks: Dict[str, asyncio.Task] = {}

    @classmethod
    def get_instance(cls) -> "AgentRuntime":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ═══════════════════════════════════════════════════════════
    # 核心：执行动作（经过钩子链 + 事件流 + 审计）
    # ═══════════════════════════════════════════════════════════

    async def execute_action(
        self,
        agent_key: str,
        factory_id: str,
        action_type: str,
        params: Dict[str, Any],
        executor: Optional[Callable[..., Coroutine]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行单个智能体动作。
        
        流程：
        1. emit ACTION_START
        2. run_before hooks（可拦截）
        3. 执行 executor（如有）
        4. run_after hooks（审计）
        5. emit ACTION_END
        6. 写入审计链
        """
        start_time = time.time()
        ctx = ActionContext(
            agent_key=agent_key,
            factory_id=factory_id,
            action_type=action_type,
            params=params,
            task_id=task_id,
        )

        # 1. 事件：动作开始
        await self.event_bus.emit(
            EventType.ACTION_START, agent_key, factory_id, task_id,
            data={"action_type": action_type, "params_keys": list(params.keys())}
        )

        # 2. 前置钩子
        hook_result = await self.hook_chain.run_before(ctx)
        if hook_result.blocked:
            # 被拦截
            await self.event_bus.emit(
                EventType.HOOK_BLOCKED, agent_key, factory_id, task_id,
                data={"action_type": action_type, "reason": hook_result.reason}
            )
            self._record_audit(AuditEntry(
                agent_key=agent_key, factory_id=factory_id, task_id=task_id,
                phase="block", action=action_type,
                input_summary=json.dumps(params, ensure_ascii=False, default=str)[:200],
                blocked=True, block_reason=hook_result.reason,
                duration_ms=(time.time() - start_time) * 1000,
            ))
            return {"success": False, "blocked": True, "reason": hook_result.reason}

        # 3. 执行
        result = None
        error = None
        if executor:
            try:
                result = await executor(**ctx.params)
            except Exception as e:
                error = str(e)
                _logger.error(f"[Runtime] {agent_key}.{action_type} error: {e}")
                await self.event_bus.emit(
                    EventType.ERROR, agent_key, factory_id, task_id,
                    data={"action_type": action_type, "error": error}
                )

        # 4. 后置钩子
        await self.hook_chain.run_after(ctx, action_result=result)

        # 5. 事件：动作结束
        duration_ms = (time.time() - start_time) * 1000
        await self.event_bus.emit(
            EventType.ACTION_END, agent_key, factory_id, task_id,
            data={
                "action_type": action_type,
                "success": error is None,
                "duration_ms": round(duration_ms, 1),
                "error": error,
            }
        )

        # 6. 审计
        self._record_audit(AuditEntry(
            agent_key=agent_key, factory_id=factory_id, task_id=task_id,
            phase="execute", action=action_type,
            input_summary=json.dumps(params, ensure_ascii=False, default=str)[:200],
            output_summary=json.dumps(result, ensure_ascii=False, default=str)[:200] if result else "",
            duration_ms=duration_ms,
            metadata={"error": error} if error else {},
        ))

        return {"success": error is None, "result": result, "error": error, "duration_ms": round(duration_ms, 1)}

    # ═══════════════════════════════════════════════════════════
    # 并行执行（无依赖任务并发）
    # ═══════════════════════════════════════════════════════════

    async def execute_parallel(
        self,
        actions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        并发执行多个无依赖动作。
        每个 action dict 需包含：agent_key, factory_id, action_type, params, executor(可选)
        
        参考 Pi Agent 的 parallel mode：先 preflight 验证，再并发执行。
        """
        # Preflight：全部过 before hook
        valid_actions = []
        results = [None] * len(actions)
        
        for i, action in enumerate(actions):
            ctx = ActionContext(
                agent_key=action["agent_key"],
                factory_id=action["factory_id"],
                action_type=action["action_type"],
                params=action.get("params", {}),
                task_id=action.get("task_id"),
            )
            hook_result = await self.hook_chain.run_before(ctx)
            if hook_result.blocked:
                results[i] = {"success": False, "blocked": True, "reason": hook_result.reason}
            else:
                valid_actions.append((i, action))

        # 并发执行通过验证的动作
        if valid_actions:
            tasks = []
            for idx, action in valid_actions:
                executor = action.get("executor")
                if executor:
                    tasks.append((idx, executor(**action.get("params", {}))))
                else:
                    tasks.append((idx, None))

            # 收集需要 await 的
            coros = [(idx, coro) for idx, coro in tasks if coro is not None]
            if coros:
                gathered = await asyncio.gather(
                    *[coro for _, coro in coros],
                    return_exceptions=True
                )
                for (idx, _), result in zip(coros, gathered):
                    if isinstance(result, Exception):
                        results[idx] = {"success": False, "error": str(result)}
                    else:
                        results[idx] = {"success": True, "result": result}

            # 无 executor 的标记成功
            for idx, coro in tasks:
                if coro is None and results[idx] is None:
                    results[idx] = {"success": True, "result": None}

        return [r or {"success": True, "result": None} for r in results]

    # ═══════════════════════════════════════════════════════════
    # Steer 纠偏（运行中注入修正指令）
    # ═══════════════════════════════════════════════════════════

    def steer(self, task_id: str, message: str, injected_by: str = "supervisor", priority: str = "normal"):
        """
        向运行中的任务注入纠偏指令。
        智能体在下一个检查点读取并响应。
        """
        steer_msg = SteerMessage(content=message, injected_by=injected_by, priority=priority)
        if task_id not in self._steer_queue:
            self._steer_queue[task_id] = []
        self._steer_queue[task_id].append(steer_msg)
        _logger.info(f"[Steer] task={task_id} by={injected_by}: {message[:100]}")
        return steer_msg

    def consume_steer(self, task_id: str) -> List[SteerMessage]:
        """智能体调用：消费待处理的纠偏指令"""
        messages = self._steer_queue.pop(task_id, [])
        return messages

    def has_steer(self, task_id: str) -> bool:
        """检查是否有待处理的纠偏指令"""
        return task_id in self._steer_queue and len(self._steer_queue[task_id]) > 0

    # ═══════════════════════════════════════════════════════════
    # 审计链（完整决策记录，可回放）
    # ═══════════════════════════════════════════════════════════

    def _record_audit(self, entry: AuditEntry):
        """写入审计链"""
        self._audit_trail.append(entry)
        if len(self._audit_trail) > self._audit_max:
            self._audit_trail = self._audit_trail[-self._audit_max:]

    def get_audit_trail(
        self,
        factory_id: Optional[str] = None,
        agent_key: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取审计链（支持过滤）"""
        entries = self._audit_trail
        if factory_id:
            entries = [e for e in entries if e.factory_id == factory_id]
        if agent_key:
            entries = [e for e in entries if e.agent_key == agent_key]
        if task_id:
            entries = [e for e in entries if e.task_id == task_id]
        return [e.to_dict() for e in entries[-limit:]]

    def get_task_timeline(self, task_id: str) -> List[Dict[str, Any]]:
        """获取单个任务的完整时间线（回放用）"""
        entries = [e for e in self._audit_trail if e.task_id == task_id]
        return [e.to_dict() for e in entries]

    # ═══════════════════════════════════════════════════════════
    # 状态概览
    # ═══════════════════════════════════════════════════════════

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "running_tasks": len(self._running_tasks),
            "pending_steers": sum(len(v) for v in self._steer_queue.values()),
            "audit_entries": len(self._audit_trail),
            "event_subscribers": self.event_bus.subscriber_count,
            "hooks": self.hook_chain.registered_hooks,
        }
