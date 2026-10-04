"""按产品族推导工艺路线的边界测试。

这里守的是"不能替工厂编工艺"：套用要有佐证，参考路线没有工时就不能补一个数。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import routing_from_family as rf

TREAD_STEPS = [
    {"step_no": 10, "name": "车架焊接", "station": "ST-HJ-01"},
    {"step_no": 20, "name": "表面涂装", "station": "ST-TZ-01"},
    {"step_no": 30, "name": "电控装配", "station": "ST-JD-01"},
    {"step_no": 40, "name": "跑步机总装", "station": "ST-JD-01"},
    {"step_no": 50, "name": "成品检验", "station": "ST-QC-02"},
    {"step_no": 60, "name": "包装入库", "station": "ST-PK-01"},
]


def test_matches_requires_the_model_to_recognize_the_operation():
    corpus = "車架組 烤漆 電控板 組立 包裝"
    assert rf._matches("车架焊接", corpus)
    assert rf._matches("表面涂装", corpus)
    assert not rf._matches("注塑成型", corpus)


def test_normalize_keeps_steps_without_inventing_times():
    normalized = []
    for idx, step in enumerate(TREAD_STEPS):
        normalized.append({
            "step_no": step["step_no"],
            "name": step["name"],
            "station": step["station"],
        })
    assert all("standard_time" not in s for s in normalized), \
        "参考路线没有确认工时，推导出来的路线也不能补一个数进去"
    assert [s["station"] for s in normalized] == [s["station"] for s in TREAD_STEPS]


@pytest.mark.asyncio
async def test_no_master_means_no_route_binding(monkeypatch):
    db = MagicMock()

    async def execute(statement):
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        return res

    db.execute = execute
    receipt = await rf.derive_routing_for_product(db, "FAC_MECH_001", "NOPE")
    assert receipt["status"] == "no_master"


def test_min_coverage_is_not_zero():
    """门槛不能是 0：否则任何一条同厂路线都能被套到一个不相干的型号上。"""
    assert rf.MIN_COVERAGE >= 0.5
