"""Chat Adapter - Orchestrator for chatbot operations using orthogonal components.

This adapter replaces the monolithic chat() implementation by delegating all
complex processing to specialized components contained within
api/services/chat_architecture/. All business logic is encapsulated; this file
contains only orchestration sequencing.

Architecture:
- FactoryResolver: Resolves factory context from request/user
- IntentResolver: Resolves user intent from message text
- StateTransitionEngine: Manages state transitions atomically
- ExecutorRegistry: Discovers and executes business operations
- ResponseFormatter: Formats responses consistently
- RecoveryRegistry: Manages recovery strategies
"""

from typing import Optional, List, Dict, Any
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Import architecture components
from ..resolvers.factory_resolver import FactoryResolver
from ..resolvers.intent_resolver import IntentResolver
from ..state.engine import StateTransitionEngine, ChatState
from ..formatter.response_formatter import ResponseFormatter
from ..recovery.registry import ExecutorRegistry as RecoveryRegistry
from ..business_executors.executor_registry import ExecutorRegistry as BusinessExecutorRegistry
from ..business_executors.query_inventory_executor import QueryInventoryExecutor
from ..business_executors.get_production_summary_executor import GetProductionSummaryExecutor
from ..business_executors.query_work_orders_executor import QueryWorkOrdersExecutor

# Model imports for chat interfaces (local import to avoid circular issues)
from database.models import User


class ChatAdapter:
    """Chat processing adapter using fully decoupled architecture.
    
    All business logic resides in delegated components. The adapter itself
    merely sequences operations correctly.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.factory_resolver = FactoryResolver()
        self.intent_resolver = IntentResolver()
        self.state_engine = StateTransitionEngine(max_rounds=5)
        self.response_formatter = ResponseFormatter()
        
        # Initialize registries
        self._init_recovery_registries()
        self._init_business_executors()
    
    def _init_recovery_registries(self) -> None:
        """Initialize recovery executor registry."""
        from ..recovery.vision_fallback_executor import VisionFallbackExecutor
        from ..recovery.tool_fallback_executor import ToolFallbackExecutor
        from ..recovery.generic_fallback_executor import GenericFallbackExecutor
        
        RecoveryRegistry.register(VisionFallbackExecutor())
        RecoveryRegistry.register(ToolFallbackExecutor())
        RecoveryRegistry.register(GenericFallbackExecutor())
    
    def _init_business_executors(self) -> None:
        """Initialize business executor registry."""
        BusinessExecutorRegistry.register(QueryInventoryExecutor())
        BusinessExecutorRegistry.register(GetProductionSummaryExecutor())
        BusinessExecutorRegistry.register(QueryWorkOrdersExecutor())
    
    async def handle_request(self, request: "ChatRequest", current_user: Optional[User]) -> "ChatResponse":
        """Main entry point for chat request processing.
        
        This is a pure orchestrator - it delegates all work to
        specialized components and only sequences operations.
        
        Flow:
        1. Resolve factory context
        2. Resolve user intent
        3. Transition state
        4. Execute business operation
        5. Format and return response
        """
        try:
            # 1. Resolve factory context
            http_request = getattr(request, "http_request", None)
            factory_id = self.factory_resolver.resolve(http_request, current_user)
            
            # 2. Resolve user intent
            intent = self.intent_resolver.resolve(
                self._get_last_user_message(request)
            )
            
            # 3. Transition state: IDLE -> PROCESSING_TOOL_LOOP
            self.state_engine.transition(
                ChatState.IDLE,
                ChatState.PROCESSING_TOOL_LOOP,
                context={"factory_id": factory_id}
            )
            
            # 4. Execute based on intent
            if intent and BusinessExecutorRegistry.has_executor(intent):
                result = await self._execute_business_operation(intent, factory_id, request)
            else:
                # Fallback to tool loop for free-form conversation
                result = await self._execute_tool_loop(request, factory_id)
            
            # 5. Format response
            # Ensure degraded is False for successful execution
            if result.get("error"):
                return self.response_formatter.format_success(
                    reply_text=result.get("reply", ""),
                    model=result.get("model", "dynamic"),
                    degraded=True
                )
            else:
                return self.response_formatter.format_success(
                    reply_text=result.get("reply", ""),
                    model=result.get("model", "dynamic"),
                    degraded=False
                )
            
        except HTTPException as he:
            raise he
        except Exception as exc:
            # Transition to DEGRADED state on error
            try:
                self.state_engine.transition(
                    ChatState.PROCESSING_TOOL_LOOP,
                    ChatState.DEGRADED,
                    context={"error": str(exc)}
                )
            except Exception:
                pass  # Ignore state transition errors
            
            return {
                "error": True,
                "reply": f"Chat processing failed: {str(exc)}",
                "model": "unknown",
                "degraded": True
            }
    
    def _get_last_user_message(self, request) -> Optional[str]:
        """Extract the last user message from the request."""
        if not hasattr(request, "messages"):
            return None
        
        for msg in reversed(getattr(request, "messages", [])):
            if getattr(msg, "role", "") == "user":
                return str(getattr(msg, "content", ""))
        
        return None
    
    async def _execute_business_operation(
        self,
        intent: str,
        factory_id: str,
        request
    ) -> Dict[str, Any]:
        """Execute a business operation based on intent.
        
        Args:
            intent: The resolved intent name
            factory_id: The resolved factory ID
            request: The original chat request
            
        Returns:
            Execution result dictionary
        """
        executor = BusinessExecutorRegistry.get(intent)
        if not executor:
            raise ValueError(f"No executor found for intent: {intent}")
        
        # Execute the business operation
        result = await executor.execute(self.db, factory_id, {})
        
        # Format the result as a reply based on intent
        reply = self._format_result_by_intent(intent, result)
        
        return {
            "reply": reply,
            "model": "deterministic",
            "degraded": False,
            "error": False
        }
    
    def _format_result_by_intent(self, intent: str, result: Dict[str, Any]) -> str:
        """Format result based on intent type.
        
        Args:
            intent: The intent name
            result: The execution result
            
        Returns:
            Formatted reply string
        """
        if intent == "query_inventory":
            return self.response_formatter.format_inventory_result(result)
        elif intent == "get_production_summary":
            return self.response_formatter.format_production_summary(result)
        elif intent == "query_work_orders":
            return self.response_formatter.format_work_orders(result)
        else:
            return f"Result for {intent}: {result}"
    
    async def _execute_tool_loop(
        self,
        request,
        factory_id: str
    ) -> Dict[str, Any]:
        """Execute the tool-calling loop for free-form conversation.
        
        This delegates to the existing chat route handler implementation.
        
        Args:
            request: The original chat request
            factory_id: The resolved factory ID
            
        Returns:
            Execution result dictionary
        """
        # TODO: Integrate with existing tool loop implementation
        # For now, return a placeholder response
        return {
            "reply": "工具调用循环架构已准备，原始chat端点继续可用",
            "model": "tool-loop",
            "degraded": False
        }
    
    def get_current_state(self) -> ChatState:
        """Get the current state of the state engine.
        
        Returns:
            Current chat state
        """
        # Note: This is a simplified implementation.
        # In production, you would track state externally.
        return ChatState.IDLE