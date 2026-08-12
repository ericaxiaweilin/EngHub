"""State Transition Engine for WMS Inventory.

Manages the stateful progression of inventory items through
different states with proper guard conditions and safe transitions.
"""

from enum import Enum
from typing import Optional, Set, Dict, Any, List
from datetime import datetime


class InventoryState(Enum):
    """Possible states for inventory items."""
    
    AVAILABLE = "available"         # 可用库存
    RESERVED = "reserved"           # 预留库存
    QC_HOLD = "qc_hold"             # 待验库存
    FROZEN = "frozen"               # 冻结库存
    QUARANTINE = "quarantine"       # 隔离库存
    SCRAPPED = "scrapped"           # 报废库存


class StateTransitionError(Exception):
    """Raised when a state transition is invalid."""
    
    def __init__(self, from_state: InventoryState, to_state: InventoryState, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}{f': {reason}' if reason else ''}")


class StateGuardFailedError(Exception):
    """Raised when a state transition guard condition fails."""
    
    def __init__(self, guard_name: str, context: Dict[str, Any]):
        self.guard_name = guard_name
        self.context = context
        super().__init__(f"State guard '{guard_name}' failed")


class StateTransitionEngine:
    """Atomic state transition manager for WMS inventory.
    
    Maintains inventory state across operations, ensuring valid
    state transitions and applying guard conditions before each change.
    All state mutations must go through this engine.
    """
    
    # Valid transition rules: from_state -> set of allowed to_states
    _TRANSITION_RULES: Dict[InventoryState, Set[InventoryState]] = {
        InventoryState.AVAILABLE: {
            InventoryState.RESERVED,
            InventoryState.QC_HOLD,
            InventoryState.FROZEN,
            InventoryState.SCRAPPED,
        },
        InventoryState.RESERVED: {
            InventoryState.AVAILABLE,
            InventoryState.FROZEN,
            InventoryState.QUARANTINE,
        },
        InventoryState.QC_HOLD: {
            InventoryState.AVAILABLE,
            InventoryState.FROZEN,
            InventoryState.QUARANTINE,
            InventoryState.SCRAPPED,
        },
        InventoryState.FROZEN: {
            InventoryState.AVAILABLE,
            InventoryState.RESERVED,
            InventoryState.SCRAPPED,
        },
        InventoryState.QUARANTINE: {
            InventoryState.AVAILABLE,
            InventoryState.FROZEN,
            InventoryState.SCRAPPED,
        },
        InventoryState.SCRAPPED: set(),  # Terminal state
    }
    
    # Guard conditions per transition
    _GUARD_CONDITIONS: Dict[tuple, Dict[str, dict]] = {
        (InventoryState.AVAILABLE, InventoryState.RESERVED): {
            "has_work_order": {"check_work_order": True},
        },
        (InventoryState.AVAILABLE, InventoryState.QC_HOLD): {
            "has_inspection": {"check_inspection_required": True},
        },
        (InventoryState.QC_HOLD, InventoryState.AVAILABLE): {
            "inspection_passed": {"check_inspection_result": "PASS"},
        },
        (InventoryState.QC_HOLD, InventoryState.SCRAPPED): {
            "inspection_failed": {"check_inspection_result": "FAIL"},
        },
    }
    
    def __init__(self):
        self._validate_rules()
    
    def _validate_rules(self) -> None:
        """Ensure all non-terminal states have at least one outgoing transition."""
        terminal_states = {InventoryState.SCRAPPED}
        for state, targets in self._TRANSITION_RULES.items():
            if state not in terminal_states and len(targets) == 0:
                raise ValueError(f"State {state.value} has no valid outgoing transitions")
    
    def can_transition(self, from_state: InventoryState, to_state: InventoryState, context: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a state transition is valid (includes guard conditions).
        
        Args:
            from_state: Current state
            to_state: Target state
            context: Optional context for guard conditions
            
        Returns:
            True if transition is valid
        """
        if from_state not in self._TRANSITION_RULES:
            return False
        
        if to_state not in self._TRANSITION_RULES[from_state]:
            return False
        
        if context is not None:
            return self._check_guard_conditions(from_state, to_state, context)
        
        return True
    
    def _check_guard_conditions(self, from_state: InventoryState, to_state: InventoryState, context: Dict[str, Any]) -> bool:
        """Check guard conditions for a specific transition."""
        transition_key = (from_state, to_state)
        
        if transition_key not in self._GUARD_CONDITIONS:
            return True  # No guards defined for this transition
        
        for guard_name, config in self._GUARD_CONDITIONS[transition_key].items():
            guard_func = getattr(self, f"_guard_{guard_name}", None)
            if guard_func is None:
                continue  # Skip unknown guards
            
            try:
                if not guard_func(context, config):
                    return False
            except Exception:
                return False  # Guard check failure prevents transition
        
        return True
    
    def _guard_has_work_order(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if there is a work order for reservation."""
        if not config.get("check_work_order", False):
            return True
        return bool(context.get("work_order_id"))
    
    def _guard_has_inspection(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if inspection is required."""
        if not config.get("check_inspection_required", False):
            return True
        # For now, assume all inventory may require inspection
        return True
    
    def _guard_inspection_passed(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if inspection passed."""
        expected_result = config.get("check_inspection_result")
        if not expected_result:
            return True
        return context.get("inspection_result") == expected_result
    
    def _guard_inspection_failed(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if inspection failed."""
        expected_result = config.get("check_inspection_result")
        if not expected_result:
            return True
        return context.get("inspection_result") == expected_result
    
    def transition(self, from_state: InventoryState, to_state: InventoryState, context: Optional[Dict[str, Any]] = None) -> InventoryState:
        """Atomically perform a state transition with validation.
        
        Args:
            from_state: Current state
            to_state: Target state
            context: Optional context for guard conditions
            
        Returns:
            The new state
            
        Raises:
            StateTransitionError: If transition is invalid
            StateGuardFailedError: If guard condition fails
        """
        if not self.can_transition(from_state, to_state, context):
            # Determine why it failed for error reporting
            if from_state not in self._TRANSITION_RULES:
                raise StateTransitionError(from_state, to_state, f"Unknown source state: {from_state.value}")
            if to_state not in self._TRANSITION_RULES[from_state]:
                allowed = [s.value for s in self._TRANSITION_RULES[from_state]]
                raise StateTransitionError(from_state, to_state, f"Invalid transition to {to_state.value}. Allowed: {allowed}")
            
            if context is not None:
                # Check guard conditions specifically
                for guard_name in self._GUARD_CONDITIONS.get((from_state, to_state), {}):
                    guard_func = getattr(self, f"_guard_{guard_name}", None)
                    if guard_func and not guard_func(context, {}):
                        raise StateGuardFailedError(guard_name, context)
            
            # Generic failure
            raise StateTransitionError(from_state, to_state)
        
        # Apply any side effects of the transition (updating context)
        self._apply_transition_effects(from_state, to_state, context)
        
        # Return the new state
        return to_state
    
    def _apply_transition_effects(self, from_state: InventoryState, to_state: InventoryState, context: Optional[Dict[str, Any]]) -> None:
        """Apply any side effects when transitioning between states."""
        if context is None:
            return
        
        # Record transition history
        if "transition_history" not in context:
            context["transition_history"] = []
        
        context["transition_history"].append({
            "from_state": from_state.value,
            "to_state": to_state.value,
            "timestamp": datetime.utcnow().isoformat(),
            "context": context.copy(),
        })
    
    def is_terminal(self, state: InventoryState) -> bool:
        """Check if a state is terminal (no outgoing transitions).
        
        Args:
            state: State to check
            
        Returns:
            True if state is terminal
        """
        return state in {InventoryState.SCRAPPED}
    
    def get_valid_transitions(self, state: InventoryState) -> Set[InventoryState]:
        """Get all valid transitions from a state.
        
        Args:
            state: Current state
            
        Returns:
            Set of valid target states
        """
        return self._TRANSITION_RULES.get(state, set()).copy()
    
    def get_transition_history(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get the transition history for a context.
        
        Args:
            context: Context with transition history
            
        Returns:
            List of transition records
        """
        return context.get("transition_history", [])