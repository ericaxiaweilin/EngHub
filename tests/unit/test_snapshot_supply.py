"""齐套刷新的口径回归：一份供应只能冲抵一条需求。

这是我在 MRP 多层展开里抓到过的同一个错（每节点按全量库存扣 → 净需求偏低）。
刷新一列数字很容易顺手写成"每行都看库存"，所以把反例钉在测试里。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import snapshot_supply as ss


def _db(lines):
    db = MagicMock()
    executed = []

    async def execute(statement, params=None):
        sql = str(statement)
        executed.append((sql, params))
        res = MagicMock()
        if "JOIN work_orders wo" in sql:
            res.mappings.return_value.all.return_value = lines
        else:
            res.mappings.return_value.all.return_value = []
        return res

    async def commit():
        executed.append(("COMMIT", None))

    async def rollback():
        executed.append(("ROLLBACK", None))

    db.execute = execute
    db.commit = commit
    db.rollback = rollback
    db.executed = executed
    return db


def _line(id_, code, required, shortage, level=1):
    return {"id": id_, "material_code": code, "required_qty": required,
            "shortage_qty": shortage, "level": level,
            "factory_id": "FAC_MECH_001", "required_date": None}


@pytest.mark.asyncio
async def test_one_pool_of_supply_is_not_credited_twice(monkeypatch):
    """同一料号两条需求、库存只够一条：第二条必须还是缺口。"""
    async def fake_supply(db, fid, codes, target_date=None):
        return {"RM-X": {"on_hand": 100.0, "on_order": 0.0}}

    monkeypatch.setattr(ss, "stock_and_supply", fake_supply)
    lines = [_line("l1", "RM-X", 100, 100), _line("l2", "RM-X", 100, 100)]
    db = _db(lines)
    receipt = await ss.refresh_snapshot_supply(db, factory_id="FAC_MECH_001")

    assert receipt["shortage_after"] == 100, "库存 100 只能冲抵一次，另一行缺口必须留着"
    updates = [c for c in db.executed if "UPDATE work_order_materials" in c[0]]
    assert len(updates) == 1, "只有第一行被改成 0，第二行不该被假装齐套"
    assert updates[0][1]["shortage_qty"] == 0


@pytest.mark.asyncio
async def test_completion_stock_clears_the_parent_gate(monkeypatch):
    """下级完工入库后（在库上升），父层缺口自动归零 —— 闭环靠这一步转起来。"""
    async def before(db, fid, codes, target_date=None):
        return {"RM-X": {"on_hand": 0.0, "on_order": 0.0}}

    monkeypatch.setattr(ss, "stock_and_supply", before)
    db = _db([_line("l1", "RM-X", 50, 50)])
    receipt = await ss.refresh_snapshot_supply(db, factory_id="FAC_MECH_001")
    assert receipt["shortage_after"] == 50, "没库存时缺口不动"

    async def after(db, fid, codes, target_date=None):
        return {"RM-X": {"on_hand": 50.0, "on_order": 0.0}}

    monkeypatch.setattr(ss, "stock_and_supply", after)
    db2 = _db([_line("l1", "RM-X", 50, 50)])
    receipt2 = await ss.refresh_snapshot_supply(db2, factory_id="FAC_MECH_001")
    assert receipt2["shortage_after"] == 0
    assert receipt2["cleared"] == 1, "齐套门要能自动放行"


@pytest.mark.asyncio
async def test_dry_run_rolls_back(monkeypatch):
    async def fake_supply(db, fid, codes, target_date=None):
        return {"RM-X": {"on_hand": 10.0, "on_order": 0.0}}

    monkeypatch.setattr(ss, "stock_and_supply", fake_supply)
    db = _db([_line("l1", "RM-X", 100, 100)])
    receipt = await ss.refresh_snapshot_supply(db, factory_id="FAC_MECH_001", apply=False)
    assert receipt["dry_run"] is True and receipt["changed"] == 1
    assert ("ROLLBACK", None) in db.executed
    assert not [c for c in db.executed if "COMMIT" == c[0]]


@pytest.mark.asyncio
async def test_query_scopes_to_master_orders_only():
    """只刷主工单：下级工单的行是执行明细，刷它们等于把同一份需求数两遍。"""
    sql = ss.LIVE_LINES_SQL.text
    assert "wo.wo_type = 'master'" in sql
    assert "NOT IN ('completed', 'cancelled')" in sql
    assert "ORDER BY" in sql, "冲抵顺序必须确定，否则同数据两次刷出不同结果"
