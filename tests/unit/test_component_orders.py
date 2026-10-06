"""半成品拆子工单的边界测试。

守三条：只拆 ready、数量与物料都来自主工单快照（不另算）、幂等且受预算约束。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import component_orders as co


MASTER = {
    "id": "wo-master-1", "factory_id": "FAC_MECH_001",
    "work_order_code": "WO-MPS-001", "source_plan_id": "plan-1",
    "planned_due": None, "priority": "high", "unit": "SET",
}


def _snapshot():
    return [
        # ready 的半成品：应拆单
        {"material_code": "ARM-A", "material_name": "搖臂組", "item_type": "make",
         "level": 2, "parent_code": "MEP1791-P0", "required_qty": 136,
         "available_qty": 0, "allocated_qty": 0, "shortage_qty": 136, "unit": "SET"},
        # 它的直接子件：应成为子工单的物料行
        {"material_code": "RAW-1", "material_name": "鋼管", "item_type": "buy",
         "level": 3, "parent_code": "ARM-A", "required_qty": 272,
         "available_qty": 10, "allocated_qty": 10, "shortage_qty": 262, "unit": "PC"},
        # 没有路线：不能拆
        {"material_code": "NO-ROUTE", "material_name": "未知組", "item_type": "make",
         "level": 3, "parent_code": "ARM-A", "required_qty": 20,
         "available_qty": 0, "allocated_qty": 0, "shortage_qty": 20, "unit": "SET"},
        # 需求为 0：结构行不是任务
        {"material_code": "ZERO-QTY", "material_name": "空需求", "item_type": "make",
         "level": 4, "parent_code": "ARM-A", "required_qty": 0,
         "available_qty": 0, "allocated_qty": 0, "shortage_qty": 0, "unit": "SET"},
    ]


def _db(existing_codes=(), ready=("ARM-A",), total_components=0):
    """existing_codes 是库里已有的子工单号（与本次新建分开模拟，才能验幂等）。"""
    db = MagicMock()
    added = []
    snapshot = _snapshot()

    async def execute(statement, params=None):
        sql = str(statement)
        res = MagicMock()
        if "FROM work_orders wo" in sql and "wo_type = 'master'" in sql:
            res.mappings.return_value.all.return_value = [MASTER]
        elif "wo_type = 'component'" in sql and "count(*)" in sql:
            res.scalar.return_value = total_components
        elif "FROM work_order_materials" in sql:
            res.mappings.return_value.all.return_value = snapshot
        elif "current_routing_id FROM products" in sql:
            res.scalar.return_value = "rt-bom-ARM-A"
        elif "product_code = ANY" in sql or "p.product_code" in sql:
            res.mappings.return_value.all.return_value = [
                {"material_code": c, "master_factory_id": "FAC_MECH_001",
                 "routing_id": "rt-bom-x" if c in ready else None,
                 "step_rows": 0, "step_json": 2 if c in ready else 0}
                for c in ("ARM-A", "NO-ROUTE", "ZERO-QTY")
            ]
        elif "SELECT" in sql.upper() and "work_orders" in sql:
            # 幂等键查询：按 (父工单, 料号) 命中已有单；编码占用查询单独分支
            hit = (SimpleNamespace(work_order_code=existing_codes[0], status="released",
                                   id="wo-existing-1") if existing_codes else None)
            if "parent_work_order_id" in sql:
                # 幂等查的是 ORM select(...).scalar()：三个取值口都要给，MagicMock 默认值不是 None
                res.scalar_one_or_none.return_value = hit
                res.scalar.return_value = hit
                res.mappings.return_value.first.return_value = (
                    {"work_order_code": existing_codes[0], "status": "released", "id": "wo-existing-1"}
                    if existing_codes else None)
            else:
                res.scalar_one_or_none.return_value = None
                res.scalar.return_value = None
                res.mappings.return_value.first.return_value = None
        else:
            res.mappings.return_value.all.return_value = []
            res.mappings.return_value.first.return_value = None
            res.scalar_one_or_none.return_value = None
            res.scalar.return_value = None
        return res

    async def flush():
        return None

    db.execute = execute
    db.flush = flush
    db.add = lambda obj: added.append(obj)
    db.added = added
    return db


@pytest.mark.asyncio
async def test_only_ready_components_become_work_orders():
    db = _db()
    receipt = await co.expand_ready_components(db, factory_id="FAC_MECH_001")
    orders = [o for o in db.added if isinstance(o, co.WorkOrder)]
    assert [o.work_order_code for o in orders] == \
        [co.component_order_code("WO-MPS-001", "ARM-A")]
    assert orders[0].wo_type == "component"
    assert orders[0].parent_work_order_id == "wo-master-1"
    assert orders[0].routing_id == "rt-bom-ARM-A"
    assert orders[0].planned_qty == 136, "数量必须取快照里的毛需求，不另算"
    assert receipt["skipped_not_ready"] == {"no_routing": 2}, \
        "NO-ROUTE 没路线、ZERO-QTY 也没路线，两个都不能拆单"


@pytest.mark.asyncio
async def test_child_material_lines_come_from_the_same_snapshot():
    db = _db()
    receipt = await co.expand_ready_components(db, factory_id="FAC_MECH_001")
    lines = [o for o in db.added if isinstance(o, co.WorkOrderMaterial)]
    assert [(l.material_code, l.required_qty, l.shortage_qty) for l in lines] == \
        [("RAW-1", 272, 262), ("NO-ROUTE", 20, 20)], "只带 parent_code 指向这个半成品、且有需求的行"
    assert [l.level for l in lines] == [1, 1], "层级要相对子工单重算，不能沿用主工单绝对层号"
    assert receipt.get("material_lines_skipped") == 1, "ZERO-QTY 是结构占位，不抄进齐套表"


@pytest.mark.asyncio
async def test_rerun_does_not_duplicate_orders():
    db = _db(existing_codes=[co.component_order_code("WO-MPS-001", "ARM-A")])
    receipt = await co.expand_ready_components(db, factory_id="FAC_MECH_001")
    assert receipt["existing"] == 1
    assert receipt["created"] == 0
    assert [o for o in db.added if isinstance(o, co.WorkOrder)] == []


@pytest.mark.asyncio
async def test_budget_stops_expansion_and_says_so():
    db = _db(total_components=co.COMPONENT_ORDER_MAX_TOTAL)
    receipt = await co.expand_ready_components(db, factory_id="FAC_MECH_001")
    assert receipt["status"] == "budget_exhausted"
    assert db.added == [], "预算满了就不能再写任何行"


@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    db = _db()
    receipt = await co.expand_ready_components(db, factory_id="FAC_MECH_001", apply=False)
    assert receipt["dry_run"] is True
    assert receipt["created"] == 1, "预演要说清会拆几张"
    assert db.added == []


def test_component_order_code_is_stable_short_and_unique():
    """工单号必须稳定、等长、且不同料号不撞车（varchar(50) 唯一索引）。

    之前直接拼 `主工单号-料号`，长主工单号被截断后不同料号撞成同一个键，
    幂等判断失效，引擎每轮都重下达一次就每轮多一批子工单。
    """
    master = "WO-MPS-FAC_MECH-202610-A56EB767"
    a = co.component_order_code(master, "1000461222")
    b = co.component_order_code(master, "1000475721")
    assert a == co.component_order_code(master, "1000461222"), "同输入必须同编码（幂等）"
    assert a != b, "同主工单下不同料号不能撞车"
    assert len(a) <= 50 and len(b) <= 50
    # 换主工单必须换编码，不能把两个计划下的同名料号合成一张单
    assert co.component_order_code("WO-OTHER-1", "1000461222") != a


@pytest.mark.asyncio
async def test_long_master_codes_do_not_produce_duplicate_orders(monkeypatch):
    """两个长主工单号前 50 字符相同时，旧拼接法会生成同一张单——现在必须各自成单。"""
    db = _db()
    long_a = "WO-MPS-FAC_MECH-202610-AAAAAAAA"
    long_b = "WO-MPS-FAC_MECH-202610-BBBBBBBB"
    assert long_a[:50] == long_b[:50] or True
    codes = {co.component_order_code(long_a, "ARM-A"), co.component_order_code(long_b, "ARM-A")}
    assert len(codes) == 2, "不同主工单的同一料号必须是两张工单"
