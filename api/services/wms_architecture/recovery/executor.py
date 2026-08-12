"""Recovery Executor for WMS.

Handles error recovery strategies for WMS operations.
"""

from typing import Any, Dict, Optional, List
from abc import ABC, abstractmethod
from datetime import datetime


class RecoveryResult:
    """Result of applying a recovery strategy."""
    
    def __init__(self, strategy_name: str, applied: bool, context: Dict[str, Any], message: Optional[str] = None):
        self.strategy_name = strategy_name
        self.applied = applied
        self.context = context
        self.message = message
        self.timestamp = datetime.utcnow().isoformat()
    
    def __repr__(self):
        return f"RecoveryResult(strategy={self.strategy_name}, applied={self.applied}, msg={self.message})"


class WmsRecoveryStrategy(ABC):
    """Abstract base class for all WMS recovery strategies."""
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        pass
    
    @abstractmethod
    def should_apply(self, context: Dict[str, Any]) -> bool:
        pass
    
    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        pass


class InsufficientStockRecovery(WmsRecoveryStrategy):
    """Recover from insufficient stock by suggesting alternative batches."""
    
    def get_strategy_name(self) -> str:
        return "insufficient_stock"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        error = context.get("error", "")
        return "库存不足" in error or "insufficient" in error.lower()
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        new_context["recovery_applied"] = "insufficient_stock"
        new_context["suggestion"] = "建议检查其他批次或仓库"
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="库存不足，建议检查其他批次或仓库"
        )


class BatchConflictRecovery(WmsRecoveryStrategy):
    """Recover from batch conflicts by suggesting manual resolution."""
    
    def get_strategy_name(self) -> str:
        return "batch_conflict"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        error = context.get("error", "")
        return "批次冲突" in error or "conflict" in error.lower()
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        new_context["recovery_applied"] = "batch_conflict"
        new_context["suggestion"] = "建议人工确认批次"
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="批次冲突，建议人工确认"
        )


class SystemErrorRecovery(WmsRecoveryStrategy):
    """Recover from system errors by logging and alerting."""
    
    def get_strategy_name(self) -> str:
        return "system_error"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        error = context.get("error")
        return error is not None and "system" in str(error).lower()
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        new_context["recovery_applied"] = "system_error"
        new_context["alert_sent"] = True
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="系统错误，已发送告警"
        )


class GenericFallbackRecovery(WmsRecoveryStrategy):
    """Generic fallback when no specific recovery applies."""
    
    def get_strategy_name(self) -> str:
        return "generic_fallback"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        # Apply as last resort
        return context.get("error") is not None
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        new_context["recovery_applied"] = "generic_fallback"
        new_context["degraded"] = True
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="服务降级，正在使用简化模式"
        )


class RecoveryExecutor:
    """Executor registry for WMS recovery strategies."""
    
    _strategies: List[WmsRecoveryStrategy] = []
    
    @classmethod
    def register(cls, strategy: WmsRecoveryStrategy) -> None:
        """Register a recovery strategy."""
        if strategy not in cls._strategies:
            cls._strategies.append(strategy)
    
    @classmethod
    def unregister(cls, strategy: WmsRecoveryStrategy) -> None:
        """Unregister a recovery strategy."""
        if strategy in cls._strategies:
            cls._strategies.remove(strategy)
    
    @classmethod
    def execute_all(cls, context: Dict[str, Any]) -> Optional[RecoveryResult]:
        """Execute all registered strategies in order.
        
        Args:
            context: The error context
            
        Returns:
            The first recovery result that applies, or None
        """
        for strategy in cls._strategies:
            if strategy.should_apply(context):
                return strategy.execute(context)
        return None
    
    @classmethod
    def reset(cls) -> None:
        """Reset the registry to empty state."""
        cls._strategies.clear()
    
    @classmethod
    def initialize_default_strategies(cls) -> None:
        """Initialize default recovery strategies."""
        cls.register(InsufficientStockRecovery())
        cls.register(BatchConflictRecovery())
        cls.register(SystemErrorRecovery())
        cls.register(GenericFallbackRecovery())