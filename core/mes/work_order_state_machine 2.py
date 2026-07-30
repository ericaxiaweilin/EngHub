"""
Work Order State Machine Configuration - Default Templates
=========================================================

This module provides default state machine definitions that can be used as fallbacks
when the database-backed configuration is not available or during initial setup.

These defaults match the original hard-coded TRANSITIONS and ACTION_ROLE_GATES.
They can be managed through the UI/API and persisted to the database for dynamic
configuration without code changes.

Reference:
- WOStatus enumeration defines all possible states
- TRANSITIONS defines valid state-to-state transitions per state
- ACTION_ROLE_GATES defines required roles for each business action
"""

from typing import List, Dict, Any

# ============================================================
# Status Enumeration (matches WOStatus in work_order_service.py)
# ============================================================
class WOStatus:
    """Work order status values"""
    DRAFT = "draft"              # 草稿
    PENDING = "pending"          # 待下发
    RELEASED = "released"        # 已下达
    IN_PROGRESS = "in_progress"  # 生产中
    ON_HOLD = "on_hold"          # 暂停
    PENDING_INBOUND = "pending_inbound"  # 待入库
    COMPLETED = "completed"      # 已完成
    CLOSED = "closed"            # 已关闭
    CANCELLED = "cancelled"      # 已取消

    ALL = [DRAFT, PENDING, RELEASED, IN_PROGRESS, ON_HOLD, PENDING_INBOUND, COMPLETED, CLOSED, CANCELLED]


# ============================================================
# State Transitions Configuration
# ============================================================
TRANSITIONS: Dict[str, List[str]] = {
    """State transition rules: current_state -> list of allowed next states"""
    WOStatus.DRAFT: [WOStatus.PENDING, WOStatus.CANCELLED],
    WOStatus.PENDING: [WOStatus.RELEASED, WOStatus.CANCELLED],
    WOStatus.RELEASED: [WOStatus.IN_PROGRESS, WOStatus.ON_HOLD, WOStatus.CANCELLED],
    WOStatus.IN_PROGRESS: [WOStatus.ON_HOLD, WOStatus.PENDING_INBOUND, WOStatus.COMPLETED, WOStatus.CANCELLED],
    WOStatus.ON_HOLD: [WOStatus.IN_PROGRESS, WOStatus.CANCELLED],
    WOStatus.PENDING_INBOUND: [WOStatus.COMPLETED],
    WOStatus.COMPLETED: [],  # Terminal state - no outgoing transitions
    WOStatus.CLOSED: [],  # Terminal state - no outgoing transitions
    WOStatus.CANCELLED: [],  # Terminal state - no outgoing transitions
}


# ============================================================
# Action Role Gates Configuration
# ============================================================
ACTION_ROLE_GATES: Dict[str, List[str]] = {
    """Action permission gates: action -> list of required roles"""
    "release": ["factory_manager", "production_manager", "admin"],   # 下达需管理角色
    "complete": ["factory_manager", "quality_manager", "admin"],     # 完工需品质确认
    "close": ["factory_manager", "admin"],                           # 关闭需厂长/管理员
    "pause": ["operator", "team_leader"],                            # 暂停需操作员或班组长
    "resume": ["operator", "team_leader"],                           # 恢复需操作员或班组长
    "cancel": ["operator", "team_leader"],                           # 取消需操作员或班组长
}


# ============================================================
# Display Configuration (for UI presentation)
# ============================================================
DISPLAY: Dict[str, str] = {
    WOStatus.DRAFT: "草稿",
    WOStatus.PENDING: "待下发",
    WOStatus.RELEASED: "已下达",
    WOStatus.IN_PROGRESS: "生产中",
    WOStatus.ON_HOLD: "暂停",
    WOStatus.PENDING_INBOUND: "待入库",
    WOStatus.COMPLETED: "已完成",
    WOStatus.CLOSED: "已关闭",
    WOStatus.CANCELLED: "已取消",
}


COLORS: Dict[str, str] = {
    WOStatus.DRAFT: "default",
    WOStatus.PENDING: "processing",
    WOStatus.RELEASED: "blue",
    WOStatus.IN_PROGRESS: "blue",
    WOStatus.ON_HOLD: "warning",
    WOStatus.PENDING_INBOUND: "cyan",
    WOStatus.COMPLETED: "success",
    WOStatus.CLOSED: "default",
    WOStatus.CANCELLED: "error",
}


# ============================================================
# Utility Functions
# ============================================================
def get_all_states() -> List[str]:
    """Return all possible work order statuses."""
    return WOStatus.ALL

def is_valid_transition(from_status: str, to_status: str, factory_id: str = "ALL") -> bool:
    """Check if a state transition is allowed based on default rules.
    
    In production, this should query the database version instead.
    """
    allowed = TRANSITIONS.get(from_status, [])
    return to_status in allowed

def is_action_permitted(action: str, user_role: str, user_factory: str = "ALL") -> bool:
    """Check if an action is permitted for the given role.
    
    In production, this should query database gates with factory filter.
    """
    required_roles = ACTION_ROLE_GATES.get(action, [])
    return user_role in required_roles


__all__ = [
    "WOStatus",
    "TRANSITIONS",
    "ACTION_ROLE_GATES",
    "DISPLAY",
    "COLORS",
    "get_all_states",
    "is_valid_transition",
    "is_action_permitted",
]
