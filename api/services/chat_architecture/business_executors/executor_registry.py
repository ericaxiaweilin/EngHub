"""Business Executor Registry.

Provides a centralized registry for business executors.
Allows dynamic registration and discovery of executors.
"""

from typing import Dict, List, Optional, Type
from api.services.chat_architecture.business_executors.base import BaseBusinessExecutor


class ExecutorRegistry:
    """Registry for business executors.
    
    Manages the lifecycle of business executors and provides
    discovery and execution capabilities.
    """
    
    _executors: Dict[str, BaseBusinessExecutor] = {}
    
    @classmethod
    def register(cls, executor: BaseBusinessExecutor) -> None:
        """Register a business executor.
        
        Args:
            executor: The business executor to register
        """
        intent_name = executor.get_intent_name()
        if intent_name not in cls._executors:
            cls._executors[intent_name] = executor
    
    @classmethod
    def unregister(cls, executor: BaseBusinessExecutor) -> None:
        """Unregister a business executor.
        
        Args:
            executor: The business executor to unregister
        """
        intent_name = executor.get_intent_name()
        if intent_name in cls._executors:
            del cls._executors[intent_name]
    
    @classmethod
    def get(cls, intent: str) -> Optional[BaseBusinessExecutor]:
        """Get an executor by intent name.
        
        Args:
            intent: The intent name to search for
            
        Returns:
            The executor if found, None otherwise
        """
        return cls._executors.get(intent)
    
    @classmethod
    def get_all(cls) -> List[BaseBusinessExecutor]:
        """Get all registered executors.
        
        Returns:
            List of all registered executors
        """
        return list(cls._executors.values())
    
    @classmethod
    def has_executor(cls, intent: str) -> bool:
        """Check if an executor exists for the given intent.
        
        Args:
            intent: The intent name to check
            
        Returns:
            True if an executor exists for the intent
        """
        return intent in cls._executors
    
    @classmethod
    def reset(cls) -> None:
        """Reset the registry to empty state.
        
        Used for testing.
        """
        cls._executors.clear()