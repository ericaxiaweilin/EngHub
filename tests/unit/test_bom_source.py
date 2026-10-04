"""BOM 唯一读入口的口径回归。

背景：同一个"这个产品用什么料"的问题，MRP 端点查 `bom_items`、领料查 engflow
镜像、还有一个 MRPService 读代码里硬编码的演示字典 —— 三个答案。现在只能有一个。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import bom_source
from api.services.bom_source import latest_bom_lines


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _session(*results):
    db = MagicMock()
    queued = list(results)
    calls = []

    async def execute(statement, params=None):
        calls.append((str(statement), params))
        return _Rows(queued.pop(0) if queued else [])

    db.execute = execute
    db.calls = calls
    return db


@pytest.mark.asyncio
async def test_mirror_wins_when_engflow_has_the_product():
    db = _session([{"material_code": "1000096854", "material_name": None,
                    "qty_per_unit": 1, "unit": "PCS",
                    "vendor_code": "V1", "vendor_name": "供方"}])
    lines, source = await latest_bom_lines(db, "FAC_MECH_001", "A-50-04-F")
    assert source == "engflow_mirror"
    assert [l["material_code"] for l in lines] == ["1000096854"]
    assert len(db.calls) == 1, "镜像命中时不该再去查本地表"


@pytest.mark.asyncio
async def test_falls_back_to_local_only_when_mirror_misses():
    db = _session([], [{"material_code": "VF-RAW-STEEL", "material_name": "钢材",
                        "qty_per_unit": 1.2, "unit": "PCS",
                        "vendor_code": None, "vendor_name": None}])
    lines, source = await latest_bom_lines(db, "FAC_ELEC_DEMO_2026", "VF-CMECH001-40HQ")
    assert source == "mes_bom_items"
    assert lines[0]["qty_per_unit"] == 1.2
    assert "enghub_bom_items" in db.calls[0][0]
    assert "bom_items" in db.calls[1][0]


@pytest.mark.asyncio
async def test_pinned_version_only_reads_local_table():
    db = _session([{"material_code": "RM-X", "material_name": None,
                    "qty_per_unit": 2, "unit": "pcs",
                    "vendor_code": None, "vendor_name": None}])
    lines, source = await latest_bom_lines(
        db, "FAC_MECH_001", "A-50-04-F", version="BOM-V3")
    assert source == "mes_bom_items"
    assert len(db.calls) == 1
    assert db.calls[0][1]["version"] == "BOM-V3"


@pytest.mark.asyncio
async def test_no_bom_anywhere_returns_none_source_not_invented_demand():
    db = _session([], [])
    lines, source = await latest_bom_lines(db, "FAC_X", "GHOST-PRODUCT")
    assert (lines, source) == ([], "none")
    assert "没有" in bom_source.label(source)


@pytest.mark.asyncio
async def test_material_issue_uses_the_same_entry(monkeypatch):
    """领料必须走同一个入口：两处各查各的表就是 MRP 与领料对不上数的根源。"""
    from api.services.wms_service import InventoryService

    seen = {}

    async def fake(db, factory_id, product_code, version=None):
        seen["product"] = product_code
        return [], "none"

    monkeypatch.setattr(bom_source, "latest_bom_lines", fake)
    svc = InventoryService(MagicMock())
    lines, source = await svc._latest_bom_lines("FAC_MECH_001", "A-50-04-F")
    assert (lines, source) == ([], "none")
    assert seen["product"] == "A-50-04-F"
