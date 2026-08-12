"""Recovery Executor Registry.

Provides a centralized registry for recovery strategy executors.
Allows dynamic registration and discovery of recovery strategies.
"""

from typing import Any, Dict, List, Optional, Type
from api.services.chat_architecture.recovery.base import MesRecoveryStrategy, RecoveryResult


class ExecutorRegistry:
    """Registry for recovery strategy executors.
    
    Manages the lifecycle of recovery executors and provides
    discovery and execution capabilities.
    """
    
    _executors: List[MesRecoveryStrategy] = []
    
    @classmethod
    def register(cls, executor: MesRecoveryStrategy) -> None:
        """Register a recovery executor.
        
        Args:
            executor: The recovery executor to register
        """
        # Check by strategy name to avoid duplicates
        executor_name = executor.get_strategy_name()
        existing_names = [e.get_strategy_name() for e in cls._executors]
        if executor_name not in existing_names:
            cls._executors.append(executor)
            cls._executors.sort(key=lambda e: cls._get_priority(e))
    
    @classmethod
    def unregister(cls, executor: MesRecoveryStrategy) -> None:
        """Unregister a recovery executor.
        
        Args:
            executor: The recovery executor to unregister
        """
        if executor in cls._executors:
            cls._executors.remove(executor)
    
    @classmethod
    def get_all(cls) -> List[MesRecoveryStrategy]:
        """Get all registered executors.
        
        Returns:
            List of all registered executors
        """
        return cls._executors.copy()
    
    @classmethod
    def get_by_name(cls, name: str) -> Optional[MesRecoveryStrategy]:
        """Get an executor by its strategy name.
        
        Args:
            name: The strategy name to search for
            
        Returns:
            The executor if found, None otherwise
        """
        for executor in cls._executors:
            if executor.get_strategy_name() == name:
                return executor
        return None
    
    @classmethod
    def execute_all(cls, context: Dict[str, Any]) -> Optional[RecoveryResult]:
        """Execute all registered executors in priority order.
        
        Args:
            context: The current execution context
            
        Returns:
            The first recovery result that applies, or None if no executor applies
        """
        for executor in cls._executors:
            if executor.should_apply(context):
                return executor.execute(context)
        return None
    
    @classmethod
    def _get_priority(cls, executor: MesRecoveryStrategy) -> int:
        """Get the priority of an executor (lower = higher priority).
        
        Args:
            executor: The executor to get priority for
            
        Returns:
            Priority value (0 = highest priority)
        """
        # Define priority order
        priority_map = {
            "vision_fallback": 0,
            "tool_fallback": 1,
            "generic_fallback": 2,
        }
        return priority_map.get(executor.get_strategy_name(), 99)
    
    @classmethod
    def reset(cls) -> None:
        """Reset the registry to empty state.
        
        Used for testing.
        """
        cls._executors.clear()