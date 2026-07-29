"""
📁 tests/conftest.py - EP881 全局 Fixture 共享配置
===================================================

本文件包含所有测试可复用的 fixture 定义，遵循以下原则：
- 默认 scope="function"（每个测试独立隔离）
- 数据库相关 fixture 自动回滚
- Mock fixture 使用 unittest.mock.MagicMock 基础对象
- 不支持 fixture 间隐式状态依赖
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import os

# ──────────────────────────────────────────────
# 全局工具 fixtures
# ──────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_root():
    """项目根目录路径（可用于构造资源路径）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def mock_logger():
    """简化日志记录器 mock，避免真实 IO"""
    return MagicMock()


@pytest.fixture()
def fake_now(monkeypatch):
    """固定时间 fixture，用于需要确定性时间的测试"""
    fixed_time = "2026-07-29T08:00:00Z"

    def mock_now(*args, **kwargs):
        from datetime import datetime, timezone
        return datetime.fromisoformat(fixed_time.replace("Z", "+00:00"))

    monkeypatch.setattr("datetime.datetime.now", mock_now)
    yield fixed_time


# ──────────────────────────────────────────────
# 数据库事务管理 fixture（集成测试用）
# ──────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_transaction_session(test_db_engine):
    """
    为每个测试开启独立事务，测试后自动回滚。
    适用于需要真实 DB 连接的集成测试，而非单元测试。
    """
    connection = test_db_engine.connect()
    transaction = connection.begin()

    try:
        yield connection
        transaction.rollback()
    finally:
        connection.close()


@pytest.fixture(scope="function")
def test_db_session(db_transaction_session):
    """基于事务回滚的 Session，每个测试独立隔离"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_transaction_session)
    session = Session()
    yield session
    session.close()


# ──────────────────────────────────────────────
# API 测试相关 fixtures
# ──────────────────────────────────────────────


@pytest.fixture(scope="function")
def test_client(test_app):
    """
    FastAPI TestClient fixture，用于集成测试 API 端点。
    每个测试独立获取新的 app 实例（如需共享用 scope="session"）。
    """
    from fastapi.testclient import TestClient
    client = TestClient(test_app, raise_server_exceptions=False)
    yield client


@pytest.fixture(scope="function")
def authenticated_test_client(test_client, fake_user):
    """带认证头的 TestClient，用于受保护端点测试"""
    test_client.headers.update({"Authorization": f"Bearer {fake_user.token}"})
    yield test_client


# ──────────────────────────────────────────────
# 业务对象工厂 fixture（扩展自现有 test_sim_erp/test_sim_factory 风格）
# ──────────────────────────────────────────────


@pytest.fixture()
def fake_sim_erp_config():
    """构建 SimERP 仿真最小配置对象"""
    from core.sim_erp.models import WorkContext, EnvironmentSnapshot, PhysicalInput

    return PhysicalInput(
        time_step_minutes=30,
        step_count=1000,
        load_weight_kg=50.0,
        posture_angle_deg=45.0,
        continuous_work_minutes=180,
        distance_meters=1500.0,
        x_position_m=0.0,
        y_position_m=0.0,
        timestamp=datetime.now(timezone.utc),
        environment=EnvironmentSnapshot(temperature_c=25.0, humidity_percent=60.0),
        work_context=WorkContext(
            worker_ref="worker-test", shift_id="shift-day", task_type="assembly",
            zone_id="line-a", action_type="walk"
        ),
    )


# ──────────────────────────────────────────────
# 全局错误断言增强 fixture（可选）
# ──────────────────────────────────────────────


@pytest.fixture()
def assert_no_unexpected_exceptions(monkeypatch):
    """
    辅助 fixture：确保测试中没有意外的异常被静默吞没。
    用法：@pytest.mark.usefixtures("assert_no_unexpected_exceptions")
    """
    original_except_hook = sys.excepthook

    def custom_except_hook(exc_type, exc_value, exc_tb):
        if exc_type is not KeyboardInterrupt:
            pytest.fail(f"意外异常捕获: {exc_type.__name__}: {exc_value}")

    monkeypatch.setattr(sys, "excepthook", custom_except_hook)
    yield
    monkeypatch.setattr(sys, "excepthook", original_except_hook)


# ──────────────────────────────────────────────
# pytest hooks（可选增强）
# ──────────────────────────────────────────────


def pytest_addoption(parser):
    """添加自定义命令行选项"""
    parser.addoption(
        "--integration", action="store_true", default=False, help="运行集成测试"
    )
    parser.addoption(
        "--slow", action="store_true", default=False, help="运行慢速测试"
    )


def pytest_configure(config):
    """注册自定义 markers"""
    config.addinivalue_line(
        "markers", "integration: 标记集成测试（默认跳过）"
    )
    config.addinivalue_line(
        "markers", "slow: 标记慢速测试（默认跳过）"
    )


def pytest_collection_modifyitems(config, items):
    """根据命令行选项筛选测试"""
    skip_integration = pytest.mark.skip(
        reason="需添加 --integration 参数运行集成测试"
    )
    skip_slow = pytest.mark.skip(reason="需添加 --slow 参数运行慢速测试")

    for item in items:
        if "integration" in item.keywords and not config.getoption("--integration"):
            item.add_marker(skip_integration)
        if "slow" in item.keywords and not config.getoption("--slow"):
            item.add_marker(skip_slow)
