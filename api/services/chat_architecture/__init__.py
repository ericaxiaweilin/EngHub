"""Chat Architecture Module.

Provides a fully decoupled architecture for chat processing with:
- FactoryResolver: Resolves factory context
- IntentResolver: Resolves user intent from messages
- StateTransitionEngine: Manages atomic state transitions
- Business Executors: Handle specific business operations
- Recovery Executors: Handle error recovery strategies
- ResponseFormatter: Formats responses consistently
"""

from .adapters.chat_adapter import ChatAdapter
from .resolvers.factory_resolver import FactoryResolver
from .resolvers.intent_resolver import IntentResolver
from .state.engine import StateTransitionEngine, ChatState
from .formatter.response_formatter import ResponseFormatter
from .recovery.registry import ExecutorRegistry as RecoveryExecutorRegistry
from .business_executors.executor_registry import ExecutorRegistry as BusinessExecutorRegistry

__all__ = [
    "ChatAdapter",
    "FactoryResolver",
    "IntentResolver",
    "StateTransitionEngine",
    "ChatState",
    "ResponseFormatter",
    "RecoveryExecutorRegistry",
    "BusinessExecutorRegistry",
]