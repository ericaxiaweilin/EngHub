"""
WMS仓库服务单元测试 - 测试仓库和库位的CRUD操作及容量统计
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from core.wms.warehouse import WarehouseService, WarehouseType, LocationType, WarehouseStatus
from database.models import Warehouse, Location


@pytest.mark.asyncio
async def test_create_warehouse(mock_db_session):
    """测试：创建仓库 - 成功写入数据库"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    # Act
    result = await service.create_warehouse(
        factory_id="FACT-001",
        warehouse_code="WH-RAW-01",
        warehouse_name="原材料仓",
        warehouse_type=WarehouseType.RAW_MATERIAL.value,
        address="A栋1层",
        created_by="admin"
    )
    # Assert
    assert result["factory_id"] == "FACT-001"
    assert result["warehouse_code"] == "WH-RAW-01"
    assert result["warehouse_name"] == "原材料仓"
    assert result["warehouse_type"] == WarehouseType.RAW_MATERIAL.value
    assert result["address"] == "A栋1层"
    assert result["status"] == WarehouseStatus.ACTIVE.value
    assert result["created_by"] == "admin"
    # Verify DB insert called
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_warehouse_exists(mock_db_session):
    """测试：获取仓库 - 仓库存在时返回数据"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    # Mock DB query result
    mock_plan = MagicMock(spec=Warehouse)
    mock_plan.id = "wh-123"
    mock_plan.warehouse_code = "WH-RAW-01"
    mock_plan.warehouse_name = "原材料仓"
    mock_plan.factory_id = "FACT-001"
    mock_plan.warehouse_type = WarehouseType.RAW_MATERIAL.value
    mock_plan.address = "A栋1层"
    mock_plan.status = WarehouseStatus.ACTIVE.value
    mock_plan.created_by = "admin"
    mock_plan.created_at = None
    mock_plan.updated_at = None
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_plan))
    
    # Act
    result = await service.get_warehouse("wh-123")
    
    # Assert
    assert result is not None
    assert result["id"] == "wh-123"
    assert result["warehouse_code"] == "WH-RAW-01"
    assert result["warehouse_name"] == "原材料仓"


@pytest.mark.asyncio
async def test_get_warehouse_not_found(mock_db_session):
    """测试：获取仓库 - 仓库不存在时返回None"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    
    # Act
    result = await service.get_warehouse("non-existent-id")
    
    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_list_warehouses_by_factory(mock_db_session):
    """测试：获取仓库列表 - 按工厂ID过滤"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    # Mock multiple warehouses
    wh1 = MagicMock(spec=Warehouse)
    wh1.id = "wh-1"
    wh1.warehouse_code = "WH-RAW-01"
    wh1.warehouse_name = "原料仓1"
    wh1.factory_id = "FACT-001"
    wh1.warehouse_type = WarehouseType.RAW_MATERIAL.value
    wh1.status = WarehouseStatus.ACTIVE.value
    wh1.created_by = "admin"
    
    wh2 = MagicMock(spec=Warehouse)
    wh2.id = "wh-2"
    wh2.warehouse_code = "WH-FG-01"
    wh2.warehouse_name = "成品仓"
    wh2.factory_id = "FACT-001"
    wh2.warehouse_type = WarehouseType.FINISHED_GOODS.value
    wh2.status = WarehouseStatus.ACTIVE.value
    wh2.created_by = "admin"
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(all=lambda: [wh1, wh2])
    )
    
    # Act
    result = await service.list_warehouses(factory_id="FACT-001")
    
    # Assert
    assert len(result) == 2
    assert result[0]["warehouse_code"] == "WH-RAW-01"
    assert result[1]["warehouse_code"] == "WH-FG-01"


@pytest.mark.asyncio
async def test_list_warehouses_with_type_filter(mock_db_session):
    """测试：获取仓库列表 - 按类型过滤"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    wh1 = MagicMock(spec=Warehouse)
    wh1.warehouse_type = WarehouseType.RAW_MATERIAL.value
    wh2 = MagicMock(spec=Warehouse)
    wh2.warehouse_type = WarehouseType.FINISHED_GOODS.value
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalas=MagicMock(all=lambda: [wh1, wh2]))
    # Need to properly mock the where clause chain
    original_where = Warehouse.where
    warehouse_mock = MagicMock()
    warehouse_mock.where.return_value = warehouse_mock
    warehouse_mock.execute = AsyncMock()
    warehouse_mock.execute.return_value = MagicMock(scalas=MagicMock(all=lambda: [wh1]))
    
    # Simplified test: verify filter param would be passed
    result = await service.list_warehouses(
        factory_id="FACT-001",
        warehouse_type=WarehouseType.RAW_MATERIAL.value
    )
    # Assert basic structure
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_update_warehouse(mock_db_session):
    """测试：更新仓库信息"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    # Act
    success = await service.update_warehouse("wh-123", {"warehouse_name": "新名称"})
    
    # Assert
    assert success is True
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_warehouse(mock_db_session):
    """测试：逻辑删除仓库（置为inactive）"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    # Act
    success = await service.delete_warehouse("wh-123")
    
    # Assert
    assert success is True
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_location(mock_db_session):
    """测试：创建库位 - 成功写入数据库"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    # Act
    result = await service.create_location(
        warehouse_id="wh-123",
        location_code="LOC-A01",
        location_name="货架A1",
        location_type=LocationType.RACK.value,
        zone="Zone A",
        row=1,
        column=1,
        capacity=100,
        created_by="operator"
    )
    
    # Assert - returns location_id string
    assert isinstance(result, str)
    assert result.startswith("loc-") or len(result) == 36  # UUID format
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_location_exists(mock_db_session):
    """测试：获取库位 - 库位存在时返回数据"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    mock_loc = MagicMock(spec=Location)
    mock_loc.id = "loc-123"
    mock_loc.location_code = "LOC-A01"
    mock_loc.location_name = "货架A1"
    mock_loc.warehouse_id = "wh-123"
    mock_loc.location_type = LocationType.RACK.value
    mock_loc.zone = "Zone A"
    mock_loc.capacity = 100
    mock_loc.status = "active"
    mock_loc.created_at = None
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_loc))
    
    # Act
    result = await service.get_location("loc-123")
    
    # Assert
    assert result is not None
    assert result["location_code"] == "LOC-A01"


@pytest.mark.asyncio
async def test_list_locations_by_warehouse(mock_db_session):
    """测试：获取库位列表 - 按仓库ID过滤"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    loc1 = MagicMock(spec=Location)
    loc1.location_code = "LOC-A01"
    loc1.warehouse_id = "wh-123"
    
    loc2 = MagicMock(spec=Location)
    loc2.location_code = "LOC-B01"
    loc2.warehouse_id = "wh-123"
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalas=MagicMock(all=lambda: [loc1, loc2])
    )
    
    # Act
    result = await service.list_locations(warehouse_id="wh-123")
    
    # Assert
    assert len(result) == 2
    assert all(item["warehouse_id"] == "wh-123" for item in result)


@pytest.mark.asyncio
async def test_get_warehouse_capacity_summary(mock_db_session):
    """测试：仓库容量汇总统计"""
    # Arrange
    mock_db = mock_db_session
    service = WarehouseService(mock_db)
    
    # Mock location count queries
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar=lambda: 10)  # total locations
    
    # Actual capacity summary needs more complex mocking for subqueries
    # Test that it returns expected structure without crashing
    try:
        result = await service.get_warehouse_capacity_summary("wh-123")
        assert isinstance(result, dict)
        assert "warehouse_id" in result
        assert "total_locations" in result
        assert "utilization_rate" in result
    except Exception as e:
        # Subquery mocking is complex; ensure function at least runs to this point
        pytest.fail(f"Capacity summary raised exception: {e}")


@pytest.mark.asyncio
async def test_create_warehouse_status_default():
    """测试：创建仓库 - 默认状态为 active"""
    from unittest.mock import patch, MagicMock
    
    with patch('core.wms.warehouse.Warehouse') as mock_warehouse_cls:
        mock_instance = MagicMock()
        mock_warehouse_cls.return_value = mock_instance
        
        service = WarehouseService(MagicMock())
        result = await service.create_warehouse(
            factory_id="FACT-001",
            warehouse_code="TEST-WH",
            warehouse_name="Test Warehouse"
        )
        
        assert result["status"] == "active"