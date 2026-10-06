"""场景推演的建模断言：覆盖率只罚一次、在制品要真能流到最后一站、混机型要真的付换线代价。

这三条都是我自己先写错过的地方（覆盖率在每道工序都乘一遍 → 永远做不完；
待加工量和总量混用一个变量 → 东西走不出第一站），所以断言就打在这上面，防止再退回去。
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.unit]

from api.services import scenario_sim as ss

START = date(2026, 11, 2)


def _pack(codes_hours, stations=None):
    models = {}
    for code, (hours, steps) in codes_hours.items():
        models[code] = {"routing_id": f"rt-{code}", "unit_hours": hours,
                        "steps": [{"step_no": (i + 1) * 10, "op_name": f"工序{i+1}",
                                   "station_code": st, "capacity_per_hour": cap,
                                   "hours_per_unit": 1.0 / cap, "station_known": True}
                                  for i, (st, cap) in enumerate(steps)]}
    default_stations = {f"ST-{chr(65+i)}": {"station_code": f"ST-{chr(65+i)}",
                                            "station_name": f"车间{i+1}",
                                            "capacity_per_hour": 4.0,
                                            "line_hours_per_day": 8.0,
                                            "setup_time_minutes": 30, "headcount_hr": 10,
                                            "capacity_known": True}
                        for i in range(6)}
    return {"stations": stations or default_stations, "models": models, "unmodeled": []}


def _scenario(code, qty=20, due_in=25):
    return [{"product_id": code, "qty": qty, "due": START + timedelta(days=due_in)}]


def test_coverage_caps_what_can_start_once_not_at_every_step():
    """0.5 覆盖率 × 4 道工序不能变成 0.5^4：缺料只罚一次，能开多少就是多少。"""
    pack = _pack({"M1": (1.0, [("ST-A", 4.0), ("ST-B", 4.0), ("ST-C", 4.0), ("ST-D", 4.0)])})
    out = ss.simulate_flow(pack, _scenario("M1", qty=100), start=START, days=30,
                           strategy="run_what_you_can", labor_rate=30.0,
                           coverage_by_model={"M1": 0.5})
    assert out["produced_units"] == 50.0            # 100 × 0.5，不是 100 × 0.5^4
    assert out["awaiting_material_units"] == 50.0


def test_wip_reaches_the_last_station_and_completes_the_order():
    """在制品必须真能一站一站走到终点，整单做完才算交付。"""
    pack = _pack({"M1": (1.0, [("ST-A", 4.0), ("ST-B", 4.0), ("ST-C", 4.0)])})
    out = ss.simulate_flow(pack, _scenario("M1", qty=8), start=START, days=30,
                           strategy="wait_for_material", labor_rate=30.0,
                           coverage_by_model={"M1": 1.0})
    assert out["orders_completed"] == 1
    assert out["produced_units"] == 8.0
    # 三道工序一天只能推进一道 → 至少 3 天才可能完工
    assert out["completions"][0]["finish_day"] >= 2


def test_mixing_models_pays_changeovers_that_single_model_does_not():
    """同机种连做零换线；混两个机种就要付换线次数 —— 这正是混线排产的成本所在。"""
    pack = _pack({"M1": (1.0, [("ST-A", 2.0), ("ST-B", 2.0)]),
                  "M2": (1.0, [("ST-A", 2.0), ("ST-B", 2.0)])})
    one_model = ss.simulate_flow(pack, _scenario("M1", qty=10) * 3, start=START, days=30,
                                 strategy="run_what_you_can", labor_rate=30.0,
                                 coverage_by_model={"M1": 1.0})
    mixed = ss.simulate_flow(
        pack, [{"product_id": "M1", "qty": 10, "due": START + timedelta(days=10)},
               {"product_id": "M2", "qty": 10, "due": START + timedelta(days=11)},
               {"product_id": "M1", "qty": 10, "due": START + timedelta(days=12)}],
        start=START, days=30, strategy="run_what_you_can", labor_rate=30.0,
        coverage_by_model={"M1": 1.0, "M2": 1.0})
    assert one_model["changeovers"] == 0
    assert mixed["changeovers"] > 0


def test_head_of_line_blocking_stops_a_station_that_could_otherwise_run():
    """队头阻塞：交期早的那张缺料，后面齐套的也不许做；重排策略就该跳过去做。"""
    pack = _pack({"SHORT": (1.0, [("ST-A", 2.0)]), "KITTED": (1.0, [("ST-A", 2.0)])})
    scenario = [{"product_id": "SHORT", "qty": 10, "due": START + timedelta(days=5)},
                {"product_id": "KITTED", "qty": 10, "due": START + timedelta(days=9)}]
    cov = {"SHORT": 0.2, "KITTED": 1.0}
    blocked = ss.simulate_flow(pack, scenario, start=START, days=10,
                               strategy="wait_for_material", labor_rate=30.0,
                               coverage_by_model=cov)
    reseql = ss.simulate_flow(pack, scenario, start=START, days=10,
                              strategy="resequence_by_due", labor_rate=30.0,
                              coverage_by_model=cov)
    assert blocked["produced_units"] == 0.0
    assert reseql["produced_units"] == 10.0         # 齐套那张被救回来了


def test_orders_without_a_route_are_not_silently_included():
    pack = _pack({"KNOWN": (1.0, [("ST-A", 2.0)])})
    out = ss.simulate_flow(pack, _scenario("UNKNOWN-MODEL"), start=START, days=10,
                           strategy="run_what_you_can", labor_rate=30.0,
                           coverage_by_model={"UNKNOWN-MODEL": 1.0})
    assert out["jobs"] == 0 and out["produced_units"] == 0.0
