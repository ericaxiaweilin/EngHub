"""Base class for business executors.

All business executors should inherit from this base class
and implement the execute() method.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession


class BaseBusinessExecutor(ABC):
    """Abstract base class for business executors.
    
    Each executor handles a single business operation type
    (e.g., query inventory, get production summary).
    """
    
    @abstractmethod
    def get_intent_name(self) -> str:
        """Get the intent name this executor handles.
        
        Returns:
            The intent name (e.g., "query_inventory")
        """
        pass
    
    @abstractmethod
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the business operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: Additional execution context
            
        Returns:
            Execution result
        """
        pass
    
    @abstractmethod
    def can_handle(self, intent: str) -> bool:
        """Check if this executor can handle the given intent.
        
        Args:
            intent: The intent name to check
            
        Returns:
            True if this executor can handle the intent
        """
        return self.get_intent_name() == intent