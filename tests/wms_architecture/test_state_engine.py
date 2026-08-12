"""Tests for WMS Architecture - StateTransitionEngine."""

import pytest
from api.services.wms_architecture.state.engine import StateTransitionEngine, InventoryState, StateTransitionError


class TestStateTransitionEngine:
    """Test StateTransitionEngine."""
    
    def test_init(self):
        """Test engine initialization."""
        engine = StateTransitionEngine()
        assert engine is not None
    
    def test_valid_transitions(self):
        """Test valid state transitions."""
        engine = StateTransitionEngine()
        
        # AVAILABLE -> RESERVED
        assert engine.can_transition(InventoryState.AVAILABLE, InventoryState.RESERVED)
        
        # AVAILABLE -> QC_HOLD
        assert engine.can_transition(InventoryState.AVAILABLE, InventoryState.QC_HOLD)
        
        # QC_HOLD -> AVAILABLE
        assert engine.can_transition(InventoryState.QC_HOLD, InventoryState.AVAILABLE)
        
        # QC_HOLD -> SCRAPPED
        assert engine.can_transition(InventoryState.QC_HOLD, InventoryState.SCRAPPED)
    
    def test_invalid_transitions(self):
        """Test invalid state transitions."""
        engine = StateTransitionEngine()
        
        # SCRAPPED is terminal
        assert not engine.can_transition(InventoryState.SCRAPPED, InventoryState.AVAILABLE)
        
        # Cannot transition from RESERVED to QC_HOLD directly
        assert not engine.can_transition(InventoryState.RESERVED, InventoryState.QC_HOLD)
    
    def test_transition_with_guards(self):
        """Test state transitions with guard conditions."""
        engine = StateTransitionEngine()
        
        # AVAILABLE -> RESERVED with work order
        context = {"work_order_id": "WO001"}
        assert engine.can_transition(InventoryState.AVAILABLE, InventoryState.RESERVED, context)
        
        # AVAILABLE -> RESERVED without work order
        context = {}
        assert not engine.can_transition(InventoryState.AVAILABLE, InventoryState.RESERVED, context)
    
    def test_transition_raises_error(self):
        """Test that invalid transitions raise errors."""
        engine = StateTransitionEngine()
        
        with pytest.raises(StateTransitionError):
            engine.transition(InventoryState.SCRAPPED, InventoryState.AVAILABLE)
    
    def test_is_terminal(self):
        """Test terminal state detection."""
        engine = StateTransitionEngine()
        
        assert engine.is_terminal(InventoryState.SCRAPPED)
        assert not engine.is_terminal(InventoryState.AVAILABLE)
    
    def test_get_valid_transitions(self):
        """Test getting valid transitions."""
        engine = StateTransitionEngine()
        
        valid = engine.get_valid_transitions(InventoryState.AVAILABLE)
        assert InventoryState.RESERVED in valid
        assert InventoryState.QC_HOLD in valid
        assert InventoryState.FROZEN in valid
        assert InventoryState.SCRAPPED in valid  # Can scrap from available
    
    def test_transition_history(self):
        """Test transition history tracking."""
        engine = StateTransitionEngine()
        context = {"work_order_id": "WO001"}  # Provide required guard condition
        
        # Perform transition
        engine.transition(InventoryState.AVAILABLE, InventoryState.RESERVED, context)
        
        # Check history
        history = engine.get_transition_history(context)
        assert len(history) == 1
        assert history[0]["from_state"] == "available"
        assert history[0]["to_state"] == "reserved"
        assert "timestamp" in history[0]
        assert "context" in history[0]