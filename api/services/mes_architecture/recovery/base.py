"""Mes Recovery Strategy Base Class

Defines the interface for all Mes recovery/handling strategies.
Each strategy encapsulates a specific business exception handling logic."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class MesRecoveryStrategy(ABC):
    """Abstract base class for Mes recovery strategies.
    
    Strategies are applied in sequence when a Mes operation encounters
    an exceptional condition that requires special handling beyond basic error raising.
    """
    
    @abstractmethod
    def should_apply(self, context: Dict[str, Any]) -> bool:
        """Check if this strategy should be applied to the given context.
        
        Args:
            context: Operation context containing relevant data (e.g., 
                     reported_qty, station_id, factory_id, etc.)
        
        Returns:
            True if this strategy applies to the current context, False otherwise
        """
        pass
    
    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the recovery strategy on the given context.
        
        Args:
            context: Operation context
            
        Returns:
            Modified context or an error dict if strategy triggered
            Original context if no action needed
        """
        pass
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        """Return the name of this recovery strategy."""
        pass


class MesRecoveryResult:
    """Result container for strategy execution."""
    
    def __init__(self, strategy_name: str, applied: bool, context: Dict[str, Any], message: Optional[str] = None):
        self.strategy_name = strategy_name
        self.applied = applied
        self.context = context
        self.message = message
    
    def is_applied(self) -> bool:
        return self.applied
    
    def get_context(self) -> Dict[str, Any]:
        return self.context
    
    def get_message(self) -> Optional[str]:
        return self.message