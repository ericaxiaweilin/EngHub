"""成本模型：参数必须带来源，目标不同排序必须变，硬成本和折旧不能混成一笔。

用户口径（10-06）：一种是机会成本、一种是硬成本；人力肯定硬，设备全款停着只是折旧。
单价没有不等于不能建模 —— 用内置标定跑，但每一项都要能看出"这是默认值还是谁给的"。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.cost_model import (DEFAULT_RATES, OBJECTIVES, cost_lines,
                                     reallocation_options, resolve_rates)


def _line(code="ST-A", name="焊接车间", **kw):
    base = {"station_code": code, "station_name": name, "headcount_hr": 100,
            "idle_ratio": 0.7, "idle_hours": 70.0, "runnable_hours": 20.0,
            "idle_person_hours_estimated": 490.0,
            "labor_hours_available_estimated": 800.0,
            "fillable_kitted_orders": 0, "fillable_need_hours": 0.0,
            "setup_time_minutes": 30.0}
    base.update(kw)
    return base


def test_defaults_are_labeled_and_labor_is_the_only_hard_labor_item():
    rates = resolve_rates([])
    assert rates["rates"]["labor_person_day"]["basis"] == "default_calibration"
    assert rates["rates"]["labor_person_day"]["hard"] is True
    # 全款设备默认按折旧算：现金没出去，所以不能和人力一起进"硬支出"
    assert rates["rates"]["equipment_line_day"]["hard"] is False


def test_override_flips_basis_source_and_hardness():
    """用户说这批设备有贷款 → equipment 变硬成本；来源必须跟着进结果。"""
    rates = resolve_rates([{
        "item_code": "equipment_line_day", "amount": 120.0, "is_hard": True,
        "source": "老板口述 2026-10-06", "note": "产线贷款未还清",
    }])
    item = rates["rates"]["equipment_line_day"]
    assert (item["basis"], item["hard"], item["source"]) == ("override", True, "老板口述 2026-10-06")
    assert rates["overridden_items"] == ["equipment_line_day"]
    assert rates["rates"]["labor_person_day"]["basis"] == "default_calibration"


def test_money_comes_out_of_hours_not_out_of_thin_air():
    rates = resolve_rates([])
    line = _line()
    costed = cost_lines([line], rates)[0]
    # 490 闲置人时 ÷ 8 = 61.25 人·天 × 30 = 1,837.5
    assert costed["idle_person_days"] == 61.25
    assert costed["labor_idle_cost"] == round(61.25 * DEFAULT_RATES["labor_person_day"]["amount"], 2)
    # 设备折旧不参与硬支出口径
    assert costed["equipment_idle_hard"] == 0.0
    assert costed["equipment_idle_depreciation"] > 0
    assert costed["hard_cost_total"] == round(costed["labor_idle_cost"] + costed["energy_cost_when_running"], 2)


def test_objective_changes_the_ranking_not_just_the_label():
    """同一份数据，人力优先和总成本优先应该给出不同排序 —— 否则"目标"是装饰不是参数。"""
    # A：人多、设备便宜（人力重）；B：人少但一条大线整天空着（设备重）
    idle_heavy = _line(code="ST-A", name="焊接车间", idle_hours=70.0, runnable_hours=20.0,
                       idle_person_hours_estimated=490.0)
    equip_heavy = _line(code="ST-B", name="注塑车间", headcount_hr=5,
                        idle_hours=6000.0, runnable_hours=24.0,
                        idle_person_hours_estimated=150.0)
    labor_view = cost_lines([idle_heavy, equip_heavy], resolve_rates([], "labor_first"))
    cost_view = cost_lines([idle_heavy, equip_heavy], resolve_rates([], "total_cost"))
    assert [c["station_code"] for c in sorted(labor_view, key=lambda c: -c["objective_score"])] == \
        ["ST-A", "ST-B"]
    assert [c["station_code"] for c in sorted(cost_view, key=lambda c: -c["objective_score"])] == \
        ["ST-B", "ST-A"]
    assert OBJECTIVES["labor_first"]["labor"] > OBJECTIVES["labor_first"]["equipment"]


def test_realoption_requires_work_waiting_and_flags_skill_check():
    rates = resolve_rates([])
    donor = _line()
    receiver = _line(code="ST-Z", name="注塑车间", headcount_hr=10,
                    fillable_kitted_orders=3, fillable_need_hours=40.0, idle_ratio=0.1)
    lines = [donor, receiver]
    costed = cost_lines(lines, rates)
    opts = reallocation_options(costed, lines, rates)
    assert opts and opts[0]["from_station_code"] == "ST-A"
    assert opts[0]["to_station_code"] == "ST-Z"
    assert opts[0]["people_to_move"] == 5          # 40 工时 ÷ 8
    assert opts[0]["changeover_cost"] > 0          # 换线 30 分钟要算钱
    assert opts[0]["net_benefit_per_day"] < opts[0]["labor_idle_saved_per_day"]
    # 技能矩阵是空的：建议必须带"待确认"，不能假装人随便调
    assert "技能矩阵" in opts[0]["skill_check"]


def test_no_options_when_nobody_is_waiting_for_labor():
    rates = resolve_rates([])
    lines = [_line()]
    assert reallocation_options(cost_lines(lines, rates), lines, rates) == []
