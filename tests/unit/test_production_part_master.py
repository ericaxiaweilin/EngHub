"""BOM 自制件主档登记的口径回归。

这里守的是两条线：一是**幂等**（重复下达不能造重复主档、不能抢注别人厂区的主档），
二是**不编数据**（源行没写品名/单位就不建，宁可主档缺着）。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services.production_part_master import register_make_part_masters


class _Master:
    def __init__(self, code, factory_id, product_name=""):
        self.product_code = code
        self.factory_id = factory_id
        self.product_name = product_name


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


def test_clean_name_takes_only_the_first_attribute_token():
    """description 是分号结构串（名稱;別名;規格;材料;表面處理…），品名只取第一段。"""
    from api.services.bom_attributes import clean_name, is_document, is_electronic
    raw = "齒輪;;;POM(塑膠鋼)+10%纖維+二硫化鉬;;H58/S22;JM03;"
    assert clean_name(raw) == "齒輪"
    assert is_document("零件爆炸圖;半成品;;;;;EP727;")
    assert not is_document(clean_name(raw))
    assert is_electronic("控制板PCB;主電控;V4.0")
    assert not is_electronic("車架組;;;烤漆;DM334;;EP298;")


@pytest.mark.asyncio
async def test_drawing_rows_and_pcb_parts_are_not_registered_as_selfmade():
    """用户口径：图纸行不是物料，PCB 上电子元器件是外购 —— 都不能变成半成品主档。"""
    db = _db()
    items = [
        {"material_code": "DWG-1", "material_name": "零件爆炸圖;半成品;;;;;EP727;",
         "unit": "PCS", "level": 3, "item_type": "make"},
        {"material_code": "PCB-1", "material_name": "主控板PCB;電阻;電容;贴片",
         "unit": "PCS", "level": 4, "item_type": "make"},
        {"material_code": "REAL-1", "material_name": "車架組;;;烤漆;DM334;;EP298;",
         "unit": "SET", "level": 3, "item_type": "make"},
    ]
    receipt = await register_make_part_masters(db, "FAC_MECH_001", "A-50-04-F", items)
    assert [p.product_code for p in db.added] == ["REAL-1"]
    assert db.added[0].product_name == "車架組", "存进主档的必须是干净品名"
    assert "源行属性原文" in db.added[0].description
    assert receipt["blocked"]["drawing_row"] == ["DWG-1"]
    assert receipt["blocked"]["electronic_purchased"] == ["PCB-1"]


@pytest.mark.asyncio
async def test_repair_fixes_only_polluted_names_and_is_idempotent():
    from api.services.production_part_master import repair_selfmade_master_names

    dirty = _Master("001681-A", "FAC_MECH_001", "固定柱;;;ABS/PA757S;;回台物料;TM81;")
    clean = _Master("029306-00", "FAC_MECH_001", "齒輪")
    db = _db([dirty, clean])
    fixed = await repair_selfmade_master_names(db)
    assert fixed == 1
    assert dirty.product_name == "固定柱"
    assert clean.product_name == "齒輪", "已经干净的行不该被动过"
    assert await repair_selfmade_master_names(db) == 0, "第二次跑应该是 0（幂等）"
