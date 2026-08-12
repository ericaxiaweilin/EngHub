"""Test fixtures for chat architecture tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def mock_user():
    """Mock user object."""
    user = MagicMock()
    user.active_factory_id = "F01"
    user.factory_id = "F01"
    return user


@pytest.fixture
def mock_request():
    """Mock chat request."""
    request = MagicMock()
    request.messages = [
        MagicMock(role="user", content="库存查询"),
        MagicMock(role="assistant", content="好的"),
        MagicMock(role="user", content="产量统计")
    ]
    request.http_request = None
    request.temperature = 0.3
    request.enable_tools = True
    request.attachments = []
    request.agent_key = None
    return request