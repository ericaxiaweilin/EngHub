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


def _row(level, part, qty, order):
    return {"level": level, "material_code": part, "qty_per_unit": qty,
            "material_name": part, "unit": "PCS", "original_row_number": order,
            "vendor_code": None}


def test_tree_parent_comes_from_indent_order():
    """前序缩进行：父级 = 前面最近的一条浅一层行。这是层级 BOM 的本来的读法。"""
    rows = [_row(1, "ASSY-A", 1, 0), _row(2, "SUB-B", 2, 1), _row(3, "RAW-C", 3, 2),
            _row(2, "RAW-D", 5, 3)]
    nodes, problems = bom_source.build_tree(rows)
    assert problems == []
    assert [(n["material_code"], n["parent_code"], n["per_unit_qty"]) for n in nodes] == [
        ("ASSY-A", None, 1.0),
        ("SUB-B", "ASSY-A", 2.0),
        ("RAW-C", "SUB-B", 6.0),
        ("RAW-D", "ASSY-A", 5.0),
    ]


def test_broken_indent_is_reported_not_repaired():
    """层深一次跳 +2 说明中间缺了父级：如实报问题，不猜一个爹挂上去。"""
    rows = [_row(1, "ASSY-A", 1, 0), _row(3, "RAW-X", 2, 1)]
    nodes, problems = bom_source.build_tree(rows)
    assert [n["material_code"] for n in nodes] == ["ASSY-A"]
    assert problems and "找不到上一层父级" in problems[0]


def test_orphan_before_any_root_is_reported():
    rows = [_row(2, "SUB-ORPHAN", 1, 0)]
    nodes, problems = bom_source.build_tree(rows)
    assert nodes == [] and problems


@pytest.mark.asyncio
async def test_no_parent_column_does_not_block_explosion():
    """parent_sap 全空也能展开：结构在行序里，不在那一列。"""
    rows = [_row(1, "ASSY-A", 2, 0), _row(2, "RAW-B", 3, 1)]
    for r in rows:
        r["parent_part"] = None  # 镜像里 parent 列就是空的

    async def fake(*a, **k):
        return rows

    class _R:
        def mappings(self): return self
        def all(self): return []

    db = MagicMock()
    calls = []

    async def execute(statement, params=None):
        calls.append(str(statement))
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "level" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "A-50-04-F", 10)
    assert out["problems"] == []
    assert out["nodes"] == 2 and out["max_level"] == 2
    # ASSY-A 毛需求 20、无库存 -> 净 20；RAW-B 挂在 ASSY-A 下：20×3=60
    by_code = {l["material_code"]: l for l in out["lines"]}
    assert by_code["ASSY-A"]["required_qty"] == 20
    assert by_code["RAW-B"]["required_qty"] == 60
    assert by_code["RAW-B"]["parent_code"] == "ASSY-A"
