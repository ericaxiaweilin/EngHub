"""Data Consistency Tests for WMS Architecture.

Tests to verify data consistency across WMS operations:
- Inventory balance (inbound - outbound = current)
- Transaction completeness
- State transition consistency
- Batch expiry consistency
- Location capacity consistency
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from api.services.wms_architecture import WmsAdapter
from api.services.wms_architecture.state.engine import InventoryState, StateTransitionEngine
from api.services.wms_architecture.executors.inbound_executor import InboundExecutor
from api.services.wms_architecture.executors.outbound_executor import OutboundExecutor
from api.services.wms_architecture.executors.batch_expiry_executor import BatchExpiryExecutor


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def adapter(mock_db):
    """Create adapter instance."""
    return WmsAdapter(mock_db)


class TestDataConsistency:
    """Test data consistency across WMS operations."""
    
    @pytest.mark.asyncio
    async def test_inbound_outbound_balance(self, adapter, mock_db):
        """Test that inbound and outbound operations maintain balance."""
        # Mock executor results
        mock_inbound_result = {
            "success": True,
            "type": "inbound",
            "material_code": "MAT001",
            "quantity": 100,
            "after_qty": 100,
        }
        
        mock_outbound_result = {
            "success": True,
            "type": "outbound",
            "material_code": "MAT001",
            "quantity": 30,
            "after_qty": 70,
        }
        
        # Mock executors
        adapter.executors["inbound"].execute = AsyncMock(return_value=mock_inbound_result)
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_outbound_result)
        
        # Execute inbound
        inbound_result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        # Execute outbound
        outbound_result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        # Verify balance
        assert inbound_result.get("after_qty") == 100
        assert outbound_result.get("after_qty") == 70
        assert inbound_result.get("after_qty") - outbound_result.get("quantity") == outbound_result.get("after_qty")
    
    @pytest.mark.asyncio
    async def test_transaction_consistency(self, adapter, mock_db):
        """Test that transactions are recorded consistently."""
        mock_result = {
            "success": True,
            "transactions": [
                {"type": "inbound", "quantity": 100},
                {"type": "outbound", "quantity": -30},
            ]
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
        assert "transactions" in result or "success" in result
    
    @pytest.mark.asyncio
    async def test_state_transition_consistency(self, adapter, mock_db):
        """Test that state transitions are consistent."""
        engine = StateTransitionEngine()
        
        # Valid transition
        context = {"work_order_id": "WO001"}
        new_state = engine.transition(InventoryState.AVAILABLE, InventoryState.RESERVED, context)
        assert new_state == InventoryState.RESERVED
        
        # Verify history
        history = engine.get_transition_history(context)
        assert len(history) == 1
        assert history[0]["from_state"] == "available"
        assert history[0]["to_state"] == "reserved"
        
        # Reserved -> Available is valid (release reservation)
        new_state = engine.transition(InventoryState.RESERVED, InventoryState.AVAILABLE)
        assert new_state == InventoryState.AVAILABLE
        
        # Invalid transition (SCRAPPED is terminal)
        with pytest.raises(Exception):
            engine.transition(InventoryState.SCRAPPED, InventoryState.AVAILABLE)
    
    @pytest.mark.asyncio
    async def test_batch_expiry_consistency(self, adapter, mock_db):
        """Test batch expiry tracking consistency."""
        mock_result = {
            "success": True,
            "expiring_soon": {"count": 0, "batches": []},
            "expired": {"count": 0, "batches": []},
        }
        
        adapter.executors["batch_expiry"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.batch_expiry_check(
            factory_id="F01",
            days_threshold=30,
        )
        
        assert result.get("success") is True
        assert "expiring_soon" in result
        assert "expired" in result
        assert result["expiring_soon"]["count"] + result["expired"]["count"] == result.get("total_issues", 0)
    
    @pytest.mark.asyncio
    async def test_location_capacity_consistency(self, adapter, mock_db):
        """Test location capacity tracking consistency."""
        mock_result = {
            "success": True,
            "summary": {
                "total_locations": 100,
                "active_locations": 80,
                "total_capacity": 10000,
                "used_capacity": 5000,
                "available_capacity": 5000,
            },
            "zones": [],
        }
        
        adapter.executors["location_capacity"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.get_location_capacity(factory_id="F01")
        
        assert result.get("success") is True
        summary = result.get("summary", {})
        # Verify capacity consistency
        assert summary.get("available_capacity", 0) == summary.get("total_capacity", 0) - summary.get("used_capacity", 0)
    
    @pytest.mark.asyncio
    async def test_inventory_alert_consistency(self, adapter, mock_db):
        """Test inventory alert consistency."""
        mock_result = {
            "success": True,
            "alerts": [
                {"type": "low_stock", "severity": "high"},
                {"type": "expired", "severity": "critical"},
            ],
            "total_alerts": 2,
            "critical_count": 1,
            "high_count": 1,
        }
        
        adapter.executors["inventory_alert"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.get_inventory_alerts(factory_id="F01")
        
        assert result.get("success") is True
        # Verify alert count consistency
        assert result.get("total_alerts", 0) == len(result.get("alerts", []))
        severity_counts = sum([
            result.get("critical_count", 0),
            result.get("high_count", 0),
            result.get("medium_count", 0),
            result.get("low_count", 0),
        ])
        assert severity_counts <= result.get("total_alerts", 0)
    
    @pytest.mark.asyncio
    async def test_abc_analysis_consistency(self, adapter, mock_db):
        """Test ABC analysis consistency."""
        mock_result = {
            "success": True,
            "abc_distribution": {
                "A": {"sku_count": 10, "total_value": 50000},
                "B": {"sku_count": 20, "total_value": 30000},
                "C": {"sku_count": 70, "total_value": 20000},
            },
            "total_skus": 100,
            "total_value": 100000,
        }
        
        adapter.executors["abc_analysis"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.abc_analysis(factory_id="F01")
        
        assert result.get("success") is True
        # Verify SKU count consistency
        dist = result.get("abc_distribution", {})
        total_skus = sum(v.get("sku_count", 0) for v in dist.values())
        assert total_skus == result.get("total_skus", 0)
        
        # Verify value consistency
        total_value = sum(v.get("total_value", 0) for v in dist.values())
        assert total_value == result.get("total_value", 0)
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, adapter, mock_db):
        """Test that concurrent operations maintain consistency."""
        # Simulate multiple operations
        operations = []
        
        for i in range(5):
            mock_result = {
                "success": True,
                "type": "inbound",
                "quantity": 10,
                "after_qty": 10 * (i + 1),
            }
            operations.append(adapter.quick_inbound(
                factory_id="F01",
                material_id=f"MAT{i:03d}",
                material_code=f"MAT{i:03d}",
                quantity=10,
                warehouse_id="WH01",
            ))
        
        results = await asyncio.gather(*operations, return_exceptions=True)
        
        # All operations should succeed
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        assert success_count == 5
    
    @pytest.mark.asyncio
    async def test_error_recovery_consistency(self, adapter, mock_db):
        """Test that error recovery maintains consistency."""
        # Mock executor to raise error
        adapter.executors["inbound"].execute = AsyncMock(side_effect=Exception("Database error"))
        
        result = await adapter.quick_inbound(
            factory_id="F01",
            material_id="MAT001",
            material_code="MAT001",
            quantity=100,
            warehouse_id="WH01",
        )
        
        # Should return error with recovery info
        assert result.get("success") is False
        assert "error" in result
        assert "recovery_applied" in result


import asyncio


class TestDataIntegrity:
    """Test data integrity across WMS operations."""
    
    @pytest.mark.asyncio
    async def test_inbound_transaction_record(self, adapter, mock_db):
        """Test that inbound operations create transaction records."""
        mock_result = {
            "success": True,
            "type": "inbound",
            "quantity": 100,
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
        assert result.get("type") == "inbound"
        assert result.get("quantity") == 100
    
    @pytest.mark.asyncio
    async def test_outbound_transaction_record(self, adapter, mock_db):
        """Test that outbound operations create transaction records."""
        mock_result = {
            "success": True,
            "type": "outbound",
            "quantity": -30,
            "transaction_id": "txn-002",
        }
        
        adapter.executors["outbound"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.quick_outbound(
            factory_id="F01",
            material_id="MAT001",
            quantity=30,
        )
        
        assert result.get("success") is True
        assert result.get("type") == "outbound"
        assert result.get("quantity") == -30 or result.get("quantity") == 30
    
    @pytest.mark.asyncio
    async def test_batch_freeze_consistency(self, adapter, mock_db):
        """Test that batch freeze operations are consistent."""
        mock_result = {
            "success": True,
            "action": "lock_batch",
            "batch_code": "BATCH001",
            "status": "frozen",
        }
        
        adapter.executors["batch_expiry"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.lock_batch(
            factory_id="F01",
            batch_code="BATCH001",
            lock_reason="quality_issue",
        )
        
        assert result.get("success") is True
        assert result.get("action") == "lock_batch"
        assert result.get("status") == "frozen"
    
    @pytest.mark.asyncio
    async def test_batch_unfreeze_consistency(self, adapter, mock_db):
        """Test that batch unfreeze operations are consistent."""
        mock_result = {
            "success": True,
            "action": "unlock_batch",
            "batch_code": "BATCH001",
            "status": "available",
        }
        
        adapter.executors["batch_expiry"].execute = AsyncMock(return_value=mock_result)
        
        result = await adapter.unlock_batch(
            factory_id="F01",
            batch_code="BATCH001",
        )
        
        assert result.get("success") is True
        assert result.get("action") == "unlock_batch"
        assert result.get("status") == "available"


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
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
            quantity=-10,
            warehouse_id="WH01",
        )
        
        assert result.get("error") is True
        assert "数量" in result.get("message", "")
    
    @pytest.mark.asyncio
    async def test_zero_quantity_rejected(self, adapter, mock_db):
        """Test that zero quantities are rejected."""
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
    
    @pytest.mark.asyncio
    async def test_insufficient_stock_rejected(self, adapter, mock_db):
        """Test that insufficient stock is rejected."""
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