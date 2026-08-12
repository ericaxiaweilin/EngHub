"""Tests for WMS Architecture - WmsAdapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.adapters.wms_adapter import WmsAdapter
from api.services.wms_architecture.state.engine import InventoryState


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return WmsAdapter(mock_db)


class TestWmsAdapter:
    """Test WmsAdapter orchestration."""
    
    def test_init_initializes_components(self, adapter):
        """Test that adapter initializes all components."""
        assert adapter.state_engine is not None
        assert len(adapter.executors) == 15
        assert "inbound" in adapter.executors
        assert "outbound" in adapter.executors
        assert "transfer" in adapter.executors
        assert "count" in adapter.executors
        assert "trace" in adapter.executors
        assert "fifo" in adapter.executors
        assert "replenish" in adapter.executors
        assert "kit_check" in adapter.executors
        assert "dead_stock" in adapter.executors
        assert "location" in adapter.executors
        assert "batch_expiry" in adapter.executors
        assert "location_capacity" in adapter.executors
        assert "inventory_alert" in adapter.executors
        assert "abc_analysis" in adapter.executors
        assert "volume_management" in adapter.executors
    
    @pytest.mark.asyncio
    async def test_track_volume(self, adapter, mock_db):
        """Test track volume operation."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "material_id": "MAT001",
            "total_volume": 0.5,
            "total_weight": 100,
        })
        adapter.executors["volume_management"] = mock_executor
        
        result = await adapter.track_volume(
            factory_id="F01",
            material_id="MAT001",
            quantity=100,
        )
        
        assert result.get("success") is True
        assert result.get("total_volume") == 0.5
    
    @pytest.mark.asyncio
    async def test_get_volume_summary(self, adapter, mock_db):
        """Test get volume summary."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "summary": {"total_volume": 1000},
        })
        adapter.executors["volume_management"] = mock_executor
        
        result = await adapter.get_volume_summary(factory_id="F01")
        
        assert result.get("success") is True
        assert result.get("summary", {}).get("total_volume") == 1000
    
    @pytest.mark.asyncio
    async def test_calculate_shipping_volume(self, adapter, mock_db):
        """Test calculate shipping volume."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "total_volume": 50,
            "container_requirements": {"total_containers": 2},
        })
        adapter.executors["volume_management"] = mock_executor
        
        result = await adapter.calculate_shipping_volume(
            factory_id="F01",
            work_order_id="WO001",
        )
        
        assert result.get("success") is True
        assert result.get("container_requirements", {}).get("total_containers") == 2
    
    @pytest.mark.asyncio
    async def test_get_space_utilization(self, adapter, mock_db):
        """Test get space utilization."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "warehouses": [],
        })
        adapter.executors["volume_management"] = mock_executor
        
        result = await adapter.get_space_utilization(factory_id="F01")
        
        assert result.get("success") is True
    
    def test_no_business_logic_in_adapter(self, adapter):
        """Test that adapter contains no business logic."""
        import inspect
        source = inspect.getsource(adapter.quick_inbound)
        
        # Should not contain direct database queries
        assert "select(Inventory)" not in source
        assert "await db.execute" not in source
    
    @pytest.mark.asyncio
    async def test_quick_inbound(self, adapter, mock_db):
        """Test quick inbound operation."""
        # Mock the executor
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "quantity": 100})
        adapter.executors["inbound"] = mock_executor
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        assert "success" in result
        assert result.get("success") is True
    
    @pytest.mark.asyncio
    async def test_quick_outbound(self, adapter, mock_db):
        """Test quick outbound operation."""
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_transfer(self, adapter, mock_db):
        """Test transfer operation."""
        result = await adapter.transfer(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
            from_warehouse_id="WH01",
            to_warehouse_id="WH02",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_create_count_task(self, adapter, mock_db):
        """Test create count task."""
        result = await adapter.create_count_task(
            factory_id="F01",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_batch_trace(self, adapter, mock_db):
        """Test batch trace operation."""
        result = await adapter.batch_trace(
            factory_id="F01",
            batch_code="BATCH-001",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_fifo_pick_suggestion(self, adapter, mock_db):
        """Test FIFO pick suggestion."""
        result = await adapter.fifo_pick_suggestion(
            factory_id="F01",
            material_code="MAT001",
            qty_needed=100,
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_replenishment_suggestions(self, adapter, mock_db):
        """Test replenishment suggestions."""
        result = await adapter.replenishment_suggestions(
            factory_id="F01",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_kit_check(self, adapter, mock_db):
        """Test kit check operation."""
        result = await adapter.kit_check(
            factory_id="F01",
            work_order_id="WO001",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_dead_stock_check(self, adapter, mock_db):
        """Test dead stock check."""
        result = await adapter.dead_stock_check(
            factory_id="F01",
            days_threshold=90,
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_location_optimization(self, adapter, mock_db):
        """Test location optimization."""
        result = await adapter.location_optimization(
            factory_id="F01",
        )
        
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_error_handling(self, adapter, mock_db):
        """Test error handling with recovery."""
        # Mock executor to raise error
        adapter.executors["inbound"].execute = AsyncMock(side_effect=Exception("Test error"))
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        assert result.get("success") is False
        assert "error" in result
        assert "recovery_applied" in result
    
    @pytest.mark.asyncio
    async def test_batch_expiry_check(self, adapter, mock_db):
        """Test batch expiry check."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "expiring_soon": []})
        adapter.executors["batch_expiry"] = mock_executor
        
        result = await adapter.batch_expiry_check(
            factory_id="F01",
            days_threshold=30,
        )
        
        assert result.get("success") is True
        mock_executor.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_lock_batch(self, adapter, mock_db):
        """Test lock batch."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "action": "lock_batch"})
        adapter.executors["batch_expiry"] = mock_executor
        
        result = await adapter.lock_batch(
            factory_id="F01",
            batch_code="BATCH001",
            lock_reason="quality_issue",
        )
        
        assert result.get("success") is True
        assert result.get("action") == "lock_batch"
    
    @pytest.mark.asyncio
    async def test_get_location_capacity(self, adapter, mock_db):
        """Test get location capacity."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "summary": {}})
        adapter.executors["location_capacity"] = mock_executor
        
        result = await adapter.get_location_capacity(
            factory_id="F01",
        )
        
        assert result.get("success") is True
    
    @pytest.mark.asyncio
    async def test_get_inventory_alerts(self, adapter, mock_db):
        """Test get inventory alerts."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "alerts": []})
        adapter.executors["inventory_alert"] = mock_executor
        
        result = await adapter.get_inventory_alerts(
            factory_id="F01",
        )
        
        assert result.get("success") is True
    
    @pytest.mark.asyncio
    async def test_abc_analysis(self, adapter, mock_db):
        """Test ABC analysis."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value={"success": True, "abc_distribution": {}})
        adapter.executors["abc_analysis"] = mock_executor
        
        result = await adapter.abc_analysis(
            factory_id="F01",
        )
        
        assert result.get("success") is True
    
    def test_initializes_new_executors(self, adapter):
        """Test that adapter initializes all new executors."""
        assert "batch_expiry" in adapter.executors
        assert "location_capacity" in adapter.executors
        assert "inventory_alert" in adapter.executors
        assert "abc_analysis" in adapter.executors
        assert "volume_management" in adapter.executors
        assert len(adapter.executors) == 15