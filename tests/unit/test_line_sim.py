"""产线级推演的断言：单向兼容必须真的单向，人力必须跟着活走，节拍口径必须能比。

用户给的线参数（跑步机 11H/300台/200人；bike 11H/400台/150人/2条线；
bike 可做跑步机、跑步机做不了 bike）就是这些断言里的物理规则。
"""

from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.unit]

from api.services.scenario_sim import _can_run, _line_capacity, simulate_lines

START = date(2026, 11, 2)
LINES = [
    {"line_code": "LINE-TREAD-01", "line_name": "跑步机线", "hours_per_day": 11,
     "units_per_day": 300, "crew_size": 200, "parallel_lines": 1,
     "can_make_models": ["A-50-04-F"],
     "cannot_make_models": ["HTM1481-00", "HTM1390-00"], "default_model": "A-50-04-F"},
    {"line_code": "LINE-BIKE-01", "line_name": "bike线", "hours_per_day": 11,
     "units_per_day": 400, "crew_size": 150, "parallel_lines": 2,
     "can_make_models": ["HTM1481-00", "HTM1390-00", "A-50-04-F"],
     "cannot_make_models": [], "default_model": "HTM1481-00"},
]


def _jobs(t_qty=8100, b_qty=16200):
    out = [{"id": "T1", "product_id": "A-50-04-F", "qty": t_qty, "line": "LINE-TREAD-01",
            "due": START + timedelta(days=30)}]
    out.append({"id": "B1", "product_id": "HTM1481-00", "qty": b_qty, "line": "LINE-BIKE-01",
                "due": START + timedelta(days=30)})
    return out


def test_compatibility_is_one_way():
    assert _can_run(LINES[1], "A-50-04-F") is True        # bike 线能做跑步机
    assert _can_run(LINES[0], "HTM1481-00") is False      # 跑步机线做不了 bike


def test_bike_capacity_reading_is_a_real_fork():
    per_line = _line_capacity(LINES[1], units_are_per_line=True)
    total = _line_capacity(LINES[1], units_are_per_line=False)
    assert (per_line, total) == (800.0, 400.0)


def test_treadmill_shortage_can_be_recovered_but_bike_shortage_cannot():
    """同样缺料 10 天：跑步机单能挪去 bike 线救回来，bike 单没地方挪。"""
    locked = simulate_lines(LINES, _jobs(), days=30, available_from={"A-50-04-F": 10},
                            labor_rate=30.0, allow_line_move=False)
    flex = simulate_lines(LINES, _jobs(), days=30, available_from={"A-50-04-F": 10},
                          labor_rate=30.0, allow_line_move=True)
    assert locked["units_unfinished"] > 0
    assert flex["units_unfinished"] < locked["units_unfinished"]
    assert flex["moved_units_to_other_lines"] > 0

    bike_jobs = _jobs(t_qty=3000, b_qty=16200)     # bike 排到 90% 负荷，跑步机留足富余
    locked_bike = simulate_lines(LINES, bike_jobs, days=30, available_from={"HTM1481-00": 10},
                                 labor_rate=30.0, allow_line_move=False)
    flex_bike = simulate_lines(LINES, [dict(j) for j in bike_jobs], days=30,
                               available_from={"HTM1481-00": 10},
                               labor_rate=30.0, allow_line_move=True)
    assert locked_bike["units_unfinished"] > 0
    # bike 的活挪不出去（跑步机线做不了 bike）：允许挪线也救不回欠交
    assert flex_bike["units_unfinished"] == locked_bike["units_unfinished"]


def test_labor_follows_work_not_machines():
    """缺料期间做不掉的跑步机单，货到之后用 bike 线的富余机器追：人还是跑步机线的人，
    所以闲置要按这条线**自己那批单的总量**算，不能因为机器是别家的就重复记一遍闲。"""
    flex = simulate_lines(LINES, _jobs(t_qty=8100, b_qty=0), days=30,
                          available_from={"A-50-04-F": 20}, labor_rate=30.0,
                          allow_line_move=True)
    locked = simulate_lines(LINES, [dict(j) for j in _jobs(t_qty=8100, b_qty=0)], days=30,
                            available_from={"A-50-04-F": 20}, labor_rate=30.0,
                            allow_line_move=False)
    tread_f = [r for r in flex["lines"] if r["line_code"] == "LINE-TREAD-01"][0]
    tread_l = [r for r in locked["lines"] if r["line_code"] == "LINE-TREAD-01"][0]
    assert flex["units_made"] == 8100.0               # 最后全部追回来了
    assert locked["units_unfinished"] > 0             # 不挪线就追不完
    assert tread_f["own_orders_units"] == 8100.0      # 家线台账记的是自己单的总量，不管谁做的
    assert tread_f["idle_person_days"] < tread_l["idle_person_days"]
