"""
生产计划(PP)服务单元测试 - 覆盖计划创建、状态流转、列表查询全流程
基于新数据库持久化实现的 MPSService
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from core.pp.plan import MPSService, PlanStatus, PlanType, CustomerLevel


@pytest.fixture(scope="function")
def plan_service_mock():
    """PlanService fixture，带mock的DB会话"""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return MPSService(mock_db)


@pytest.mark.asyncio
async def test_plan_create_valid(plan_service_mock):
    """测试：计划创建 - 有效数据写入数据库成功"""
    # Arrange - Mock DB insert operation
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    
    # Act
    result = await plan_service_mock.create_plan(
        factory_id="F001",
        product_id="PROD-001",
        quantity=500,
        required_date=datetime(2026, 8, 15),
        plan_type=PlanType.MPS.value,
        sales_order_id="SO-001",
        customer_level=CustomerLevel.A.value,
        priority=50,
        created_by="scheduler"
    )
    
    # Assert
    assert result["id"] is not None  # Has generated plan_id
    assert result["factory_id"] == "F001"
    assert result["product_id"] == "PROD-001"
    assert result["quantity"] == 500
    assert result["status"] == PlanStatus.DRAFT.value
    assert result["customer_level"] == CustomerLevel.A.value
    assert result["priority"] == 50
    assert result["plan_code"] is not None
    assert result["created_at"] is not None
    # Verify DB commit was called
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_plan_get_not_found(plan_service_mock):
    """测试：获取不存在的计划 - 返回None"""
    # Arrange - Mock query returning None
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    
    # Act
    result = await plan_service_mock.get_plan("non-existent-id")
    
    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_plan_get_exists(plan_service_mock):
    """测试：获取已存在的计划详情"""
    # Arrange
    mock_db = plan_service_mock.db
    mock_plan = MagicMock()
    mock_plan.id = "plan-001"
    mock_plan.plan_code = "MPS-F001-001"
    mock_plan.factory_id = "F001"
    mock_plan.product_id = "PROD-001"
    mock_plan.quantity = 500
    mock_plan.required_date = date(2026, 8, 15)
    mock_plan.due_date = date(2026, 8, 15)
    mock_plan.customer_level = "a"
    mock_plan.priority = 50
    mock_plan.priority_score = 95.5
    mock_plan.status = "draft"
    mock_plan.created_by = "scheduler"
    mock_plan.created_at = datetime.now()
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_plan))
    
    # Act
    result = await plan_service_mock.get_plan("plan-001")
    
    # Assert
    assert result is not None
    assert result["id"] == "plan-001"
    assert result["plan_code"] == "MPS-F001-001"
    assert result["quantity"] == 500
    assert result["status"] == "draft"


@pytest.mark.asyncio
async def test_plan_list_by_factory(plan_service_mock):
    """测试：按工厂获取计划列表"""
    # Arrange
    mock_db = plan_service_mock.db
    plan1 = MagicMock()
    plan1.id = "p1"
    plan1.factory_id = "F001"
    plan1.status = "draft"
    plan1.priority_score = 90.0
    
    plan2 = MagicMock()
    plan2.id = "p2"
    plan2.factory_id = "F001"
    plan2.status = "released"
    plan2.priority_score = 85.0
    
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalas=MagicMock(all=lambda: [plan1, plan2]))
    
    # Act
    results = await plan_service_mock.list_plans(
        factory_id="F001",
        limit=100
    )
    
    # Assert
    assert len(results) == 2
    assert all(r["factory_id"] == "F001" for r in results)


@pytest.mark.asyncio
async def test_plan_confirm_success(plan_service_mock):
    """测试：确认计划 - 草稿状态转为已确认"""
    # Arrange
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    # Simulate _get_plan_by_id returning draft plan
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "draft", "plan_code": "TEST-001"
    })
    
    # Act
    result = await plan_service_mock.confirm_plan(
        plan_id="plan-001",
        confirmed_by="manager"
    )
    
    # Assert
    assert result["status"] == "confirmed"
    assert result["confirmed_by"] == "manager"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_plan_confirm_invalid_status(plan_service_mock):
    """测试：确认计划 - 非草稿状态应报错"""
    # Arrange
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "released", "plan_code": "TEST-001"
    })
    
    # Act - Should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await plan_service_mock.confirm_plan(
            plan_id="plan-001",
            confirmed_by="manager"
        )
    
    assert "只有草稿状态的计划可以确认" in str(exc_info.value)


@pytest.mark.asyncio
async def test_plan_release_success(plan_service_mock):
    """测试：下达计划 - 已确认状态转为已下达"""
    # Arrange
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "confirmed", "plan_code": "TEST-001"
    })
    plan_service_mock.detect_capacity_conflict = AsyncMock(return_value=[])
    
    # Act
    result = await plan_service_mock.release_plan(
        plan_id="plan-001",
        released_by="planner",
        trigger_aps=False
    )
    
    # Assert
    assert result["status"] == "released"
    assert result["released_by"] == "planner"


@pytest.mark.asyncio
async def test_plan_release_invalid_status(plan_service_mock):
    """测试：下达计划 - 非已确认状态应报错"""
    # Arrange
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "draft", "plan_code": "TEST-001"
    })
    
    # Act - Should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await plan_service_mock.release_plan(
            plan_id="plan-001",
            released_by="planner"
        )
    
    assert "只有已确认的计划可以下达" in str(exc_info.value)


@pytest.mark.asyncio
async def test_plan_complete_success(plan_service_mock):
    """测试：完成计划 - 执行中或已下达状态转为已完成"""
    # Arrange
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "released", "plan_code": "TEST-001"
    })
    
    # Act
    result = await plan_service_mock.complete_plan(
        plan_id="plan-001",
        completed_by="operator"
    )
    
    # Assert
    assert result["status"] == "completed"
    assert result["completed_by"] == "operator"


@pytest.mark.asyncio
async def test_plan_cancel_success(plan_service_mock):
    """测试：取消计划 - 有效状态转为已取消"""
    # Arrange
    mock_db = plan_service_mock.db
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value = MagicMock(rowcount=1)
    mock_db.commit = AsyncMock()
    
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "in_progress", "plan_code": "TEST-001"
    })
    
    # Act
    result = await plan_service_mock.cancel_plan(
        plan_id="plan-001",
        cancelled_by="supervisor",
        reason="生产变更"
    )
    
    # Assert
    assert result["status"] == "cancelled"
    assert result["cancelled_by"] == "supervisor"


@pytest.mark.asyncio
async def test_plan_cancel_invalid_state(plan_service_mock):
    """测试：取消计划 - 已完成或已取消状态不可取消"""
    # Arrange
    plan_service_mock._get_plan_by_id = AsyncMock(return_value={
        "id": "plan-001", "status": "cancelled", "plan_code": "TEST-001"
    })
    
    # Act - Should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await plan_service_mock.cancel_plan(
            plan_id="plan-001",
            cancelled_by="supervisor"
        )
    
    assert "计划已完成或已取消，无法再次取消" in str(exc_info.value)


@pytest.mark.asyncio
async def test_priority_score_calculation(plan_service_mock):
    """测试：优先级分数计算 - 交期紧迫度+客户等级+自定义优先级"""
    # Act - Use the calculation logic directly
    now = datetime(2026, 7, 1)
    
    # Near deadline + VIP customer + high priority = high score
    score = plan_service_mock._calculate_priority_score(
        required_date=datetime(2026, 7, 5),  # 4 days away
        customer_level="vip",
        priority=50
    )
    
    assert score > 0
    # Score should be capped at 150
    assert score <= 150
    
    # Far deadline + low priority = lower score
    score_far = plan_service_mock._calculate_priority_score(
        required_date=datetime(2026, 12, 31),
        customer_level="c",
        priority=0
    )
    assert score_far < score  # Lower than near deadline case


@pytest.mark.asyncio
async def test_estimate_plan_hours(plan_service_mock):
    """测试：计划工时估算 - 基于产品标准工时定额"""
    # ACT
    hours_a = plan_service_mock._estimate_plan_hours("PRODUCT-A", 100)
    hours_b = plan_service_mock._estimate_plan_hours("PRODUCT-B", 100)
    hours_unknown = plan_service_mock._estimate_plan_hours("UNKNOWN-PROD", 100)
    
    # ASSERT - PRODUCT-A should be 2.5 * 100 = 250 hours
    assert abs(hours_a - 250.0) < 0.01
    # PRODUCT-B should be 3.0 * 100 = 300 hours
    assert abs(hours_b - 300.0) < 0.01
    # Unknown falls back to default 2.0
    assert abs(hours_unknown - 200.0) < 0.01


@pytest.mark.asyncio
async def test_generate_plan_code(plan_service_mock):
    """测试：计划编码生成"""
    code = plan_service_mock.generate_plan_code("FACT-001")
    assert code.startswith("MPS-FACT-001")


@pytest.mark.asyncio
async def test_capacity_conflict_detection_empty():
    """测试：产能冲突检测 - 当前无冲突返回空列表"""
    # Service returns empty list by default (no workstation data)
    service = MPSService(db_session=None)
    # Should not crash even without DB
    result = service.detect_capacity_conflict("any-plan-id")
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_mpsservice_requires_database():
    """测试：MPSService需要数据库会话才能操作"""
    service = MPSService(db_session=None)
    
    # Try operations that require DB - should fail gracefully or with specific error
    # In our implementation, _get_db() raises RuntimeError if no DB
    
    with pytest.raises(RuntimeError):
        await service.create_plan(
            factory_id="F001",
            product_id="PROD-001",
            quantity=100,
            required_date=datetime.now()
        )