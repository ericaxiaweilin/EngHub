"""
TMS (Task Management System) - 企业级任务管理系统

以任务分发为核心，开放 Agent/Chatbot 接入的智能任务管理平台。

核心模块：
- distribution_engine: 任务分发引擎（核心）
- approval_workflow: 审批工作流引擎
- agent_interface: Agent/Chatbot 命令接口层
- events: 事件总线（任务生命周期事件）
"""

from core.tms.distribution_engine import (
    DistributionEngine,
    DistributionStrategy,
    DistributionMode,
    DistributionResult,
    CandidateScore,
)
from core.tms.approval_workflow import (
    ApprovalWorkflowEngine,
    FlowType,
    FlowStatus,
    ApprovalAction,
    FlowResult,
)
from core.tms.agent_interface import (
    AgentInterface,
    AgentCommand,
    AgentPermissionLevel,
    AgentCommandRequest,
    AgentCommandResponse,
)
from core.tms.events import (
    TMSEventBus,
    TMSEventType,
    TMSEvent,
    tms_event_bus,
)

__all__ = [
    # Distribution Engine
    "DistributionEngine",
    "DistributionStrategy",
    "DistributionMode",
    "DistributionResult",
    "CandidateScore",
    # Approval Workflow
    "ApprovalWorkflowEngine",
    "FlowType",
    "FlowStatus",
    "ApprovalAction",
    "FlowResult",
    # Agent Interface
    "AgentInterface",
    "AgentCommand",
    "AgentPermissionLevel",
    "AgentCommandRequest",
    "AgentCommandResponse",
    # Events
    "TMSEventBus",
    "TMSEventType",
    "TMSEvent",
    "tms_event_bus",
]
