"""Tests for business executors and registry."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_architecture.business_executors.executor_registry import ExecutorRegistry
from api.services.chat_architecture.business_executors.query_inventory_executor import QueryInventoryExecutor
from api.services.chat_architecture.business_executors.get_production_summary_executor import GetProductionSummaryExecutor
from api.services.chat_architecture.business_executors.query_work_orders_executor import QueryWorkOrdersExecutor


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Cleanup registry after each test."""
    yield
    ExecutorRegistry.reset()


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def mock_result():
    """Mock query result."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


@pytest.mark.asyncio
async def test_query_inventory_executor(mock_db, mock_result):
    """Test executing inventory query."""
    # Mock db.execute to return mock result
    mock_db.execute = AsyncMock(return_value=mock_result)
    
    executor = QueryInventoryExecutor()
    
    with patch('api.services.chat_architecture.business_executors.query_inventory_executor._tool_query_inventory') as mock_tool:
        mock_tool.return_value = {"inventory": [{"material_code": "TEST", "total_qty": 100}]}
        
        result = await executor.execute(
            db=mock_db,
            factory_id="F01",
            context={"material_keyword": "test", "limit": 5}
        )
        
        assert "inventory" in result


def test_query_inventory_executor_get_intent_name():
    """Test getting intent name."""
    executor = QueryInventoryExecutor()
    assert executor.get_intent_name() == "query_inventory"


def test_query_inventory_executor_can_handle_matching_intent():
    """Test can_handle with matching intent."""
    executor = QueryInventoryExecutor()
    assert executor.can_handle("query_inventory") is True


def test_query_inventory_executor_can_handle_nonmatching_intent():
    """Test can_handle with non-matching intent."""
    executor = QueryInventoryExecutor()
    assert executor.can_handle("get_production_summary") is False


@pytest.mark.asyncio
async def test_get_production_summary_executor(mock_db):
    """Test executing production summary query."""
    executor = GetProductionSummaryExecutor()
    
    with patch('api.services.chat_architecture.business_executors.get_production_summary_executor._tool_get_production_summary') as mock_tool:
        mock_tool.return_value = {
            "today_good_output": 1000,
            "today_defect": 10,
            "yield_rate_pct": 99.0
        }
        
        result = await executor.execute(
            db=mock_db,
            factory_id="F01",
            context={}
        )
        
        assert "today_good_output" in result


def test_get_production_summary_executor_get_intent_name():
    """Test getting intent name."""
    executor = GetProductionSummaryExecutor()
    assert executor.get_intent_name() == "get_production_summary"


def test_get_production_summary_executor_can_handle_matching_intent():
    """Test can_handle with matching intent."""
    executor = GetProductionSummaryExecutor()
    assert executor.can_handle("get_production_summary") is True


@pytest.mark.asyncio
async def test_query_work_orders_executor(mock_db):
    """Test executing work orders query."""
    executor = QueryWorkOrdersExecutor()
    
    with patch('api.services.chat_architecture.business_executors.query_work_orders_executor._tool_query_work_orders') as mock_tool:
        mock_tool.return_value = {
            "work_orders": [{"work_order_code": "WO-001", "status": "in_progress"}],
            "count": 1
        }
        
        result = await executor.execute(
            db=mock_db,
            factory_id="F01",
            context={"status": "in_progress"}
        )
        
        assert "work_orders" in result


def test_query_work_orders_executor_get_intent_name():
    """Test getting intent name."""
    executor = QueryWorkOrdersExecutor()
    assert executor.get_intent_name() == "query_work_orders"


def test_query_work_orders_executor_can_handle_matching_intent():
    """Test can_handle with matching intent."""
    executor = QueryWorkOrdersExecutor()
    assert executor.can_handle("query_work_orders") is True


class TestBusinessExecutorRegistry:
    """Test cases for BusinessExecutorRegistry."""
    
    def test_register_and_get(self):
        """Test registering and retrieving an executor."""
        executor = QueryInventoryExecutor()
        ExecutorRegistry.register(executor)
        
        retrieved = ExecutorRegistry.get("query_inventory")
        assert retrieved == executor
    
    def test_get_nonexistent_intent(self):
        """Test getting a nonexistent intent returns None."""
        result = ExecutorRegistry.get("nonexistent_intent")
        assert result is None
    
    def test_has_executor(self):
        """Test checking if executor exists."""
        executor = QueryInventoryExecutor()
        ExecutorRegistry.register(executor)
        
        assert ExecutorRegistry.has_executor("query_inventory")
        assert not ExecutorRegistry.has_executor("nonexistent_intent")
    
    def test_get_all(self):
        """Test getting all registered executors."""
        executor1 = QueryInventoryExecutor()
        executor2 = GetProductionSummaryExecutor()
        
        ExecutorRegistry.register(executor1)
        ExecutorRegistry.register(executor2)
        
        all_executors = ExecutorRegistry.get_all()
        assert len(all_executors) == 2
        assert executor1 in all_executors
        assert executor2 in all_executors
    
    def test_unregister(self):
        """Test unregistering an executor."""
        executor = QueryInventoryExecutor()
        ExecutorRegistry.register(executor)
        
        ExecutorRegistry.unregister(executor)
        
        assert not ExecutorRegistry.has_executor("query_inventory")
    
    def test_reset(self):
        """Test resetting the registry."""
        executor = QueryInventoryExecutor()
        ExecutorRegistry.register(executor)
        
        ExecutorRegistry.reset()
        
        assert len(ExecutorRegistry.get_all()) == 0
        assert not ExecutorRegistry.has_executor("query_inventory")