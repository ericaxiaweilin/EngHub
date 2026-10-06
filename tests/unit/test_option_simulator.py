"""选择推演的核心断言：部分投产要真的比"等料"多干出活，没依据的单任何策略都不许算能干。

推演的意义不是给一个正确答案，而是把几条路的后果摆出来比较 —— 所以断言打在**相对关系**上：
同一份现状，`run_what_you_can` 的产出必须 ≥ `wait_for_material`，闲置必须 ≤；
否则这个模型就没有回答"要不要换排法"的能力。
"""

from datetime import date

import pytest

pytestmark = [pytest.mark.unit]

from api.services.option_simulator import PARTIAL_COVERAGE_MIN, STRATEGY_LABELS, _coverage, _simulate


def _stations(code="ST-A", cap=10.0, hours=8.0, people=20):
    return {code: {"station_code": code, "station_name": code, "capacity_per_hour": cap,
                   "line_hours_per_day": hours, "setup_time_minutes": 30, "headcount_hr": people}}


def _order(code, qty=100, required=100, covered=100, due=date(2026, 12, 31), product="P-A"):
    return {"id": code, "work_order_code": code, "remaining_qty": qty, "planned_due": due,
            "required": required, "covered": covered, "route_ref": "rt-ST-A", "unit": "PCS",
            "product_id": product}


ROUTES = {"rt-ST-A": "ST-A"}


def _run(strategy, orders):
    return _simulate(strategy, orders, _stations(), ROUTES, [],
                     start=date(2026, 11, 2), days=10, labor_rate=30.0)


def test_partial_launch_beats_waiting_on_full_kit():
    """半覆盖的单：等料一条都不干；能干就先干要产出，且闲置更少。"""
    orders = [_order("WO-1", covered=int(100 * PARTIAL_COVERAGE_MIN))]
    wait = _run("wait_for_material", [dict(o) for o in orders])
    run = _run("run_what_you_can", [dict(o) for o in orders])
    assert wait["produced_units"] == 0
    assert run["produced_units"] > 0
    assert run["idle_station_days"] < wait["idle_station_days"]


def test_orders_without_any_kit_evidence_are_never_runnable():
    """required=0 不是"不缺料"，是没有依据：任何策略都不许把它排成能开工。"""
    orders = [_order("WO-2", qty=50, required=0, covered=0)]
    assert _coverage(orders[0]) == 0.0
    for strategy in STRATEGY_LABELS:
        assert _run(strategy, [dict(o) for o in orders])["produced_units"] == 0


def test_idle_cost_is_counted_in_person_days_not_station_days():
    result = _run("wait_for_material", [_order("WO-3", covered=0)])
    assert result["idle_station_days"] == 10.0
    assert result["idle_person_days"] == 200.0          # 10 台日 × 20 人
    assert result["labor_idle_cost"] == 6000.0          # × 30 USD/人·天


def test_simulation_is_reproducible():
    """同输入两次必须一模一样：推演结果要能被别人复核，不能带随机性。"""
    orders = [_order("WO-4", covered=70)]
    assert _run("run_what_you_can", [dict(o) for o in orders]) == \
        _run("run_what_you_can", [dict(o) for o in orders])


def test_transfer_strategy_declares_its_own_boundary():
    """人力在这版模型里不是产能约束：调人必须自带说明，不能被读成"厂里不该调人"。"""
    out = _run("transfer_idle_labor", [_order("WO-5", covered=80)])
    assert out["transfer_note"] and "人力" in out["transfer_note"]


def test_head_of_line_blocking_is_worse_than_resequencing_same_data():
    """他指出的关键：队头阻塞与按交期重排**理论上就不该同分**。
    交期早的那张缺料、后面那张齐套 —— 阻塞时整台工位停着；重排时后面的活能插队做完。"""
    blocked_first = _order("WO-EARLY", qty=100, covered=0, required=100, due=date(2026, 11, 5))
    kitted_later = _order("WO-LATER", qty=100, covered=100, required=100, due=date(2026, 11, 20))
    orders = [blocked_first, kitted_later]
    blocked = _run("wait_for_material", [dict(o) for o in orders])
    reseql = _run("resequence_by_due", [dict(o) for o in orders])
    assert blocked["produced_units"] == 0            # 卡在第一张上，整天不动
    assert blocked["idle_station_days"] == 10.0
    assert reseql["produced_units"] > 0              # 跳过缺料的，把齐套的做完
    assert reseql["orders_completed"] == 1
    assert reseql["idle_station_days"] < blocked["idle_station_days"]


def test_changeover_between_products_costs_capacity():
    """换不同机种要扣换线时间（setup_time_minutes 是实测字段）：否则模型永远鼓励乱切。"""
    a = _order("WO-A", qty=60, product="P-A")
    b = _order("WO-B", qty=60, product="P-B", due=date(2026, 11, 3))
    out = _run("resequence_by_due", [dict(o) for o in [a, b]])
    assert out["changeovers"] >= 1
    assert out["setup_capacity_lost_days"] > 0
