"""Tests for new WMS Executors."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.executors.batch_expiry_executor import BatchExpiryExecutor
from api.services.wms_architecture.executors.location_capacity_executor import LocationCapacityExecutor
from api.services.wms_architecture.executors.inventory_alert_executor import InventoryAlertExecutor
from api.services.wms_architecture.executors.abc_analysis_executor import AbcAnalysisExecutor


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def mock_result():
    """Mock SQLAlchemy result."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.mappings.return_value.all.return_value = []
    result.scalar.return_value = None
    result.first.return_value = None
    return result


class TestBatchExpiryExecutor:
    """Test BatchExpiryExecutor."""
    
    def test_get_operation_name(self):
        executor = BatchExpiryExecutor()
        assert executor.get_operation_name() == "batch_expiry"
    
    def test_can_handle(self):
        executor = BatchExpiryExecutor()
        assert executor.can_handle("batch_expiry") is True
        assert executor.can_handle("inbound") is False
    
    @pytest.mark.asyncio
    async def test_check_expiry(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = BatchExpiryExecutor()
        context = {
            "factory_id": "F01",
            "operation": "check_expiry",
            "days_threshold": 30,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "expiring_soon" in result
        assert "expired" in result
    
    @pytest.mark.asyncio
    async def test_get_warnings(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = BatchExpiryExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_warnings",
            "days_threshold": 30,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "warnings" in result
        assert "total_warnings" in result
    
    @pytest.mark.asyncio
    async def test_lock_batch_missing_batch_code(self, mock_db):
        executor = BatchExpiryExecutor()
        context = {
            "factory_id": "F01",
            "operation": "lock_batch",
            "lock_reason": "quality_issue",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "批次号不能为空" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_unlock_batch_missing_batch_code(self, mock_db):
        executor = BatchExpiryExecutor()
        context = {
            "factory_id": "F01",
            "operation": "unlock_batch",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "批次号不能为空" in result.get("message", "")


class TestLocationCapacityExecutor:
    """Test LocationCapacityExecutor."""
    
    def test_get_operation_name(self):
        executor = LocationCapacityExecutor()
        assert executor.get_operation_name() == "location_capacity"
    
    def test_can_handle(self):
        executor = LocationCapacityExecutor()
        assert executor.can_handle("location_capacity") is True
        assert executor.can_handle("inbound") is False
    
    @pytest.mark.asyncio
    async def test_get_capacity(self, mock_db, mock_result):
        # Mock the result to return proper data
        mock_row = MagicMock()
        mock_row._mapping = {
            "total_locations": 100,
            "active_locations": 80,
            "inactive_locations": 10,
            "maintenance_locations": 10,
            "total_capacity": 10000,
            "used_capacity": 5000,
            "avg_usage_rate": 50.0,
        }
        mock_result.first.return_value = mock_row
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        
        executor = LocationCapacityExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_capacity",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        # Should return success
        assert result.get("success") is True
        assert "summary" in result
        assert "zones" in result
    
    @pytest.mark.asyncio
    async def test_update_capacity_missing_location_id(self, mock_db):
        executor = LocationCapacityExecutor()
        context = {
            "factory_id": "F01",
            "operation": "update_capacity",
            "capacity": 100,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "库位 ID 不能为空" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_get_status(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = LocationCapacityExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_status",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "locations" in result
    
    @pytest.mark.asyncio
    async def test_list_locations(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = LocationCapacityExecutor()
        context = {
            "factory_id": "F01",
            "operation": "list_locations",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "locations" in result
        assert "total" in result


class TestInventoryAlertExecutor:
    """Test InventoryAlertExecutor."""
    
    def test_get_operation_name(self):
        executor = InventoryAlertExecutor()
        assert executor.get_operation_name() == "inventory_alert"
    
    def test_can_handle(self):
        executor = InventoryAlertExecutor()
        assert executor.can_handle("inventory_alert") is True
        assert executor.can_handle("inbound") is False
    
    @pytest.mark.asyncio
    async def test_get_all_alerts(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = InventoryAlertExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_alerts",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "alerts" in result
        assert "total_alerts" in result
    
    @pytest.mark.asyncio
    async def test_get_low_stock(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = InventoryAlertExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_low_stock",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "items" in result
    
    @pytest.mark.asyncio
    async def test_get_overstock(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = InventoryAlertExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_overstock",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "items" in result
    
    @pytest.mark.asyncio
    async def test_get_stagnant(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = InventoryAlertExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_stagnant",
            "days_threshold": 90,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "items" in result
    
    @pytest.mark.asyncio
    async def test_get_expiry(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = InventoryAlertExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_expiry",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "items" in result


class TestAbcAnalysisExecutor:
    """Test AbcAnalysisExecutor."""
    
    def test_get_operation_name(self):
        executor = AbcAnalysisExecutor()
        assert executor.get_operation_name() == "abc_analysis"
    
    def test_can_handle(self):
        executor = AbcAnalysisExecutor()
        assert executor.can_handle("abc_analysis") is True
        assert executor.can_handle("inbound") is False
    
    @pytest.mark.asyncio
    async def test_analyze(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = AbcAnalysisExecutor()
        context = {
            "factory_id": "F01",
            "operation": "analyze",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "abc_distribution" in result
        assert "top_items" in result
    
    @pytest.mark.asyncio
    async def test_get_turnover(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = AbcAnalysisExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_turnover",
            "period_days": 30,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "items" in result
    
    @pytest.mark.asyncio
    async def test_get_cost(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = AbcAnalysisExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_cost",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "cost_by_class" in result
    
    @pytest.mark.asyncio
    async def test_get_utilization(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = AbcAnalysisExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_utilization",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "zones" in result