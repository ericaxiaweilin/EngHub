"""Base classes for chat recovery strategies."""

from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class RecoveryResult:
    """Result of applying a recovery strategy."""
    
    def __init__(self, strategy_name: str, applied: bool, context: Dict[str, Any], message: Optional[str] = None):
        self.strategy_name = strategy_name
        self.applied = applied
        self.context = context
        self.message = message
    
    def __repr__(self):
        return f"RecoveryResult(strategy={self.strategy_name}, applied={self.applied}, msg={self.message})"


class MesRecoveryStrategy(ABC):
    """Abstract base class for all recovery executor strategies."""
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        pass
    
    @abstractmethod
    def should_apply(self, context: Dict[str, Any]) -> bool:
        pass
    
    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        pass