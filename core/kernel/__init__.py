"""EngFlow Harness Kernel。

Chat V2 链路的编成内核，包含：
- AgentLoop: 工具调用循环
- KernelContext: 请求上下文
- HarnessKernel: 编排器
- CheckpointManager: 断点保存/恢复
- Telemetry: 结构化遥测
"""

from core.kernel.agent_loop import AgentLoop, LoopResult
from core.kernel.approvals import ApprovalManager, get_approval_manager
from core.kernel.checkpoint import CheckpointManager
from core.kernel.context import KernelContext
from core.kernel.context_window import CompactionResult, compact_messages
from core.kernel.events import HarnessEvent, HarnessEventBus, get_harness_event_bus
from core.kernel.kernel import HarnessKernel, KernelResponse
from core.kernel.plugins import (
    CapabilityDefinition,
    HarnessPluginRegistry,
    HarnessProfile,
    PluginContext,
    PluginRuntimeError,
    PluginSpec,
    get_harness_plugin_registry,
)
from core.kernel.telemetry import Telemetry, TelemetryEvent, TelTimer
from core.kernel.thread_manager import ThreadBusyError, ThreadManager, get_thread_manager

__version__ = "0.12.0"

__all__ = [
    "AgentLoop",
    "LoopResult",
    "ApprovalManager",
    "get_approval_manager",
    "CheckpointManager",
    "KernelContext",
    "CompactionResult",
    "compact_messages",
    "HarnessKernel",
    "KernelResponse",
    "HarnessEvent",
    "HarnessEventBus",
    "get_harness_event_bus",
    "CapabilityDefinition",
    "HarnessPluginRegistry",
    "HarnessProfile",
    "PluginContext",
    "PluginRuntimeError",
    "PluginSpec",
    "get_harness_plugin_registry",
    "Telemetry",
    "TelemetryEvent",
    "TelTimer",
    "ThreadBusyError",
    "ThreadManager",
    "get_thread_manager",
    "__version__",
]
