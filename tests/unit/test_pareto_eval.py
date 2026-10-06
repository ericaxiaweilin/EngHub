"""权衡评估的口径：不许用"干脆不做"拿最优，也不许用一个牺牲另一维到离谱的解当推荐。

这一段是反过拟合的骨架，断言全部打在"考试思维会怎么作弊"上：
① 产量不达标直接淘汰（否则不开工永远是成本最优）；
② 帕累托前沿正确（不被任何解支配）；
③ 推荐规则是 min-max regret，加权和会被单维刷分骗到 —— 这里专门造一个那样的解来证明它选不出来。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services import pareto_eval as pe


def _sol(i, name=None, **objectives):
    return {"id": i, "name": name or str(i), "objectives": objectives, "evidence": {}}


ALL = list(pe.DIRECTIONS)


def test_dominance_is_over_all_objectives():
    a = _sol("a", on_time_rate=1.0, throughput_units=300, labor_cost_usd=100,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=0.9, peak_load_ratio=1.0)
    b = _sol("b", on_time_rate=1.0, throughput_units=300, labor_cost_usd=200,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=0.9, peak_load_ratio=1.0)
    assert pe.dominates(a, b, ALL) and not pe.dominates(b, a, ALL)
    # 各赢一维 → 互不支配，都该留在前沿上
    # 各赢一个**目标**维才叫互不支配（准点率/产量现在是约束，不再算目标）
    c = _sol("c", on_time_rate=1.0, throughput_units=300, labor_cost_usd=300,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0,
             load_band_gap=0.0, line_activation_cost_usd=0)
    assert pe.dominates(a, c, ALL)          # a 更便宜且别处不差 → a 支配 c
    d = _sol("d", on_time_rate=1.0, throughput_units=300, labor_cost_usd=300,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0,
             load_band_gap=0.0, line_activation_cost_usd=0)
    e = _sol("e", on_time_rate=1.0, throughput_units=300, labor_cost_usd=50,
             expedite_cost_usd=99, standby_person_days=0, data_confidence=1.0,
             load_band_gap=0.0, line_activation_cost_usd=0)
    assert not pe.dominates(d, e, ALL) and not pe.dominates(e, d, ALL)


def test_doing_nothing_is_eliminated_not_optimal():
    """"这单不开工"会让成本、闲置、加急全都最好看 —— 必须硬淘汰，不进比较。"""
    skip = _sol("skip", on_time_rate=0.0, throughput_units=0, labor_cost_usd=0,
                expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0, peak_load_ratio=0.0)
    work = _sol("work", on_time_rate=1.0, throughput_units=300, labor_cost_usd=5000,
                expedite_cost_usd=0, standby_person_days=10, data_confidence=0.9, peak_load_ratio=1.0)
    out = pe.evaluate([skip, work], demand_units=300, keys=ALL)
    assert [e["id"] for e in out["eliminated"]] == ["skip"]
    assert [f["id"] for f in out["frontier"]] == ["work"]
    assert out["recommended"]["id"] == "work"
    assert "不参与比较" in out["eliminated"][0]["eliminated_for"]


def test_recommended_balances_instead_of_maxing_one_dimension():
    """加权和会选"成本极低但延误严重"或"准点但烧钱堆出来"的那个；min-max regret 必须选中间解。"""
    cheap_late = _sol("cheap", "便宜但延", on_time_rate=0.0, throughput_units=300, labor_cost_usd=1000,
                      expedite_cost_usd=0, standby_person_days=0, data_confidence=0.9,
                      load_band_gap=3.0, line_activation_cost_usd=0)
    # 保准点的极端解靠"整班守着等料 + 疯狂加急 + 开第二条线"堆出来：三维全场最差
    perfect_costly = _sol("perfect", "堆出来的准点", on_time_rate=1.0, throughput_units=300,
                          labor_cost_usd=90000, expedite_cost_usd=80000, standby_person_days=60,
                          data_confidence=0.9, load_band_gap=0.0, line_activation_cost_usd=90000)
    middle = _sol("middle", "平衡解", on_time_rate=1.0, throughput_units=300, labor_cost_usd=12000,
                  expedite_cost_usd=3000, standby_person_days=20, data_confidence=0.9,
                  load_band_gap=1.2, line_activation_cost_usd=0)
    out = pe.evaluate([cheap_late, perfect_costly, middle], demand_units=300, keys=ALL)
    # 便宜但延期：直接淘汰 —— 交期不是可以拿成本换的评分项
    assert [e["id"] for e in out["eliminated"]] == ["cheap"]
    assert "合同约束" in out["eliminated"][0]["eliminated_for"]
    profiles = {f["id"]: tuple(sorted((f["regret_by_objective"] or {}).values(), reverse=True))
                for f in out["frontier"]}
    assert out["recommended"]["id"] == "middle"
    # 只剩两个可行解时，"最大后悔"必然都是 1.0（谁都有输的维度）——
    # 真正区分平衡与否的是整条后悔向量：perfect 在四维上同时最差，middle 只在开线费上一维
    assert sum(profiles["perfect"]) > sum(profiles["middle"])
    assert profiles["middle"] < profiles["perfect"]
    assert list(profiles["perfect"]).count(1.0) >= 3


def _s(scen, policy, on_time, cost, standby=0.0, expedite=0.0, load=0.0, line=0.0):
    return {"id": f"{scen}-{policy}", "name": policy, "scenario": scen,
            "objectives": {"on_time_rate": on_time, "throughput_units": 600,
                           "labor_cost_usd": cost, "expedite_cost_usd": expedite,
                           "standby_person_days": standby, "data_confidence": 0.9,
                           "load_band_gap": load, "line_activation_cost_usd": line},
            "evidence": {}}


def test_robust_pick_requires_covering_every_weather_scenario():
    """稳健推荐挑"好天到暴雨都不差"的政策；只在某个天气下好看的解不能当选。"""
    by_scenario = {
        "好天": {"solutions": [_s("好天", "赌好天", 1.0, 1000), _s("好天", "稳的", 1.0, 9000)]},
        "雨季": {"solutions": [_s("雨季", "赌好天", 0.0, 1000), _s("雨季", "稳的", 1.0, 9000)]},
        "暴雨": {"solutions": [_s("暴雨", "赌好天", 0.0, 1000), _s("暴雨", "稳的", 1.0, 9000)]},
    }
    out = pe.evaluate_by_scenario(by_scenario, demand_units=600, keys=ALL)
    assert out["robust_recommendation"]["policy"] == "稳的"
    # 被支配解也必须带后悔向量：空向量在字典序里"最小"，会把最差解选成最平衡（实测踩过）
    for name, res in out["by_scenario"].items():
        for row in res["frontier"] + res["dominated"]:
            assert row.get("regret_by_objective"), f"{name}/{row['name']} 没有后悔向量"


def test_hard_constraint_dims_are_named_not_silently_compared():
    """交期是硬约束后，准点率/延误天数在存活解里必然全同 —— 要明说它们退出了比较。"""
    keep = [dict(_sol("k1"), objectives={"on_time_rate": 1.0, "throughput_units": 600,
                                         "labor_cost_usd": 100, "expedite_cost_usd": 0,
                                         "standby_person_days": 0, "data_confidence": 0.9,
                                         "load_band_gap": 0.0, "line_activation_cost_usd": 0,
                                         "days_late_worst": 0}),
            dict(_sol("k2"), objectives={"on_time_rate": 1.0, "throughput_units": 600,
                                         "labor_cost_usd": 200, "expedite_cost_usd": 5,
                                         "standby_person_days": 3, "data_confidence": 0.9,
                                         "load_band_gap": 0.2, "line_activation_cost_usd": 10,
                                         "days_late_worst": 0})]
    out = pe.evaluate(keep, demand_units=600, keys=list(pe.DIRECTIONS))
    assert {"on_time_rate", "throughput_units"} <= set(out["absorbed_by_constraint"])
    assert out["recommended"]["id"] == "k1"          # 剩下按成本/加急/空档/负载/开线费比


def test_self_check_stays_silent_when_there_is_nothing_to_choose_between():
    """可行解只有 1~2 个时不许报"每个维度都可被刷"—— 那是样本不足，不是可刷分。"""
    one = [dict(_sol("only"), objectives={"on_time_rate": 1.0, "throughput_units": 600,
                                         "labor_cost_usd": 100, "expedite_cost_usd": 0,
                                         "standby_person_days": 0, "data_confidence": 0.9,
                                         "load_band_gap": 0.0, "line_activation_cost_usd": 0,
                                         "days_late_worst": 0}),
           dict(_sol("late"), objectives={"on_time_rate": 0.0, "throughput_units": 600,
                                         "labor_cost_usd": 50, "expedite_cost_usd": 0,
                                         "standby_person_days": 0, "data_confidence": 0.9,
                                         "load_band_gap": 0.0, "line_activation_cost_usd": 0,
                                         "days_late_worst": 9})]
    out = pe.evaluate(one, demand_units=600, keys=list(pe.DIRECTIONS))
    assert out["self_check"] == []
    assert any("可行解只剩" in n for n in out["notes"])


def test_unknown_objective_direction_is_rejected_not_defaulted():
    """目标名写错时必须报错。默认按 max 处理会把"越小越好"的维度反过来选。"""
    sols = [_s("好天", "a", 1.0, 1000), _s("好天", "b", 0.0, 2000)]
    with pytest.raises(KeyError):
        pe.evaluate(sols, demand_units=300, keys=["cost_is_honestly_lower_is_better"])


def test_solution_built_on_borrowed_evidence_is_flagged_not_recommended():
    """靠借来的路线/反推工时跑出来的漂亮解可以进前沿，但要写明依据薄、不能当推荐。"""
    solid = _sol("solid", on_time_rate=1.0, throughput_units=300, labor_cost_usd=20000,
                 expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0,
                 peak_load_ratio=1.0)
    solid["evidence"] = {"route_standard_hours": 3, "own_route": 3, "line_declared_can_make": 3}
    shaky = _sol("shaky", on_time_rate=1.0, throughput_units=300, labor_cost_usd=1000,
                expedite_cost_usd=0, standby_person_days=0, data_confidence=0.3,
                peak_load_ratio=1.0)
    shaky["evidence"] = {"borrowed_route_from_family": 3, "takt_from_line_capacity": 3,
                        "line_inferred_by_family_name": 3}
    out = pe.evaluate([solid, shaky], demand_units=300, keys=ALL)
    assert pe.assumption_share(shaky) == 1.0 and pe.assumption_share(solid) == 0.0
    assert out["recommended"]["id"] == "solid"       # 便宜的借用解不配被推荐
    assert shaky["id"] in [f["id"] for f in out["frontier"]]


def test_regret_is_normalized_per_objective():
    sols = [
        _sol("a", on_time_rate=1.0, throughput_units=300, labor_cost_usd=100,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0, peak_load_ratio=1.0),
        _sol("b", on_time_rate=0.0, throughput_units=300, labor_cost_usd=200,
             expedite_cost_usd=0, standby_person_days=0, data_confidence=1.0, peak_load_ratio=1.0),
    ]
    keys = ["labor_cost_usd", "expedite_cost_usd", "standby_person_days"]
    r = pe.regret_matrix(sols, keys)
    assert r["a"]["labor_cost_usd"] == 0.0 and r["b"]["labor_cost_usd"] == 1.0
    assert r["a"]["expedite_cost_usd"] == 0.0          # 同值目标后悔为 0
    # 准点率/产量已经不是目标维（它们是硬约束），写进 keys 会直接报错而不是被当成可优化的分
    with pytest.raises(KeyError):
        pe.regret_matrix(sols, ["on_time_rate"])


def _scenario(name, sols):
    return name, {"solutions": sols}


def test_robust_pick_requires_covering_every_weather_scenario():
    """稳健推荐要挑"好天到暴雨都不差"的政策；只在某一个天气下好看的解不能当选。"""
    def s(scen, policy, on_time, cost):
        return {"id": f"{scen}-{policy}", "name": policy, "scenario": scen,
                "objectives": {"on_time_rate": on_time, "throughput_units": 600,
                               "labor_cost_usd": cost, "expedite_cost_usd": 0,
                               "standby_person_days": 0, "data_confidence": 0.9,
                               "load_band_gap": 0.0, "line_activation_cost_usd": 0},
                "evidence": {}}
    good_weather_only = [s("好天", "赌好天", 1.0, 1000), s("雨季", "赌好天", 0.0, 1000), s("暴雨", "赌好天", 0.0, 1000)]
    steady = [s("好天", "加急+开线", 1.0, 9000), s("雨季", "加急+开线", 1.0, 9000), s("暴雨", "加急+开线", 1.0, 9000)]
    by_scenario = {}
    for block in (good_weather_only, steady):
        grouped = {}
        for sol in block:
            grouped.setdefault(sol["scenario"], []).append(sol)
        for name, sols in grouped.items():
            by_scenario.setdefault(name, {"solutions": []})["solutions"].extend(sols)
    out = pe.evaluate_by_scenario(by_scenario, demand_units=600, keys=ALL)
    assert out["robust_recommendation"]["policy"] == "加急+开线"
    # 被支配解也必须带后悔向量，否则空向量会在字典序里"最小"，把最差的解选成最平衡（实测踩过）
    for name, res in out["by_scenario"].items():
        for row in res["frontier"] + res["dominated"]:
            assert row.get("regret_by_objective"), f"{name}/{row['name']} 没有后悔向量"


def test_empty_input_does_not_invent_a_recommendation():
    out = pe.evaluate([], demand_units=300, keys=ALL)
    assert out["recommended"] is None and out["frontier"] == []
