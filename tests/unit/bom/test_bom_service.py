"""BOM 服务单元测试：只调真实存在的方法签名。"""
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, AsyncMock

from api.services.bom_service import BomService


@pytest.fixture(scope="function")
def bom_service():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return BomService(db)


def _item(**kw):
    base = dict(
        id="r1", source_row_id=1, product_model="MODEL-ROOT",
        part_number="P-001", description="d", level=1, quantity=2,
        unit="pcs", unit_price=1.5, total_cost=3.0, vendor_code="V",
        vendor_name="VN", parent_part=None, category_l1="c1",
        category_l2="c2", material_family="f", component_type="t",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _scalars(rows):
    res = MagicMock()
    res.scalars.return_value.all.return_value = list(rows)
    return res


@pytest.mark.asyncio
async def test_bom_tree_expand_root(bom_service):
    bom_service.db.execute = AsyncMock(return_value=_scalars([
        _item(part_number="ASM", level=0),
        _item(part_number="P-001", level=1, parent_part="ASM"),
    ]))
    out = await bom_service.get_bom_tree("MODEL-ROOT")
    assert out["total_items"] == 2
    assert out["tree"][0]["part_number"] == "ASM"
    assert out["tree"][0]["children"][0]["part_number"] == "P-001"


@pytest.mark.asyncio
async def test_bom_tree_empty_model(bom_service):
    bom_service.db.execute = AsyncMock(return_value=_scalars([]))
    out = await bom_service.get_bom_tree("NOPE")
    assert out == {"model_name": "NOPE", "tree": [], "total_items": 0}


@pytest.mark.asyncio
async def test_bom_material_search_by_code(bom_service):
    count_res = MagicMock()
    count_res.scalar.return_value = 1
    item_res = _scalars([_item(part_number="MAT-12345")])

    async def _exec(stmt, *a, **k):
        return count_res if "count" in str(stmt).lower() else item_res

    bom_service.db.execute = AsyncMock(side_effect=_exec)
    out = await bom_service.search_materials(keyword="MAT-12345")
    assert out["total"] == 1
    assert out["items"][0]["part_number"] == "MAT-12345"


@pytest.mark.asyncio
async def test_bom_material_search_partial_match(bom_service):
    count_res = MagicMock()
    count_res.scalar.return_value = 2
    item_res = _scalars([_item(part_number="螺丝-A"), _item(part_number="螺丝-B")])

    async def _exec(stmt, *a, **k):
        return count_res if "count" in str(stmt).lower() else item_res

    bom_service.db.execute = AsyncMock(side_effect=_exec)
    out = await bom_service.search_materials(keyword="螺丝")
    assert out["total"] == 2
    assert len(out["items"]) == 2


@pytest.mark.asyncio
async def test_bom_version_compare_two_versions(bom_service):
    old = MagicMock()
    old.all.return_value = [("P-1", 2, 1.0)]
    new = MagicMock()
    new.all.return_value = [("P-1", 2, 1.0), ("P-2", 1, 5.0)]
    bom_service.db.execute = AsyncMock(side_effect=[old, new])
    out = await bom_service.compare_bom("MODEL-ROOT", "2026-01-01", "2026-08-01")
    assert "error" not in out
    assert "P-2" in out.get("added", [])


@pytest.mark.asyncio
async def test_bom_models_listing(bom_service):
    row = SimpleNamespace(product_model="MODEL-ROOT", item_count=7, last_synced=None)
    res = MagicMock()
    res.all.return_value = [row]
    bom_service.db.execute = AsyncMock(return_value=res)
    out = await bom_service.get_models()
    assert out[0]["model_name"] == "MODEL-ROOT"
    assert out[0]["item_count"] == 7
