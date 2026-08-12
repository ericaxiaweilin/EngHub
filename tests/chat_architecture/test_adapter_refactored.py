"""Tests for refactored ChatAdapter.

Verifies that the adapter is now a pure orchestrator
with no business logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_architecture.adapters.chat_adapter import ChatAdapter
from api.services.chat_architecture.state.engine import ChatState
from api.services.chat_architecture.business_executors.executor_registry import ExecutorRegistry


@pytest.fixture(autouse=True)
def cleanup_registries():
    """Cleanup registries after each test."""
    yield
    ExecutorRegistry.reset()


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return ChatAdapter(mock_db)


class TestChatAdapterOrchestration:
    """Test that ChatAdapter is a pure orchestrator."""
    
    def test_init_initializes_components(self, adapter):
        """Test that adapter initializes all components."""
        assert adapter.factory_resolver is not None
        assert adapter.intent_resolver is not None
        assert adapter.state_engine is not None
        assert adapter.response_formatter is not None
    
    def test_no_business_logic_in_adapter(self, adapter):
        """Test that adapter contains no business logic."""
        # The adapter should only contain orchestration methods
        # Business logic should be in executors
        import inspect
        source = inspect.getsource(adapter._execute_business_operation)
        
        # Should not contain direct database queries or service calls
        assert "_tool_query_inventory" not in source
        assert "_tool_get_production_summary" not in source
        assert "_tool_query_work_orders" not in source
    
    @pytest.mark.asyncio
    async def test_handle_request_with_intent(self, adapter, mock_db):
        """Test handling request with resolved intent."""
        # Create mock request
        request = MagicMock()
        request.messages = [
            MagicMock(role="user", content="库存查询")
        ]
        request.http_request = None
        
        # Mock intent resolver
        with patch.object(adapter.intent_resolver, 'resolve') as mock_resolve:
            mock_resolve.return_value = "query_inventory"
            
            # Mock business executor
            with patch.object(ExecutorRegistry, 'has_executor') as mock_has:
                mock_has.return_value = True
                
                mock_executor = MagicMock()
                mock_executor.execute = AsyncMock(return_value={
                    "inventory": [{"material_code": "TEST", "total_qty": 100}]
                })
                
                with patch.object(ExecutorRegistry, 'get') as mock_get:
                    mock_get.return_value = mock_executor
                    
                    result = await adapter.handle_request(request, None)
                    
                    # Verify result structure
                    assert "reply" in result
                    assert "model" in result
                    assert "degraded" in result
                    # degraded should be False for successful execution
                    assert result.get("degraded") is False
    
    @pytest.mark.asyncio
    async def test_handle_request_without_intent(self, adapter, mock_db):
        """Test handling request without resolved intent (falls back to tool loop)."""
        # Create mock request
        request = MagicMock()
        request.messages = [
            MagicMock(role="user", content="你好")
        ]
        request.http_request = None
        
        # Mock intent resolver to return None
        with patch.object(adapter.intent_resolver, 'resolve') as mock_resolve:
            mock_resolve.return_value = None
            
            result = await adapter.handle_request(request, None)
            
            # Should fall back to tool loop
            assert "reply" in result
            assert result["model"] == "tool-loop"
    
    @pytest.mark.asyncio
    async def test_handle_request_error(self, adapter, mock_db):
        """Test handling request with error."""
        # Create mock request
        request = MagicMock()
        request.messages = [
            MagicMock(role="user", content="测试")
        ]
        request.http_request = None
        
        # Mock intent resolver to raise error
        with patch.object(adapter.intent_resolver, 'resolve') as mock_resolve:
            mock_resolve.side_effect = Exception("Test error")
            
            result = await adapter.handle_request(request, None)
            
            # Should return error response
            assert result["error"] is True
            assert result["degraded"] is True
            assert "Test error" in result["reply"]
    
    def test_get_current_state(self, adapter):
        """Test getting current state."""
        state = adapter.get_current_state()
        assert state == ChatState.IDLE