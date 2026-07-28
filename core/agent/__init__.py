"""
智能体运行时核心（Agent Runtime Core）
=====================================
参考 Pi Agent 的 pi-agent-core 设计：
- 事件总线：所有智能体行为以事件流暴露，前端可实时订阅
- 钩子系统：beforeAction/afterAction 拦截链（可配置规则引擎驱动）
- 并行执行：无依赖的智能体任务并发执行
- Steer 纠偏：运行中注入修正指令
- 审计链：每次决策完整记录，可回放
"""
from .event_bus import AgentEventBus, AgentEvent, EventType
from .hooks import HookChain, HookResult
from .runtime import AgentRuntime

__all__ = [
    "AgentEventBus", "AgentEvent", "EventType",
    "HookChain", "HookResult",
    "AgentRuntime",
]
