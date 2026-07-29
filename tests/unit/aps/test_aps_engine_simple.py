"""
APS排程引擎简化测试 - P0优先级验证
仅验证测试框架和基础mock交互是否正常
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from database.models import WorkOrder


@pytest.mark.asyncio
async def test_aps_engine_fixture_available():
    """测试：ApsEngine fixture是否可正常导入和使用"""
    from api.services.aps_engine import ApsEngine
    
    # 这个测试只是确认类可以被导入
    assert ApsEngine is not None
    assert hasattr(ApsEngine, 'schedule')
    assert hasattr(ApsEngine, 'reschedule')
    assert hasattr(ApsEngine, 'detect_conflicts')


@pytest.mark.asyncio
async def test_aps_schedule_method_exists():
    """测试：schedule方法是否存在且为async"""
    from api.services.aps_engine import ApsEngine
    
    # 检查方法存在性
    assert hasattr(ApsEngine, 'schedule')
    schedule_method = getattr(ApsEngine, 'schedule')
    # 应该是协变函数
    import inspect
    assert inspect.iscoroutinefunction(schedule_method)


@pytest.mark.asyncio
async def test_mock_aps_engine_works():
    """测试：mock ApsEngine是否能正确响应调用"""
    from api.services.aps_engine import ApsEngine
    
    # 创建真实实例并用patch替换其方法
    with patch.object(ApsEngine, 'schedule', new_callable=AsyncMock) as mock_schedule:
        mock_schedule.return_value = {"success": True, "message": "mocked"}
        
        engine = ApsEngine(MagicMock())
        result = await engine.schedule("F001", algorithm="EDD", horizon_days=7)
        
        assert result["success"] is True
        mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_aps_detect_conflicts_mock():
    """测试：detect_conflicts方法mock测试"""
    from api.services.aps_engine import ApsEngine
    
    with patch.object(ApsEngine, 'detect_conflicts', new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = {
            "has_conflicts": False,
            "conflicting_stations": [],
            "recommendations": []
        }
        
        engine = ApsEngine(MagicMock())
        result = await engine.detect_conflicts("F001")
        
        assert result["has_conflicts"] is False