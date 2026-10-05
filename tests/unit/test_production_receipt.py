"""完工入库与下级工单按快照领料的口径回归。

`production_in` 以前只在枚举里、没人写过：工单完工后库存不增，
父层齐套门就永远等不到"下级做完了"。这两条把它钉住。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.wms_service import InventoryService


def _service(rows_by_sql):
    class _Res:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def scalar(self):
            return self._rows[0] if isinstance(self._rows, list) and self._rows else self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def all(self):
            return self._rows if isinstance(self._rows, list) else [self._rows]

    from unittest.mock import MagicMock

    db = MagicMock()
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append((sql, params))
        for key, rows in rows_by_sql.items():
            if key in sql:
                return _Res(rows)
        return _Res([])

    db.execute = execute
    db.calls = calls
    return db, calls


@pytest.mark.asyncio
async def test_snapshot_issue_prorates_by_the_order_itself():
    """下级装配件没有 BOM：用量 = 本单需求 ÷ 本单计划产量，不另编系数。"""
    db, _ = _service({
        "SELECT planned_qty FROM work_orders": [10],
        "FROM work_order_materials": [
            {"material_code": "RM-A", "material_name": "钢材", "unit": "KG",
             "qty_per_unit": 4.0},
        ],
        "SELECT material_id FROM inventory": [None],
    })
    svc = InventoryService(db)
    lines, source = await svc._work_order_snapshot_lines("FAC_MECH_001", "wo-1")
    assert source == "work_order_snapshot"
    assert lines[0]["qty_per_unit"] == 4.0

    db2, _ = _service({
        "SELECT planned_qty FROM work_orders": [0],
    })
    empty_lines, empty_source = await InventoryService(db2)._work_order_snapshot_lines(
        "FAC_MECH_001", "wo-1"
    )
    assert empty_lines == [] and empty_source == "none", "计划产量为 0 不能除，也不能瞎给用量"


@pytest.mark.asyncio
async def test_snapshot_issue_skips_selfmade_lines():
    """SQL 必须把 make 行挡在外面：那些料由各自子工单生产入库，两处都扣就是数两遍。"""
    sql = InventoryService._work_order_snapshot_lines.__code__.co_consts
    text_blob = " ".join(str(c) for c in sql if isinstance(c, str))
    assert "item_type" in text_blob and "<> 'make'" in text_blob.replace("'", "'")


@pytest.mark.asyncio
async def test_production_output_requires_real_qty_and_order():
    db, _ = _service({"SELECT planned_qty FROM work_orders": [10]})
    svc = InventoryService(db)
    assert (await svc.record_production_output(
        factory_id="FAC_MECH_001", work_order_id="wo-1",
        product_code="ARM-A", qty=0)) == {"posted": 0, "reason": "no_output"}

    db2, _ = _service({"SELECT id, work_order_code FROM work_orders": []})
    r = await InventoryService(db2).record_production_output(
        factory_id="FAC_MECH_001", work_order_id="missing",
        product_code="ARM-A", qty=5,
    )
    assert r == {"posted": 0, "reason": "work_order_not_found"}, "没有工单就不许入库"


def test_pulse_posts_completion_into_inventory():
    """报工链路要真的调用完工入库，不然只是把工单状态改成 completed。"""
    import inspect

    from api.services.virtual_factory_service import VirtualFactoryService

    src = inspect.getsource(VirtualFactoryService)
    assert "record_production_output(" in src
    assert src.index("record_production_output(") < src.index("issue_materials_for_production("), \
        "先入库再扣料：同一批物料不能在本单里既算产出又算消耗"
