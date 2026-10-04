"""BOM 自制件主档登记的口径回归。

这里守的是两条线：一是**幂等**（重复下达不能造重复主档、不能抢注别人厂区的主档），
二是**不编数据**（源行没写品名/单位就不建，宁可主档缺着）。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services.production_part_master import register_make_part_masters


class _Master:
    def __init__(self, code, factory_id):
        self.product_code = code
        self.factory_id = factory_id


def _db(existing=()):
    db = MagicMock()
    added = []

    async def execute(statement):
        res = MagicMock()
        res.scalars.return_value.all.return_value = list(existing)
        return res

    async def flush():
        return None

    db.execute = execute
    db.flush = flush
    db.add = lambda obj: added.append(obj)
    db.added = added
    return db


def _items():
    return [
        {"material_code": "ASSY-A", "material_name": "总成A", "unit": "SET",
         "level": 1, "item_type": "make"},
        {"material_code": "SUB-B", "material_name": "部件B", "unit": "PCS",
         "level": 2, "item_type": "make"},
        {"material_code": "RAW-C", "material_name": "钢材", "unit": "KG",
         "level": 3, "item_type": "buy"},
    ]


@pytest.mark.asyncio
async def test_registers_selfmade_parts_only():
    db = _db()
    receipt = await register_make_part_masters(db, "FAC_MECH_001", "A-50-04-F", _items())
    assert receipt["requested"] == 2, "只有 make 件需要主档，采购件不建"
    assert receipt["created"] == 2
    assert {p.product_code for p in db.added} == {"ASSY-A", "SUB-B"}
    assert all(p.factory_id == "FAC_MECH_001" for p in db.added)
    assert all(p.current_routing_id is None for p in db.added), "路线不能替工厂编"


@pytest.mark.asyncio
async def test_existing_master_is_left_alone():
    """重复下达不能重复建主档：已存在的只记账，不动那一行。"""
    db = _db([_Master("ASSY-A", "FAC_MECH_001")])
    receipt = await register_make_part_masters(db, "FAC_MECH_001", "A-50-04-F", _items())
    assert receipt["existing"] == 1
    assert receipt["created"] == 1
    assert [p.product_code for p in db.added] == ["SUB-B"]


@pytest.mark.asyncio
async def test_master_in_other_factory_is_blocked_not_grabbed():
    """product_code 是全局唯一索引：别厂区已有的主档不能靠抢注改归属。"""
    db = _db([_Master("ASSY-A", "FAC_ELEC_DEMO_2026")])
    receipt = await register_make_part_masters(db, "FAC_MECH_001", "A-50-04-F", _items())
    assert receipt["blocked"]["master_other_factory"] == ["ASSY-A"]
    assert [p.product_code for p in db.added] == ["SUB-B"]


@pytest.mark.asyncio
async def test_source_row_without_unit_or_name_is_not_invented():
    db = _db()
    items = [
        {"material_code": "NO-UNIT", "material_name": "有名字", "unit": None,
         "level": 2, "item_type": "make"},
        {"material_code": "NO-NAME", "material_name": "  ", "unit": "PCS",
         "level": 2, "item_type": "make"},
    ]
    receipt = await register_make_part_masters(db, "FAC_MECH_001", "A-50-04-F", items)
    assert receipt["created"] == 0
    assert sorted(receipt["blocked"]["missing_source_fields"]) == ["NO-NAME", "NO-UNIT"]
    assert db.added == []


@pytest.mark.asyncio
async def test_dry_run_reports_without_writing():
    db = _db()
    receipt = await register_make_part_masters(
        db, "FAC_MECH_001", "A-50-04-F", _items(), apply=False
    )
    assert receipt["dry_run"] is True
    assert receipt["created"] == 2, "预演要说清会建几条"
    assert db.added == [], "预演不能落库"
