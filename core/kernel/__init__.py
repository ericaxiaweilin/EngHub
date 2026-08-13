"""EngFlow Harness Kernel。

Chat V2 链路的编成内核，包含：
- AgentLoop: 工具调用循环
- KernelContext: 请求上下文
- HarnessKernel: 编排器
- CheckpointManager: 断点保存/恢复
- Telemetry: 结构化遥测
"""

from core.kernel.agent_loop import AgentLoop, LoopResult
from core.kernel.checkpoint import CheckpointManager
from core.kernel.context import KernelContext
from core.kernel.kernel import HarnessKernel, KernelResponse
from core.kernel.telemetry import Telemetry, TelemetryEvent, TelTimer

__all__ = [
    "AgentLoop",
    "LoopResult",
    "CheckpointManager",
    "KernelContext",
    "HarnessKernel",
    "KernelResponse",
    "Telemetry",
    "TelemetryEvent",
    "TelTimer",
]