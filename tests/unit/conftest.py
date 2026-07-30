"""
pytest fixture 配置 - 单元测试入口
提供数据库会话、mock服务等共享 fixture
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from api.services.work_order_service import WorkOrderService
from api.services.bom_service import BomService
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """pytest-asyncio 的事件循环fixture"""
    loop = asyncio.get_event_loop_policy().get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def mock_db_session():
    """模拟AsyncSession fixture，用于隔离测试"""
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture(scope="function")
def work_order_service(mock_db_session):
    """WorkOrder服务fixture，带自动mock的DB会话"""
    return WorkOrderService(mock_db_session)


@pytest.fixture(scope="function")
def bom_service(mock_db_session):
    """BOM服务fixture"""
    return BomService(mock_db_session)


@pytest.fixture(scope="function")
def mock_plan_service():
    """计划服务的mock fixture"""
    service = MagicMock()
    service.create_plan = AsyncMock(return_value={"success": True, "data": {"id": "plan-001"}})
    service.update_plan = AsyncMock(return_value={"success": True})
    service.delete_plan = AsyncMock(return_value={"success": True})
    return service


# ==================== 测试辅助函数 ====================

def _mock_execute(session, result):
    """设置session.execute的返回结果"""
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: result))
    )
    return session


def _mock_execute_scalar(session, scalar):
    """设置execute返回标量值（如count）"""
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock(scalar=lambda: scalar)
    return session