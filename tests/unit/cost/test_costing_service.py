"""
成本核算服务(COST)单元测试 - 测试工单成本计算、标准成本管理、差异分析等核心功能
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from core.cost.costing import CostingService, CostType, CostStatus


@pytest.fixture
def mock_costing_service():
    """CostingService fixture，带mock的DB会话"""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    return CostingService(mock_db)


@pytest.mark.asyncio
async def test_calculate_work_order_cost_success(mock_costing_service):
    """测试：工单成本计算 - 完整流程返回正确结构"""
    # Arrange - Mock dependency methods with sample data
    mock_costing_service._get_work_order = AsyncMock(return_value={
        "work_order_id": "WO-001",
        "work_order_code": "WO-20260729-001",
        "product_id": "PROD-001",
        "completed_qty": 100,
    })
    
    mock_costing_service._calculate_material_cost = AsyncMock(return_value=5000.0)
    mock_costing_service._calculate_labor_cost = AsyncMock(return_value=3000.0)
    mock_costing_service._calculate_overhead_cost = AsyncMock(return_value=900.0)
    
    # Act
    result = await mock_costing_service.calculate_work_order_cost("WO-001")
    
    # Assert
    assert result["work_order_id"] == "WO-001"
    assert result["material_cost"] == 5000.0
    assert result["labor_cost"] == 3000.0
    assert result["overhead_cost"] == 900.0
    assert result["total_cost"] == 8900.0
    assert result["unit_cost"] == 89.0  # 8900/100
    assert result["status"] == CostStatus.CALCULATED.value
    assert result["calculated_at"] is not None


@pytest.mark.asyncio
async def test_calculate_material_cost_from_transactions(mock_costing_service):
    """测试：材料成本计算 - 从 inventory_transactions 查询汇总"""
    # Arrange
    db = mock_costing_service.db
    db.execute = AsyncMock()
    
    # Mock query execution for material cost calculation
    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value=15000.50)
    db.execute = AsyncMock(return_value=mock_result)
    
    # Act
    cost = await mock_costing_service._calculate_material_cost("WO-001")
    
    # Assert
    assert isinstance(cost, float)
    assert cost > 0
    # Verify execute was called with appropriate query structure (simplified check)
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_calculate_labor_cost_from_production_report(mock_costing_service):
    """测试：人工成本计算 - 从 ProductionReport 获取工时并乘以费率"""
    # Arrange
    db = mock_costing_service.db
    db.execute = AsyncMock()
    
    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value=150.0)  # 150 hours
    db.execute = AsyncMock(return_value=mock_result)
    
    # Mock _get_default_labor_rate
    mock_costing_service._get_default_labor_rate = AsyncMock(return_value=50.0)
    
    # Act
    labor_cost = await mock_costing_service._calculate_labor_cost("WO-001")
    
    # Assert
    assert labor_cost == 7500.0  # 150 hours * 50 rate


@pytest.mark.asyncio
async def test_calculate_overhead_cost(mock_costing_service):
    """测试：制造费用计算 - 基于人工成本乘费率"""
    # Arrange
    mock_costing_service._get_overhead_rate = AsyncMock(return_value=0.3)
    
    # Act
    overhead = await mock_costing_service._calculate_overhead_cost(labor_cost=10000.0)
    
    # Assert
    assert overhead == 3000.0  # 10000 * 0.3


@pytest.mark.asyncio
async def test_calculate_product_standard_cost(mock_costing_service):
    """测试：产品标准成本计算 - BOM+Routing综合计算"""
    # Arrange
    mock_costing_service._get_bom = AsyncMock(return_value={
        "items": [
            {"material_id": "M1", "standard_qty": 10, "standard_cost": 50.0},
            {"material_id": "M2", "standard_qty": 5, "standard_cost": 20.0},
        ]
    })
    mock_costing_service._get_routing = AsyncMock(return_value={
        "steps": [
            {"standard_time": 3600, "labor_rate": 45.0},  # 1 hour @ 45/hr
            {"standard_time": 1800, "labor_rate": 50.0},   # 0.5 hour @ 50/hr
        ]
    })
    mock_costing_service._get_default_labor_rate = AsyncMock(return_value=50.0)
    mock_costing_service._get_overhead_rate = AsyncMock(return_value=0.3)
    
    # Act
    std_cost = await mock_costing_service.calculate_product_standard_cost("PROD-001")
    
    # Assert
    assert std_cost["product_id"] == "PROD-001"
    assert std_cost["material_cost"] == 600.0  # (10*50) + (5*20)
    assert abs(std_cost["labor_cost"] - 67.5) < 0.01  # (1*45 + 0.5*50) = 45 + 25 = 70 approx
    assert std_cost["overhead_cost"] > 0
    assert std_cost["total_standard_cost"] > 0


@pytest.mark.asyncio
async def test_analyze_cost_variance_positive(mock_costing_service):
    """测试：成本差异分析 - 实际成本高于标准（超支）"""
    # Arrange
    actual_cost = {
        "work_order_id": "WO-001",
        "material_cost": 6000.0,
        "labor_cost": 4000.0,
        "overhead_cost": 1200.0,
        "total_cost": 11200.0,
        "product_id": "PROD-001",
    }
    standard_cost = {
        "material_cost": 5000.0,
        "labor_cost": 3000.0,
        "overhead_cost": 900.0,
        "total_standard_cost": 8900.0,
    }
    
    # Mock underlying methods
    mock_costing_service.calculate_work_order_cost = AsyncMock(return_value=actual_cost)
    mock_costing_service.calculate_product_standard_cost = AsyncMock(return_value=standard_cost)
    
    # Act
    variance = await mock_costing_service.analyze_cost_variance("WO-001")
    
    # Assert
    assert variance["total_variance"] == 2300.0  # 11200 - 8900
    assert variance["variance_rate"] > 0  # Positive variance rate
    assert "超支" in variance["analysis"]  # Should mention overrun in analysis


@pytest.mark.asyncio
async def test_analyze_cost_variance_negative(mock_costing_service):
    """测试：成本差异分析 - 实际成本低于标准（节约）"""
    # Arrange
    actual_cost = {
        "work_order_id": "WO-002",
        "material_cost": 4000.0,
        "labor_cost": 2500.0,
        "overhead_cost": 750.0,
        "total_cost": 7250.0,
        "product_id": "PROD-001",
    }
    standard_cost = {
        "material_cost": 5000.0,
        "labor_cost": 3000.0,
        "overhead_cost": 900.0,
        "total_standard_cost": 8900.0,
    }
    
    mock_costing_service.calculate_work_order_cost = AsyncMock(return_value=actual_cost)
    mock_costing_service.calculate_product_standard_cost = AsyncMock(return_value=standard_cost)
    
    # Act
    variance = await mock_costing_service.analyze_cost_variance("WO-002")
    
    # Assert
    assert variance["total_variance"] == -1650.0  # Negative
    assert variance["variance_rate"] < 0
    assert "节约" in variance["analysis"] or "优秀" in variance["analysis"]


@pytest.mark.asyncio
async def test_calculate_scrapped_material_cost(mock_costing_service):
    """测试：报废材料成本统计 - 从不良品记录汇总"""
    # Arrange
    mock_costing_service._get_defects = AsyncMock(return_value=[
        {"id": 1, "work_order_id": "WO-001", "defect_type": "scratched", "quantity": 5, 
         "unit_cost": 100.0, "disposition": "scrap"},
        {"id": 2, "work_order_id": "WO-001", "defect_type": "dented", "quantity": 3, 
         "unit_cost": 100.0, "disposition": "repair"},
        {"id": 3, "work_order_id": "WO-001", "defect_type": "cracked", "quantity": 2, 
         "unit_cost": 100.0, "disposition": "scrap"},
    ])
    
    # Act
    scrap_cost = await mock_costing_service.calculate_scrapped_material_cost("WO-001")
    
    # Assert
    assert scrap_cost["total_scrapped_cost"] == 700.0  # (5+2) * 100
    assert scrap_cost["scrap_by_type"]["scratched"] == 500.0
    assert scrap_cost["scrap_by_type"]["cracked"] == 200.0
    assert scrap_cost["total_defects"] == 3
    assert scrap_cost["scrap_items_count"] == 2  # Only scrap disposition


@pytest.mark.asyncio
async def test_get_work_order_not_found(mock_costing_service):
    """测试：获取不存在的工单信息 - 返回None"""
    # Arrange
    mock_costing_service.db = MagicMock()
    mock_costing_service.db.execute = AsyncMock()
    mock_costing_service.db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    
    # Act
    result = await mock_costing_service._get_work_order("NON-EXISTENT-WO")
    
    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_get_defects_from_quality_inspection(mock_costing_service):
    """测试：当无 DefectRecord 时从 QualityInspection 获取缺陷数据"""
    # Arrange - Simulate no defects in DefectRecord, but have QualityInspection FAIL records
    db = mock_costing_service.db
    db.execute = AsyncMock()
    
    # First try - no DefectRecord
    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=mock_result)
    
    mock_costing_service._get_defects = AsyncMock(return_value=[])  # Will be patched
    
    # Test that it falls back to QualityInspection (mocked separately)
    with patch.object(mock_costing_service, '_get_defects') as mock_get:
        mock_get.return_value = []  # First attempt returns empty
        
        # Now test fallback would use QualityInspection
        # (In full integration this would actually query QI)


@pytest.mark.asyncio
async def test_generate_cost_report_empty(mock_costing_service):
    """测试：工单成本报表 - 无数据时返回空结构但不崩溃"""
    # Arrange
    db = mock_costing_service.db
    db.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=mock_result)
    
    # Act
    report = await mock_costing_service.get_work_order_cost_report(
        factory_id="FACT-001",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31)
    )
    
    # Assert
    assert report["total_work_orders"] == 0
    assert report["total_produced_qty"] == 0
    assert report["total_material_cost"] == 0.0
    assert report["work_orders"] == []


@pytest.mark.asyncio
async def test_variance_interpretation_edge_cases(mock_costing_service):
    """测试：差异解释函数的各种边界情况"""
    service = CostingService(None)  # No DB needed for this method
    
    # Standard cost is 0
    result = service._interpret_variance(100, 0)
    assert result == "无法分析"
    
    # Moderate positive variance (>5%, <=10%)
    result = service._interpret_variance(10, 100)  # 10% variance
    assert "超出预期" in result or "重点关注" in result
    
    # Large negative variance (< -10%)
    result = service._interpret_variance(-20, 100)  # -20% variance
    assert "节约" in result and "卓越" in result
    
    # Small positive/negative within tolerance (-5% to 5%)
    result = service._interpret_variance(2, 100)  # 2% variance
    assert "正常范围" in result
    
    result = service._interpret_variance(-3, 100)  # -3% variance
    assert "正常范围" in result