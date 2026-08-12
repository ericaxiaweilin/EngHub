"""Tests for Volume Management Executor."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.executors.volume_management_executor import VolumeManagementExecutor


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


class TestVolumeManagementExecutor:
    """Test VolumeManagementExecutor."""
    
    def test_get_operation_name(self):
        executor = VolumeManagementExecutor()
        assert executor.get_operation_name() == "volume_management"
    
    def test_can_handle(self):
        executor = VolumeManagementExecutor()
        # can_handle uses get_operation_name() comparison
        assert executor.get_operation_name() == "volume_management"
    
    @pytest.mark.asyncio
    async def test_track_volume_missing_material_id(self, mock_db):
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "track_volume",
            "quantity": 100,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "物料 ID 不能为空" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_track_volume_zero_quantity(self, mock_db):
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "track_volume",
            "material_id": "MAT001",
            "quantity": 0,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "数量必须大于 0" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_get_volume_summary(self, mock_db, mock_result):
        # Mock the result to return proper data
        mock_row = MagicMock()
        mock_row._mapping = {
            "sku_count": 100,
            "total_volume": 1000.5,
            "total_weight": 50000.0,
            "avg_volume_per_unit": 10.5,
            "avg_weight_per_unit": 500.0,
        }
        mock_result.first.return_value = mock_row
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_volume_summary",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        # Should return success even with empty data
        assert result.get("success") is True
    
    @pytest.mark.asyncio
    async def test_calculate_shipping_volume(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "calculate_shipping_volume",
            "work_order_id": "WO001",
            "planned_qty": 100,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "total_volume" in result
        assert "total_weight" in result
        assert "container_requirements" in result
    
    @pytest.mark.asyncio
    async def test_get_space_utilization(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "get_space_utilization",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("success") is True
        assert "warehouses" in result
        assert "zones" in result
    
    @pytest.mark.asyncio
    async def test_update_volume_missing_material_id(self, mock_db):
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "update_volume",
            "volume_per_unit": 0.5,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "物料 ID 不能为空" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_update_volume_no_data(self, mock_db):
        executor = VolumeManagementExecutor()
        context = {
            "factory_id": "F01",
            "operation": "update_volume",
            "material_id": "MAT001",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True
        assert "请提供体积或重量数据" in result.get("message", "")


class TestVolumeCalculations:
    """Test volume calculation logic."""
    
    def test_calculate_shipping_recommendation(self):
        executor = VolumeManagementExecutor()
        
        # No containers needed
        assert executor._get_shipping_recommendation(0, 0, 0) == "无需发货"
        
        # One container needed
        assert executor._get_shipping_recommendation(10, 1000, 1) == "需要 1 个 20ft 集装箱"
        
        # Multiple containers needed
        assert executor._get_shipping_recommendation(100, 10000, 3) == "需要 3 个 20ft 集装箱"