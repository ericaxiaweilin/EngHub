"""Generic Fallback Executor.

Final fallback strategy when all other recovery options have been exhausted.
Strategy: Return a degraded user-friendly message indicating service is operating with reduced capability.
"""

from typing import Dict, Any
from api.services.chat_architecture.recovery.base import MesRecoveryStrategy, RecoveryResult


class GenericFallbackExecutor(MesRecoveryStrategy):
    """Provide degraded response when no other recovery strategy applies."""
    
    def get_strategy_name(self) -> str:
        return "generic_fallback"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        # Trigger when we've reached max attempts or unrecoverable error
        attempt = context.get("attempt", 0)
        max_attempts = context.get("max_attempts", 3)
        has_error = context.get("error") is not None
        
        return attempt >= max_attempts and has_error
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        new_context["degraded"] = True
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="服务已降级，正在使用简化模式回复。复杂功能可能不可用。"
        )