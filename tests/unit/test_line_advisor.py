"""线组建议的两条底线：没差额就不许发待办，有差额时一条线组只发一条。"""

from datetime import date

import pytest

pytestmark = [pytest.mark.unit]

from api.services import line_strategy_advisor as adv

LINES = [
    {"line_code": "LINE-TREAD-01", "line_name": "跑步机线", "hours_per_day": 11,
     "units_per_day": 300, "crew_size": 300, "parallel_lines": 1,
     "line_group": "GROUP-TREAD", "group_units_per_day": 300,
     "can_make_models": ["A-50-04-F"], "cannot_make_models": ["HTM1481-00"],
     "default_model": "A-50-04-F"},
    {"line_code": "LINE-BIKE-01", "line_name": "bike线1", "hours_per_day": 11,
     "units_per_day": 400, "crew_size": 150, "parallel_lines": 1,
     "line_group": "GROUP-BIKE", "group_units_per_day": 700,
     "can_make_models": ["HTM1481-00", "A-50-04-F"], "cannot_make_models": [],
     "default_model": "HTM1481-00"},
    {"line_code": "LINE-BIKE-02", "line_name": "bike线2", "hours_per_day": 11,
     "units_per_day": 400, "crew_size": 150, "parallel_lines": 1,
     "line_group": "GROUP-BIKE", "group_units_per_day": 700,
     "can_make_models": ["HTM1481-00", "A-50-04-F"], "cannot_make_models": [],
     "default_model": "HTM1481-00"},
]


def _demand(rows):
    return [{"product_id": p, "remaining": q, "required": q, "covered": q,
             "first_due": None, "home_line": h} for p, q, h in rows]


def test_no_delta_no_suggestion():
    """两条路跑出来一样（没有可挪的富余，也没有欠交）时不许发待办：噪音比沉默更糟。"""
    demand = _demand([("HTM1481-00", 1000.0, "LINE-BIKE-01")])
    jobs = adv._jobs(demand)
    cov = adv._coverage(demand)
    from api.services.scenario_sim import simulate_lines
    fixed = simulate_lines(LINES, jobs, days=30, available_from={}, labor_rate=30.0,
                           allow_line_move=False, coverage_by_model=cov)
    flex = simulate_lines(LINES, jobs, days=30, available_from={}, labor_rate=30.0,
                          allow_line_move=True, coverage_by_model=cov)
    deltas = adv._group_deltas(fixed, flex)
    assert all(d["idle_person_days_saved"] <= 0 and d["units_recovered"] <= 0 for d in deltas)


def test_treadmill_shortage_produces_one_group_delta():
    """跑步机排不下时，差额要出现在 GROUP-TREAD 上（bike 组有富余节拍可接）。"""
    demand = _demand([("A-50-04-F", 12000.0, "LINE-TREAD-01")])   # 跑步机组 30 天只有 9,000 台能力
    jobs = adv._jobs(demand)
    cov = adv._coverage(demand)
    from api.services.scenario_sim import simulate_lines
    fixed = simulate_lines(LINES, jobs, days=30, available_from={}, labor_rate=30.0,
                           allow_line_move=False, coverage_by_model=cov)
    flex = simulate_lines(LINES, jobs, days=30, available_from={}, labor_rate=30.0,
                          allow_line_move=True, coverage_by_model=cov)
    deltas = {d["line_group"]: d for d in adv._group_deltas(fixed, flex)}
    assert deltas["GROUP-TREAD"]["units_recovered"] > 0
    assert fixed["units_unfinished"] > flex["units_unfinished"]


def test_coverage_caps_what_can_be_started():
    """覆盖率 0.5 时只能开一半，另一半记成等料，不能算成已产出。"""
    from api.services.scenario_sim import simulate_lines
    demand = _demand([("A-50-04-F", 1000.0, "LINE-TREAD-01")])
    out = simulate_lines(LINES, adv._jobs(demand), days=30, available_from={}, labor_rate=30.0,
                         allow_line_move=False, coverage_by_model=adv._coverage(
                             [{"product_id": "A-50-04-F", "remaining": 1000.0,
                               "required": 1000.0, "covered": 500.0, "first_due": None,
                               "home_line": "LINE-TREAD-01"}]))
    assert out["units_awaiting_material"] == 500.0
    assert out["units_made"] <= 500.0
