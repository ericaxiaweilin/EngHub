"""WMS 增强服务单元测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.wms_enhancement_service import WmsEnhancementService, _code


def _mock_db(rows=None):
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=None)
    if rows is not None:
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        result.mappings.return_value.first.return_value = rows[0] if rows else None
        result.scalar.return_value = len(rows) if rows else 0
        result.rowcount = 1
        db.execute.return_value = result
    return db


def test_code_prefix():
    c = _code("XFR")
    assert c.startswith("XFR-")


@pytest.mark.asyncio
async def test_generate_barcode():
    db = _mock_db([])
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    svc = WmsEnhancementService(db)
    result = await svc.generate_barcode("FAC", "MID", "MAT-001")
    assert result["success"] is True
    assert result["barcode"].startswith("EH-MAT-001-")
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_dispatch_automation_job():
    db = _mock_db([])
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    svc = WmsEnhancementService(db)
    result = await svc.dispatch_automation_job("FAC", "agv_dispatch", material_code="MAT-A", quantity=5)
    assert result["success"] is True
    assert result["job_type"] == "agv_dispatch"
    assert result["status"] == "dispatched"
