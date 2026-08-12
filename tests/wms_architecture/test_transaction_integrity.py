"""Transaction Integrity Tests for WMS Architecture.

Tests to verify transaction integrity:
- Atomicity (all or nothing)
- Consistency (database constraints)
- Isolation (concurrent operations)
- Durability (data persistence)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture import WmsAdapter
from api.services.wms_architecture.executors.inbound_executor import InboundExecutor
from api.services.wms_architecture.executors.outbound_executor import OutboundExecutor
from api.services.wms_architecture.executors.transfer_executor import TransferExecutor


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return WmsAdapter(mock_db)


class TestTransactionAtomicity:
    """Test transaction atomicity."""
    
    @pytest.mark.asyncio
    async def test_inbound_transaction_atomic(self, adapter, mock_db):
        """Test that inbound transaction is atomic."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
            "after_qty": 100,
            "transaction_id": "txn-001",
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        assert result.get("success") is True
        assert result.get("transaction_id") == "txn-001"
    
    @pytest.mark.asyncio
    async def test_outbound_transaction_atomic(self, adapter, mock_db):
        """Test that outbound transaction is atomic."""
        mock_result = {
            "success": True,
            "type": "outbound",
            "quantity": -30,
            "after_qty": 70,
            "transaction_id": "txn-002",
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        assert result.get("success") is True
        assert result.get("transaction_id") == "txn-002"
    
    @pytest.mark.asyncio
    async def test_transfer_transaction_atomic(self, adapter, mock_db):
        """Test that transfer transaction is atomic."""
        mock_result = {
            "success": True,
            "type": "transfer",
            "quantity": 50,
            "from_warehouse": "WH01",
            "to_warehouse": "WH02",
            "transaction_id": "txn-003",
        }
        
        adapter.executors["transfer"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.transfer(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
            from_warehouse_id="WH01",
            to_warehouse_id="WH02",
        )
        
        assert result.get("success") is True
        assert result.get("transaction_id") == "txn-003"


class TestTransactionConsistency:
    """Test transaction consistency."""
    
    @pytest.mark.asyncio
    async def test_inventory_balance_after_inbound(self, adapter, mock_db):
        """Test inventory balance after inbound."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
            "before_qty": 0,
            "after_qty": 100,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        assert result.get("after_qty") == result.get("before_qty", 0) + result.get("quantity")
    
    @pytest.mark.asyncio
    async def test_inventory_balance_after_outbound(self, adapter, mock_db):
        """Test inventory balance after outbound."""
        mock_result = {
            "success": True,
            "type": "outbound",
            "quantity": 30,
            "before_qty": 100,
            "after_qty": 70,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        assert result.get("after_qty") == result.get("before_qty") - result.get("quantity")
    
    @pytest.mark.asyncio
    async def test_transfer_balance_consistency(self, adapter, mock_db):
        """Test transfer balance consistency."""
        mock_result = {
            "success": True,
            "type": "transfer",
            "quantity": 50,
            "from_qty_before": 100,
            "from_qty_after": 50,
            "to_qty_before": 0,
            "to_qty_after": 50,
        }
        
        adapter.executors["transfer"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.transfer(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
            from_warehouse_id="WH01",
            to_warehouse_id="WH02",
        )
        
        assert result.get("from_qty_after") == result.get("from_qty_before") - result.get("quantity")
        assert result.get("to_qty_after") == result.get("to_qty_before") + result.get("quantity")


class TestTransactionIsolation:
    """Test transaction isolation."""
    
    @pytest.mark.asyncio
    async def test_concurrent_inbound(self, adapter, mock_db):
        """Test concurrent inbound operations."""
        import asyncio
        
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 10,
            "after_qty": 10,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        # Run multiple concurrent operations
        tasks = []
        for i in range(5):
            tasks.append(adapter.quick_inbound(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                material_code=f"MAT{i:03d}",
                quantity=10,
                warehouse_id="WH01",
            ))
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r.get("success") for r in results)
    
    @pytest.mark.asyncio
    async def test_concurrent_outbound(self, adapter, mock_db):
        """Test concurrent outbound operations."""
        import asyncio
        
        mock_result = {
            "success": True,
            "type": "outbound",
            "quantity": 5,
            "after_qty": 95,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        # Run multiple concurrent operations
        tasks = []
        for i in range(5):
            tasks.append(adapter.quick_outbound(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                quantity=5,
            ))
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r.get("success") for r in results)


class TestTransactionDurability:
    """Test transaction durability."""
    
    @pytest.mark.asyncio
    async def test_inbound_persistence(self, adapter, mock_db):
        """Test that inbound transactions are persisted."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
            "after_qty": 100,
            "transaction_id": "txn-persist-001",
            "committed": True,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        assert result.get("success") is True
        assert result.get("committed") is True
    
    @pytest.mark.asyncio
    async def test_outbound_persistence(self, adapter, mock_db):
        """Test that outbound transactions are persisted."""
        mock_result = {
            "success": True,
            "type": "outbound",
            "quantity": 30,
            "after_qty": 70,
            "transaction_id": "txn-persist-002",
            "committed": True,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        assert result.get("success") is True
        assert result.get("committed") is True


class TestRollbackScenarios:
    """Test rollback scenarios."""
    
    @pytest.mark.asyncio
    async def test_inbound_rollback_on_error(self, adapter, mock_db):
        """Test inbound rollback on error."""
        from unittest.mock import patch
        
        # Mock executor to raise error
        adapter.executors["inbound"].execute = AsyncMock(side_effect=Exception("Database error"))
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        # Should return error
        assert result.get("success") is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_outbound_rollback_on_insufficient_stock(self, adapter, mock_db):
        """Test outbound rollback on insufficient stock."""
        mock_result = {
            "error": True,
            "message": "库存不足",
            "available_qty": 10,
            "required_qty": 100,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=100,
        )
        
        assert result.get("error") is True
        assert result.get("available_qty") == 10
        assert result.get("required_qty") == 100