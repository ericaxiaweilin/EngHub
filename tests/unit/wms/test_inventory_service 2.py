"""
WMS库存服务单元测试 - 测试入库、出库、库存查询等核心功能
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime, date
from core.wms.inventory import InventoryService, TransactionType, InventoryStatus
from database.models import Inventory, InboundOrder, OutboundOrder


@pytest.fixture
def mock_inventory_service():
    """InventoryService fixture，带mock的DB会话"""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return InventoryService(mock_db)


@pytest.mark.asyncio
async def test_generate_batch_code(mock_inventory_service):
    """测试：生成批次号格式正确"""
    # Act
    batch_code = mock_inventory_service.generate_batch_code("MAT-001")
    
    # Assert
    assert isinstance(batch_code, str)
    assert batch_code.startswith("BATCH-MAT-001-")
    assert len(batch_code) > 20  # includes UUID suffix


@pytest.mark.asyncio
async def test_get_inventory_no_records(mock_inventory_service):
    """测试：获取无库存物料信息"""
    # Arrange
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(scalas=MagicMock(all=lambda: []))
    
    # Act
    result = await mock_inventory_service.get_inventory("MAT-999", warehouse_id="WH-001")
    
    # Assert
    assert result["material_id"] == "MAT-999"
    assert result["total_qty"] == 0
    assert result["available_qty"] == 0
    assert result["batches"] == []


@pytest.mark.asyncio
async def test_get_inventory_with_records(mock_inventory_service):
    """测试：获取有库存物料信息 - 汇总各状态库存量"""
    # Arrange
    inv1 = MagicMock(spec=Inventory)
    inv1.id = "inv-1"
    inv1.material_id = "MAT-001"
    inv1.batch_code = "BATCH-001"
    inv1.total_qty = 100
    inv1.available_qty = 80
    inv1.reserved_qty = 10
    inv1.status = InventoryStatus.AVAILABLE.value
    inv1.unit_cost = 10.50
    inv1.created_at = datetime(2026, 7, 1, 10, 0, 0)
    
    inv2 = MagicMock(spec=Inventory)
    inv2.id = "inv-2"
    inv2.material_id = "MAT-001"
    inv2.batch_code = "BATCH-002"
    inv2.total_qty = 50
    inv2.available_qty = 45
    inv2.reserved_qty = 0
    inv2.status = InventoryStatus.QC_HOLD.value
    inv2.unit_cost = None
    inv2.created_at = datetime(2026, 7, 2, 10, 0, 0)
    
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalas=MagicMock(all=lambda: [inv1, inv2])
    )
    
    # Act
    result = await mock_inventory_service.get_inventory("MAT-001")
    
    # Assert
    assert result["material_id"] == "MAT-001"
    assert result["total_qty"] == 150  # 100 + 50
    assert result["available_qty"] == 125  # 80 + 45
    assert result["reserved_qty"] == 10
    assert len(result["batches"]) == 2
    assert result["batches"][0]["batch_code"] == "BATCH-001"
    assert result["batches"][1]["status"] == "qc_hold"


@pytest.mark.asyncio
async def test_list_inventory(mock_inventory_service):
    """测试：获取库存列表"""
    # Arrange
    inv = MagicMock(spec=Inventory)
    inv.id = "inv-1"
    inv.material_id = "MAT-001"
    inv.material_code = "MAT-001-CODE"
    inv.material_name = "Test Material"
    inv.factory_id = "FACT-001"
    inv.warehouse_id = "WH-001"
    inv.location_id = "LOC-001"
    inv.batch_code = "BATCH-001"
    inv.total_qty = 100
    inv.available_qty = 90
    inv.reserved_qty = 10
    inv.unit_cost = 15.50
    inv.unit = "pcs"
    inv.status = "available"
    inv.last_movement_at = datetime.now()
    inv.created_at = datetime.now()
    inv.updated_at = datetime.now()
    
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalas=MagicMock(all=lambda: [inv])
    )
    
    # Act
    result = await mock_inventory_service.list_inventory(
        factory_id="FACT-001", material_id="MAT-001"
    )
    
    # Assert
    assert len(result) == 1
    assert result[0]["material_id"] == "MAT-001"
    assert result[0]["material_code"] == "MAT-001-CODE"
    assert result[0]["total_qty"] == 100
    assert result[0]["available_qty"] == 90


@pytest.mark.asyncio
async def test_inbound_new_material(mock_inventory_service):
    """测试：新物料入库 - 创建新的Inventory记录"""
    # Arrange
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.commit = AsyncMock()
    mock_inventory_service.db.refresh = AsyncMock()
    
    # Mock _get_inventory_record returns None (new material)
    mock_inventory_service._get_inventory_record = AsyncMock(return_value=None)
    
    # Act
    result = await mock_inventory_service.inbound(
        factory_id="FACT-001",
        warehouse_id="WH-RAW-01",
        material_id="NEW-MAT",
        material_code="NEW-MAT-001",
        quantity=500,
        unit_cost=10.00,
        location_id="LOC-001",
        created_by="operator"
    )
    
    # Assert
    assert result["inbound_record"]["quantity"] == 500
    assert result["inbound_record"]["status"] == "completed"
    assert result["inventory_record"]["total_qty"] == 500
    assert result["inventory_record"]["available_qty"] == 500
    assert result["inventory_record"]["status"] == "available"
    mock_inventory_service.db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_inbound_existing_material(mock_inventory_service):
    """测试：现有物料入库 - 更新现有Inventory记录"""
    # Arrange
    existing_inv = MagicMock(spec=Inventory)
    existing_inv.total_qty = 100
    existing_inv.available_qty = 80
    
    mock_inventory_service._get_inventory_record = AsyncMock(return_value=existing_inv)
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.commit = AsyncMock()
    
    # Act
    result = await mock_inventory_service.inbound(
        factory_id="FACT-001",
        warehouse_id="WH-RAW-01",
        material_id="EXISTING-MAT",
        material_code="EXISTING-001",
        quantity=200,
        unit_cost=15.00,
        created_by="operator"
    )
    
    # Assert - existing_inv should be updated
    assert existing_inv.total_qty == 300
    assert existing_inv.available_qty == 280  # added 200 to 80
    assert result["inventory_record"]["total_qty"] == 300


@pytest.mark.asyncio
async def test_inbound_qc_hold(mock_inventory_service):
    """测试：质检状态入库 - 物料进入QC_HOLD状态"""
    # Arrange
    mock_inventory_service._get_inventory_record = AsyncMock(return_value=None)
    mock_inventory_service.db.commit = AsyncMock()
    
    # Act with QC_HOLD transaction type
    result = await mock_inventory_service.inbound(
        factory_id="FACT-001",
        warehouse_id="WH-QC-HOLD",
        material_id="QC-MAT",
        material_code="QC-001",
        quantity=100,
        transaction_type=TransactionType.QC_HOLD.value,
        created_by="qc_operator"
    )
    
    # Assert
    assert result["inventory_record"]["status"] == "qc_hold"


@pytest.mark.asyncio
async def test_outbound_fifo_batches_not_found(mock_inventory_service):
    """测试：出库时FIFO批次未找到 - 应抛出异常"""
    # Arrange
    mock_inventory_service._get_fifo_batches = AsyncMock(return_value=[])
    
    # Act - should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await mock_inventory_service.outbound(
            factory_id="FACT-001",
            warehouse_id="WH-001",
            material_id="NO-STOCK",
            quantity=100
        )
    
    assert "无可用库存" in str(exc_info.value)


@pytest.mark.asyncio
async def test_outbound_insufficient_quantity(mock_inventory_service):
    """测试：出库数量超过可用库存 - 应抛出异常"""
    # Arrange
    mock_inventory_service._get_fifo_batches = AsyncMock(
        return_value=[{"batch_code": "BATCH-001", "qty": 50, "location_id": "LOC-001"}]
    )
    
    # Act
    with pytest.raises(ValueError) as exc_info:
        await mock_inventory_service.outbound(
            factory_id="FACT-001",
            warehouse_id="WH-001",
            material_id="MAT-001",
            quantity=100  # Only 50 available
        )
    
    assert "库存不足" in str(exc_info.value)


@pytest.mark.asyncio
async def test_outbound_valid(mock_inventory_service):
    """测试：正常出库 - 扣减库存并创建出库单"""
    # Arrange
    mock_inventory_service._get_fifo_batches = AsyncMock(
        return_value=[{"batch_code": "BATCH-001", "qty": 100, "location_id": "LOC-001"}]
    )
    mock_inventory_service._get_inventory_record = AsyncMock(return_value=MagicMock())
    mock_inventory_service.db.commit = AsyncMock()
    
    # Act
    result = await mock_inventory_service.outbound(
        factory_id="FACT-001",
        warehouse_id="WH-001",
        material_id="MAT-001",
        quantity=100,
        work_order_id="WO-001",
        created_by="worker"
    )
    
    # Assert
    assert result["transaction_type"] == "production_out"
    assert result["quantity"] == 100
    assert result["work_order_id"] == "WO-001"
    assert result["status"] == "completed"
    assert len(result["outbound_batches"]) == 1
    mock_inventory_service.db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_fifo_batches(mock_inventory_service):
    """测试：获取FIFO批次 - 按创建日期排序最早批次优先"""
    # Arrange
    inv1 = MagicMock(spec=Inventory)
    inv1.material_id = "MAT-001"
    inv1.batch_code = "BATCH-A"
    inv1.available_qty = 50
    inv1.unit_cost = 10.0
    inv1.created_at = datetime(2026, 7, 1, 10, 0, 0)
    
    inv2 = MagicMock(spec=Inventory)
    inv2.material_id = "MAT-001"
    inv2.batch_code = "BATCH-B"
    inv2.available_qty = 30
    inv2.unit_cost = 12.0
    inv2.created_at = datetime(2026, 7, 2, 10, 0, 0)  # Later than inv1
    
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalas=MagicMock(all=lambda: [inv1, inv2])
    )
    
    # Act
    batches = await mock_inventory_service._get_fifo_batches(
        factory_id="FACT-001",
        warehouse_id="WH-001",
        material_id="MAT-001",
        required_qty=100
    )
    
    # Assert - BATCH-A should come first (earlier created)
    assert batches[0]["batch_code"] == "BATCH-A"
    assert batches[1]["batch_code"] == "BATCH-B"
    assert batches[0]["qty"] == 50
    assert batches[1]["qty"] == 30


@pytest.mark.asyncio
async def test_reserve_inventory_success(mock_inventory_service):
    """测试：预留库存成功 - 从可用库存中扣除并设置预留量"""
    # Arrange
    mock_inventory_service.get_inventory = AsyncMock(return_value={
        "material_id": "MAT-001",
        "warehouse_id": "WH-001",
        "available_qty": 100,
        "reserved_qty": 20,
        "batches": [{"batch_code": "BATCH-001", "available_qty": 100}]
    })
    mock_inventory_service._get_inventory_records_for_reserve = AsyncMock(
        return_value=[MagicMock(available_qty=100, reserved_qty=None)]
    )
    mock_inventory_service.db.commit = AsyncMock()
    
    # Act
    result = await mock_inventory_service.reserve_inventory(
        material_id="MAT-001",
        warehouse_id="WH-001",
        quantity=50,
        work_order_id="WO-001",
        reserved_by="operator"
    )
    
    # Assert
    assert result["quantity"] == 50
    assert result["work_order_id"] == "WO-001"
    assert result["status"] == "reserved"
    assert result["inventory_updated"] > 0
    mock_inventory_service.db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reserve_inventory_insufficient_stock(mock_inventory_service):
    """测试：预留库存不足 - 应抛出异常"""
    # Arrange
    mock_inventory_service.get_inventory = AsyncMock(return_value={
        "material_id": "MAT-001",
        "warehouse_id": "WH-001",
        "available_qty": 30,
        "reserved_qty": 0,
        "batches": []
    })
    
    # Act
    with pytest.raises(ValueError) as exc_info:
        await mock_inventory_service.reserve_inventory(
            material_id="MAT-001",
            warehouse_id="WH-001",
            quantity=50,  # More than available
            work_order_id="WO-001"
        )
    
    assert "库存不足" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_material_trace_inbound_records(mock_inventory_service):
    """测试：物料追溯 - 获取入库记录历史"""
    # Arrange
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalas=MagicMock(return_value=[])
    )
    
    # Act
    result = await mock_inventory_service.get_material_trace("MAT-001")
    
    # Assert
    assert result["trace_summary"]["total_inbound"] == 0
    assert isinstance(result["inbound_records"], list)


@pytest.mark.asyncio
async def test_get_current_location(mock_inventory_service):
    """测试：获取物料当前所在位置"""
    # Arrange
    inv = MagicMock(spec=Inventory)
    inv.warehouse_id = "WH-001"
    inv.location_id = "LOC-001"
    inv.batch_code = "BATCH-001"
    inv.total_qty = 100
    inv.available_qty = 100
    inv.status = InventoryStatus.AVAILABLE.value
    
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=inv)
    )
    
    # Act
    location = await mock_inventory_service._get_current_location("MAT-001")
    
    # Assert
    assert location is not None
    assert location["warehouse_id"] == "WH-001"
    assert location["location_id"] == "LOC-001"
    assert location["total_qty"] == 100


@pytest.mark.asyncio
async def test_list_inventory_with_filters(mock_inventory_service):
    """测试：库存列表查询 - 多条件过滤"""
    # Arrange
    inv1 = MagicMock(spec=Inventory)
    inv1.material_id = "MAT-001"
    inv1.factory_id = "FACT-001"
    inv1.warehouse_id = "WH-001"
    inv1.status = "available"
    
    inv2 = MagicMock(spec=Inventory)
    inv2.material_id = "MAT-002"
    inv2.factory_id = "FACT-001"
    inv2.warehouse_id = "WH-001"
    inv2.status = "qc_hold"
    
    mock_inventory_service.db.execute = AsyncMock()
    mock_inventory_service.db.execute.return_value = MagicMock(
        scalas=MagicMock(all=lambda: [inv1, inv2])
    )
    
    # Act with filter
    results = await mock_inventory_service.list_inventory(
        factory_id="FACT-001",
        warehouse_id="WH-001",
        status="available"
    )
    
    # Assert - only should return available status
    assert len(results) == 1
    assert results[0]["status"] == "available"


@pytest.mark.asyncio
async def test_submit_count_result_with_adjustments(mock_inventory_service):
    """测试：提交盘点结果 - 包含差异调整建议"""
    # Arrange
    items = [
        {"material_id": "MAT-001", "system_qty": 100, "counted_qty": 105, "difference": 5},
        {"material_id": "MAT-002", "system_qty": 200, "counted_qty": 198, "difference": -2},
    ]
    
    # Act
    result = await mock_inventory_service.submit_count_result("count-001", items)
    
    # Assert
    assert result["count_id"] == "count-001"
    assert result["total_difference"] == 3  # 5 + (-2)
    assert len(result["adjustments"]) == 2
    assert result["adjustments"][0]["adjustment_type"] == "increase"
    assert result["adjustments"][1]["adjustment_type"] == "decrease"
    assert result["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_submit_count_result_no_adjustments(mock_inventory_service):
    """测试：提交盘点结果 - 无差异情况下状态为completed"""
    # Arrange
    items = [
        {"material_id": "MAT-001", "system_qty": 100, "counted_qty": 100, "difference": 0},
    ]
    
    # Act
    result = await mock_inventory_service.submit_count_result("count-002", items)
    
    # Assert
    assert result["status"] == "completed"
    assert len(result["adjustments"]) == 0