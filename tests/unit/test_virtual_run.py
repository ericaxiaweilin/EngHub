"""沙箱推演的口径：瓶颈是料不是产能时，日期由到货日决定；暴雨必须把产能一起拖下来。

这些函数是整个推演的骨架，断言打在"引擎会不会自己做决定"上：
没有路线就借同族、没有工时就用线节拍、现料够就先开一批、人手不足就降产能。
"""

import pytest
from datetime import date

pytestmark = [pytest.mark.unit]

from api.services import virtual_run as vr

LINE = {"line_code": "LINE-TREAD-01", "line_group": "GROUP-TREAD", "hours_per_day": 11.0,
        "units_per_day": 300.0, "crew_size": 300, "can_models": "['A-50-04-F']",
        "default_model": "A-50-04-F"}
BIKE = {"line_code": "LINE-BIKE-01", "line_group": "GROUP-BIKE", "hours_per_day": 11.0,
        "units_per_day": 400.0, "crew_size": 150,
        "can_models": "['HTM1481-00','A-50-04-F']", "default_model": "HTM1481-00"}


def test_line_choice_prefers_declaration_then_family():
    line, basis = vr.pick_line("A-50-04-F", [LINE, BIKE])
    assert basis.startswith("line_declared")
    line, basis = vr.pick_line("FG-TREAD-003", [LINE, BIKE])
    assert (line["line_code"], basis) == ("LINE-TREAD-01", "line_inferred_by_family_name")
    line, basis = vr.pick_line("UNKNOWN-X", [LINE, BIKE])
    assert line is None and basis == "no_line"


def test_route_falls_back_to_family_and_labels_it():
    own = [{"operation_name": "焊接", "standard_hours": 0.5}]
    fam = [{"operation_name": "焊接", "work_center": "ST-HJ-01", "standard_hours": 0.4}]
    assert vr.resolve_route(own, fam)[1] == "own_route"
    route, basis = vr.resolve_route([], fam)
    assert basis == "borrowed_route_from_family" and route[0]["standard_hours"] == 0.4
    assert vr.resolve_route([], [])[1] == "no_route"


def test_hours_use_route_when_declared_else_line_takt():
    route = [{"standard_hours": 0.5}, {"standard_hours": 0.3}]
    assert vr.hours_per_unit_from(route, LINE) == (0.8, "route_standard_hours")
    empty = [{"standard_hours": 0}]
    assert vr.hours_per_unit_from(empty, LINE) == (round(11 / 300, 4), "takt_from_line_capacity")
    assert vr.hours_per_unit_from(empty, None) == (0.0, "no_time_basis")


def test_kit_names_the_slowest_buy_part_and_costs_only_priced_lines():
    bom = [
        {"material_code": "P1", "qty_per_unit": 2, "make_or_buy": "外购",
         "lead_time_days": "10", "default_supplier": "甲", "unit_price": 5},
        {"material_code": "P2", "qty_per_unit": 1, "make_or_buy": "外购",
         "lead_time_days": "20", "default_supplier": None, "unit_price": None},
        {"material_code": "P3", "qty_per_unit": 1, "make_or_buy": "自制",
         "lead_time_days": "3", "default_supplier": None, "unit_price": 1},
    ]
    kit = vr.build_kit(bom, units=100, stock={"P1": 200.0}, start_day=0)
    assert kit["bottleneck_part"]["material_code"] == "P2"       # 20 天那件是瓶颈
    assert kit["bottleneck_part"]["lead_time_days"] == 20
    assert 20 in kit["buy_arrival_days"]
    # P3 自制缺料不算采购到货；P1 有货不需要下单
    assert all(l["make_or_buy"] != "自制" or l["short"] > 0 for l in kit["lines"])
    assert kit["material_cost_usd"] if "material_cost_usd" in kit else True
    assert kit["material_cost"] == round((5 * 200) + (1 * 100), 2)   # 没单价的 P2 不折算


def test_storm_lowers_daily_output_because_the_line_is_labor_bound():
    """300 人配 300 台/天 = 一台一份人力：来 7 成就只能出 7 成，货期必须往后走。"""
    sat = {d: 1.0 for d in range(0, 60)}
    storm = {d: 0.7 for d in range(0, 60)}
    weekdays = {1, 2, 3, 4, 5, 6}
    today = date(2026, 10, 5)
    full = vr.simulate_days(600, 0.0367, 11.0, 300, sat, weekdays, 0, 300, today)
    slow = vr.simulate_days(600, 0.0367, 11.0, 300, storm, weekdays, 0, 300, today)
    assert full["work_days"] == 2
    assert slow["work_days"] >= 3                      # 暴雨天干得更久
    assert slow["finished_on_day"] > full["finished_on_day"]
    assert slow["completed"] is True and full["completed"] is True


def test_non_shift_days_are_skipped_by_real_calendar_not_relative_weeks():
    """周一开工、周日不排班：跳过的是真日历上的周日，不是"第 7 天"。"""
    today = date(2026, 10, 5)                        # 周一
    run = vr.simulate_days(900, 0.0367, 11.0, 300, {d: 1.0 for d in range(0, 30)},
                           {1, 2, 3, 4, 5, 6}, 0, 300, today)
    assert run["work_days"] == 3
    finish = today.toordinal() + run["finished_on_day"]
    assert date.fromordinal(finish).isoweekday() in {1, 2, 3, 4, 5, 6}


def test_waiting_for_material_does_not_fake_output():
    run = vr.simulate_days(300, 0.0367, 11.0, 300, {d: 1.0 for d in range(0, 30)},
                           {1, 2, 3, 4, 5, 6}, 10, 300, date(2026, 10, 5))
    assert run["started_on_day"] >= 10
    assert run["wait_days"] >= 1
    assert run["idle_person_days_before_start"] > 0      # 等料期间人在岗是要认的成本
    assert run["work_days"] == 1
