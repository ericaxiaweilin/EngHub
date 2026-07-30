"""Work Order State Machine Module

Provides a unified, atomic state transition mechanism for work orders.
All state changes go through this single mechanism - no direct state mutations.
Defines valid state transitions and guard conditions.
"""

from enum import Enum, IntEnum
from typing import Optional, Set, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class WorkOrderStatus(IntEnum):
    """Work order status values with numeric ordering for transition validation."""
    
    CREATED = 0      # Created but not released
    RELEASED = 1     # Released to production line
    IN_PROGRESS = 2  # Currently being processed
    PAUSED = 3       # Temporarily halted
    RESUMED = 4      # Resume from paused
    COMPLETED = 5    # Fully completed
    CANCELLED = 6    # Cancelled before completion
    REWORK_NEEDED = 7  # Requires rework


class WorkOrderStateMachineError(Exception):
    """Base exception for work order state machine errors."""
    pass


class InvalidStateTransitionError(WorkOrderStateMachineError):
    """Raised when an invalid state transition is attempted."""
    
    def __init__(self, from_status: WorkOrderStatus, to_status: WorkOrderStatus, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        # Convert enum values to strings for error message
        allowed_strs = [str(s.value) for s in self._get_allowed_statuses(from_status)]
        super().__init__(f"Invalid transition: {from_status.value} -> {to_status.value}{f' ({reason})' if reason else f'. Allowed: [{allowed_strs}]'}")
    
    @staticmethod
    def _get_allowed_statuses(from_status: WorkOrderStatus) -> Set[WorkOrderStatus]:
        # Helper to get allowed statuses for error messaging
        rules = {
            WorkOrderStatus.CREATED: {WorkOrderStatus.RELEASED, WorkOrderStatus.CANCELLED},
            WorkOrderStatus.RELEASED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED},
            WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.PAUSED, WorkOrderStatus.COMPLETED, WorkOrderStatus.REWORK_NEEDED, WorkOrderStatus.CANCELLED},
            WorkOrderStatus.PAUSED: {WorkOrderStatus.RESUMED, WorkOrderStatus.CANCELLED},
            WorkOrderStatus.RESUMED: {WorkOrderStatus.IN_PROGRESS},
            WorkOrderStatus.COMPLETED: set(),
            WorkOrderStatus.CANCELLED: set(),
            WorkOrderStatus.REWORK_NEEDED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED},
        }
        return rules.get(from_status, set())


class StateGuardFailedError(WorkOrderStateMachineError):
    """Raised when a state guard condition fails."""
    
    def __init__(self, guard_name: str, context: Dict[str, Any]):
        self.guard_name = guard_name
        self.context = context
        super().__init__(f"State guard '{guard_name}' failed")


class WorkOrderStateMachine:
    """Work order state machine with atomic state transitions.
    
    All state transitions must go through this machine's transition() method.
    Direct mutation of work order status outside this class is prohibited.
    """
    
    # Valid transition rules: from_status -> set of allowed to_statuses
    _TRANSITION_RULES: Dict[WorkOrderStatus, Set[WorkOrderStatus]] = {
        WorkOrderStatus.CREATED: {WorkOrderStatus.RELEASED, WorkOrderStatus.CANCELLED},
        WorkOrderStatus.RELEASED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED},
        WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.PAUSED, WorkOrderStatus.COMPLETED, 
                                      WorkOrderStatus.REWORK_NEEDED, WorkOrderStatus.CANCELLED},
        WorkOrderStatus.PAUSED: {WorkOrderStatus.RESUMED, WorkOrderStatus.CANCELLED},
        WorkOrderStatus.RESUMED: {WorkOrderStatus.IN_PROGRESS},
        WorkOrderStatus.COMPLETED: set(),  # Terminal states
        WorkOrderStatus.CANCELLED: set(),
        WorkOrderStatus.REWORK_NEEDED: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED},
    }
    
    # Guard conditions
    _GUARD_CONDITIONS: Dict[tuple, Dict[str, dict]] = {
        (WorkOrderStatus.RELEASED, WorkOrderStatus.IN_PROGRESS): {
            "material_available": {"min_required": 1, "check_inventory": True},
            "equipment_available": {"check_capacity": True},
        },
        (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.COMPLETED): {
            "quality_checked": {"requires_inspection": True},
        },
    }
    
    def __init__(self):
        self._validate_rules()
    
    def _validate_rules(self) -> None:
        terminal_states = {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}
        for status, targets in self._TRANSITION_RULES.items():
            if status in terminal_states and len(targets) > 0:
                raise ValueError(f"Terminal state {status.value} has outgoing transitions")
        self._reachability_check()
    
    def _reachability_check(self) -> None:
        visited = set()
        stack = [status for status in self._TRANSITION_RULES if status not in 
                 {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}]
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            
            if self._can_reach_terminal(current):
                continue
            
            for next_status in self._TRANSITION_RULES.get(current, set()):
                if next_status not in visited:
                    stack.append(next_status)
        
        reachable = set(self._TRANSITION_RULES.keys()) - visited
        if reachable:
            logger.warning(f"Some states may not reach terminal: {[s.value for s in reachable]}")
    
    def _can_reach_terminal(self, start_state: WorkOrderStatus, visited=None) -> bool:
        if visited is None:
            visited = set()
        
        if start_state in {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}:
            return True
        
        if start_state in visited:
            return False
        
        visited.add(start_state)
        
        for next_status in self._TRANSITION_RULES.get(start_state, set()):
            if self._can_reach_terminal(next_status, visited.copy()):
                return True
        
        return False
    
    def can_transition(self, from_status: WorkOrderStatus, to_status: WorkOrderStatus, 
                      context: Optional[Dict[str, Any]] = None) -> bool:
        if from_status not in self._TRANSITION_RULES:
            raise InvalidStateTransitionError(from_status, to_status, f"Unknown source state: {from_status.value}")
        
        if to_status not in self._TRANSITION_RULES[from_status]:
            allowed = ", ".join(str(s.value) for s in self._TRANSITION_RULES[from_status])
            raise InvalidStateTransitionError(
                from_status, to_status, 
                f"From {from_status.value}, only allowed to go to: [{allowed}]"
            )
        
        if context is not None:
            self._check_guard_conditions(from_status, to_status, context)
        
        return True
    
    def _check_guard_conditions(self, from_status: WorkOrderStatus, to_status: WorkOrderStatus, 
                               context: Dict[str, Any]) -> None:
        transition_key = (from_status, to_status)
        
        if transition_key not in self._GUARD_CONDITIONS:
            return
        
        for guard_name, config in self._GUARD_CONDITIONS[transition_key].items():
            guard_func = getattr(self, f"_guard_{guard_name}", None)
            if guard_func is None:
                logger.warning(f"Guard function '{guard_name}' not found, skipping check")
                continue
            
            try:
                if not guard_func(context, config):
                    raise StateGuardFailedError(guard_name, context)
            except Exception as e:
                logger.error(f"Guard check '{guard_name}' raised exception: {e}")
                raise StateGuardFailedError(guard_name, context) from e
    
    def _guard_material_available(self, context: Dict[str, Any], config: dict) -> bool:
        if not config.get("check_inventory", False):
            return True
        
        material_id = context.get("material_id")
        required_qty = context.get("required_qty", 1)
        factory_id = context.get("factory_id", "F01")
        
        sample_inventory = {
            ("芯片模组", "F01"): 8000,
            ("鞋底组件", "F01"): 1500,
        }
        
        actual = sample_inventory.get((material_id, factory_id), 0)
        return actual >= required_qty
    
    def _guard_equipment_available(self, context: Dict[str, Any], config: dict) -> bool:
        if not config.get("check_capacity", False):
            return True
        
        equipment_id = context.get("equipment_id")
        sample_status = {
            "CNC-001": "running",
            "CNC-002": "running",
            "EDM-001": "running",
            "GRIND-001": "running",
        }
        
        return sample_status.get(equipment_id, "available") in ("running", "idle")
    
    def _guard_quality_checked(self, context: Dict[str, Any], config: dict) -> bool:
        if not config.get("requires_inspection", False):
            return True
        
        inspection_passed = context.get("inspection_passed", False)
        return bool(inspection_passed)
    
    def transition(self, from_status: WorkOrderStatus, to_status: WorkOrderStatus, 
                  context: Optional[Dict[str, Any]] = None) -> WorkOrderStatus:
        self.can_transition(from_status, to_status, context)
        
        logger.info(f"Work order state transition: {from_status.value} -> {to_status.value}")
        return to_status
    
    def get_valid_next_states(self, status: WorkOrderStatus) -> Set[WorkOrderStatus]:
        return self._TRANSITION_RULES.get(status, set()).copy()
    
    def is_terminal(self, status: WorkOrderStatus) -> bool:
        return status in {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}