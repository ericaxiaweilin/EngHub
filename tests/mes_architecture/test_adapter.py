"""Characterization Tests for MES Adapter

Tests the MESAdapter orchestration behavior by mocking its dependencies.
Ensures the adapter correctly delegates to components and formats responses.
"""

import pytest
import asyncio
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
    
    @pytest.fixture
    def mock_adapter(self):
        """Create a mocked MESAdapter for testing."""
        mock_db = AsyncMock()
        adapter = MESAdapter(
            db=mock_db,
            current_user_id="test_user"
        )
        
        # Replace real components with mocks
        adapter.state_machine = MagicMock()
        adapter.repository = MagicMock()
        adapter.response_formatter = MagicMock()
        
        return adapter
    
    @pytest.mark.asyncio
    async def test_get_work_orders_calls_repo_with_criteria(self, mock_adapter):
        """get_work_orders should call repository with parsed criteria."""
        mock_adapter.repository.find_work_orders = AsyncMock(return_value=[])
        mock_adapter.repository.count_work_orders = AsyncMock(return_value=0)
        
        result = await mock_adapter.get_work_orders(
            factory_id="F01",
            status="in_progress",
            page=1,
            size=10
        )
        
        mock_adapter.repository.find_work_orders.assert_called_once()
        assert "items" in result
        assert "total" in result
    
    @pytest.mark.asyncio
    async def test_get_work_orders_rejects_unauthorized_factory(self):
        """Unauthorized factory access should raise HTTP 403."""
        from fastapi import HTTPException
        from api.services.mes_architecture.adapters.mes_adapter import MESAdapter
        
        mock_db = AsyncMock()
        adapter = MESAdapter(mock_db, "test_user")
        adapter.factory_resolver = MagicMock()
        adapter.factory_resolver.resolve.return_value = "INVALID_FACTORY"
        
        with patch.object(adapter, '_validate_factory_access', return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await adapter.get_work_orders(factory_id="BAD_FACTORY")
            
            assert exc_info.value.status_code == 403
    
    @pytest.mark.asyncio
    async def test_update_work_order_status_validates_transition(self):
        """update_work_order_status should validate transition through state machine."""
        mock_db = AsyncMock()
        adapter = MESAdapter(mock_db, "test_user")
        
        mock_order = MagicMock()
        mock_order.id = "wo-001"
        mock_order.status = "created"
        adapter.repository.get_work_order_by_id = AsyncMock(return_value=mock_order)
        adapter.repository.update_work_order_status = AsyncMock(return_value=mock_order)
        adapter.state_machine.can_transition = MagicMock(return_value=True)
        adapter.state_machine.transition = MagicMock(return_value=WorkOrderStatus.RELEASED)
        
        request = {"new_status": "released"}
        result = await adapter.update_work_order_status(request)
        
        adapter.state_machine.can_transition.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_work_order_status_on_invalid_transition(self):
        """Invalid transition should raise HTTP 400."""
        mock_db = AsyncMock()
        adapter = MESAdapter(mock_db, "test_user")
        
        mock_order = MagicMock()
        mock_order.id = "wo-001"
        mock_order.status = "completed"
        adapter.repository.get_work_order_by_id = AsyncMock(return_value=mock_order)
        
        from core.mes.state_machine.work_order_state_machine import InvalidStateTransitionError
        adapter.state_machine.can_transition = MagicMock(side_effect=InvalidStateTransitionError(
            WorkOrderStatus.COMPLETED, WorkOrderStatus.IN_PROGRESS
        ))
        
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await adapter.update_work_order_status({"new_status": "in_progress"})
        
        assert exc_info.value.status_code == 400
    
    @pytest.mark.asyncio
    async def test_create_production_report_runs_recovery_strategies(self):
        """create_production_report should execute recovery strategies before persisting."""
        mock_db = AsyncMock()
        adapter = MESAdapter(mock_db, "test_user")
        
        report_data = {
            "factory_id": "F01",
            "work_order_id": "wo-001",
            "station_id": "ST-ASSY-01",
            "operator_id": "operator_01",
            "quantity": 100,
            "good_qty": 95,
            "defect_qty": 5,
        }
        
        adapter.repository.create_production_report = AsyncMock(return_value=MagicMock())
        adapter.response_formatter.format_production_report = MagicMock(return_value={})
        
        # Make all strategies return not applied
        for strategy in adapter.recovery_strategies:
            strategy.should_apply = MagicMock(return_value=False)
        
        result = await adapter.create_production_report(report_data)
        
        for strategy in adapter.recovery_strategies:
            strategy.should_apply.assert_called_once_with(report_data)
            if strategy.should_apply.return_value:
                strategy.execute.assert_called_once_with(report_data)
            else:
                strategy.execute.assert_not_called()
        
        adapter.repository.create_production_report.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_production_report_halts_on_strategy_trigger(self):
        """A triggered recovery strategy should abort creation."""
        mock_db = AsyncMock()
        adapter = MESAdapter(mock_db, "test_user")
        
        from api.services.mes_architecture.reproduction.capacity_limit_reject import CapacityLimitReject
        cap_strategy = CapacityLimitReject(default_capacity=100)
        
        report_data = {
            "factory_id": "F01",
            "work_order_id": "wo-001",
            "station_id": "ST-ASSY-01",
            "operator_id": "operator_01",
            "quantity": 1500,  # High number to trigger capacity limit
            "good_qty": 0,
            "defect_qty": 0,
        }
        
        cap_strategy.should_apply = MagicMock(return_value=True)
        cap_strategy.execute = MagicMock(return_value=MesRecoveryResult(
            strategy_name="capacity_limit_reject",
            applied=True,
            context=report_data,
            message="Capacity exceeded"
        ))
        
        # Replace the strategy in the adapter's list
        adapter.recovery_strategies[1] = cap_strategy
        
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await adapter.create_production_report(report_data)
        
        assert exc_info.value.status_code == 422
        assert "capacity" in str(exc_info.value.detail).lower()
        assert adapter.repository.create_production_report.call_count == 0