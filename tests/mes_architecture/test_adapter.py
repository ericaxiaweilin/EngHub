"""Characterization Tests for MES Adapter

Tests the MESAdapter orchestration behavior by mocking its dependencies.
Ensures the adapter correctly delegates to components and formats responses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Import the actual adapter to test
from api.services.mes_architecture.adapters.mes_adapter import MESAdapter, get_mes_adapter
from api.services.mes_architecture.repository.mes_repository import MESRepository
from api.services.mes_architecture.formatter.response_formatter import ResponseFormatter
from core.mes.state_machine.work_order_state_machine import WorkOrderStatus, InvalidStateTransitionError
from api.services.mes_architecture.recovery.base import MesRecoveryResult


class TestMESAdapter:
    """Test suite for MESAdapter."""
    
    def setup_method(self):
        """Set up mock objects for testing."""
        self.mock_db = AsyncMock()
        self.mock_repo = MagicMock()
        self.mock_formatter = ResponseFormatter()
        self.mock_sm = MagicMock()
        
        # Build adapter with mocks
        self.adapter = MESAdapter(
            db=self.mock_db,
            current_user_id="test_user_123"
        )
        
        # Replace real components with mocks for testing
        self.adapter.state_machine = self.mock_sm
        self.adapter.repository = self.mock_repo
        self.adapter.response_formatter = self.mock_formatter
    
    # ── get_work_orders Tests ────────────────────────────────────────
    
    @patch.object(MESAdapter, '_validate_factory_access', return_value=True)
    async def test_get_work_orders_calls_repo_with_criteria(self, mock_validate):
        """get_work_orders should call repository with parsed criteria."""
        # Setup mock response
        self.mock_repo.find_work_orders = AsyncMock(return_value=[])
        self.mock_repo.count_work_orders = AsyncMock(return_value=0)
        self.mock_db.session_factory = AsyncMock(return_value=self.mock_db)
        
        # Call adapter
        result = await self.adapter.get_work_orders(
            factory_id="F01",
            status="in_progress",
            page=1,
            size=10
        )
        
        # Verify repository was called
        self.mock_repo.find_work_orders.assert_called_once()
        self.mock_repo.count_work_orders.assert_called_once()
        
        # Verify result structure
        assert "items" in result
        assert "total" in result
        assert "page" in result
    
    @patch.object(MESAdapter, '_validate_factory_access', return_value=False)
    async def test_get_work_orders_rejects_unauthorized_factory(self, mock_validate):
        """Unauthorized factory access should raise HTTP 403."""
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await self.adapter.get_work_orders(factory_id="INVALID_FACTORY")
        
        assert exc_info.value.status_code == 403
    
    # ── update_work_order_status Tests ───────────────────────────────
    
    async def test_update_work_order_status_validates_transition(self):
        """update_work_order_status should validate transition through state machine."""
        # Mock the order object
        mock_order = MagicMock()
        mock_order.id = "wo-001"
        mock_order.status = "created"
        self.mock_repo.get_work_order_by_id = AsyncMock(return_value=mock_order)
        self.mock_repo.update_work_order_status = AsyncMock(return_value=mock_order)
        
        # Setup state machine - allow transition
        self.mock_sm.can_transition = MagicMock(return_value=True)
        self.sm.transition = MagicMock(return_value=WorkOrderStatus.RELEASED)
        
        # Call adapter (using WorkOrderUpdateRequest-like dict)
        request = {"new_status": "released"}
        result = await self.adapter.update_work_order_status(request)
        
        # Verify state machine was consulted
        self.sm.can_transition.assert_called_once()
    
    async def test_update_work_order_status_on_invalid_transition(self):
        """Invalid transition should raise HTTP 400."""
        mock_order = MagicMock()
        mock_order.id = "wo-001"
        mock_order.status = "completed"  # Terminal state
        self.mock_repo.get_work_order_by_id = AsyncMock(return_value=mock_order)
        
        # State machine will reject this transition
        self.mock_sm.can_transition = MagicMock(side_effect=InvalidStateTransitionError(
            WorkOrderStatus.COMPLETED, WorkOrderStatus.IN_PROGRESS
        ))
        
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await self.adapter.update_work_order_status({"new_status": "in_progress"})
        
        assert exc_info.value.status_code == 400
    
    # ── create_production_report Tests ───────────────────────────────
    
    @pytest.mark.asyncio
    async def test_create_production_report_runs_recovery_strategies(self):
        """create_production_report should execute recovery strategies before persisting."""
        # Mock a report data payload
        report_data = {
            "factory_id": "F01",
            "work_order_id": "wo-001",
            "station_id": "ST-ASSY-01",
            "operator_id": "operator_01",
            "quantity": 100,
            "good_qty": 95,
            "defect_qty": 5,
        }
        
        # Mock repository and formatter
        self.adapter.repository.create_production_report = AsyncMock(return_value=MagicMock())
        self.adapter.response_formatter.format_production_report = MagicMock(return_value={})
        
        # Mock recovery strategies - none should trigger in this valid case
        self.adapter.recovery_strategies[0].should_apply = MagicMock(return_value=False)
        
        # Call adapter
        result = await self.adapter.create_production_report(report_data)
        
        # Verify each strategy was checked
        for strategy in self.adapter.recovery_strategies:
            strategy.should_apply.assert_called_once_with(report_data)
            if strategy.should_apply.return_value:
                strategy.execute.assert_called_once()
            else:
                strategy.execute.assert_not_called()
        
        # Repository called only after all strategies passed
        self.adapter.repository.create_production_report.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_production_report_halts_on_strategy_trigger(self):
        """A triggered recovery strategy should abort creation."""
        report_data = {
            "factory_id": "F01",
            "work_order_id": "wo-001",
            "station_id": "ST-ASSY-01",
            "operator_id": "operator_01",
            "quantity": 10000,  # Very high number to trigger capacity limit
            "good_qty": 0,
            "defect_qty": 0,
        }
        
        # Make CapacityLimitReject trigger
        from api.services.mes_architecture.reproduction.capacity_limit_reject import CapacityLimitReject
        cap_strategy = CapacityLimitReject(default_capacity=1000)
        cap_strategy.should_apply = MagicMock(return_value=True)
        cap_strategy.execute = MagicMock(return_value=MesRecoveryResult(
            strategy_name="capacity_limit_reject",
            applied=True,
            context=report_data,
            message="Capacity exceeded"
        ))
        
        # Replace the strategy in the adapter's list
        self.adapter.recovery_strategies[1] = cap_strategy
        
        # Expect HTTP exception on strategy trigger
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await self.adapter.create_production_report(report_data)
        
        assert exc_info.value.status_code == 422
        assert "capacity" in str(exc_info.value.detail).lower()
        assert self.adapter.repository.create_production_report.call_count == 0  # Not called!