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


BIKE_G = {**BIKE, "group_units_per_day": 700.0}
BIKE_G2 = {**BIKE, "line_code": "LINE-BIKE-02", "group_units_per_day": 700.0}


def test_parallel_lines_are_capped_by_the_declared_group_capacity():
    """同组两条 bike 线合并是 700 台/天，不是 400×2=800（用户 10-06 口述定稿）。

    凭空多出的那 100 台/天会改变"缺料时靠另一条线追不追得回来"的结论，
    而政策网格里的"并联开满"档就是靠这个判断输赢的。
    """
    one = vr.group_capacity([BIKE_G, BIKE_G2], BIKE_G, 1)
    two = vr.group_capacity([BIKE_G, BIKE_G2], BIKE_G, 2)
    assert one["units_per_day"] == 400.0 and one["capacity_basis"] == "single_line"
    assert two["units_per_day"] == 700.0 and "group_declared" in two["capacity_basis"]
    assert two["crew"] == 300.0            # 并联要用两条线的人，不能只算一条
    loose = vr.group_capacity([BIKE, {**BIKE, "line_code": "LINE-BIKE-02"}], BIKE, 2)
    assert loose["units_per_day"] == 800.0
    assert loose["capacity_basis"].startswith("multiplied")   # 没声明就只能乘，但要写明是乘的


def _res(vecs, *, objectives=("labor_cost_usd", "expedite_cost_usd"), dead=(),
         frontier=2, eliminated=0, no_feasible=False, report_only=False):
    """vecs: 每个可行解的后悔向量（写成 {目标: 后悔} 或单独一个数）。"""
    pool = []
    for i, v in enumerate(vecs):
        reg = {"labor_cost_usd": float(v)} if isinstance(v, (int, float)) else dict(v)
        pool.append({"name": f"p{i}", "regret_by_objective": reg,
                     "max_regret": max(reg.values()) if reg else None})
    return {"frontier": pool[:frontier], "dominated": pool[frontier:],
            "eliminated": [{"name": f"e{i}"} for i in range(eliminated)],
            "objectives": [k for k in objectives if k not in dead],
            "non_discriminating_objectives": list(dead),
            "no_feasible_solution": no_feasible,
            "report_only_comparison": report_only,
            "recommended": {"name": "p0", "objectives": {"days_late_worst": 0}},
            "recommended_tied_with": []}


def test_scenario_is_left_alone_when_objectives_still_discriminate():
    """全政策准点不该靠收紧交期去制造区分度：人力/加急/开线还能比出差别就是有效的一轮。"""
    res = _res([0.1, 0.4, 0.7, 0.9, 1.2, 1.5, 1.8])
    disc = vr.scenario_discrimination(res, 7)
    cal = {"days_of_output": 6.0, "lead_margin": 1.15}
    assert disc["feasible_ratio"] == 1.0 and disc["runner_up_regret_gap"] == 0.3
    assert vr._tune_one(cal, disc) is None
    assert cal == {"days_of_output": 6.0, "lead_margin": 1.15}


def test_saturated_and_tied_scenario_gets_tightened():
    """都准点 + 推荐解与次优解后悔并列 + 目标维度全平 = 这一轮白算，收紧该场景交期。"""
    res = _res([0.5, 0.5, 0.5], dead=("labor_cost_usd", "expedite_cost_usd"))
    disc = vr.scenario_discrimination(res, 3)
    cal = {"days_of_output": 6.0, "lead_margin": 1.15}
    assert vr._tune_one(cal, disc) is not None
    assert cal["lead_margin"] == 1.05          # 只动这个场景，别动全局


def test_hungry_scene_is_relaxed_before_the_batch_is_touched():
    """几乎没政策能准点：先分清是交期定太紧，还是量定太大 —— 顺序不能反。"""
    res = _res([], eliminated=10, no_feasible=True)
    disc = vr.scenario_discrimination(res, 10)
    cal = {"days_of_output": 6.0, "lead_margin": 1.15}
    vr._tune_one(cal, disc)
    assert cal["lead_margin"] == 1.25 and cal["days_of_output"] == 6.0
    cal2 = {"days_of_output": 6.0, "lead_margin": 1.6}
    vr._tune_one(cal2, disc)
    assert cal2["lead_margin"] == 1.6 and cal2["days_of_output"] == 5.0


def test_calibration_does_not_tune_an_infeasible_deadline_into_feasibility():
    """交期系数与批量都到边界还是没人能准点 → 不再调参。

    继续调下去就是把"以现有提前期做不到"调成"做得到"，这是自欺，不是优化。
    """
    res = _res([], eliminated=13, no_feasible=True)
    disc = vr.scenario_discrimination(res, 13)
    cal = {"days_of_output": 2.0, "lead_margin": 1.6}
    assert vr._tune_one(cal, disc) is None
    assert cal == {"days_of_output": 2.0, "lead_margin": 1.6}


def test_warm_start_keeps_the_calibration_found_last_cycle():
    """15 分钟一轮，标定不能每轮从 1.15 重摸一遍。"""
    hot = vr.WEATHER_SCENARIOS[-1]["name"]
    seed = {hot: {"days_of_output": 4.0, "lead_margin": 1.45},
            "不存在的场景": {"days_of_output": 99.0, "lead_margin": 0.1},
            "坏值": "不是字典"}
    calib = vr._seed_calibration(seed, 6.0, 1.15)
    assert calib[hot] == {"days_of_output": 4.0, "lead_margin": 1.45}
    assert "不存在的场景" not in calib
    assert all(c["lead_margin"] <= vr.MARGIN_BOUNDS[1] and c["days_of_output"] <= vr.BATCH_BOUNDS[1]
               for c in calib.values())
    assert vr._seed_calibration({}, 6.0, 1.15)[hot] == {"days_of_output": 6.0, "lead_margin": 1.15}


def test_a_head_to_head_frontier_is_not_misread_as_a_tie():
    """两个各让一头的解，max_regret 都是 1.0 —— 拿它做差会恒等于 0，看着像"全并列"。

    真实数据集里就是这样：加急省钱的政策人力贵、开线的政策负载好，量错了就会
    一路去收紧交期，去制造"延不延期"的假区分度。
    """
    res = _res([{"labor_cost_usd": 0.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                 "load_band_gap": 1.0},
                {"labor_cost_usd": 1.0, "expedite_cost_usd": 1.0, "line_activation_cost_usd": 1.0,
                 "load_band_gap": 0.0}], frontier=2)
    disc = vr.scenario_discrimination(res, 2)
    assert disc["runner_up_regret_gap"] == 1.0      # 排序后悔向量第一位就不同
    assert disc["tied_with_recommended"] == 0

def test_truly_tied_solutions_are_reported_not_ordered():
    """后悔向量每一位都相同 = 并列，得说明"这轮没说哪个最好"，不许按列表顺序假装选出来。"""
    same = {"labor_cost_usd": 1.0, "expedite_cost_usd": 0.0}
    res = _res([same, dict(same), dict(same)], frontier=1)
    disc = vr.scenario_discrimination(res, 3)
    assert disc["runner_up_regret_gap"] is None and disc["feasible"] == 3
    cal = {"days_of_output": 6.0, "lead_margin": 1.15}
    assert vr._tune_one(cal, disc) is not None      # 并列 + 全可行 → 该收紧这一格了


def _scan_with(policy_name, scen_details, *, expedite_lead_days=None, parallel=1):
    """造一轮扫描：一个稳健政策在若干场景下每台单的推演明细。"""
    scen = {}
    for name, details in scen_details.items():
        scen[name] = {"attendance": 0.9, "solutions": [{
            "id": f"{name}-0", "name": policy_name, "scenario": name,
            "policy": {"expedite_lead_days": expedite_lead_days, "parallel_lines": parallel},
            "detail": details}]}
    return {"by_scenario": scen}, {"robust_recommendation": {"policy": policy_name}}


def test_recommendation_names_the_part_the_supplier_and_the_date():
    """政策要变成动作：哪个料号、向谁催、几号前下单、几号前要到。"""
    scan, verdict = _scan_with("加急到 10 天", {
        "暴雨": [{"model_code": "FG-TREAD-003", "units": 1800, "days_late": 0,
                 "material_arrival_day": 20, "due_date": "2026-11-06",
                 "finish_date": "2026-11-04", "line": "LINE-TREAD-01",
                 "batch_a_units": 600, "batch_b_units": 1200,
                 "bottleneck_part": {"material_code": "M-9001", "short": 1800,
                                     "lead_time_days": 20, "supplier": "VN-77",
                                     "unit_price": 3.5},
                 "blockers": []}]}, expedite_lead_days=10)
    acts = vr.recommendation_actions(scan, verdict, today=date(2026, 10, 6))
    exp = [a for a in acts if a["type"] == "expedite_purchase"]
    assert len(exp) == 1
    a = exp[0]
    assert a["material_code"] == "M-9001" and a["supplier"] == "VN-77"
    assert a["current_lead_days"] == 20 and a["target_lead_days"] == 10
    assert a["pulled_in_days"] == 10
    assert a["order_by_date"] == "2026-10-06"
    assert a["required_arrival_date"] == "2026-10-26"      # 到货日 = 推演里加急后的到货日
    assert a["sandbox_only"] is True
    assert [x["type"] for x in acts if x["model_code"] == "FG-TREAD-003"] == [
        "expedite_purchase", "start_first_batch", "schedule_second_batch_after_arrival"]
    second = [x for x in acts if x["type"] == "schedule_second_batch_after_arrival"][0]
    assert second["units"] == 1200 and second["not_before"] == "2026-10-26"
    assert second["not_before"] == a["required_arrival_date"]


def test_missing_supplier_becomes_a_data_action_not_an_invented_vendor():
    """没有供应商主数据就不许编一个厂商出来 —— 这类缺口卡的是数据，不是产能。"""
    scan, verdict = _scan_with("加急到 10 天", {
        "好天": [{"model_code": "X", "days_late": 0, "material_arrival_day": 15,
                 "bottleneck_part": {"material_code": "M-2", "short": 40,
                                     "lead_time_days": 15, "supplier": None},
                 "blockers": ["M-2 无提前期"]}]}, expedite_lead_days=5)
    acts = vr.recommendation_actions(scan, verdict, today=date(2026, 10, 6))
    kinds = {a["type"] for a in acts}
    assert "expedite_purchase" not in kinds and "supplier_master_missing" in kinds
    assert "master_data_gap" in kinds
    # 待办正文只放得下前几条：能办事的排前面，主数据缺口垫底
    assert [a["type"] for a in vr.recommendation_actions(scan, verdict, today=date(2026, 10, 6))][-1] \
        == "master_data_gap"


def test_actions_use_the_tightest_weather_scenario_not_the_pretty_one():
    """按好天的到货日下单，暴雨天就直接失约 —— 动作依据必须取最紧那个场景。"""
    easy = {"model_code": "X", "days_late": 0, "material_arrival_day": 10,
            "finish_date": "2026-10-20", "due_date": "2026-10-25",
            "bottleneck_part": {"material_code": "M-1", "short": 10,
                                "lead_time_days": 20, "supplier": "VN-1"},
            "batch_a_units": 0, "batch_b_units": 0, "blockers": []}
    hard = dict(easy, days_late=3, material_arrival_day=18, finish_date="2026-10-28")
    scan, verdict = _scan_with("加急到 10 天", {"好天（到岗 0.97）": [easy], "暴雨（到岗 0.70）": [hard]},
                               expedite_lead_days=10)
    acts = vr.recommendation_actions(scan, verdict, today=date(2026, 10, 6))
    a = [x for x in acts if x["type"] == "expedite_purchase"][0]
    assert a["scenario"].startswith("暴雨")
    assert a["required_arrival_date"] == "2026-10-24"       # 取的是最紧场景的到货日(第 18 天)
    assert a["pulled_in_days"] == 10


def test_no_robust_policy_no_actions():
    scan, verdict = _scan_with("加急", {"好天": []})
    verdict["robust_recommendation"] = None
    assert vr.recommendation_actions(scan, verdict) == []


def test_batch_actions_survive_for_every_model():
    """分批/开线这类动作没有"料号"身份，不能因为身份为空就被当成重复项吃掉。"""
    def detail(m, a_units, b_units):
        return {"model_code": m, "days_late": 0, "material_arrival_day": 12,
                "batch_a_units": a_units, "batch_b_units": b_units,
                "bottleneck_part": None, "blockers": ["RM-X 未标自制/外购"]}
    scan, verdict = _scan_with("现况", {"好天": [detail("M-1", 10, 90), detail("M-2", 20, 80)]})
    acts = vr.recommendation_actions(scan, verdict, today=date(2026, 10, 6))
    first = [a for a in acts if a["type"] == "start_first_batch"]
    assert {a["model_code"] for a in first} == {"M-1", "M-2"}
    gaps = [a for a in acts if a["type"] == "master_data_gap"]      # 同一个缺口跨台单要合并
    assert len(gaps) == 1 and sorted(gaps[0]["models"]) == ["M-1", "M-2"]
