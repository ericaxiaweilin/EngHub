"""Integration Tests for MES Architecture

These tests verify that all components can be imported and work together
at a basic level. They are less granular than unit tests but provide
confidence that the architecture assembles correctly.
"""

import pytest
from api.services.mes_architecture.adapters.mes_adapter import MESAdapter
from api.services.mes_architecture.repository.mes_repository import MESRepository
from api.services.mes_architecture.formatter.response_formatter import ResponseFormatter
from core.mes.state_machine.work_order_state_machine import WorkOrderStateMachine
from api.services.mes_architecture.resolvers.request_parser import MESRequestParser


class TestMESArchitectureIntegration:
    """Test that the MES architecture components can be assembled."""
    
    def test_all_components_importable(self):
        """All key MES architecture modules should import without errors."""
        # This test simply verifies imports work - actual usage tested in other files
        assert MESAdapter is not None
        assert MESRepository is not None
        assert ResponseFormatter is not None
        assert WorkOrderStateMachine is not None
        assert MESRequestParser is not None
    
    def test_mes_adapter_can_be_instantiated(self):
        """MESAdapter can be instantiated with required dependencies."""
        from unittest.mock import MagicMock
        
        # Create mock dependencies
        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_formatter = MagicMock()
        
        # We need to temporarily replace actual implementations with mocks during instantiation
        # This is a simple check that the class can be constructed
        adapter = MESAdapter(
            db=mock_db,
            current_user_id="test_user"
        )
        
        # Verify attributes are set correctly
        assert adapter.db is not None
        assert adapter.factory_resolver is not None
        assert adapter.state_machine is not None
        assert adapter.repository is not None
        assert adapter.response_formatter is not None
        assert len(adapter.recovery_strategies) > 0
    
    def test_request_parser_validates_pagination(self):
        """MESRequestParser handles page/size validation correctly."""
        parser = MESRequestParser()
        
        # Default values
        criteria = parser.parse_work_order_query({})
        assert criteria.page == 1
        assert criteria.size == 10
        
        # Custom values
        criteria = parser.parse_work_order_query({"page": "2", "size": "25"})
        assert criteria.page == 2
        assert criteria.size == 25
        
        # Size cap at 100
        criteria = parser.parse_work_order_query({"size": "500"})
        assert criteria.size == 100  # Cap applied
        
        # Page minimum at 1
        criteria = parser.parse_work_order_query({"page": "-1"})
        assert criteria.page == 1  # Minimum enforced