"""Test fixtures for WMS architecture tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import Result


class MockResult:
    """Mock SQLAlchemy Result object."""
    
    def __init__(self, items):
        self._items = items
    
    def scalars(self):
        return self
    
    def mappings(self):
        return self
    
    def all(self):
        return self._items
    
    def first(self):
        return self._items[0] if self._items else None
    
    def scalar(self):
        return self._items[0] if self._items else None
    
    def scalar_one_or_none(self):
        return self._items[0] if self._items else None
    
    def fetchall(self):
        return self._items


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def mock_result():
    """Mock SQLAlchemy result."""
    return MockResult([])


@pytest.fixture
def mock_inventory():
    """Mock inventory object."""
    inv = MagicMock()
    inv.id = "inv-001"
    inv.material_id = "MAT001"
    inv.material_code = "MAT001"
    inv.material_name = "Test Material"
    inv.factory_id = "F01"
    inv.warehouse_id = "WH01"
    inv.location_id = "LOC01"
    inv.batch_code = "BATCH001"
    inv.total_qty = 100
    inv.available_qty = 80
    inv.reserved_qty = 20
    inv.unit = "pcs"
    inv.status = "available"
    inv.last_movement_at = None
    inv.created_at = MagicMock()
    inv.updated_at = MagicMock()
    inv.created_at.isoformat.return_value = "2026-08-02T00:00:00"
    inv.updated_at.isoformat.return_value = "2026-08-02T00:00:00"
    return inv