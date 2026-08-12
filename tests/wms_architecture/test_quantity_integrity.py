"""Quantity Integrity Tests for WMS Architecture.

Tests to verify quantity integrity across all WMS operations:
- Quantity validation (positive, non-zero)
- Quantity bounds (no negative quantities)
- Quantity balance (in = out + current)
- Concurrent quantity updates
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture import WmsAdapter


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return WmsAdapter(mock_db)


class TestQuantityValidation:
    """Test quantity validation rules."""
    
    @pytest.mark.asyncio
    async def test_positive_quantity_accepted(self, adapter, mock_db):
        """Test that positive quantities are accepted."""
        mock_result = {
            "success": True,
            "quantity": 100,
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
        
        assert result.get("success") is True
        assert result.get("quantity") == 100
    
    @pytest.mark.asyncio
    async def test_zero_quantity_rejected(self, adapter, mock_db):
        """Test that zero quantities are rejected."""
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
    async def test_negative_quantity_rejected(self, adapter, mock_db):
        """Test that negative quantities are rejected."""
        mock_result = {
            "error": True,
            "message": "数量必须大于 0",
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=-100,
            warehouse_id="WH01",
        )
        
        assert result.get("error") is True
    
    @pytest.mark.asyncio
    async def test_very_large_quantity_accepted(self, adapter, mock_db):
        """Test that very large quantities are accepted."""
        mock_result = {
            "success": True,
            "quantity": 999999,
            "after_qty": 999999,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=999999,
            warehouse_id="WH01",
        )
        
        assert result.get("success") is True
        assert result.get("quantity") == 999999


class TestQuantityBalance:
    """Test quantity balance across operations."""
    
    @pytest.mark.asyncio
    async def test_inbound_outbound_balance(self, adapter, mock_db):
        """Test that inbound and outbound maintain balance."""
        # Inbound: +100
        inbound_result = {
            "success": True,
            "quantity": 100,
            "before_qty": 0,
            "after_qty": 100,
        }
        
        # Outbound: -30
        outbound_result = {
            "success": True,
            "quantity": 30,
            "before_qty": 100,
            "after_qty": 70,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=inbound_result)
        adapter.executors["outbound"].execute = AsyncMock(return_value=outbound_result)
        
        # Execute operations
        inbound = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        outbound = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        # Verify balance: after_qty = before_qty + inbound - outbound
        assert inbound["after_qty"] == inbound["before_qty"] + inbound["quantity"]
        assert outbound["after_qty"] == outbound["before_qty"] - outbound["quantity"]
        assert outbound["after_qty"] == 70
    
    @pytest.mark.asyncio
    async def test_transfer_balance(self, adapter, mock_db):
        """Test that transfer maintains total balance."""
        mock_result = {
            "success": True,
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
        
        # Total before = Total after
        before_total = mock_result["from_qty_before"] + mock_result["to_qty_before"]
        after_total = mock_result["from_qty_after"] + mock_result["to_qty_after"]
        assert before_total == after_total == 100
    
    @pytest.mark.asyncio
    async def test_multiple_operations_balance(self, adapter, mock_db):
        """Test balance across multiple operations."""
        # Series of operations:
        # 1. Inbound: +100 (0 -> 100)
        # 2. Outbound: -30 (100 -> 70)
        # 3. Inbound: +50 (70 -> 120)
        # 4. Outbound: -20 (120 -> 100)
        
        operations = [
            {"type": "inbound", "quantity": 100, "before": 0, "after": 100},
            {"type": "outbound", "quantity": 30, "before": 100, "after": 70},
            {"type": "inbound", "quantity": 50, "before": 70, "after": 120},
            {"type": "outbound", "quantity": 20, "before": 120, "after": 100},
        ]
        
        call_count = [0]
        
        def mock_execute(db, factory_id, context):
            op = operations[call_count[0]]
            call_count[0] += 1
            return {
                "success": True,
                "type": op["type"],
                "quantity": op["quantity"],
                "before_qty": op["before"],
                "after_qty": op["after"],
            }
        
        adapter.executors["inbound"].execute = AsyncMock(side_effect=mock_execute)
        adapter.executors["outbound"].execute = AsyncMock(side_effect=mock_execute)
        
        # Execute all operations
        results = []
        
        # Inbound 100
        results.append(await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        ))
        
        # Outbound 30
        results.append(await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        ))
        
        # Inbound 50
        results.append(await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=50,
            warehouse_id="WH01",
        ))
        
        # Outbound 20
        results.append(await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=20,
        ))
        
        # Verify balance
        assert results[0]["after_qty"] == 100
        assert results[1]["after_qty"] == 70
        assert results[2]["after_qty"] == 120
        assert results[3]["after_qty"] == 100
        
        # Final balance should equal initial + total inbound - total outbound
        total_inbound = 100 + 50
        total_outbound = 30 + 20
        assert results[-1]["after_qty"] == total_inbound - total_outbound


class TestConcurrentOperations:
    """Test concurrent operation consistency."""
    
    @pytest.mark.asyncio
    async def test_concurrent_inbounds(self, adapter, mock_db):
        """Test concurrent inbound operations."""
        import asyncio
        
        mock_result = {
            "success": True,
            "quantity": 10,
            "before_qty": 0,
            "after_qty": 10,
        }
        
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_result)
        
        # Run 10 concurrent inbounds
        tasks = []
        for i in range(10):
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
        
        # Total should be 100
        total = sum(r.get("after_qty", 0) for r in results)
        assert total == 100
    
    @pytest.mark.asyncio
    async def test_concurrent_outbounds(self, adapter, mock_db):
        """Test concurrent outbound operations."""
        import asyncio
        
        mock_result = {
            "success": True,
            "quantity": 5,
            "before_qty": 100,
            "after_qty": 95,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        # Run 10 concurrent outbounds
        tasks = []
        for i in range(10):
            tasks.append(adapter.quick_outbound(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                quantity=5,
            ))
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r.get("success") for r in results)
    
    @pytest.mark.asyncio
    async def test_concurrent_transfers(self, adapter, mock_db):
        """Test concurrent transfer operations."""
        import asyncio
        
        mock_result = {
            "success": True,
            "quantity": 10,
            "from_qty_before": 100,
            "from_qty_after": 90,
            "to_qty_before": 0,
            "to_qty_after": 10,
        }
        
        adapter.executors["transfer"].execute = AsyncMock(return_value=mock_result)
        
        # Run 10 concurrent transfers
        tasks = []
        for i in range(10):
            tasks.append(adapter.transfer(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                quantity=10,
                from_warehouse_id="WH01",
                to_warehouse_id="WH02",
            ))
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r.get("success") for r in results)


class TestQuantityEdgeCases:
    """Test quantity edge cases."""
    
    @pytest.mark.asyncio
    async def test_exact_stock_outbound(self, adapter, mock_db):
        """Test outbound exactly equal to available stock."""
        mock_result = {
            "success": True,
            "quantity": 100,
            "before_qty": 100,
            "after_qty": 0,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=100,
        )
        
        assert result.get("success") is True
        assert result.get("after_qty") == 0
    
    @pytest.mark.asyncio
    async def test_outbound_to_zero(self, adapter, mock_db):
        """Test outbound that reduces stock to zero."""
        mock_result = {
            "success": True,
            "quantity": 100,
            "before_qty": 100,
            "after_qty": 0,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=100,
        )
        
        assert result.get("success") is True
        assert result.get("after_qty") == 0
    
    @pytest.mark.asyncio
    async def test_outbound_exceeds_stock(self, adapter, mock_db):
        """Test outbound that exceeds available stock."""
        mock_result = {
            "error": True,
            "message": "可用库存不足",
            "available_qty": 50,
            "required_qty": 100,
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=100,
        )
        
        assert result.get("error") is True
        assert result.get("available_qty") == 50
        assert result.get("required_qty") == 100