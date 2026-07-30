"""State Transition Engine for Chat Tool-Calling Loop.

Manages the stateful progression through multi-turn tool-calling conversations
with proper guard conditions, recovery strategy coordination, and safe state transitions.

All state changes go through this single atomic mechanism — no direct payload mutation outside the engine.
"""

from enum import Enum
from typing import Optional, Set, Dict, Any
from datetime import datetime


class ChatState(Enum):
    """Possible states in the chat tool-calling conversation."""
    
    IDLE = "idle"           # Waiting for new message
    PROCESSING_TOOL_LOOP = "tool_loop"  # Currently executing tool-calling sequence
    VISION_FALLBACK = "vision_fallback"   # Attempting vision-only fallback (images stripped)
    TOOL_FALLBACK = "tool_fallback"      # Attempting tools-free fallback (tool_mode disabled)
    DEGRADED = "degraded"         # In degraded mode due to unrecoverable error
    COMPLETE = "complete"         # Conversation finished with final response


class StateGuardFailedError(Exception):
    """Raised when a state transition guard condition fails."""
    
    def __init__(self, guard_name: str, context: Dict[str, Any]):
        self.guard_name = guard_name
        self.context = context
        super().__init__(f"State guard '{guard_name}' failed")


class StateTransitionEngine:
    """Atomic state transition manager for chat conversations.
    
    Maintains conversation state across multiple turns, ensuring valid
    state transitions and applying guard conditions before each change.
    All state mutations must go through this engine.
    """
    
    # Valid transition rules: from_state -> set of allowed to_states
    _TRANSITION_RULES: Dict[ChatState, Set[ChatState]] = {
        ChatState.IDLE: {ChatState.PROCESSING_TOOL_LOOP},
        ChatState.PROCESSING_TOOL_LOOP: {
            ChatState.VISION_FALLBACK,
            ChatState.TOOL_FALLBACK,
            ChatState.DEGRADED,
            ChatState.COMPLETE,
        },
        ChatState.VISION_FALLBACK: {
            ChatState.PROCESSING_TOOL_LOOP,  # Try original path again after stripping images
            ChatState.TOOL_FALLBACK,         # If vision also fails, try tool fallback
            ChatState.DEGRADED,
            ChatState.COMPLETE,
        },
        ChatState.TOOL_FALLBACK: {
            ChatState.DEGRADED,
            ChatState.COMPLETE,
        },
        ChatState.DEGRADED: {ChatState.COMPLETE},
        ChatState.COMPLETE: set(),  # Terminal state
    }
    
    # Guard conditions per transition
    _GUARD_CONDITIONS: Dict[tuple, Dict[str, dict]] = {
        (ChatState.PROCESSING_TOOL_LOOP, ChatState.VISION_FALLBACK): {
            "has_images": {"check_image_records": True},
        },
        (ChatState.PROCESSING_TOOL_LOOP, ChatState.TOOL_FALLBACK): {
            "gateway_supports_tools": {"check_tool_capability": True},
        },
    }
    
    def __init__(self, max_rounds: int = 5):
        self.max_rounds = max_rounds
        self._validate_rules()
    
    def _validate_rules(self) -> None:
        """Ensure all non-terminal states have at least one outgoing transition."""
        terminal_states = {ChatState.COMPLETE}
        for state, targets in self._TRANSITION_RULES.items():
            if state not in terminal_states and len(targets) == 0:
                raise ValueError(f"State {state.value} has no valid outgoing transitions")
    
    def can_transition(self, from_state: ChatState, to_state: ChatState, context: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a state transition is valid (includes guard conditions)."""
        if from_state not in self._TRANSITION_RULES:
            return False
        
        if to_state not in self._TRANSITION_RULES[from_state]:
            return False
        
        if context is not None:
            return self._check_guard_conditions(from_state, to_state, context)
        
        return True
    
    def _check_guard_conditions(self, from_state: ChatState, to_state: ChatState, context: Dict[str, Any]) -> bool:
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
    
    def _guard_has_images(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if there are image records that require vision processing."""
        if not config.get("check_image_records", False):
            return True
        return bool(context.get("image_records", [])) or context.get("has_vision_input", False)
    
    def _guard_gateway_supports_tools(self, context: Dict[str, Any], config: dict) -> bool:
        """Check if the LLM gateway supports tool calling mode."""
        if not config.get("check_tool_capability", False):
            return True
        # In production, check gateway capabilities via model list / feature detection
        # For now assume supported
        return True
    
    def transition(self, from_state: ChatState, to_state: ChatState, context: Optional[Dict[str, Any]] = None) -> ChatState:
        """Atomically perform a state transition with validation."""
        if not self.can_transition(from_state, to_state, context):
            # Determine why it failed for error reporting
            if from_state not in self._TRANSITION_RULES:
                raise ValueError(f"Unknown source state: {from_state.value}")
            if to_state not in self._TRANSITION_RULES[from_state]:
                allowed = [s.value for s in self._TRANSITION_RULES[from_state]]
                raise ValueError(f"Cannot transition from {to_state.value} to {allowed}")
            
            if context is not None:
                # Check guard conditions specifically
                for guard_name in self._GUARD_CONDITIONS.get((from_state, to_state), {}):
                    guard_func = getattr(self, f"_guard_{guard_name}", None)
                    if guard_func and not guard_func(context, {}):
                        raise StateGuardFailedError(guard_name, context)
            
            # Generic failure
            raise ValueError(f"Invalid state transition: {from_state.value} -> {to_state.value}")
        
        # Apply any side effects of the transition (updating context)
        self._apply_transition_effects(from_state, to_state, context)
        
        # Return the new state
        return to_state
    
    def _apply_transition_effects(self, from_state: ChatState, to_state: ChatState, context: Optional[Dict[str, Any]]) -> None:
        """Apply any side effects when transitioning between states."""
        if context is None:
            return
        
        if to_state == ChatState.VISION_FALLBACK:
            # Mark that we're in vision fallback mode
            context["fallback_mode"] = "vision"
            # Strip image records from messages (handled by executor)
            context["vision_dropped"] = True
        
        elif to_state == ChatState.TOOL_FALLBACK:
            context["fallback_mode"] = "tool"
            context["tool_mode_disabled"] = True
        
        elif to_state == ChatState.DEGRADED:
            context["degraded"] = True
            context["degradation_reason"] = "unrecoverable error"
    
    def is_terminal(self, state: ChatState) -> bool:
        """Check if a state is terminal (no outgoing transitions)."""
        return state in {ChatState.COMPLETE}