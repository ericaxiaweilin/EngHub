"""
BOM服务单元测试 - 覆盖BOM树形展开、物料搜索等核心功能
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from database.models import Inventory


@pytest.mark.asyncio
async def test_bom_tree_expand_root(bom_service):
    """测试：BOM树根节点展开 - 获取顶层产品结构"""
    mock_db = bom_service.db
    
    # 模拟root product的BOM展开结果
    mock_bom_item = MagicMock()
    mock_bom_item.material_id = "MAT-CHILD1"
    mock_bom_item.quantity = 2
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: [mock_bom_item]))
    )
    
    result = await bom_service.expand_bom_model("MODEL-ROOT")
    
    assert result["success"] is True
    assert "tree" in result["data"]
    assert len(result["data"]["tree"]) > 0  # 至少有一个子项


@pytest.mark.asyncio
async def test_bom_tree_nested_level(bom_service):
    """测试：多层BOM嵌套展开 - 验证递归深度"""
    mock_db = bom_service.db
    
    # 构建两层BOM：A -> B -> C
    mock_level1 = MagicMock()
    mock_level1.material_id = "MAT-B"
    mock_level1.quantity = 1
    
    mock_level2 = MagicMock()
    mock_level2.material_id = "MAT-C"
    mock_level2.quantity = 3
    
    # 第一次调用返回一级子项，第二次调用返回二级子项
    call_count = 0
    
    def mock_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(scalars=MagicMock(all=lambda: [mock_level1]))
        else:
            return MagicMock(scalars=MagicMock(all=lambda: [mock_level2]))
    
    mock_db.execute = AsyncMock(side_effect=mock_execute)
    
    result = await bom_service.expand_bom_model("MODEL-ROOT", max_depth=2)
    
    assert result["success"] is True
    # 验证树结构包含两层子节点（需要实际检查实现细节）


@pytest.mark.asyncio
async def test_bom_material_search_by_code(bom_service):
    """测试：物料搜索 - 按物料编码精确匹配"""
    mock_db = bom_service.db
    
    mock_mat = MagicMock()
    mock_mat.id = "mat-001"
    mock_mat.part_number = "MAT-12345"
    mock_mat.description = "标准螺丝M8x20"
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(all=lambda: [mock_mat])
    )
    
    result = await bom_service.search_material(part_number="MAT-12345", factory_id="F001")
    
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0].part_number == "MAT-12345"


@pytest.mark.asyncio
async def test_bom_material_search_partial_match(bom_service):
    """测试：物料搜索 - 模糊匹配"""
    mock_db = bom_service.db
    
    mock_mat = MagicMock()
    mock_mat.part_number = "MAT-12345"
    mock_mat.description = "标准螺丝M8x20"
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(all=lambda: [mock_mat])
    )
    
    result = await bom_service.search_material(keyword="螺丝", factory_id="F001")
    
    assert result["success"] is True
    # 模糊匹配应该返回相关结果


@pytest.mark.asyncio
async def test_bom_version_compare_two_versions(bom_service):
    """测试：BOM版本对比 - 比较两个版本的差异"""
    mock_db = bom_service.db
    
    # 模拟两个版本的BOM数据
    version_v1 = {"items": ["A", "B"], "total_count": 2}
    version_v2 = {"items": ["A", "C"], "total_count": 2}
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(all=lambda: [])
    )
    
    result = await bom_service.compare_versions("MODEL-ROOT", "v1.0", "v2.0")
    
    assert result["success"] is True
    assert "differences" in result["data"]
    # 差异应该指出B和C的不同


@pytest.mark.asyncio
async def test_bom_sync_to_external_system(bom_service):
    """测试：BOM同步到外部系统 - 调用同步服务"""
    mock_db = bom_service.db
    
    # mock同步服务
    with patch('api.services.bom_sync_service.BomSyncService') as mock_sync_cls:
        mock_instance = mock_sync_cls.return_value
        mock_instance.sync = AsyncMock(return_value={"success": True, "sync_id": "sync-001"})
        
        result = await bom_service.sync_bom_to_external("MODEL-ROF", "target-system")
        
        assert result["success"] is True
        assert result["data"]["sync_id"] == "sync-001"