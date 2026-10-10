"""周期盘点的范围判据：为什么是这一行该盘，必须说得出理由。"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.services.stock_counts import MAX_ITEMS_PER_ORDER, plan_scope
from api.services.wms_service import WmsService

NOW = datetime(2026, 10, 9)


def _row(i, **kw):
    base = {"id": i, "material_code": f"M{i}", "batch_code": None, "location_code": "LOC-1",
            "warehouse_id": "wh1", "total_qty": 10, "available_qty": 10, "abc_class": "B",
            "last_movement_at": datetime(2026, 10, 1), "movement_rows": 3}
    base.update(kw)
    return base


def test_never_moved_rows_are_counted_first():
    """台账有量、却从没记过一次移动 —— 最可能是导入灌进来的数，必须先盘。"""
    plan = plan_scope([_row("a", last_movement_at=None, total_qty=5000)], now=NOW)
    assert plan["items"][0]["reason"] == "never_moved"
    assert plan["by_reason"]["never_moved"] == 1


def test_rows_without_location_are_counted():
    plan = plan_scope([_row("b", location_code="")], now=NOW)
    assert plan["items"][0]["reason"] == "no_location"


def test_class_a_and_zero_stock_rows_are_in_scope():
    plan = plan_scope([_row("c", abc_class="A"),
                       _row("d", total_qty=0, available_qty=0, movement_rows=7)], now=NOW)
    assert {p["reason"] for p in plan["items"]} == {"class_a", "zero_stock"}
    # 零库存且从没动过的行不值得盘（既没量也没历史）
    assert all(p["system_qty"] is not None for p in plan["items"])


def test_dirty_nan_rows_never_enter_a_count_order():
    """料号是 nan 的行不派盘点：它缺的是料号，不是"数一数有多少"。"""
    plan = plan_scope([_row("x", material_code="nan", last_movement_at=None)], now=NOW)
    assert plan["items_planned"] == 0
    assert plan["excluded_dirty_rows"] == 1


def test_rows_already_in_an_open_order_are_not_counted_twice():
    rows = [_row("a", last_movement_at=None), _row("b", last_movement_at=None)]
    plan = plan_scope(rows, already_counted=["a"], now=NOW)
    assert [p["inventory_id"] for p in plan["items"]] == ["b"]


def test_scope_caps_items_and_keeps_reasons_honest():
    rows = [_row(str(i), last_movement_at=None) for i in range(MAX_ITEMS_PER_ORDER + 30)]
    plan = plan_scope(rows, now=NOW)
    assert plan["items_planned"] == MAX_ITEMS_PER_ORDER
    assert sum(plan["by_reason"].values()) == MAX_ITEMS_PER_ORDER


def test_healthy_rows_are_left_out():
    """有库位、有移动、B/C 类、有量 —— 这轮不该占仓管的时间。"""
    plan = plan_scope([_row("ok", abc_class="C", last_movement_at=datetime(2026, 10, 8))], now=NOW)
    assert plan["items_planned"] == 0


def test_scope_rotates_reasons_instead_of_burning_the_cap_on_one():
    """一轮 200 行如果全按件数排，会被"从没动过的大件"占满 —— 另外三类一行都盘不到。"""
    rows = ([_row(f"n{i}", last_movement_at=None) for i in range(60)]
            + [_row(f"l{i}", location_code="") for i in range(30)]
            + [_row(f"a{i}", abc_class="A") for i in range(30)])
    plan = plan_scope(rows, max_items=12, now=NOW)
    assert plan["items_planned"] == 12
    assert plan["by_reason"]["never_moved"] == 4
    assert plan["by_reason"]["no_location"] == 4
    assert plan["by_reason"]["class_a"] == 4
    # 候选总数与本轮取数分开报：读的人要知道"还剩多少没盘到"，不是"就这么点问题"
    assert plan["candidates_by_reason"] == {"never_moved": 60, "no_location": 30,
                                            "class_a": 30, "zero_stock": 0}


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class _Db:
    """只回放一条明细查询 —— 列明细不该绕第二次 DB。"""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        assert len(self.calls) == 1, f"列一次明细打了 {len(self.calls)} 条查询"
        return _Result(self._rows)


def _item(i, counted, diff, factory="FAC_MECH_001"):
    return {"item_id": f"i{i}", "material_id": f"M{i}", "batch_code": f"B{i}",
            "system_qty": 10, "counted_qty": counted, "diff_qty": diff,
            "adjusted": False, "remark": None, "material_code": f"M{i}",
            "material_name": "墊圈", "unit": "pcs", "location_code": f"LOC-{i}",
            "warehouse_code": "WH-MECH-RAW", "factory_id": factory}


@pytest.mark.asyncio
async def test_count_items_lists_ids_the_entry_endpoint_needs():
    """录入要 item_id，之前全仓没人能列出它 —— 这条通路是盘点能不能走起来的分界。"""
    db = _Db([_item(1, None, None)])
    out = await WmsService(db).get_count_items("c1")
    assert [it["item_id"] for it in out["items"]] == ["i1"]
    sql = db.calls[0][0]
    assert "inventory_count_items ci" in sql and "LEFT JOIN inventory i" in sql
    assert db.calls[0][1] == {"cid": "c1"}


@pytest.mark.asyncio
async def test_uncounted_rows_are_pending_not_zero_diff():
    """没录的行算"还没盘"，不算"盘平了"：差异只数已录入且 diff≠0 的行。"""
    rows = [_item(1, 10, 0), _item(2, None, None), _item(3, 7, -3)]
    out = await WmsService(_Db(rows)).get_count_items("c1")
    assert (out["total"], out["counted"], out["pending"], out["with_diff"]) == (3, 2, 1, 1)
    assert out["factories"] == ["FAC_MECH_001"]


@pytest.mark.asyncio
async def test_factories_are_named_not_assumed():
    """明细要能报出自哪个厂，否则拿 A 厂的进度答 B 厂的问题。"""
    out = await WmsService(_Db([_item(1, None, None, "FAC_MECH_001"),
                                _item(2, None, None, "FAC_BIKE_001")])).get_count_items("c1")
    assert out["factories"] == ["FAC_BIKE_001", "FAC_MECH_001"]
    assert out["counted"] == 0


@pytest.mark.asyncio
async def test_submit_item_uses_the_same_diff_ruler_as_approval():
    """录入和审批必须同一把尺：缺 system_qty 时按 0 算，别一边 500 一边静默。"""
    from api.services.wms_service import WmsService

    class _Item:
        def __init__(self):
            self.count_id = "c1"
            self.system_qty = None
            self.counted_qty = None
            self.diff_qty = None
            self.remark = None

    class _Order:
        status = "draft"

    item, order = _Item(), _Order()

    async def fake_get(model, _pk):
        return item if model.__name__ == "InventoryCountItem" else order

    db = MagicMock()
    db.get = fake_get
    db.commit = AsyncMock()

    out = await WmsService(db).submit_count_item("c1", "i1", 12, None)
    assert out["success"] is True and out["diff_qty"] == 12, out

