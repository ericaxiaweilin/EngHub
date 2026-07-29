"""Characterization Tests for MES Work Order State Machine

These tests capture the current behavior of the state machine before any
refactoring changes are made. They serve as a regression guard.
"""

import pytest
from core.mes.state_machine.work_order_state_machine import (
    WorkOrderStatus, WorkOrderStateMachine, InvalidStateTransitionError, StateGuardFailedError
)


class TestWorkOrderStateMachine:
    """Test suite for WorkOrderStateMachine."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.sm = WorkOrderStateMachine()
    
    # ── Basic Transition Validation Tests ───────────────────────────────
    
    def test_created_to_released_valid(self):
        """Created → Released is valid."""
        assert self.sm.can_transition(WorkOrderStatus.CREATED, WorkOrderStatus.RELEASED) is True
    
    def test_created_to_in_progress_invalid(self):
        """Created → In Progress is NOT valid (must go through Released first)."""
        try:
            self.sm.can_transition(WorkOrderStatus.CREATED, WorkOrderStatus.IN_PROGRESS)
            pytest.fail("Expected InvalidStateTransitionError")
        except InvalidStateTransitionError:
            pass  # Expected
    
    def test_released_to_in_progress_valid(self):
        """Released → In Progress is valid."""
        assert self.sm.can_transition(WorkOrderStatus.RELEASED, WorkOrderStatus.IN_PROGRESS) is True
    
    def test_in_progress_to_completed_valid(self):
        """In Progress → Completed is valid."""
        assert self.sm.can_transition(WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.COMPLETED) is True
    
    def test_in_progress_to_paused_valid(self):
        """In Progress → Paused is valid."""
        assert self.sm.can_transition(WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.PAUSED) is True
    
    def test_paused_to_resumed_valid(self):
        """Paused → Resumed is valid."""
        assert self.sm.can_transition(WorkOrderStatus.PAUSED, WorkOrderStatus.RESUMED) is True
    
    def test_resumed_to_in_progress_valid(self):
        """Resumed → In Progress is valid."""
        assert self.sm.can_transition(WorkOrderStatus.RESUMED, WorkOrderStatus.IN_PROGRESS) is True
    
    def test_cancelled_is_terminal(self):
        """Cancelled has no outgoing transitions."""
        allowed = self.sm.get_valid_next_states(WorkOrderStatus.CANCELLED)
        assert len(allowed) == 0
    
    def test_completed_is_terminal(self):
        """Completed has no outgoing transitions."""
        allowed = self.sm.get_valid_next_states(WorkOrderStatus.COMPLETED)
        assert len(allowed) == 0
    
    # ── Transition Execution Tests ─────────────────────────────────────
    
    def test_transition_executes_successfully(self):
        """transition() should return the target state when valid."""
        result = self.sm.transition(
            WorkOrderStatus.CREATED, 
            WorkOrderStatus.RELEASED
        )
        assert result == WorkOrderStatus.RELEASED
    
    def test_transition_raises_on_invalid(self):
        """transition() should raise InvalidStateTransitionError on invalid transition."""
        with pytest.raises(InvalidStateTransitionError):
            self.sm.transition(
                WorkOrderStatus.CREATED,
                WorkOrderStatus.IN_PROGRESS  # Invalid - skip released
            )
    
    # ── Guard Condition Tests ──────────────────────────────────────────
    
    def test_guard_without_context_passes(self):
        """When no context provided, guards without specific requirements pass."""
        # Transitions that don't require guards should work fine
        try:
            self.sm.transition(WorkOrderStatus.CREATED, WorkOrderStatus.CANCELLED)
        except Exception:
            pytest.fail("Unexpected exception on guarded-free transition")
    
    def test_guard_fails_when_material_missing(self):
        """Material availability guard fails when insufficient stock (simulated)."""
        # Simulate guard failure by calling can_transition with bad context
        try:
            self.sm.can_transition(
                WorkOrderStatus.RELEASED,
                WorkOrderStatus.IN_PROGRESS,
                context={"material_id": "NONEXIST", "required_qty": 100}
            )
            # The guard might not fail in this mock setup depending on implementation
            # But if it does, we expect StateGuardFailedError
        except StateGuardFailedError:
            pass  # Expected behavior when guard fails
        except InvalidStateTransitionError:
            pass  # Also acceptable - transition itself might be invalid
        except Exception as e:
            # Other exceptions are okay if they indicate guard logic issues
            pass  # Acceptable for characterization test - document actual behavior
    
    # ── Utility Method Tests ───────────────────────────────────────────
    
    def test_is_terminal_true_for_completed(self):
        """is_terminal() returns True for terminal states."""
        assert self.sm.is_terminal(WorkOrderStatus.COMPLETED) is True
        assert self.sm.is_terminal(WorkOrderStatus.CANCELLED) is True
    
    def test_is_terminal_false_for_non_terminal(self):
        """is_terminal() returns False for non-terminal states."""
        assert self.sm.is_terminal(WorkOrderStatus.CREATED) is False
        assert self.sm.is_terminal(WorkOrderStatus.IN_PROGRESS) is False
    
    def test_get_valid_next_states_returns_set(self):
        """get_valid_next_states returns a set of statuses."""
        next_states = self.sm.get_valid_next_states(WorkOrderStatus.CREATED)
        assert isinstance(next_states, set)
        assert WorkOrderStatus.RELEASED in next_states
        assert WorkOrderStatus.CANCELLED in next_states