"""半成品路线只取被它自己子树佐证的工序（用户 10-05 的工厂口径）。"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import routing_from_family as rf


class _Route:
    def __init__(self, id, product_id, steps):
        self.id = id
        self.product_id = product_id
        self.steps = steps
        self.created_by = "treadmill_flow_seed"


TREAD = [
    {"step_no": 10, "name": "车架焊接", "station": "ST-HJ-01"},
    {"step_no": 20, "name": "表面涂装", "station": "ST-TZ-01"},
    {"step_no": 30, "name": "电控装配", "station": "ST-JD-01"},
    {"step_no": 40, "name": "跑步机总装", "station": "ST-JD-01"},
    {"step_no": 50, "name": "成品检验", "station": "ST-QC-02"},
    {"step_no": 60, "name": "包装入库", "station": "ST-PK-01"},
]


class _Master:
    def __init__(self):
        self.product_code = "車架組"
        self.current_routing_id = None
        self.factory_id = "FAC_MECH_001"


def _db(route_steps):
    db = MagicMock()
    added = []
    master = _Master()

    async def execute(statement):
        res = MagicMock()
        res.scalar_one_or_none.return_value = master
        route = _Route("rt-tread-004-2026", "FG-TREAD-004", route_steps)
        res.scalars.return_value.all.return_value = [route]
        return res

    async def get(entity, pk):
        return None

    async def flush():
        return None

    db.execute = execute
    db.get = get
    db.flush = flush
    db.add = lambda obj: added.append(obj)
    db.master = master
    db.added = added
    return db


@pytest.mark.asyncio
async def test_component_route_keeps_only_corroborated_steps():
    """車架組的子树只写著"烤漆/焊接"，就只能拿到这两道工序，不该被塞进電控/包裝。"""
    db = _db(TREAD)
    corpus = "車架組 焊接 烤漆 冰銀金"
    receipt = await rf.derive_routing_for_component(db, "FAC_MECH_001", "車架組", corpus, level=3)

    assert receipt["status"] == "derived", receipt
    created = db.added[0]
    assert [s["name"] for s in created.steps] == ["车架焊接", "表面涂装"]
    assert [s["station"] for s in created.steps] == ["ST-HJ-01", "ST-TZ-01"]
    assert all("standard_time" not in s for s in created.steps), "不替工厂编工时"
    assert db.master.current_routing_id == created.id, "主档要指向新路线，否则工单还是排不动"


@pytest.mark.asyncio
async def test_component_needs_two_corroborated_operations_to_get_a_route():
    """只佐证到 1 道工序就不建路线：一道工序的"路线"是编出来的。"""
    db = _db(TREAD)
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "端蓋", "端蓋 ABS 黑色", level=4
    )
    assert receipt["status"] == "not_derived"
    assert db.added == []
    assert "不足 2 道" in receipt["reason"]


def test_component_gate_is_documented_separately_from_model_gate():
    """型号级要覆盖整条产线的一半；半成品级按子集，两个门槛不能混成一个数。"""
    assert rf.MIN_COVERAGE == 0.5
    assert rf.MIN_COMPONENT_STEPS == 2
