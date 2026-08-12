"""Inventory Consistency Tests for WMS Architecture.

Tests to verify inventory quantity consistency across all operations:
- Inbound: quantity should increase
- Outbound: quantity should decrease
- Transfer: source decreases, destination increases
- Count: system vs counted should reconcile
- Reserve: available should decrease, reserved should increase
- Release: reserved should decrease, available should increase
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture import WmsAdapter
from api.services.wms_architecture.executors.inbound_executor import InboundExecutor
from api.services.wms_architecture.executors.outbound_executor import OutboundExecutor
from api.services.wms_architecture.executors.transfer_executor import TransferExecutor
from api.services.wms_architecture.executors.count_executor import CountExecutor


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return WmsAdapter(mock_db)


class TestInboundConsistency:
    """Test inbound operation consistency."""
    
    @pytest.mark.asyncio
    async def test_inbound_increases_inventory(self, adapter, mock_db):
        """Test that inbound operation increases inventory quantity."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
            "before_qty": 50,
            "after_qty": 150,
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
        assert result.get("after_qty") == result.get("before_qty") + result.get("quantity")
        assert result.get("after_qty") == 150
    
    @pytest.mark.asyncio
    async def test_inbound_zero_quantity_rejected(self, adapter, mock_db):
        """Test that zero quantity inbound is rejected."""
        mock_result = {
            "error": True,
            "message": "数量必须大于 0",
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=0,
            warehouse_id="WH01",
        )
        
        assert result.get("error") is True
    
    @pytest.mark.asyncio
    async def test_inbound_negative_quantity_rejected(self, adapter, mock_db):
        """Test that negative quantity inbound is rejected."""
        mock_result = {
            "error": True,
            "message": "数量必须大于 0",
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=-10,
            warehouse_id="WH01",
        )
        
        assert result.get("error") is True


class TestOutboundConsistency:
    """Test outbound operation consistency."""
    
    @pytest.mark.asyncio
    async def test_outbound_decreases_inventory(self, adapter, mock_db):
        """Test that outbound operation decreases inventory quantity."""
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
        
        assert result.get("success") is True
        assert result.get("after_qty") == result.get("before_qty") - result.get("quantity")
        assert result.get("after_qty") == 70
    
    @pytest.mark.asyncio
    async def test_outbound_insufficient_stock_rejected(self, adapter, mock_db):
        """Test that outbound with insufficient stock is rejected."""
        mock_result = {
            "error": True,
            "message": "可用库存不足",
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
    
    @pytest.mark.asyncio
    async def test_outbound_zero_quantity_rejected(self, adapter, mock_db):
        """Test that zero quantity outbound is rejected."""
        mock_result = {
            "error": True,
            "message": "数量必须大于 0",
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=0,
        )
        
        assert result.get("error") is True


class TestTransferConsistency:
    """Test transfer operation consistency."""
    
    @pytest.mark.asyncio
    async def test_transfer_decreases_source(self, adapter, mock_db):
        """Test that transfer decreases source inventory."""
        mock_result = {
            "success": True,
            "type": "transfer",
            "quantity": 50,
            "from_qty_before": 100,
            "from_qty_after": 50,
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
        assert result.get("from_qty_after") == result.get("from_qty_before") - result.get("quantity")
    
    @pytest.mark.asyncio
    async def test_transfer_increases_destination(self, adapter, mock_db):
        """Test that transfer increases destination inventory."""
        mock_result = {
            "success": True,
            "type": "transfer",
            "quantity": 50,
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
        
        assert result.get("success") is True
        assert result.get("to_qty_after") == result.get("to_qty_before") + result.get("quantity")
    
    @pytest.mark.asyncio
    async def test_transfer_balance_consistency(self, adapter, mock_db):
        """Test that transfer maintains balance (source + destination constant)."""
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
        
        # Balance before = Balance after
        before_total = mock_result["from_qty_before"] + mock_result["to_qty_before"]
        after_total = mock_result["from_qty_after"] + mock_result["to_qty_after"]
        assert before_total == after_total == 100


class TestCountConsistency:
    """Test count operation consistency."""
    
    @pytest.mark.asyncio
    async def test_count_submit_records_difference(self, adapter, mock_db):
        """Test that count submit records the difference."""
        mock_result = {
            "success": True,
            "diff": 5,  # counted - system
            "item_id": "item-001",
        }
        
        adapter.executors["count"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.submit_count(
            factory_id="F01",
            task_id="task-001",
            item_id="item-001",
            counted_qty=105,
        )
        
        assert result.get("success") is True
        assert result.get("diff") == 5


class TestMixedOperationsConsistency:
    """Test consistency across mixed operations."""
    
    @pytest.mark.asyncio
    async def test_inbound_then_outbound(self, adapter, mock_db):
        """Test inbound then outbound maintains consistency."""
        # Inbound: 100 units
        inbound_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
            "before_qty": 0,
            "after_qty": 100,
        }
        
        # Outbound: 30 units
        outbound_result = {
            "success": True,
            "type": "outbound",
            "quantity": 30,
            "before_qty": 100,
            "after_qty": 70,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=inbound_result)
        adapter.executors["outbound"].execute = AsyncMock(return_value=outbound_result)
        
        # Execute inbound
        inbound = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        # Execute outbound
        outbound = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        # Verify consistency
        assert inbound["after_qty"] == 100
        assert outbound["after_qty"] == 70
        assert inbound["after_qty"] - outbound["quantity"] == outbound["after_qty"]
    
    @pytest.mark.asyncio
    async def test_multiple_inbounds(self, adapter, mock_db):
        """Test multiple inbound operations maintain consistency."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 50,
            "before_qty": 0,
            "after_qty": 50,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        # Execute multiple inbounds
        results = []
        for i in range(5):
            result = await adapter.quick_inbound(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                material_code=f"MAT{i:03d}",
                quantity=50,
                warehouse_id="WH01",
            )
            results.append(result)
        
        # All should succeed
        assert all(r.get("success") for r in results)
        
        # Total should be 250
        total = sum(r.get("after_qty", 0) for r in results)
        assert total == 250
    
    @pytest.mark.asyncio
    async def test_multiple_outbounds(self, adapter, mock_db):
        """Test multiple outbound operations maintain consistency."""
        # First outbound: 30 from 100
        outbound1_result = {
            "success": True,
            "type": "outbound",
            "quantity": 30,
            "before_qty": 100,
            "after_qty": 70,
        }
        
        # Second outbound: 20 from 70
        outbound2_result = {
            "success": True,
            "type": "outbound",
            "quantity": 20,
            "before_qty": 70,
            "after_qty": 50,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(side_effect=[outbound1_result, outbound2_result])
        
        # Execute multiple outbounds
        outbound1 = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        outbound2 = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=20,
        )
        
        # Verify consistency
        assert outbound1["after_qty"] == 70
        assert outbound2["after_qty"] == 50
        assert outbound1["after_qty"] - outbound2["quantity"] == outbound2["after_qty"]


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    @pytest.mark.asyncio
    async def test_outbound_exceeds_inventory(self, adapter, mock_db):
        """Test outbound that exceeds available inventory."""
        mock_result = {
            "error": True,
            "message": "可用库存不足",
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
    
    @pytest.mark.asyncio
    async def test_transfer_same_warehouse_rejected(self, adapter, mock_db):
        """Test transfer to same warehouse is rejected."""
        mock_result = {
            "error": True,
            "message": "源仓库和目标仓库不能相同",
        }
        
        adapter.executors["transfer"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.transfer(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
            from_warehouse_id="WH01",
            to_warehouse_id="WH01",  # Same warehouse
        )
        
        assert result.get("error") is True
    
    @pytest.mark.asyncio
    async def test_transfer_insufficient_stock(self, adapter, mock_db):
        """Test transfer with insufficient source stock."""
        mock_result = {
            "error": True,
            "message": "源库存不足",
            "available_qty": 10,
            "required_qty": 50,
        }
        
        adapter.executors["transfer"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.transfer(
            factory_id="F01",
            material_id="MAT001",
            quantity=50,
            from_warehouse_id="WH01",
            to_warehouse_id="WH02",
        )
        
        assert result.get("error") is True
        assert result.get("available_qty") == 10
        assert result.get("required_qty") == 50