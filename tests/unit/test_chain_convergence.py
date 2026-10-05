"""收敛自检的合约：判定要能被别人拿同一串数字复算，且不许把"没报工"读成"算法坏了"。"""

import json
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import chain_convergence as cc


BASE = {
    "open_pool": 461, "child_orders": 474, "completed_orders": 5,
    "released_by_gate": 30, "shortage_qty": 34550.0, "reports_24h": 14,
    "live_plans": 7, "plan_task_rows": 5138, "reports_24h_virtual": 14,
}


def _prev(**over):
    metrics = dict(BASE)
    metrics.update(over)
    return {"metrics": metrics, "stalled_ticks": 0}


def test_first_tick_only_sets_a_baseline_and_dares_not_judge():
    out = cc.judge(BASE, None)
    assert out["verdict"] == "baseline" and out["alert"] is False
    assert out["deltas"] == {}


def test_forward_movement_in_any_of_the_three_signals_counts_as_advancing():
    for over in ({"completed_orders": 4},
                 {"released_by_gate": 29, "open_pool": 465},
                 {"shortage_qty": 34600.0}):
        prev = _prev(**over)
        out = cc.judge(BASE, prev)
        assert out["verdict"] == "advancing", over
        assert out["stalled_ticks"] == 0


def test_releasing_fewer_than_arriving_is_never_reported_as_progress():
    """这条就是第一版假绿灯的反例：放 5 张、进 10 张、缺口还涨 —— 不能叫推进。"""
    prev = _prev(released_by_gate=72, open_pool=611 - 10, shortage_qty=49115.0 - 90,
                 reports_24h=8)
    current = dict(BASE, open_pool=611, released_by_gate=77, shortage_qty=49115.0,
                   reports_24h=8)
    out = cc.judge(current, prev)
    assert out["verdict"] == "diverging"
    assert out["deltas"]["open_pool"] == 10 and out["deltas"]["released_by_gate"] == 5
    assert "放行速度盖不住" in out["reason"]


def test_pool_growing_while_nothing_gets_released_is_called_diverging():
    prev = _prev(open_pool=441, released_by_gate=30, shortage_qty=33000.0)
    out = cc.judge(BASE, prev)
    assert out["verdict"] == "diverging"
    assert out["deltas"]["open_pool"] == 20
    assert out["deltas"]["shortage_qty"] > 0


def test_three_stalled_ticks_in_a_row_raises_the_alert():
    prev = _prev()
    prev["stalled_ticks"] = 2
    out = cc.judge(BASE, prev)  # 三个数都没动
    assert out["verdict"] == "stalled"
    assert out["stalled_ticks"] == 3
    assert out["alert"] is True


def test_report_provenance_is_stated_instead_of_calling_virtual_work_not_real():
    """执行侧口径：报工由虚拟工厂脉搏承担，不能再写成"没有真实报工输入"。"""
    prev = _prev(reports_24h=0, reports_24h_virtual=0)
    current = dict(BASE, reports_24h=6, reports_24h_virtual=6)
    out = cc.judge(current, prev)
    assert "近 24h 报工 6 条（虚拟工厂脉搏 6 条 / 外部接入 0 条）" in out["reason"]
    assert "没有真实报工" not in out["reason"]


def test_rules_travel_with_the_verdict_so_a_reviewer_can_recompute():
    out = cc.judge(BASE, _prev(completed_orders=4))
    assert set(out["verdict_rules"]) >= {"advancing", "diverging", "stalled",
                                        "alert_after_stalled_ticks", "shortage_epsilon"}


@pytest.mark.asyncio
async def test_previous_reading_only_uses_the_heartbeat_row_and_survives_junk():
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "FROM engine_loop_state" in sql:
            r.mappings.return_value.first.return_value = {
                "last_detail": json.dumps({"convergence": {
                    "metrics": BASE, "stalled_ticks": 1}})
            }
        else:
            r.mappings.return_value.first.return_value = None
        return r

    db = MagicMock()
    db.execute = execute
    prev = await cc.read_previous(db, "routing-backfill")
    assert prev["stalled_ticks"] == 1 and prev["metrics"]["open_pool"] == 461

    async def broken(statement, params=None):
        r = MagicMock()
        r.mappings.return_value.first.return_value = {"last_detail": "not-json{"}
        return r
    db.execute = broken
    assert await cc.read_previous(db, "routing-backfill") is None, "读不到就说不清，不许猜一个基线"


@pytest.mark.asyncio
async def test_measure_is_read_only():
    calls = []

    async def execute(statement, params=None):
        calls.append(str(statement))
        r = MagicMock()
        r.mappings.return_value.first.return_value = {
            "open_pool": 461, "child_orders": 474, "completed_orders": 5,
            "released_by_gate": 30, "shortage_qty": 34550, "reports_24h": 14,
            "live_plans": 7, "plan_task_rows": 5138, "reports_24h_virtual": 14,
        }
        return r

    db = MagicMock()
    db.execute = execute
    out = await cc.measure(db, "FAC_MECH_001")
    assert out["shortage_qty"] == 34550.0 and isinstance(out["shortage_qty"], float)
    assert not any(k in c.upper() for c in calls for k in ("INSERT", "UPDATE", "DELETE"))
