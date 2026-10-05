"""外购缺口汇成采购待办的口径：只读、与控制塔同源、不往没人读的表里灌行。"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services.procurement_demand import kit_shortage_demands


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _db(suppliers=(), po_history=(), on_order=(), other_status=(), material_suppliers=(),
        master_suppliers=()):
    db = MagicMock()
    writes = []

    async def execute(statement, params=None):
        sql = str(statement)
        if "FROM supplier_materials" in sql:
            return _Rows(suppliers)
        if "DISTINCT material_code, supplier_name" in sql:
            return _Rows(po_history)
        if "NOT IN ('confirmed', 'shipped', 'received')" in sql:
            return _Rows(other_status)
        if "FROM suppliers" in sql:
            return _Rows(master_suppliers)
        if "FROM materials" in sql:
            return _Rows(material_suppliers)
        if "FROM purchase_orders" in sql:
            return _Rows(on_order)
        writes.append(sql)
        return _Rows([])

    db.execute = execute
    db.writes = writes
    return db


@pytest.mark.asyncio
async def test_demands_aggregate_buy_shortage_with_supplier_evidence():
    db = _db(
        suppliers=[{"material_code": "1000205705", "supplier_name": "某線材廠",
                    "lead_time_days": 14, "min_order_qty": 100}],
        po_history=[{"material_code": "RM-STEEL-009", "supplier_name": "鋼材供應商"}],
        on_order=[{"material_code": "RM-STEEL-009", "on_order": 40, "first_expected": None}],
    )
    items = [
        {"material_code": "RM-STEEL-009", "material_name": "鋼板", "shortage_qty": 505,
         "item_type": "buy", "affected_work_orders": ["WO-1"]},
        {"material_code": "1000205705", "material_name": "電源線", "shortage_qty": 60,
         "item_type": "buy", "affected_work_orders": ["WO-1"]},
        {"material_code": "1000999999", "material_name": ".unknown", "shortage_qty": 10,
         "item_type": "buy", "affected_work_orders": ["WO-2"]},
    ]
    out = await kit_shortage_demands(db, "FAC_MECH_001", items)
    assert out["materials"] == 3 and out["shortage_qty"] == 575
    assert out["supplier_known"] == 2 and out["supplier_missing"] == 1
    assert out["on_order_qty"] == 40
    assert out["top"][0]["material_code"] == "RM-STEEL-009"
    assert out["top"][0]["supplier_name"] == "鋼材供應商"


@pytest.mark.asyncio
async def test_demands_never_write_and_are_read_only():
    """这一档以前灌出过 890 万行采购申请；这里明确只做读，不产生任何写入语句。"""
    db = _db()
    await kit_shortage_demands(db, "FAC_MECH_001", [
        {"material_code": "X", "material_name": "X", "shortage_qty": 1,
         "item_type": "buy", "affected_work_orders": []}])
    assert db.writes == []


@pytest.mark.asyncio
async def test_po_status_outside_the_mrp_basis_is_reported_not_silently_added():
    """in_transit/ordered 这些状态 MRP 的在途口径看不见 —— 要报成分歧，不是悄悄算进去。"""
    db = _db(other_status=[{"status": "in_transit", "orders": 3, "qty": 250}])
    out = await kit_shortage_demands(db, "FAC_MECH_001", [
        {"material_code": "X", "material_name": "X", "shortage_qty": 5,
         "item_type": "buy", "affected_work_orders": []}])
    assert out["po_status_not_counted"]["in_transit"]["qty"] == 250
    assert "MRP 现在看不到" in out["note"]


@pytest.mark.asyncio
async def test_zero_shortage_returns_an_empty_list_not_a_fake_number():
    out = await kit_shortage_demands(_db(), "FAC_MECH_001", [])
    assert out["materials"] == 0 and out["shortage_qty"] == 0
    assert out["top"] == []


@pytest.mark.asyncio
async def test_material_master_default_supplier_counts_as_evidence():
    """物料主档的 `default_supplier` 是"向谁买"的正式落点，不能只查 supplier_materials。"""
    db = _db(material_suppliers=[{"material_code": "RM-STEEL-009",
                                  "default_supplier": "宝钢金属(佛山)"}])
    out = await kit_shortage_demands(db, "FAC_MECH_001", [
        {"material_code": "RM-STEEL-009", "material_name": "鋼板", "shortage_qty": 505,
         "item_type": "buy", "affected_work_orders": ["WO-1"]}])
    assert out["supplier_known"] == 1 and out["supplier_missing"] == 0
    assert out["top"][0]["supplier_name"] == "宝钢金属(佛山)"


@pytest.mark.asyncio
async def test_suggestion_only_uses_real_registered_suppliers():
    """没依据的料号给一个**建议**供应商：名字必须来自 suppliers 档案，且标明未经确认。"""
    db = _db(master_suppliers=[{"supplier_name": "永年紧固件(邯郸)"},
                               {"supplier_name": "裕同包装(东莞)"}])
    out = await kit_shortage_demands(db, "FAC_MECH_001", [
        {"material_code": "RM-BOLT-9", "material_name": "M8螺栓", "shortage_qty": 90,
         "item_type": "buy", "affected_work_orders": ["WO-1"]},
        {"material_code": "RM-BOX-9", "material_name": "出口纸箱", "shortage_qty": 40,
         "item_type": "buy", "affected_work_orders": ["WO-1"]},
    ])
    assert out["supplier_known"] == 0 and out["suggested"] == 2
    by_code = {i["material_code"]: i for i in out["top"]}
    assert by_code["RM-BOLT-9"]["suggested_supplier"] == "永年紧固件(邯郸)"
    assert by_code["RM-BOX-9"]["suggested_supplier"] == "裕同包装(东莞)"
    assert all(i["supplier_basis"] == "建议·未经采购确认" for i in by_code.values())


@pytest.mark.asyncio
async def test_no_suggestion_when_master_has_no_fitting_supplier():
    """档案里一家都对不上就不建议 —— 空着比拿个不相干的名字填位好。"""
    db = _db(master_suppliers=[])
    out = await kit_shortage_demands(db, "FAC_MECH_001", [
        {"material_code": "X", "material_name": "M8螺栓", "shortage_qty": 5,
         "item_type": "buy", "affected_work_orders": []}])
    assert out["suggested"] == 0
    assert "suggested_supplier" not in out["top"][0]
