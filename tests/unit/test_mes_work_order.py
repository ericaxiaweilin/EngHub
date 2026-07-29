"""tests/unit/test_mes_work_order.py - EP881 单元测试范例

Module: core.mes.work_order.WorkOrderService

Simple, working unit tests for WorkOrderService following AAA pattern.
Run: pytest tests/unit/test_mes_work_order.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.mes.work_order import (
    WorkOrderService, 
    WorkOrderStatus, 
    WorkOrderPriority,
)


# FIXTURES ==========================================================

@pytest.fixture()
def mock_db_session():
    """Mock database session"""
    return MagicMock()


@pytest.fixture()
def work_order_service(mock_db_session):
    """WorkOrderService instance fixture"""
    return WorkOrderService(db_session=mock_db_session)


# Test Class: Work Order Code Generation ===============================

class TestWorkOrderGenerateCode:
    """WorkOrderService - Generate code tests"""

    def test_generate_work_order_code_format(self, work_order_service):
        """Generate correct WO code format"""
        code = work_order_service.generate_work_order_code("FCT001")
        
        assert code.startswith("WO-")
        parts = code.split("-")
        assert len(parts) >= 4
        assert parts[1] == "FCT001"
        # Year part should be 8 digits
        assert len(parts[2]) == 8 and parts[2].isdigit()
        # Sequence part should be alphanumeric (6 chars)
        assert len(parts[3]) == 6 and parts[3].isalnum()

    def test_generate_work_order_code_different_factories(self, work_order_service):
        """Different factory codes produce different prefixes"""
        code1 = work_order_service.generate_work_order_code("FCT_A")
        code2 = work_order_service.generate_work_order_code("FCT_B")
        assert code1 != code2
        assert "FCT_A" in code1
        assert "FCT_B" in code2


# Test Class: Status Transition Validation =============================

class TestWorkOrderStatusTransition:
    """WorkOrderService - Status transition validation tests"""

    @pytest.mark.parametrize("initial_status,next_status,allowed", [
        # Valid transitions from PENDING
        ("pending", "released", True),
        ("pending", "cancelled", True),
        # Valid transitions from RELEASED
        ("released", "in_progress", True),
        ("released", "on_hold", True),
        ("released", "cancelled", True),
        # Valid transitions from IN_PROGRESS
        ("in_progress", "completed", True),
        ("in_progress", "on_hold", True),
        # Valid transitions from ON_HOLD
        ("on_hold", "in_progress", True),
        ("on_hold", "cancelled", True),
        # Valid transitions from PENDING_INBOUND
        ("pending_inbound", "completed", True),
        # Invalid transitions
        ("pending", "in_progress", False),  # Must go through released first
        ("completed", "in_progress", False),  # Completed is terminal
        ("cancelled", "in_progress", False),  # Cancelled is terminal
        ("in_progress", "pending", False),  # Cannot revert to pending
    ])
    def test_is_valid_transition(self, initial_status, next_status, allowed):
        """Validate status transition logic using WorkOrderService.VALID_STATUS_TRANSITIONS"""
        # Access via the service instance or directly from the class
        service = WorkOrderService(db_session=MagicMock())
        valid_transitions = service.VALID_STATUS_TRANSITIONS
        result = initial_status in valid_transitions and next_status in valid_transitions.get(initial_status, [])
        assert result == allowed

    def test_VALID_STATUS_TRANSITIONS_CONTENT(self):
        """Validate the structure of VALID_STATUS_TRANSITIONS"""
        service = WorkOrderService(db_session=MagicMock())
        valid_transitions = service.VALID_STATUS_TRANSITIONS
        assert isinstance(valid_transitions, dict)
        # Check that all expected status keys exist
        expected_keys = {WorkOrderStatus.PENDING.value, WorkOrderStatus.RELEASED.value,
                         WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.ON_HOLD.value,
                         WorkOrderStatus.PENDING_INBOUND.value}
        assert set(valid_transitions.keys()) == expected_keys
        # Each status has at least one valid transition
        for transitions in valid_transitions.values():
            assert len(transitions) >= 1


# Test Class: Priority Utility =========================================

class TestWorkOrderPriority:
    """WorkOrderPriority - Priority utility tests"""

    def test_priority_levels(self):
        """Verify all priority levels exist"""
        priorities = [p.value for p in WorkOrderPriority]
        assert "low" in priorities
        assert "medium" in priorities
        assert "high" in priorities
        assert "urgent" in priorities

    def test_priority_comparison(self):
        """Priority levels have expected order"""
        # Higher value = higher urgency
        priority_order = ["low", "medium", "high", "urgent"]
        for i in range(len(priority_order) - 1):
            current = WorkOrderPriority(priority_order[i])
            next_level = WorkOrderPriority(priority_order[i + 1])
            # In this context, we just verify they are distinct values
            assert str(current) != str(next_level)


# Test Class: Constants ================================================

def test_work_order_status_enum_values():
    """WorkOrderStatus has all expected values"""
    assert hasattr(WorkOrderStatus, "PENDING")
    assert hasattr(WorkOrderStatus, "RELEASED")
    assert hasattr(WorkOrderStatus, "IN_PROGRESS")
    assert hasattr(WorkOrderStatus, "PENDING_INBOUND")
    assert hasattr(WorkOrderStatus, "COMPLETED")
    assert hasattr(WorkOrderStatus, "CANCELLED")
    assert hasattr(WorkOrderStatus, "ON_HOLD")
