"""Tests for WMS Architecture - Executors."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.executors.inbound_executor import InboundExecutor
from api.services.wms_architecture.executors.outbound_executor import OutboundExecutor
from api.services.wms_architecture.executors.transfer_executor import TransferExecutor
from api.services.wms_architecture.executors.count_executor import CountExecutor
from api.services.wms_architecture.executors.trace_executor import TraceExecutor
from api.services.wms_architecture.executors.fifo_executor import FifoExecutor
from api.services.wms_architecture.executors.replenish_executor import ReplenishExecutor
from api.services.wms_architecture.executors.kit_check_executor import KitCheckExecutor
from api.services.wms_architecture.executors.dead_stock_executor import DeadStockExecutor
from api.services.wms_architecture.executors.location_executor import LocationExecutor


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


@pytest.fixture
def mock_inventory():
    """Mock inventory object."""
    inv = MagicMock()
    inv.id = "inv-001"
    inv.material_id = "MAT001"
    inv.material_code = "MAT001"
    inv.material_name = "Test Material"
    inv.factory_id = "F01"
    inv.warehouse_id = "WH01"
    inv.location_id = "LOC01"
    inv.batch_code = "BATCH001"
    inv.total_qty = 100
    inv.available_qty = 80
    inv.reserved_qty = 20
    inv.unit = "pcs"
    inv.status = "available"
    inv.last_movement_at = None
    inv.created_at = MagicMock()
    inv.updated_at = MagicMock()
    inv.created_at.isoformat.return_value = "2026-08-02T00:00:00"
    inv.updated_at.isoformat.return_value = "2026-08-02T00:00:00"
    return inv


class TestInboundExecutor:
    """Test InboundExecutor."""
    
    def test_get_operation_name(self):
        executor = InboundExecutor()
        assert executor.get_operation_name() == "inbound"
    
    def test_can_handle(self):
        executor = InboundExecutor()
        assert executor.can_handle("inbound") is True
        assert executor.can_handle("outbound") is False
    
    @pytest.mark.asyncio
    async def test_execute_missing_factory_id(self, mock_db):
        executor = InboundExecutor()
        context = {"material_id": "MAT001"}  # Missing factory_id
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True


class TestOutboundExecutor:
    """Test OutboundExecutor."""
    
    def test_get_operation_name(self):
        executor = OutboundExecutor()
        assert executor.get_operation_name() == "outbound"
    
    def test_can_handle(self):
        executor = OutboundExecutor()
        assert executor.can_handle("outbound") is True
        assert executor.can_handle("inbound") is False


class TestTransferExecutor:
    """Test TransferExecutor."""
    
    def test_get_operation_name(self):
        executor = TransferExecutor()
        assert executor.get_operation_name() == "transfer"
    
    def test_can_handle(self):
        executor = TransferExecutor()
        assert executor.can_handle("transfer") is True


class TestCountExecutor:
    """Test CountExecutor."""
    
    def test_get_operation_name(self):
        executor = CountExecutor()
        assert executor.get_operation_name() == "count"
    
    def test_can_handle(self):
        executor = CountExecutor()
        assert executor.can_handle("count") is True
    
    @pytest.mark.asyncio
    async def test_create_task(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = CountExecutor()
        context = {
            "factory_id": "F01",
            "operation": "create_task",
            "count_type": "cycle",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        # With empty mock_result, it should return error "无可盘点的库存"
        assert result.get("error") is True
        assert "无可盘点的库存" in result.get("message", "")


class TestTraceExecutor:
    """Test TraceExecutor."""
    
    def test_get_operation_name(self):
        executor = TraceExecutor()
        assert executor.get_operation_name() == "trace"
    
    def test_can_handle(self):
        executor = TraceExecutor()
        assert executor.can_handle("trace") is True
    
    @pytest.mark.asyncio
    async def test_execute_missing_batch_code(self, mock_db):
        executor = TraceExecutor()
        context = {"factory_id": "F01"}  # Missing batch_code
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True


class TestFifoExecutor:
    """Test FifoExecutor."""
    
    def test_get_operation_name(self):
        executor = FifoExecutor()
        assert executor.get_operation_name() == "fifo"
    
    def test_can_handle(self):
        executor = FifoExecutor()
        assert executor.can_handle("fifo") is True
    
    @pytest.mark.asyncio
    async def test_execute_missing_material_code(self, mock_db):
        executor = FifoExecutor()
        context = {"factory_id": "F01", "qty_needed": 100}  # Missing material_code
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True


class TestReplenishExecutor:
    """Test ReplenishExecutor."""
    
    def test_get_operation_name(self):
        executor = ReplenishExecutor()
        assert executor.get_operation_name() == "replenish"
    
    def test_can_handle(self):
        executor = ReplenishExecutor()
        assert executor.can_handle("replenish") is True
    
    @pytest.mark.asyncio
    async def test_get_suggestions(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = ReplenishExecutor()
        context = {
            "factory_id": "F01",
            "operation": "suggestions",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert "success" in result


class TestKitCheckExecutor:
    """Test KitCheckExecutor."""
    
    def test_get_operation_name(self):
        executor = KitCheckExecutor()
        assert executor.get_operation_name() == "kit_check"
    
    def test_can_handle(self):
        executor = KitCheckExecutor()
        assert executor.can_handle("kit_check") is True
    
    @pytest.mark.asyncio
    async def test_execute_missing_work_order_id(self, mock_db):
        executor = KitCheckExecutor()
        context = {"factory_id": "F01"}  # Missing work_order_id
        
        result = await executor.execute(mock_db, "F01", context)
        assert result.get("error") is True


class TestDeadStockExecutor:
    """Test DeadStockExecutor."""
    
    def test_get_operation_name(self):
        executor = DeadStockExecutor()
        assert executor.get_operation_name() == "dead_stock"
    
    def test_can_handle(self):
        executor = DeadStockExecutor()
        assert executor.can_handle("dead_stock") is True
    
    @pytest.mark.asyncio
    async def test_check(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = DeadStockExecutor()
        context = {
            "factory_id": "F01",
            "operation": "check",
            "days_threshold": 90,
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert "success" in result


class TestLocationExecutor:
    """Test LocationExecutor."""
    
    def test_get_operation_name(self):
        executor = LocationExecutor()
        assert executor.get_operation_name() == "location"
    
    def test_can_handle(self):
        executor = LocationExecutor()
        assert executor.can_handle("location") is True
    
    @pytest.mark.asyncio
    async def test_optimize(self, mock_db, mock_result):
        mock_db.execute.return_value = mock_result
        
        executor = LocationExecutor()
        context = {
            "factory_id": "F01",
            "operation": "optimize",
        }
        
        result = await executor.execute(mock_db, "F01", context)
        assert "success" in result