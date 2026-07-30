"""
APS排程引擎单元测试 - P0优先级
覆盖调度引擎核心算法、任务队列处理、冲突检测等
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from database.models import ApsSchedule, WorkOrder
from api.services.aps_engine import ApsEngine
from api.services.aps_service import ApsService


@pytest.fixture(scope="function")
def mock_aps_engine():
    """ApsEngine的mock fixture"""
    engine = MagicMock(spec=ApsEngine)
    engine.schedule = AsyncMock()
    engine.reschedule = AsyncMock()
    engine.detect_conflicts = AsyncMock()
    return engine


@pytest.fixture(scope="function")
def mock_db_session():
    """模拟AsyncSession"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_aps_engine_schedule_basic(mock_aps_engine, mock_db_session):
    """测试：APS基本调度 - 成功生成计划"""
    # 设置mock返回值
    mock_aps_engine.schedule.return_value = {
        "success": True,
        "schedule_id": "sched-001",
        "total_tasks": 45,
        "message": "排程成功"
    }
    
    engine = ApsEngine(mock_db_session)
    result = await engine.schedule(
        factory_id="F001",
        priority="high",
        mode="hybrid"
    )
    
    assert result["success"] is True
    assert result["schedule_id"] == "sched-001"
    assert result["total_tasks"] == 45
    # 验证schedule被正确调用
    mock_aps_engine.schedule.assert_called_once_with(
        factory_id="F001", priority="high", mode="hybrid"
    )


@pytest.mark.asyncio
async def test_aps_engine_reschedule_incremental(mock_aps_engine, mock_db_session):
    """测试：增量重排 - 仅影响指定工单"""
    mock_aps_engine.reschedule.return_value = {
        "success": True,
        "affected_wo_count": 3,
        "tasks_revised": 12,
        "message": "3个工单重排完成"
    }
    
    engine = ApsEngine(mock_db_session)
    result = await engine.reschedule(
        factory_id="F001",
        insert_wo_ids=["WO-001", "WO-002"],
        created_by="scheduler"
    )
    
    assert result["success"] is True
    assert result["affected_wo_count"] == 3
    assert result["tasks_revised"] == 12


@pytest.mark.asyncio
async def test_aps_engine_detect_capacity_conflicts(mock_aps_engine, mock_db_session):
    """测试：产能冲突检测 - 识别过载站"""
    mock_aps_engine.detect_conflicts.return_value = {
        "has_conflicts": True,
        "conflicting_stations": [
            {"station_id": "STN-001", "load_pct": 115, "overload_hours": 8}
        ],
        "recommendations": ["调整工时", "增加班次"]
    }
    
    engine = ApsEngine(mock_db_session)
    result = await engine.detect_conflicts(factory_id="F001", days=7)
    
    assert result["has_conflicts"] is True
    assert len(result["conflicting_stations"]) > 0
    assert "recommendations" in result


# ==================== APS Service 层测试 ====================

@pytest.fixture(scope="function")
def mock_aps_service():
    """ApsService的mock fixture"""
    service = MagicMock(spec=ApsService)
    service.generate_schedule = AsyncMock()
    service.confirm_schedule = AsyncMock()
    service.release_schedule = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_aps_service_generate_schedule_success(mock_db_session):
    """测试：APS服务生成计划 - 成功路径"""
    from api.services.aps_service import ApsService
    
    # 真实的服务实例（会实际调用数据库，用mock替换依赖）
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.schedule.return_value = {
            "success": True,
            "schedule_id": "sched-123",
            "plan_count": 5,
            "message": "生成5个生产计划"
        }
        
        service = ApsService(mock_db_session)
        result = await service.generate_schedule(
            factory_id="F001",
            priority="high",
            modes=["hybrid", "constraint_based"]
        )
        
        assert result["success"] is True
        assert result["schedule_id"] == "sched-123"
        assert result["plan_count"] == 5


@pytest.mark.asyncio
async def test_aps_service_confirm_schedule(mock_db_session):
    """测试：确认计划 - 从draft转为confirmed状态"""
    from api.services.aps_service import ApsService
    
    # mock计划对象
    mock_schedule = MagicMock(spec=ApsSchedule)
    mock_schedule.id = "sched-123"
    mock_schedule.status = "draft"
    
    mock_db_session.get = AsyncMock(return_value=mock_schedule)
    mock_db_session.commit = AsyncMock()
    
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        service = ApsService(mock_db_session)
        result = await service.confirm_schedule("sched-123", "user123")
        
        assert result["success"] is True
        # 验证状态已更新
        assert mock_schedule.status == "confirmed"
        assert mock_schedule.confirmed_by == "user123"


@pytest.mark.asyncio
async def test_aps_service_release_schedule(mock_db_session):
    """测试：下达计划 - 触发生成工单"""
    from api.services.aps_service import ApsService
    
    mock_schedule = MagicMock(spec=ApsSchedule)
    mock_schedule.id = "sched-123"
    mock_schedule.status = "confirmed"
    
    mock_db_session.get = AsyncMock(return_value=mock_schedule)
    mock_db_session.commit = AsyncMock()
    
    # mock MES工作订单服务
    with patch('api.services.aps_service.WorkOrderService') as mock_wos_cls:
        mock_wos = mock_wos_cls.return_value
        mock_wos.create_from_schedule = AsyncMock(return_value={"success": True, "wo_count": 10})
        
        service = ApsService(mock_db_session)
        result = await service.release_schedule("sched-123")
        
        assert result["success"] is True
        assert result["message"] == "计划已下达，生成10个工单"
        assert mock_schedule.status == "released"


@pytest.mark.asyncio
async def test_aps_service_get_gantt_data(mock_db_session):
    """测试：获取甘特图数据 - 返回时间轴布局信息"""
    from api.services.aps_service import ApsService
    
    mock_schedule = MagicMock(spec=ApsSchedule)
    mock_schedule.id = "sched-123"
    
    mock_db_session.get = AsyncMock(return_value=mock_schedule)
    
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.get_gantt_data = AsyncMock(return_value={
            "tasks": [
                {"id": "t1", "start": "2026-08-01T08:00", "end": "2026-08-01T12:00", "wo_id": "WO-001"},
                {"id": "t2", "start": "2026-08-01T13:00", "end": "2026-08-01T17:00", "wo_id": "WO-002"}
            ],
            "stations": ["STN-001", "STN-002"],
            "time_range": {"start": "2026-08-01", "end": "2026-08-02"}
        })
        
        service = ApsService(mock_db_session)
        result = await service.get_gantt_data("sched-123")
        
        assert result["success"] is True
        assert len(result["data"]["tasks"]) == 2
        assert result["data"]["time_range"]["start"] == "2026-08-01"


@pytest.mark.asyncio
async def test_aps_service_get_capacity_load(mock_db_session):
    """测试：获取产能负荷 - 统计工站在指定时间范围内的使用情况"""
    from api.services.aps_service import ApsService
    
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.get_capacity_load = AsyncMock(return_value={
            "station_id": "STN-001",
            "total_available_hours": 168,
            "allocated_hours": 142,
            "remaining_hours": 26,
            "utilization_rate": 0.845,
            "schedule_items": 15
        })
        
        service = ApsService(mock_db_session)
        result = await service.get_capacity_load(factory_id="F001", days=7)
        
        assert result["success"] is True
        assert result["data"]["station_id"] == "STN-001"
        assert result["data"]["utilization_rate"] == 0.845
        assert result["data"]["allocated_hours"] == 142


@pytest.mark.asyncio
async def test_aps_service_reschedule_on_change(mock_db_session):
    """测试：变更触发重排 - 当计划变更后自动重受影响工单"""
    from api.services.aps_service import ApsService
    
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.reschedule = AsyncMock(return_value={
            "success": True,
            "affected_wo_count": 2,
            "message": "2个工单重新排程"
        })
        
        service = ApsService(mock_db_session)
        result = await service.reschedule_on_change(
            factory_id="F001",
            insert_wo_id="WO-001",
            created_by="system"
        )
        
        assert result["success"] is True
        assert result["affected_wo_count"] == 2


@pytest.mark.asyncio
async def test_aps_service_handle_capacity_conflict_detection():
    """测试：产能冲突检测处理 - 当检测到冲突时给出建议"""
    from api.services.aps_service import ApsService
    
    # 使用真实的mock方式测试冲突检测
    with patch('api.services.aps_service.ApsEngine') as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        
        # 场景1：有冲突
        mock_engine.detect_conflicts.return_value = {
            "has_conflicts": True,
            "conflicting_stations": [{"station_id": "STN-001", "load_pct": 110}],
            "recommendations": ["调整优先级", "拆分任务"]
        }
        
        service = ApsService(MagicMock())  # 不传实际db用于此测试
        result = service.detect_conflicts("F001")
        
        assert result["has_conflicts"] is True
        assert len(result["recommendations"]) > 2  # 至少两个建议
        
        # 场景2：无冲突
        mock_engine.detect_conflicts.return_value = {
            "has_conflicts": False,
            "conflicting_stations": [],
            "recommendations": ["无需操作"]
        }
        
        result2 = service.detect_conflicts("F001")
        assert result2["has_conflicts"] is False