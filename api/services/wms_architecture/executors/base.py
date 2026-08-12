"""Base class for WMS executors.

All WMS executors should inherit from this base class
and implement the execute() method.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession


class BaseWmsExecutor(ABC):
    """Abstract base class for WMS executors.
    
    Each executor handles a single WMS operation type
    (e.g., inbound, outbound, transfer, count).
    """
    
    @abstractmethod
    def get_operation_name(self) -> str:
        """Get the operation name this executor handles.
        
        Returns:
            The operation name (e.g., "inbound", "outbound")
        """
        pass
    
    @abstractmethod
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the WMS operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: Additional execution context
            
        Returns:
            Operation result
        """
        pass
    
    @abstractmethod
    def can_handle(self, operation: str) -> bool:
        """Check if this executor can handle the given operation.
        
        Args:
            operation: The operation name to check
            
        Returns:
            True if this executor can handle the operation
        """
        return self.get_operation_name() == operation
    
    def validate_context(self, context: Dict[str, Any]) -> Dict[str, str]:
        """Validate the execution context and return errors.
        
        Args:
            context: The execution context
            
        Returns:
            Dictionary of validation errors (empty if valid)
        """
        errors = {}
        
        # Factory ID is required
        if not context.get("factory_id"):
            errors["factory_id"] = "Factory ID is required"
        
        return errors