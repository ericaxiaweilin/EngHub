"""
PMC 工作矩阵数据缺口修复测试：
- _supplier_lead_time_rows：supplier_prices 空时降级读 supplier_materials
- build：产品缺 BOM 且缺路由时 next_focus 区分"双缺"

注：异步服务方法通过 asyncio.run() 包装为同步调用，规避
pytest-asyncio 1.3.0 + Python 3.14 的循环作用域不兼容。
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from api.services.pmc_work_matrix_service import PmcWorkMatrixService


def _run(coro):
    return asyncio.run(coro)


def _mock_db_with_prices(price_rows):
    """db.execute 首次命中 supplier_prices 查询返回 price_rows，其余为空。"""
    db = MagicMock()
    exec_count = {"n": 0}

    async def fake_execute(stmt, *a, **k):
        exec_count["n"] += 1
        res = MagicMock()
        sql = str(stmt)
        if "supplier_prices" in sql:
            res.mappings.return_value.all.return_value = price_rows
            return res
        res.mappings.return_value.all.return_value = []
        return res

    db.execute = AsyncMock(side_effect=fake_execute)
    db.begin_nested = MagicMock()
    return db


def test_supplier_lead_time_reads_prices_first():
    db = _mock_db_with_prices([
        {"supplier_code": "SUP-RES-001", "supplier_name": "Resistor", "lead_days": 5,
         "moq": 100, "currency": "USD", "unit_price": 0.01},
    ])
    svc = PmcWorkMatrixService(db)
    out = _run(svc._supplier_lead_time_rows("FAC_MECH_001", "RES-10K-0603"))
    assert out["available"] is True
    assert out["source"] == "supplier_prices"
    assert out["rows"][0]["lead_days"] == 5


def test_supplier_lead_time_falls_back_to_supplier_materials():
    db = MagicMock()
    calls = []

    async def fake_execute(stmt, *a, **k):
        calls.append(str(stmt))
        res = MagicMock()
        if "supplier_prices" in str(stmt):
            res.mappings.return_value.all.return_value = []
        else:
            res.mappings.return_value.all.return_value = [
                {"supplier_code": "SUP-RES-001", "supplier_name": "Resistor",
                 "lead_days": 5, "moq": 100, "currency": None, "unit_price": 0.01},
            ]
        return res

    db.execute = AsyncMock(side_effect=fake_execute)
    db.begin_nested = MagicMock()
    svc = PmcWorkMatrixService(db)
    out = _run(svc._supplier_lead_time_rows("FAC_MECH_001", "CAP-10UF-0603"))
    assert out["available"] is True
    assert out["source"] == "supplier_materials"
    assert out["rows"][0]["lead_days"] == 5
    assert any("supplier_materials" in c for c in calls)


def test_supplier_lead_time_empty_when_no_data():
    db = MagicMock()

    async def fake_execute(stmt, *a, **k):
        res = MagicMock()
        res.mappings.return_value.all.return_value = []
        return res

    db.execute = AsyncMock(side_effect=fake_execute)
    db.begin_nested = MagicMock()
    svc = PmcWorkMatrixService(db)
    out = _run(svc._supplier_lead_time_rows("FAC_MECH_001", "VF-RAW-STEEL"))
    assert out["available"] is True
    assert out["rows"] == []
    assert out["source"] == "missing"


def test_supplier_lead_time_survives_sql_error():
    from sqlalchemy.exc import SQLAlchemyError

    db = MagicMock()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("no such table: supplier_prices"))

    def bad_nested():
        raise SQLAlchemyError("no such table: supplier_prices")

    db.begin_nested = MagicMock(side_effect=bad_nested)
    svc = PmcWorkMatrixService(db)
    out = _run(svc._supplier_lead_time_rows("FAC_MECH_001", "X"))
    assert out["available"] is False
    assert out["rows"] == []
    assert "supplier_prices unavailable" in out.get("error", "")
