"""敏感度与映射精度的算数：斜率取局部两档、误差要传导成天数、不敏感要说明原因。

这一层是"引擎对自己的输出有多可信"的回答，所以断言全部打在算式上，不依赖真库。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services import sim_sensitivity as ss


def _curve():
    return [{"level": 1.0, "finish_date": "2026-11-03", "days_vs_base": 0, "labor_delta_usd": 0.0,
             "on_time_models": 0, "is_base": True},
            {"level": 0.9, "finish_date": "2026-11-01", "days_vs_base": -2, "labor_delta_usd": -1000.0,
             "on_time_models": 2},
            {"level": 1.5, "finish_date": "2026-11-13", "days_vs_base": 10, "labor_delta_usd": 9000.0,
             "on_time_models": 0}]


def test_slope_is_local_not_a_global_average():
    """全局回归会把阶跃曲线抹成一个假平均数：只取基准两侧最近那一档。"""
    lever = {"label": "外购提前期", "step": 0.1, "base": 1.0}
    out = ss.slope_per_step(_curve(), lever, 1.0)
    # 一律读成"加大一档会怎样"：有上档就用上档，符号不再随两边档位翻来覆去
    assert out["computable"] and out["measured_between"] == [1.0, 0.9]   # 取离基准最近那档
    assert out["days_per_step"] == 2.0             # 提前期每 +10% → 晚 2 天（下档差值换算成 +方向）
    assert out["on_time_models_per_step"] == -2.0  # 每 +10% → 少 2 台准点
    assert out["money_per_day_saved"] == 500.0
    # 这条测试曲线是线性的：局部与拟合应当一致，不能虚报"台阶型"
    assert out["nonlinear"] is False and out["days_per_step_fit"] == 2.0


def test_stepwise_curve_is_flagged_so_nobody_extrapolates_it():
    """提前期那类曲线是台阶：压到跨过到货门槛那一档才跳几天，平均值会低报。"""
    rows = [{"level": 1.0, "finish_date": "2026-11-19", "days_vs_base": 0, "labor_delta_usd": 0.0,
             "on_time_models": 0, "is_base": True},
            {"level": 0.9, "finish_date": "2026-11-19", "days_vs_base": 0, "labor_delta_usd": 0.0,
             "on_time_models": 0},
            {"level": 0.75, "finish_date": "2026-11-03", "days_vs_base": -16, "labor_delta_usd": 0.0,
             "on_time_models": 4}]
    lever = {"label": "外购提前期", "step": 0.1, "base": 1.0}
    out = ss.slope_per_step(rows, lever, 1.0)
    assert out["days_per_step"] == 0.0                      # 近处那一档一动不动
    assert out["steepest_days_per_step"] == 6.4             # 跨过门槛那档才跳
    assert out["days_per_step_fit"] == 5.517                 # 平均数会低报跨门槛的收益
    assert out["nonlinear"] is True and out["steepest_at_level"] == 0.75
    assert "台阶" in out["shape_note"]
    meta = {"label": "外购提前期", "step": 0.1}
    txt = ss._reads_as(meta, out)
    assert "台阶" in txt and "跨不过" not in txt and "0.75" in txt


def test_slope_refuses_when_base_missing():
    lever = {"label": "到岗率", "step": 0.05, "base": 0.97}
    rows = [{"level": 0.7, "finish_date": "2026-11-12", "days_vs_base": 9, "labor_delta_usd": 0.0}]
    out = ss.slope_per_step(rows, lever, 0.97)
    assert out["computable"] is False and "基准档" in out["why"]


def test_uncertainty_converts_error_band_into_days():
    """允许误差 ±30% 的工时，斜率每 10% 值 2 天 → 交期不确定 ±6 天；补到 ±5% 就只剩 1 天。"""
    sens = {"base": {"binding": "ie_hours"}, "levers": [
        {"key": "hours_multiplier", "slope": {"days_per_step": 2.0}},
        {"key": "lead_multiplier", "slope": {"days_per_step": 1.0}}]}
    acc = {"models": [{"model_code": "M-1", "accuracy_score": 60.0, "hours_error_band": 0.30,
                       "components": {"hours": {"score": 0.35}, "lead_time": {"score": 0.4}}}]}
    out = ss.propagate_uncertainty(sens, acc)
    m = out["per_model"][0]
    now = {i["input"]: i for i in m["items"]}
    assert now["单件工时"]["uncertainty_days_now"] == 6.0
    assert now["单件工时"]["uncertainty_days_after"] == 1.0
    assert now["外购提前期"]["uncertainty_days_now"] == 6.0      # 覆盖率 40% → 误差按 60% 算
    assert m["uncertainty_days_sum"] == 12.0
    assert out["value_of_repair"][0]["days_removed"] > 0


def test_insensitive_input_explains_why_instead_of_looking_safe():
    """斜率为 0 时必须说清是"这项数据当前不进约束"，不能让它读成"这项数据不重要"。"""
    sens = {"base": {"binding": "line_declared"}, "levers": [
        {"key": "hours_multiplier", "slope": {"days_per_step": 0.0}},
        {"key": "lead_multiplier", "slope": {"computable": False}}]}
    acc = {"models": [{"model_code": "M-1", "accuracy_score": 73.0, "hours_error_band": 0.30,
                       "components": {"hours": {"score": 0.35}, "lead_time": {"score": 1.0}}}]}
    m = ss.propagate_uncertainty(sens, acc)["per_model"][0]
    assert m["insensitive_inputs"] and "瓶颈工位" in m["insensitive_inputs"][0]["because"]
    assert m["uncertainty_days_sum"] == 0


def test_accuracy_weights_sum_to_one():
    assert abs(sum(ss.ACCURACY_WEIGHTS.values()) - 1.0) < 1e-9


def test_every_lever_has_a_base_and_a_step():
    for lever in ss.LEVERS:
        assert lever["step"] > 0 and lever["levels"]
        if lever["kind"] in ("ratio", "batch", "margin", "policy"):
            assert lever.get("base") is not None or lever["kind"] == "policy"


def test_interaction_classifies_additive_substitutable_and_complementary():
    """两把钥匙开同一把锁 → 第二个白花钱，这条必须能被分类出来。"""
    kind, reading = ss.classify_interaction(0.0, 6.0, 0.0)
    assert kind == "additive" and "分开算" in reading
    kind, reading = ss.classify_interaction(-2.0, 6.0, 2.0)
    assert kind == "substitutable" and "白花" in reading
    kind, reading = ss.classify_interaction(3.0, 0.0, 0.0)
    assert kind == "complementary" and "前提" in reading
    # 一天以内的差值不解读：这套台账的分辨率不支持把它当成"互补"
    assert ss.classify_interaction(0.4, 5.0, 5.0)[0] == "additive"


def test_pairwise_scan_reads_joint_effect_off_the_same_path_as_solo(monkeypatch):
    """Δ(AB) 必须与 Δ(A)、Δ(B) 走同一条推演路（scan_policies），不能另建一套算法。"""
    import asyncio

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": m, "units": 1800, "due_in_days": 23} for m in models]

    # 真实关系：卡的是料 —— 压提前期买 9 天，加班买 0 天，一起上还是 9 天
    table = {
        "": {"days_late_worst": 9.0, "labor_cost_usd": 100000.0, "expedite_cost_usd": 0.0,
             "line_activation_cost_usd": 0.0, "finish_date": "2026-11-21", "binding": "line_declared"},
        "expedite": {"days_late_worst": 0.0, "labor_cost_usd": 100000.0, "expedite_cost_usd": 6030.0,
                     "line_activation_cost_usd": 0.0, "finish_date": "2026-11-12", "binding": "line_declared"},
        "crew": {"days_late_worst": 9.0, "labor_cost_usd": 131428.0, "expedite_cost_usd": 0.0,
                 "line_activation_cost_usd": 0.0, "finish_date": "2026-11-21", "binding": "line_declared"},
        "parallel": {"days_late_worst": 9.0, "labor_cost_usd": 100000.0, "expedite_cost_usd": 0.0,
                     "line_activation_cost_usd": 8730.0, "finish_date": "2026-11-21", "binding": "line_declared"},
        "expedite+crew": {"days_late_worst": 0.0, "labor_cost_usd": 131428.0, "expedite_cost_usd": 6030.0,
                          "line_activation_cost_usd": 0.0, "finish_date": "2026-11-12", "binding": "line_declared"},
        "expedite+parallel": {"days_late_worst": 0.0, "labor_cost_usd": 100000.0, "expedite_cost_usd": 6030.0,
                              "line_activation_cost_usd": 8730.0, "finish_date": "2026-11-12", "binding": "line_declared"},
        "crew+parallel": {"days_late_worst": 9.0, "labor_cost_usd": 131428.0, "expedite_cost_usd": 0.0,
                          "line_activation_cost_usd": 8730.0, "finish_date": "2026-11-21", "binding": "line_declared"},
    }

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        keys = []
        if policy.get("expedite_lead_days"):
            keys.append("expedite")
        if policy.get("crew_bonus"):
            keys.append("crew")
        if int(policy.get("parallel_lines") or 1) > 1:
            keys.append("parallel")
        return dict(table["+".join(keys)])

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    out = asyncio.run(ss.interactions(None, "FAC_MECH_001", ["A-50-04-F"]))

    assert out["base"]["days_late_worst"] == 9.0
    solo = out["solo"]
    assert solo["expedite_lead_days"]["days_saved"] == 9.0
    assert solo["crew_bonus"]["days_saved"] == 0.0
    assert solo["parallel_lines"]["cost_usd"] == 8730.0
    pairs = {p["pair"]: p for p in out["pairs"]}
    ec = next(p for k, p in pairs.items() if "提前期" in k and "加班" in k)
    assert ec["joint_days_saved"] == 9.0 and ec["interaction_days"] == 0.0
    assert ec["relation"] == "additive"
    # 加班单独上白花 $31,428：这条要在读数里看得见，不能只剩一个 0
    assert ec["cost_usd"]["b"] == 31428.0
    cp = next(p for k, p in pairs.items() if "加班" in k and "并联" in k)
    assert cp["interaction_days"] == 0.0 and cp["cost_usd"]["joint_minus_sum"] == 0.0


def test_interaction_levers_only_use_keys_the_same_path_accepts():
    import inspect

    from api.services.virtual_run import run_target

    accepted = set(inspect.signature(run_target).parameters)
    for lever in ss.INTERACTION_LEVERS:
        assert lever["on"] and lever.get("buys")
        assert set(lever["on"]) <= accepted, f"{lever['key']} 的开关不是 run_target 的参数"


def test_every_interaction_lever_has_a_business_name_for_the_contract():
    """契约只按受控词表出去：对不上业务名的杠杆会被整条丢掉，宁可事先知道。"""
    from api.services.engine_contract import INPUTS, _public_input_for

    for lever in ss.INTERACTION_LEVERS:
        pub = _public_input_for(str(lever["key"]))
        assert pub, f"{lever['label']} 没有业务输入名，进不了 /engine-sensitivity"
        assert pub in INPUTS, f"{pub} 不在受控词表里"


def test_interaction_rows_carry_internal_keys_for_the_public_mapping(monkeypatch):
    """pair 只带中文名就没法映射成业务名 —— keys 字段是契约那一层的唯一依据。"""
    import asyncio

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 5}]

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        return {"days_late_worst": 3.0, "labor_cost_usd": 100.0, "expedite_cost_usd": 0.0,
                "line_activation_cost_usd": 0.0, "finish_date": "2026-01-10",
                "binding": "line_declared"}

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    out = asyncio.run(ss.interactions(None, "FAC", ["M-1"]))
    assert out["pairs"], "三对组合都该有读数"
    known = {str(l["key"]) for l in ss.INTERACTION_LEVERS}
    for p in out["pairs"]:
        assert p["status"] == "ok" and set(p["keys"]) <= known and len(p["keys"]) == 2


def test_schedule_risk_is_reproducible_and_reports_percentiles_not_a_point(monkeypatch):
    """同一个种子必须重算出同一条分布，否则这条 P90 不可核对。"""
    import asyncio

    dates = ["2026-11-21", "2026-11-24", "2026-11-18", "2026-11-30"]

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    calls = {"n": 0}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        calls["n"] += 1
        idx = calls["n"] % len(dates)
        late = 0.0 if idx == 2 else float(idx * 3)
        return {"finish_date": dates[idx], "days_late_worst": late,
                "on_time_rate": 1.0 if late <= 0 else 0.0, "labor_cost_usd": 1000.0,
                "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "first_batch_units": 10, "queued_units": 0}

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 73.0, "hours_error_band": 0.30,
                            "components": {"lead_time": {"score": 1.0}, "hours": {"score": 0.35}}}]}

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss.vr, "equipment_rate", fake_equip)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)

    calls["n"] = 0
    first = asyncio.run(ss.schedule_risk(None, "FAC", ["M-1"], samples=12, seed=7))
    calls["n"] = 0
    again = asyncio.run(ss.schedule_risk(None, "FAC", ["M-1"], samples=12, seed=7))
    assert first["status"] == "ok" and first["with_date"] == 12
    assert [p["finish_date"] for p in first["percentiles"]] == [p["finish_date"] for p in again["percentiles"]]
    assert first["p_on_time"] == again["p_on_time"]
    pcs = {p["percentile"]: p["finish_date"] for p in first["percentiles"]}
    assert pcs[10] <= pcs[50] <= pcs[90]
    assert first["promise_date"] <= pcs[50] or first["p_on_time"] == 0
    assert first["bands_used"]["purchase_lead_time"] == 0.2 and first["bands_used"]["unit_work_hours"] == 0.3
    assert "只报 P50" in first["how_to_quote"]
    assert first["reading"] and "P90" in first["reading"]


def test_schedule_risk_says_no_dates_instead_of_inventing_a_distribution(monkeypatch):
    import asyncio

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        return {"finish_date": None, "binding": "no_time_basis", "days_late_worst": None,
                "labor_cost_usd": 0.0, "on_time_rate": None}

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "hours_error_band": 0.3,
                            "components": {"lead_time": {"score": 1.0}}}]}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    out = asyncio.run(ss.schedule_risk(None, "FAC", ["M-1"], samples=6))
    assert out["status"] == "no_dates" and "给不出分布" in out["why"]
    assert out["bindings_seen"] == ["no_time_basis"]


def test_lead_error_band_is_one_source_for_sampling_and_for_propagation():
    """抽样带宽与误差传导必须同一个出处，不然两处各说一个 ±%。"""
    assert ss.lead_error_band(1.0) == 0.20
    assert ss.lead_error_band(0.8) == 0.20
    assert ss.lead_error_band(0.5) == 0.50
    assert ss.lead_error_band(0.0) == 1.0


def test_sensitivity_chat_answer_carries_interactions_and_the_distribution():
    from api.routes.chat_routes import _format_sensitivity_reply

    result = {"status": "ok", "has_data": True, "factory_id": "FAC_MECH_001",
              "models": ["A-50-04-F", "FG-BIKE-003"],
              "base": {"finish_date": "2026-11-21", "days_late_worst": 21.0, "on_time_rate": 0.0,
                       "labor_cost_usd": 314280.0, "expedite_cost_usd": 0.0,
                       "line_activation_cost_usd": 0.0, "binding": "line_declared"},
              "levers": [{"lever": "外购提前期", "slope": {"computable": True, "days_per_step": 0.8,
                                                          "money_per_day_saved": 2070.0,
                                                          "on_time_models_per_step": -0.4,
                                                          "nonlinear": True, "steepest_days_per_step": 2.2,
                                                          "steepest_at_level": 1.5}},
                         {"lever": "单件工时", "slope": {"computable": True, "days_per_step": 0.0}}],
              "lever_interactions": [{"pair": "压瓶颈件提前期 × 加班加人 30%", "solo_days_saved": 4.0,
                                      "solo_days_saved_other": 0.0, "joint_days_saved": 4.0,
                                      "interaction_days": 0.0, "relation": "additive",
                                      "extra_cost_usd": 110844.0,
                                      "reading": "两个杠杆各解各的，钱可以分开算"}],
              "schedule_risk": {"status": "ok", "reading": "48 抽 48 次有完工日：P50=2026-11-21、P90=2026-11-27",
                                "percentiles": [{"percentile": 10, "finish_date": "2026-11-19"},
                                                {"percentile": 50, "finish_date": "2026-11-21"},
                                                {"percentile": 90, "finish_date": "2026-11-27"}],
                                "bands_used": {"purchase_lead_time": 0.2, "unit_work_hours": 0.3}},
              "risk_not_sampled_because": None,
              "accuracy_overall": 71.6, "method": "斜率只取基准两侧最近两档",
              "uncertainty": [{"model_code": "M-1", "uncertainty_days_sum": 1.6,
                               "uncertainty_days_after_repair": 0.4}]}
    text = _format_sensitivity_reply(result)
    assert "组合完工 2026-11-21" in text and "卡在 line_declared" in text
    assert "每档 0.8 天" in text and "台阶型" in text
    assert "动不了的输入：单件工时" in text
    assert "交互 0.0 天" in text and "各解各的" in text
    assert "交期分布" in text and "2026-11-27" in text and "这段就是毛边" in text
    assert "映射精度：71.6" in text
    assert "没抽" not in text


def test_cost_per_day_counts_expedite_and_activation_not_labor_only():
    """只按人工折算会把加急费说成 $0/天 —— 贵的东西被读成免费的。"""
    lever = {"label": "外购提前期", "step": 0.1, "base": 1.0}
    rows = [
        {"level": 1.0, "finish_date": "2026-01-11", "days_vs_base": 0, "labor_delta_usd": 0.0,
         "expedite_delta_usd": 0.0, "activation_delta_usd": 0.0, "on_time_models": 3},
        {"level": 0.9, "finish_date": "2026-01-09", "days_vs_base": -2, "labor_delta_usd": 0.0,
         "expedite_delta_usd": -600.0, "activation_delta_usd": 0.0, "on_time_models": 5},
    ]
    out = ss.slope_per_step(rows, lever, 1.0)
    assert out["days_per_step"] == 2.0
    assert out["labor_usd_per_step"] == 0.0
    assert out["cost_usd_per_step"] == 600.0
    assert out["money_per_day_saved"] == 300.0     # 每提前一天花 $300，而不是 $0


def test_free_data_band_step_is_not_reported_as_a_free_purchase():
    """提前期倍数那一档买到天数但不花钱 —— 因为它改的是数据带宽，不是加急单。"""
    lever = {"label": "外购提前期", "key": "lead_multiplier", "step": 0.1, "base": 1.0}
    rows = [
        {"level": 1.0, "finish_date": "2026-01-11", "days_vs_base": 0, "labor_delta_usd": 0.0,
         "expedite_delta_usd": 0.0, "activation_delta_usd": 0.0, "on_time_models": 3},
        {"level": 0.9, "finish_date": "2026-01-09", "days_vs_base": -2, "labor_delta_usd": 0.0,
         "expedite_delta_usd": 0.0, "activation_delta_usd": 0.0, "on_time_models": 5},
    ]
    out = ss.slope_per_step(rows, lever, 1.0)
    assert out["cost_usd_per_step"] == 0.0
    assert "数据" in out["cost_note"] and "加急" in out["cost_note"]
    # 真掏钱的那一档（并联开线）不能被这条注释洗白
    paid = {"label": "并联开线", "key": "parallel_lines", "step": 1.0, "base": 1.0}
    rows2 = [
        {"level": 1.0, "finish_date": "2026-01-11", "days_vs_base": 0, "labor_delta_usd": 0.0,
         "expedite_delta_usd": 0.0, "activation_delta_usd": 0.0, "on_time_models": 3},
        {"level": 2.0, "finish_date": "2026-01-06", "days_vs_base": -5, "labor_delta_usd": 0.0,
         "expedite_delta_usd": 0.0, "activation_delta_usd": 8730.0, "on_time_models": 4},
    ]
    assert ss.slope_per_step(rows2, paid, 1.0)["cost_note"] is None


def test_against_policies_are_sampled_on_the_same_draws_not_two_independent_runs(monkeypatch):
    """比两条政策必须同序配对：各抽各的分位数相减，会把抽样噪声算成政策功效。"""
    import asyncio
    from datetime import date, timedelta

    base_lates = [20.0, 23.0, 38.0, 21.0]
    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "hours_error_band": 0.3,
                            "components": {"lead_time": {"score": 1.0}}}]}

    calls = []

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        calls.append((str(policy.get("name")), attendance, perturb["lead_multiplier"]))
        late = (base_lates[calls.count(("现况", attendance, perturb["lead_multiplier"])) - 1]
                if policy.get("name") == "现况" else base_lates[len(calls) // 2 % 4] - 5.0)
        due = date(2026, 1, 1) + timedelta(days=23)
        return {"finish_date": str(due + timedelta(days=int(late))), "days_late_worst": late,
                "labor_cost_usd": 1000.0,
                "expedite_cost_usd": (0.0 if policy.get("name") == "现况" else 6030.0),
                "line_activation_cost_usd": 0.0, "binding": "material_arrival"}

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss.vr, "equipment_rate", fake_equip)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)

    out = asyncio.run(ss.schedule_risk(
        None, "FAC", ["M-1"], samples=8, seed=3,
        policy={"name": "现况", "allow_partial": True},
        against=[{"name": "加急到 7 天", "expedite_lead_days": 7}]))
    assert out["status"] == "ok"
    assert len(out["against"]) == 1
    alt = out["against"][0]
    assert alt["status"] == "ok" and alt["settings"] == {"expedite_lead_days": 7}
    p = alt["paired"]
    assert p["computable"] and p["paired_draws"] == 8
    # 同序：每一抽的抽样工况一模一样，只有政策不同
    seq_base = [c[1:] for c in calls if c[0] == "现况"]
    seq_alt = [c[1:] for c in calls if c[0] == "加急到 7 天"]
    assert seq_base == seq_alt, "两条政策必须共用同一串抽样"
    assert p["days_saved_median"] > 0 and p["median_extra_cost_usd"] == 6030.0
    assert "同序配对" in alt["headline"] and "每省一天" in alt["headline"]


def test_schedule_risk_rejects_a_malformed_against_list(monkeypatch):
    """against 只能按 JSON 数组传；传错了要 422 点名，不能悄悄当成"没有对照"。"""
    import asyncio

    from fastapi import HTTPException

    from api.routes.pmc_routes import get_sim_schedule_risk

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "hours_error_band": 0.3,
                            "components": {"lead_time": {"score": 1.0}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        return {"finish_date": "2026-01-20", "days_late_worst": 5.0, "labor_cost_usd": 1.0,
                "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0, "binding": "line_declared"}

    async def fake_default_models(db, fid, n=5):
        return ["M-1"]

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss.vr, "equipment_rate", fake_equip)
    monkeypatch.setattr(ss.vr, "default_models", fake_default_models)   # 路由里那句 import 在调用时才解析
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)

    async def call(against_value):
        return await get_sim_schedule_risk("FAC", n_models=1, samples=6, seed=1,
                                           against=against_value, lead_center=None,
                                           db=None, current_user=None)

    for bad in ("{不是JSON}", '[1,2]', '"加急"'):
        try:
            asyncio.run(call(bad))
            raise AssertionError(f"坏输入被放过了：{bad}")
        except HTTPException as exc:
            assert exc.status_code == 422 and "against" in str(exc.detail)

    ok = asyncio.run(call('[{"name":"加急到 7 天","expedite_lead_days":7}]'))
    assert ok["status"] == "ok" and len(ok["against"]) == 1
    empty = asyncio.run(call(""))
    assert empty["status"] == "ok" and empty["against"] == []


def test_rescale_draws_narrows_only_the_named_band_around_its_own_center():
    """配对的前提：改一条带宽时，另外几条必须逐抽一字不动，中心也不能漂。"""
    draws = ss._risk_draws(8, 99, lead_band=0.6, hours_band=0.4, base_equip=0.8)
    out = ss._rescale_draws(draws, 0.8, narrowed={"purchase_lead_time": 0.5})
    assert len(out) == len(draws)
    for a, b in zip(draws, out):
        assert b["hours_multiplier"] == a["hours_multiplier"], "工时那一维不能跟着动"
        assert b["equip_rate"] == a["equip_rate"] and b["attendance"] == a["attendance"]
        assert b["lead_multiplier"] == round(1.0 + 0.5 * (a["lead_multiplier"] - 1.0), 4), \
            "偏移要按精确比例收窄到代码那 4 位小数，中心不许漂"
    assert out != draws, "没改动就说明 narrowed 没接上"


def test_rescale_draws_anchors_equipment_at_the_measured_rate_and_attendance_at_the_median():
    draws = ss._risk_draws(9, 7, lead_band=0.2, hours_band=0.2, base_equip=0.8)
    eq = ss._rescale_draws(draws, 0.8, narrowed={"equipment_availability": 0.0})
    assert all(d["equip_rate"] == 0.8 for d in eq), "归零必须回到台账实测率，不是回到 1.0"
    at = ss._rescale_draws(draws, 0.8, narrowed={"crew_attendance": 0.0})
    assert len({d["attendance"] for d in at}) == 1
    assert list({d["attendance"] for d in at})[0] == 0.92, "三档的中位是 0.92，不是均值"


def test_repair_floors_come_from_the_same_declared_sources_as_the_sampling_bands():
    """下限不许另立一套：提前期用 lead_error_band 的底线、工时用 IE 声明工时那条带。"""
    floors = {t["input"]: t["floor_band"] for t in ss.DATA_REPAIR_TARGETS}
    assert floors["purchase_lead_time"] == ss.lead_error_band(1.0)
    assert floors["unit_work_hours"] == ss.ERROR_BAND["route_standard_hours"]
    assert floors["crew_attendance"] == 0.0
    assert not [t for t in ss.DATA_REPAIR_TARGETS if t["repairable"]
                and t["input"] not in ss.BAND_KEY], "可修的因子必须抽得到"


def _fake_env(monkeypatch, *, lead_score=0.3, hours_band=0.30):
    """造一个只有提前期真的卡住工时的世界：修提前期该窄，修工时该白花。"""
    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 60.0,
                            "hours_error_band": hours_band,
                            "components": {"lead_time": {"score": lead_score},
                                           "hours": {"score": 0.5, "basis": "route_standard_hours"}}}]}

    seen = {"draws": []}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        p = perturb or {}
        seen["draws"].append(dict(p))
        days = round(60.0 * float(p.get("lead_multiplier", 1.0)), 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(days))),
                "days_late_worst": days - 45.0, "labor_cost_usd": 1000.0,
                "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival"}

    monkeypatch.setattr(ss.vr, "derive_targets", fake_targets)
    monkeypatch.setattr(ss.vr, "equipment_rate", fake_equip)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    return seen


def test_data_repair_experiment_prices_each_band_in_narrowed_days(monkeypatch):
    import asyncio

    _fake_env(monkeypatch, lead_score=0.3)      # 覆盖率 30% → 提前期带宽 ±0.70，远高于 ±0.20 下限
    out = asyncio.run(ss.data_repair_experiment(None, "FAC", ["M-1"], samples=16, seed=11))
    assert out["status"] == "ok"
    by = {r["input"]: r for r in out["repairs"]}
    assert by["purchase_lead_time"]["band_now"] == 0.7
    assert by["purchase_lead_time"]["band_after"] == ss.lead_error_band(1.0)
    assert by["purchase_lead_time"]["gap_days_narrowed"] > 0, "提前期修准必须真把毛边窄下来"
    assert by["unit_work_hours"]["status"] == "ok"
    assert by["unit_work_hours"]["gap_days_narrowed"] == 0.0, "工时不 binding 就不能报成值钱"
    assert by["crew_attendance"]["status"] == "not_repairable"
    assert out["first_fix"]["input"] == "purchase_lead_time"
    dec = out["decomposition"]
    assert 0 < dec["repairable_gap_days"] <= dec["gap_days_now"]
    assert dec["not_repairable_gap_days"] == out["all_repaired"]["p90_p50_gap_days"]
    assert any("先修哪条（按窄下来的天数排序）" in x for x in out["reading"])
    assert any("毛边构成" in x for x in out["reading"])
    assert "修数据只把毛边变窄" in out["claim_guard"]


def test_data_repair_experiment_is_paired_on_one_draw_stream_not_rerolled_dice(monkeypatch):
    import asyncio

    seen = _fake_env(monkeypatch, lead_score=0.3)
    out = asyncio.run(ss.data_repair_experiment(None, "FAC", ["M-1"], samples=12, seed=5))
    n = out["samples"]
    base_block = seen["draws"][:n]
    lead_block = seen["draws"][n:2 * n]
    assert [d["hours_multiplier"] for d in base_block] == [d["hours_multiplier"] for d in lead_block]
    assert all(abs(l["lead_multiplier"] - 1.0) <= ss.lead_error_band(1.0) + 1e-9 for l in lead_block), \
        "修过的那一档必须整串落在下限带宽里"
    again = asyncio.run(ss.data_repair_experiment(None, "FAC", ["M-1"], samples=12, seed=5))
    assert again["reading"] == out["reading"], "同种子必须能重算核对"


def test_data_repair_experiment_refuses_to_rank_when_no_repair_narrows_anything(monkeypatch):
    """空集合不许报成"先修哪条：修完了"：测过但没用要说清是约束不 binding，不是数据已齐。"""
    import asyncio

    _fake_env(monkeypatch, lead_score=1.0, hours_band=0.05)
    out = asyncio.run(ss.data_repair_experiment(None, "FAC", ["M-1"], samples=10, seed=3))
    by = {r["input"]: r for r in out["repairs"]}
    assert by["purchase_lead_time"]["status"] == "already_at_floor"
    assert by["unit_work_hours"]["status"] == "already_at_floor"
    assert out["first_fix"] is None
    line = [x for x in out["reading"] if "先修哪条" in x][0]
    assert "没有一条数据能压掉毛边" in line and "已经在下限的" in line
    dec = out["decomposition"]
    assert dec["gap_change_if_all_repaired"] == 0.0, "只有设备能动而设备不 binding → 一天也压不出"
    assert dec["repairable_gap_days"] == 0.0 and dec["wider_by_days_if_all_repaired"] == 0.0
    assert dec["not_repairable_gap_days"] == dec["gap_days_now"]
    assert any("一天没窄" in x for x in out["reading"]), "合修那格要如实报没窄，不许给比例"
    assert any("这些带宽各自量的是什么" in x and "铺进去的默认值也算有数" in x for x in out["reading"]), \
        "覆盖率 100% 不等于量过 —— 这句口径必须随读数一起出去"


def test_data_repair_experiment_says_no_repair_instead_of_inventing_one(monkeypatch):
    import asyncio

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 0.0, "hours_error_band": 0.4,
                            "components": {"lead_time": {"score": 0.0}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        return {"finish_date": None, "days_late_worst": None, "binding": "no_material"}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)

    out = asyncio.run(ss.data_repair_experiment(None, "FAC", ["M-1"], samples=8, seed=1))
    assert out["status"] == "no_dates" and out["repairs"] == [] and out["first_fix"] is None
    assert any("没跑成" in x for x in out["reading"])


def test_data_repair_chat_answer_names_the_first_fix():
    """聊天那一屏必须把"先修哪条"渲染出来，否则引擎算了但没人看得见。"""
    from api.routes.chat_routes import _format_sensitivity_reply

    res = {"factory_id": "FAC", "models": ["M-1"], "has_data": True,
           "base": {"finish_date": "2026-11-27", "days_late_worst": 9.0, "on_time_rate": 0.0,
                    "binding": "material_arrival"}, "data_repair": {
        "status": "ok", "samples": 16, "seed": 11,
        "reading": ["毛边构成：16 抽 P50=2026-11-26、P90=2026-12-05 → 毛边 9 天（跨度 14 天）、准点概率 0%",
                    "可修/不可修：三条可修数据同时到下限 → 毛边 9 天收窄到 3 天，其中 6.0 天是数据能修的（占 67%），"
                    "剩下 3 天修台账不动它（到岗真实波动+约束本身）",
                    "先修哪条（按窄下来的天数排序）：外购提前期逐料号实测（带宽 ±0.70→±0.20，毛边窄 6 天、"
                    "准点 +12.5pp）",
                    "这一条的依据：把请购→到货的实测提前期按料号回填，替掉铺进去的默认值｜"
                    "覆盖率≥80% 时 lead_error_band 的底线就是 ±20%"],
        "first_fix": {"label": "外购提前期逐料号实测", "gap_days_narrowed": 6.0,
                      "on_time_uplift_pp": 12.5, "band_now": 0.7, "band_after": 0.2,
                      "how": "把请购→到货的实测提前期按料号回填", "p_on_time_after": 0.125},
        "decomposition": {"gap_days_now": 9, "not_repairable_gap_days": 3,
                          "repairable_gap_days": 6.0, "meaning": "剩下的 3 天不是数据"}}}
    text = _format_sensitivity_reply(res)
    assert "先修哪条（按窄下来的天数排序）：外购提前期逐料号实测" in text
    assert "毛边窄 6 天" in text and "毛边构成" in text and "把请购→到货的实测提前期" in text

    no_repair = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
                 "data_repair": {"status": "no_dates", "why": "抽到的每一轮都推不出完工日", "reading": []}}
    refuse = _format_sensitivity_reply(no_repair)
    assert "没跑成 —— 抽到的每一轮都推不出完工日" in refuse
    assert "先修哪条" not in refuse, "没跑成就不许摆出一张优先级"



def test_metrics_exposes_the_crew_it_actually_used():
    """人头要出自推演结果里那台机占用的班组，不是台账上写的在册数。"""
    detail = [{"model_code": "M-1", "finish_date": "2026-11-05",
               "staffing": {"crew_before_staffing": 120.0, "crew_effective": 100.0}},
              {"model_code": "M-2", "finish_date": "2026-11-06",
               "staffing": {"crew_before_staffing": 80.0, "crew_effective": 60.0}}]
    sol = {"objectives": {"days_late_worst": 4.0, "on_time_rate": 0.0, "labor_cost_usd": 1000.0,
                          "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0},
           "detail": detail}
    scan = {"by_scenario": {"基准": {"solutions": [sol]}}}
    m = ss._metrics(scan)
    assert m["crew_before_staffing_sum"] == 200.0 and m["crew_effective_sum"] == 160.0
    assert ss._metrics({"by_scenario": {"基准": {"solutions": []}}})["crew_before_staffing_sum"] == 0.0


def _crew_env(monkeypatch, *, effect=3.0, floor_shift=18.0):
    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 60.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        k = float((policy or {}).get("crew_bonus") or 0)
        p = perturb or {}
        late = round(20.0 * float(p.get("lead_multiplier", 1.0)) * (2.0 - float(attendance))
                     / (1.0 + effect * k) - floor_shift, 1)
        return {"finish_date": str(date(2026, 12, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "labor_cost_usd": round(1000.0 + 800.0 * k, 2),
                "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival",
                "crew_before_staffing_sum": round(100.0 * (1.0 + k), 1),
                "crew_effective_sum": round(100.0 * (1.0 + k) * float(attendance), 1)}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)


def test_crew_margin_reports_the_rung_that_actually_holds(monkeypatch):
    import asyncio

    _crew_env(monkeypatch)
    out = asyncio.run(ss.crew_margin_for_p90(None, "FAC", ["M-1"], samples=24, seed=9))
    assert out["status"] == "ok" and out["verdict"]["kind"] == "found"
    v = out["verdict"]
    assert v["p_on_time_at_level"] >= out["on_time_required"], "报出的档位必须自己就达标"
    assert (v["below_p_on_time"] or 0) < out["on_time_required"], "低一档要真的不达标，否则报高了"
    assert v["crew_bonus"] == max(a["crew_bonus"] for a in out["ladder_tried"])
    assert v["extra_heads_per_day"] == int(v["crew_per_day_at_level"] - out["baseline"]["crew_per_day"])
    assert v["median_extra_labor_cost_usd"] > 0
    assert any("赶得上要加" in x for x in out["reading"]) and any("低一档" in x for x in out["reading"])
    assert any("加人买到的时间在哪儿" in x for x in out["reading"])
    assert "这是'要让 P90 也赶上承诺'" in out["claim_guard"]


def test_crew_margin_says_so_when_people_are_not_the_binding_thing(monkeypatch):
    """加满也达不到 → 不许报'再加点'，要报名字：这串抽样里卡的是什么。"""
    import asyncio

    _crew_env(monkeypatch, effect=0.0)
    out = asyncio.run(ss.crew_margin_for_p90(None, "FAC", ["M-1"], samples=16, seed=4))
    v = out["verdict"]
    assert v["kind"] == "not_crew_bound" and v["top_crew_bonus"] == max(ss.CREW_LADDER)
    assert v["binding_seen"] == ["material_arrival"]
    assert len(out["ladder_tried"]) == len(ss.CREW_LADDER)
    # "每天多几人"要说最高那一档的人头，不是第一个并列档位（这里 100% → 100 人）
    assert v["top_extra_heads_per_day"] == 100.0
    assert v["top_median_extra_labor_cost_usd"] > 0
    assert any("加人解不到" in x and "100 人" in x for x in out["reading"])
    assert any("加人买到的时间在哪儿" in x and "哪一档都没买到" in x for x in out["reading"])
    flat = [x for x in out["reading"] if "加人买到的时间在哪儿" in x][0]
    assert "到岗本身确实改延误" in flat and "还得再核" in flat, "不许把'加人没用'说成'到岗没用'"
    assert "→" in [x for x in out["reading"] if "准点概率随加人" in x][0]


def test_crew_margin_does_not_ask_for_people_it_does_not_need(monkeypatch):
    import asyncio

    _crew_env(monkeypatch, effect=3.0, floor_shift=60.0)   # 现况就已经全部准点
    out = asyncio.run(ss.crew_margin_for_p90(None, "FAC", ["M-1"], samples=10, seed=2))
    assert out["verdict"]["kind"] == "already_ok" and out["ladder_tried"] == []
    assert any("不用加人" in x for x in out["reading"])


def test_crew_margin_chat_answer_names_heads_and_the_refusal(monkeypatch):
    from api.routes.chat_routes import _format_sensitivity_reply

    found = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
             "crew_margin": {"status": "ok", "on_time_required": 0.9, "samples": 24,
                             "baseline": {"p_on_time": 0.12, "crew_per_day": 412.0},
                             "verdict": {"kind": "found", "crew_bonus": 0.2,
                                         "extra_heads_per_day": 83, "crew_per_day_at_level": 494.4,
                                         "p_on_time_at_level": 0.92, "below_crew_bonus": 0.1,
                                         "below_p_on_time": 0.54}}}
    text = _format_sensitivity_reply(found)
    assert "赶得上要加：人手 +20%＝每天多 83 人" in text and "12%→92%" in text
    assert "低一档 10% 实测只到 54%" in text

    refused = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
               "crew_margin": {"status": "ok", "on_time_required": 0.9,
                               "baseline": {"p_on_time": 0.0, "crew_per_day": 412.0},
                               "verdict": {"kind": "not_crew_bound", "top_crew_bonus": 1.0,
                                           "top_p_on_time": 0.0, "top_p90_days_late": 31.0,
                                           "top_extra_heads_per_day": 412,
                                           "binding_seen": ["line_declared"]}}}
    t2 = _format_sensitivity_reply(refused)
    assert "加人解不到：加到 100%（每天多 412 人）仍只 0% 准点" in t2 and "line_declared" in t2
    assert "赶得上要加" not in t2

    not_run = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
               "margin_not_sampled_because": "没点要人手余量（with_crew_margin=true 才逐档加人真跑）"}
    assert "没算 —— 没点要人手余量" in _format_sensitivity_reply(not_run)


def _promise_env(monkeypatch, *, dated=True):
    from datetime import date, timedelta

    due = date(2026, 10, 31)

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        if not dated:
            return {"finish_date": None, "days_late_worst": None, "binding": "no_material",
                    "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0,
                    "line_activation_cost_usd": 0.0}
        p = policy or {}
        d = perturb or {}
        cut = 13.0 if p.get("expedite_lead_days") else 0.0
        par = 4.0 if p.get("parallel_lines") else 0.0
        crew = 2.0 if p.get("crew_bonus") else 0.0
        late = round(30.0 * float(d.get("lead_multiplier", 1.0)) * (2.0 - float(attendance))
                     - 20.0 - cut - par - crew, 1)
        return {"finish_date": str(due + timedelta(days=int(max(late, 1.0)))),
                "days_late_worst": late,
                "labor_cost_usd": 1000.0 + (300.0 if crew else 0.0),
                "expedite_cost_usd": 6300.0 if cut else 0.0,
                "line_activation_cost_usd": 45000.0 if par else 0.0,
                "binding": "material_arrival"}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)


def test_same_promisable_date_picks_the_cheaper_policy_not_whichever_came_first():
    """并列 P90 时按钱排序：实测『压提前期』与『压提前期＋并联』同为 11-28，差 $180,630/批。"""
    opts = [{"p90_finish_date": "2026-11-28", "median_total_cost_usd": 502740.0, "policy": "加并联"},
            {"p90_finish_date": "2026-11-28", "median_total_cost_usd": 322110.0, "policy": "只加急"},
            {"p90_finish_date": "2026-12-02", "median_total_cost_usd": 305550.0, "policy": "现政策"}]
    assert ss._earliest_then_cheapest(opts)["policy"] == "只加急"
    earlier = [{"p90_finish_date": "2026-11-20", "median_total_cost_usd": 999999.0, "policy": "贵但更早"},
               {"p90_finish_date": "2026-11-28", "median_total_cost_usd": 100.0, "policy": "便宜但晚"}]
    assert ss._earliest_then_cheapest(earlier)["policy"] == "贵但更早", "日期优先，钱只做并列裁决"


def test_promise_headroom_reports_the_date_that_carries_nine_tenths_confidence(monkeypatch):
    import asyncio

    _promise_env(monkeypatch)
    out = asyncio.run(ss.promise_headroom(None, "FAC", ["M-1"], samples=20, seed=6))
    assert out["status"] == "ok" and len(out["options"]) == len(ss.PROMISE_POLICIES)
    v = out["verdict"]
    now = out["options"][0]
    assert v["current_policy_p90"] == now["p90_finish_date"]
    assert v["earliest_defensible_promise"] <= v["current_policy_p90"], "加政策不能让可承诺日更晚"
    assert v["policy"] == ss.PROMISE_POLICIES[-1]["name"], "三条都省钱时该取最全那条"
    assert v["days_saved_by_policy"] > 0
    p90s = [o["p90_finish_date"] for o in out["options"]]
    assert p90s == sorted(p90s, reverse=True), "每加一条杠杆，P90 完工日必须往早走（这台假引擎就是这么设计的）"
    assert v["median_total_cost_usd"] > 0
    assert any("有 90% 把握能承诺的最早日期" in x for x in out["reading"])
    assert any("这个日期报不出去" in x for x in out["reading"])
    assert "不代做承诺" in out["claim_guard"] and "改承诺日要企业授权流程确认" in out["claim_guard"]
    assert "能写进承诺的那个数" in out["method"]


def test_promise_headroom_gives_no_date_when_the_sample_has_none(monkeypatch):
    import asyncio

    _promise_env(monkeypatch, dated=False)
    out = asyncio.run(ss.promise_headroom(None, "FAC", ["M-1"], samples=8, seed=1))
    assert out["status"] == "no_dates" and out["verdict"] is None
    assert any("算不出" in x for x in out["reading"])


def test_promise_headroom_chat_answer_names_the_date_and_the_refusal():
    from api.routes.chat_routes import _format_sensitivity_reply

    res = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
           "promise_headroom": {"status": "ok", "on_time_required": 0.9,
                                "current_promise": "2026-10-31",
                                "verdict": {"earliest_defensible_promise": "2026-12-02",
                                            "policy": "压提前期＋并联＋加班加人 30%",
                                            "days_later_than_current": 32,
                                            "days_saved_by_policy": 19,
                                            "p_on_time_at_current_promise": 0.25,
                                            "median_total_cost_usd": 51800.0,
                                            "current_policy_p90": "2026-12-21"},
                                "reading": ["现承诺 2026-10-31：现政策下 P90 完工 2026-12-21（晚 51 天），"
                                            "准点概率 0% —— 要 90% 把握的话这个日期报不出去"]}}
    text = _format_sensitivity_reply(res)
    assert "有 90% 把握能承诺的最早日期：2026-12-02（比现承诺 2026-10-31 晚 32 天）" in text
    assert "这条政策把 P90 拉回 19 天" in text and "$51,800" in text
    assert "改日期要企业授权流程确认" in text

    not_run = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
               "promise_not_sampled_because": "没点要承诺上限（with_promise_headroom=true 才逐条政策取 P90）"}
    assert "承诺上限：没算 —— 没点要承诺上限" in _format_sensitivity_reply(not_run)

    broken = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
              "promise_headroom": {"status": "no_dates", "why": "4 条政策没有一条抽得出完工日"}}
    t3 = _format_sensitivity_reply(broken)
    assert "没算成 —— 4 条政策没有一条抽得出完工日" in t3


def _volume_env(monkeypatch, *, units_effect=1.0, offset=12.0, dated=True):
    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 1800, "due_in_days": 23},
                {"model_code": "M-2", "units": 600, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        if not dated:
            return {"finish_date": None, "days_late_worst": None, "binding": "no_material",
                    "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0,
                    "line_activation_cost_usd": 0.0}
        d = perturb or {}
        total = sum(float(t.get("units") or 0) for t in targets)
        # units_effect=0 时减量完全不改天数（等料窗口卡着的真实形状）
        scale = (total / 2400.0) if units_effect else 1.0
        late = round(20.0 * float(d.get("lead_multiplier", 1.0))
                     * (2.0 - float(attendance)) * scale - offset, 1)
        return {"finish_date": str(date(2026, 10, 31) + timedelta(days=int(late))),
                "days_late_worst": late, "labor_cost_usd": round(total * 0.5, 2),
                "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "work_duration"}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)


def test_volume_ceiling_reports_units_not_percentage(monkeypatch):
    import asyncio

    _volume_env(monkeypatch)
    out = asyncio.run(ss.volume_ceiling_for_promise(None, "FAC", ["M-1", "M-2"], samples=20, seed=8))
    assert out["status"] == "ok" and out["calibrated_units"] == 2400
    v = out["verdict"]
    assert v["kind"] == "found"
    assert v["p_on_time"] >= out["on_time_required"], "报出的台数必须自己就达标"
    assert (v["next_ratio_p_on_time"] or 0) < out["on_time_required"], "多做一档要真的不达标"
    assert v["units_total"] == sum(v["units_per_model"].values())
    assert v["units_cut"] == out["calibrated_units"] - v["units_total"] > 0
    assert any("最多做" in x and "台" in x for x in out["reading"])
    assert v["next_ratio_fails"] == 0.5, "反面要贴着的上一档（0.5），不是最大的 1.0"
    assert any("每台怎么砍" in x for x in out["reading"])
    assert "少做=少卖" in [x for x in out["reading"] if "省下的人工" in x][0], "省下的钱要说清不等于赚了钱"
    assert "不替厂里挑客户" in out["claim_guard"]


def test_adjacent_above_picks_the_nearest_rung_not_the_biggest():
    """"多做一档就崩"的反面必须贴着报出的台数：拿 100% 当反例会把结论说轻。"""
    rungs = [{"status": "ok", "ratio": 1.0, "p_on_time": 0.0},
             {"status": "ok", "ratio": 0.75, "p_on_time": 0.3},
             {"status": "ok", "ratio": 0.5, "p_on_time": 0.67},
             {"status": "no_dates", "ratio": 0.35},
             {"status": "ok", "ratio": 0.2, "p_on_time": 1.0}]
    # 0.35 那档抽不出日期，不能拿它当"多做一档"的反例
    assert ss._adjacent_above(rungs, 0.2)["ratio"] == 0.5
    assert ss._adjacent_above(rungs, 0.5)["ratio"] == 0.75
    assert ss._adjacent_above(rungs, 1.0) == {}


def test_volume_ceiling_says_volume_is_not_the_lever_when_cutting_buys_nothing(monkeypatch):
    """一档都不达标就报"减量也换不到时间"，不许把最小那档包装成可行方案。"""
    import asyncio

    _volume_env(monkeypatch, units_effect=0.0)
    out = asyncio.run(ss.volume_ceiling_for_promise(None, "FAC", ["M-1"], samples=16, seed=3))
    v = out["verdict"]
    assert v["kind"] == "volume_not_the_lever"
    assert v["units_at_smallest"] < out["calibrated_units"] and v["units_cut_at_smallest"] > 0
    assert v["base_p_on_time"] == v["best_p_on_time"] == 0.0, "量不动天数时准点概率一格都不变"
    assert len(out["ladder_tried"]) == len(ss.VOLUME_LADDER)
    assert any("准点概率一点没动" in x for x in out["reading"])
    assert "不许被引用成" in out["claim_guard"]


def test_volume_ceiling_separates_helps_a_little_from_does_not_help(monkeypatch):
    """实测形状：砍到 20% 把准点概率从 0% 抬到 ~25%，仍不到 9 成 —— 这不能报成"减量没用"。"""
    import asyncio

    _volume_env(monkeypatch, offset=4.0)
    out = asyncio.run(ss.volume_ceiling_for_promise(None, "FAC", ["M-1", "M-2"], samples=16, seed=13))
    v = out["verdict"]
    assert v["kind"] == "volume_helps_but_not_enough"
    assert v["base_p_on_time"] < v["best_p_on_time"] < out["on_time_required"]
    assert any("抬到" in x for x in out["reading"]) and any("P90 延误随量" in x for x in out["reading"])
    assert any("只是少卖" in x for x in out["reading"])


def test_volume_ceiling_does_not_ask_for_cuts_it_does_not_need(monkeypatch):
    import asyncio

    _volume_env(monkeypatch, offset=60.0)      # 现量就全部准点
    out = asyncio.run(ss.volume_ceiling_for_promise(None, "FAC", ["M-1"], samples=10, seed=2))
    assert out["verdict"]["kind"] == "already_ok" and out["verdict"]["ratio"] == 1.0
    assert any("减量不是这条路要动的东西" in x for x in out["reading"])


def test_volume_ceiling_gives_no_units_when_the_sample_has_no_dates(monkeypatch):
    import asyncio

    _volume_env(monkeypatch, dated=False)
    out = asyncio.run(ss.volume_ceiling_for_promise(None, "FAC", ["M-1"], samples=8, seed=1))
    assert out["status"] == "no_dates" and out["verdict"] is None
    assert any("没跑成" in x for x in out["reading"])


def test_volume_ceiling_chat_answer_names_units_and_the_refusal():
    from api.routes.chat_routes import _format_sensitivity_reply

    found = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
             "volume_ceiling": {"status": "ok", "on_time_required": 0.9, "calibrated_units": 2400,
                                "verdict": {"kind": "found", "units_total": 1200, "units_cut": 1200,
                                            "promise_date": "2026-10-31", "p_on_time": 0.95,
                                            "next_ratio_fails": 0.75, "next_ratio_p_on_time": 0.4}}}
    text = _format_sensitivity_reply(found)
    assert "最多做 1,200 台（比标定场景砍 1,200 台）" in text and "掉到 40%" in text

    flat = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
            "volume_ceiling": {"status": "ok", "on_time_required": 0.9, "calibrated_units": 2400,
                               "verdict": {"kind": "volume_not_the_lever", "units_at_smallest": 480,
                                           "units_cut_at_smallest": 1920, "base_p_on_time": 0.0,
                                           "best_p_on_time": 0.0, "p90_days_late_at_base": 33.0,
                                           "p90_days_late_at_smallest": 21.0,
                                           "binding_seen": ["material_arrival"]}}}
    t2 = _format_sensitivity_reply(flat)
    assert "减量一点用没有：2,400 台砍到 480 台" in t2 and "material_arrival" in t2
    assert "0%→0%" in t2
    assert "最多做" not in t2, "一档都不达标时不许摆出一张可行的台数"

    ok = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
          "volume_ceiling": {"status": "ok", "on_time_required": 0.9, "calibrated_units": 2400,
                             "verdict": {"kind": "already_ok", "units_total": 2400, "p_on_time": 1.0}}}
    assert "不用砍台数" in _format_sensitivity_reply(ok)

    not_run = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
               "volume_not_sampled_because": "没点要减量测算（with_volume_ceiling=true 才逐档改量真跑）"}
    assert "减量测算：没算 —— 没点要减量测算" in _format_sensitivity_reply(not_run)


def _blockers_env(monkeypatch, *, effect=2.0, cut=12.0):
    """一条只卡等料的世界：加人不动、修带宽不动、减量只挪 cut 天、只有压提前期真的省天。"""
    from datetime import date, timedelta

    due = date(2026, 10, 31)

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 1800, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 60.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        p = policy or {}
        d = perturb or {}
        lead_mult = float(d.get("lead_multiplier", 1.0))
        days = 20.0 * lead_mult * (2.0 - float(attendance)) / (1.0 + effect * float(p.get("crew_bonus") or 0))
        if p.get("expedite_lead_days"):
            days = days * 0.45
        days = days * (sum(float(t.get("units") or 0) for t in targets) / 1800.0) ** 0.25
        late = round(days - cut, 1)
        return {"finish_date": str(due + timedelta(days=int(late))), "days_late_worst": late,
                "labor_cost_usd": 900.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "line_declared",
                # _run_one 出来的是 _metrics 的形状（复数、按机种分组），不是 detail 那一行
                "bottleneck_parts": {"M-1": "RM-ELEC-101"},
                "arrival_critical_parts": {"M-1": ["RM-ELEC-101"]},
                "material_arrival_days": {"M-1": 20}, "lines_used": ["LINE-TREAD-01"],
                "capacity_line_declared_max": 300.0,
                "crew_before_staffing_sum": round(300.0 * (1.0 + float(p.get("crew_bonus") or 0)), 1),
                "crew_effective_sum": round(300.0 * (1.0 + float(p.get("crew_bonus") or 0))
                                            * float(attendance), 1)}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)


def test_metrics_names_the_part_and_the_line_behind_the_binding():
    detail = [{"model_code": "M-1", "finish_date": "2026-11-05", "bottleneck_part": "RM-ELEC-101",
               "arrival_critical_parts": ["RM-ELEC-101"], "material_arrival_day": 20,
               "capacity_line_declared": 300.0, "staffing": {"line": "LINE-TREAD-01"}}]
    m = ss._metrics({"by_scenario": {"基准": {"solutions": [{"objectives": {}, "detail": detail}]}}})
    assert m["bottleneck_parts"] == {"M-1": "RM-ELEC-101"}
    assert m["material_arrival_days"] == {"M-1": 20}
    assert m["lines_used"] == ["LINE-TREAD-01"], "『卡在料上』要点名线与件，否则是空话"


def test_delivery_blockers_runs_all_four_paths_and_names_what_moves_it(monkeypatch):
    import asyncio

    _blockers_env(monkeypatch)

    async def no_calibration(db, fid):   # 卡片默认核对锚定；这里让它报"没有可用校准"
        return {"rows": 0, "zero_ratio_rows": 0, "median_ratio_nonzero": None,
                "reliable_rows": 0, "anchor": None, "spread_nonzero": {}, "examples": []}

    monkeypatch.setattr(ss, "lead_calibration", no_calibration)
    out = asyncio.run(ss.delivery_blockers(None, "FAC", ["M-1"], samples=8, seed=5))
    assert out["status"] == "ok"
    assert [p["key"] for p in out["paths"]] == ["date", "crew", "data", "volume"]
    assert all(p["endpoint"].startswith("/api/v1/pmc/") for p in out["paths"])
    w = out["what_moves_it"]
    assert w["bottleneck_parts"] == {"M-1": "RM-ELEC-101"}
    assert w["lines_used"] == ["LINE-TREAD-01"] and w["binding"] == "line_declared"
    assert w["line_declared_units_per_day_max"] == 300.0
    assert out["p_on_time"] is not None and out["promise_date"]
    line0 = [x for x in out["reading"] if x.startswith("结论")][0]
    assert "做不到" in line0 and "1 台机" in line0 and "8 抽" in line0 and "seed 5" in line0, \
        "判定卡要自报场景形状，否则不同 n_models/samples 的数会被横向比较"
    assert any("能动的是两处" in x and "RM-ELEC-101" in x and "LINE-TREAD-01" in x for x in out["reading"])
    assert out["took_seconds"] >= 0 and out["samples"] == 8
    assert "企业授权动作" in out["claim_guard"] and "该不该接单" in out["claim_guard"]


def test_delivery_blockers_refuses_to_guess_when_no_dates(monkeypatch):
    import asyncio

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 0.0, "hours_error_band": 0.4,
                            "components": {"lead_time": {"score": 0.0}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        return {"finish_date": None, "days_late_worst": None, "binding": "no_material",
                "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)

    out = asyncio.run(ss.delivery_blockers(None, "FAC", ["M-1"], samples=6, seed=1))
    assert out["status"] == "no_dates" and out["paths"] == []
    assert any("判定卡没生成" in x for x in out["reading"])


def test_delivery_blockers_chat_answer_is_one_screen_with_the_four_paths():
    from api.routes.chat_routes import _format_sensitivity_reply

    res = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
           "delivery_blockers": {"status": "ok", "factory_id": "FAC", "samples": 8,
                                 "took_seconds": 41.3, "promise_date": "2026-10-31",
                                 "p_on_time": 0.0,
                                 "paths": [{"path": "改日期（承诺上限）", "endpoint": "/api/v1/pmc/sim-promise-headroom"},
                                           {"path": "加人手（杠杆）", "endpoint": "/api/v1/pmc/sim-crew-margin"}],
                                 "reading": ["结论：承诺 2026-10-31 做不到 —— 现政策 P50=11-21、P90=12-04（延 34 天）、准点概率 0%",
                                             "能动的是两处：等料（瓶颈件 ['RM-ELEC-101']，到料第 ['20'] 天）与线声明产能（LINE-TREAD-01 最多 300 台/天，binding=line_declared）",
                                             "改日期（承诺上限）：有 90% 把握最早能报 2026-11-28（P90 换到 4 天）｜不该做的：不许拿 P50 当承诺日"],
                                 "claim_guard": "这一格只回答'该动哪一处'，不回答'该不该接单'"}}
    text = _format_sensitivity_reply(res)
    assert "判定（FAC，8 抽粗筛，跑了 41.3 秒）" in text
    assert "能动的是两处" in text and "RM-ELEC-101" in text and "LINE-TREAD-01" in text
    assert "改日期（承诺上限）→/api/v1/pmc/sim-promise-headroom" in text
    assert "只回答'该动哪一处'" in text

    broken = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
              "delivery_blockers": {"status": "no_dates", "why": "抽不出完工日", "reading": []}}
    assert "判定卡：没生成 —— 抽不出完工日" in _format_sensitivity_reply(broken)


def _expedite_env(monkeypatch, *, parts=None, dated=True):
    from datetime import date, timedelta

    due = date(2026, 11, 1)
    default_parts = {
        "FG-TREAD-001": {"material_code": "RM-ELEC-036", "lead_time_days": 20,
                         "ledger_lead_time_days": 20, "lead_evidence": "measured",
                         "short": 15180.0, "supplier": "中联重工(佛山)", "unit_price": 12.0},
        "A-50-04-F": {"material_code": "1000489841", "lead_time_days": 12,
                      "ledger_lead_time_days": 12, "lead_evidence": "unverified_default",
                      "short": 428.0, "supplier": None, "unit_price": None},
    }
    parts_map = default_parts if parts is None else parts

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": m, "units": 600, "due_in_days": 23} for m in ("FG-TREAD-001", "A-50-04-F")]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": m, "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}
                           for m in ("FG-TREAD-001", "A-50-04-F")]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        p = policy or {}
        d = perturb or {}
        cut = float(p.get("expedite_lead_days") or 0)
        detail = []
        for t in targets:
            code = str(t.get("model_code"))
            base_days = 20.0 * float(d.get("lead_multiplier", 1.0)) * (2.0 - float(attendance))
            if code == "A-50-04-F":
                base_days = 12.0 * float(d.get("lead_multiplier", 1.0))
            days = max(1.0, base_days - cut)
            late = round(days - 23.0, 1)
            part = parts_map.get(code) or {}
            detail.append({"model_code": code, "units": t.get("units"), "finish_date": None,
                           "days_late": late, "bottleneck_part": part, "capacity_binding": "material_arrival",
                           "binding_terms": ["material_arrival"], "staffing": {"line": "LINE-TREAD-01",
                                                                              "crew_before_staffing": 100.0,
                                                                              "crew_effective": 90.0},
                           "material_arrival_day": int(round(base_days))})
        return {"finish_date": str(due + timedelta(days=int(max(late, 1.0)))),
                "days_late_worst": late, "days_late_per_model": {str(x["model_code"]): x["days_late"]
                                                                 for x in detail},
                "finish_date_per_model": {str(x["model_code"]): str(x["finish_date"]) for x in detail},
                "labor_cost_usd": 1000.0,
                "expedite_cost_usd": round(900.0 * cut, 2),
                "line_activation_cost_usd": 0.0, "binding": "material_arrival",
                "bottleneck_parts": {k: v for k, v in parts_map.items()},
                "arrival_critical_parts": {}, "material_arrival_days": {},
                "lines_used": ["LINE-TREAD-01"], "capacity_line_declared_max": 300.0,
                "crew_before_staffing_sum": 200.0, "crew_effective_sum": 180.0,
                } if dated else {
            "finish_date": None, "days_late_worst": None, "binding": "no_material",
            "days_late_per_model": {}, "finish_date_per_model": {},
            "bottleneck_parts": {}, "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0,
            "line_activation_cost_usd": 0.0}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)


def test_expedite_price_attributes_days_to_models_and_labels_evidence(monkeypatch):
    import asyncio

    _expedite_env(monkeypatch)
    out = asyncio.run(ss.expedite_price_by_part(None, "FAC", ["M-1", "M-2"], samples=12, seed=7))
    assert out["status"] == "ok" and len(out["runs"]) == len(ss.EXPEDITE_LEAD_DAYS)
    assert out["base_days_late_per_model"], "机种级延误是归件的前提"
    by_code = {p["material_code"]: p for p in out["parts"]}
    assert by_code["RM-ELEC-036"]["usable_for_pricing"] is True
    assert by_code["RM-ELEC-036"]["days_bought"] > 0, "量过的件压 20→5 天必须省出天数"
    assert by_code["1000489841"]["usable_for_pricing"] is False
    assert "unverified_default" in by_code["1000489841"]["why"]
    # 加急费公式与单价无关（台数×压短天数×0.15），单价缺失不能挂在这一格上（已被配对验算推翻过一次）
    assert by_code["1000489841"]["unit_price_affects_this_quote"] is False
    assert by_code["RM-ELEC-036"]["unit_price_affects_this_quote"] is False
    assert "不是这一个件的价格" in by_code["RM-ELEC-036"]["cost_scope"]
    assert "SIM_EXPEDITE_COST_PER_UNIT_DAY" in out["method"] and "内置标定" not in out["method"]
    assert out["first_escalation"]["material_code"] == "RM-ELEC-036"
    assert out["usable_quote_count"] == 1 and out["unverified_parts"] == ["1000489841"]
    assert any("先催哪个件（只算量过的）" in x or "按料号" in x for x in out["reading"])
    assert "拿默认值当事实" in out["claim_guard"]


def test_expedite_price_refuses_to_name_a_first_part_when_nothing_is_measured(monkeypatch):
    """全是铺的默认值时不许摆出'先催这个'，要交回'先量哪个数'。"""
    import asyncio

    _expedite_env(monkeypatch, parts={
        "FG-TREAD-001": {"material_code": "RM-A", "lead_time_days": 20, "ledger_lead_time_days": 20,
                         "lead_evidence": "unverified_default", "short": 5.0, "supplier": None,
                         "unit_price": 3.0},
        "A-50-04-F": {"material_code": "RM-B", "lead_time_days": 12, "ledger_lead_time_days": 12,
                      "lead_evidence": "ledger_declared", "short": 7.0, "supplier": "某厂",
                      "unit_price": 4.0}})
    out = asyncio.run(ss.expedite_price_by_part(None, "FAC", ["M-1"], samples=10, seed=4))
    assert out["first_escalation"] is None and out["usable_quote_count"] == 0
    assert set(out["unverified_parts"]) == {"RM-A", "RM-B"}
    assert all(p["usable_for_pricing"] is False for p in out["parts"])


def test_expedite_price_gives_no_quote_when_no_model_gets_a_date(monkeypatch):
    import asyncio

    _expedite_env(monkeypatch, dated=False)
    out = asyncio.run(ss.expedite_price_by_part(None, "FAC", ["M-1"], samples=8, seed=2))
    assert out["status"] == "no_dates" and out["runs"] == []
    assert any("没跑成" in x for x in out["reading"])


def test_expedite_price_chat_line_names_the_part_and_the_fallback():
    from api.routes.chat_routes import _format_sensitivity_reply

    ok = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
          "expedite_price": {"status": "ok", "unverified_parts": ["1000489841"],
                             "reading": ["现政策…", "加急档位：压到 5 天 → 组合 P90 少延 15 天"],
                             "first_escalation": {"material_code": "RM-ELEC-036",
                                                  "bottlenecks_model": "FG-TREAD-001",
                                                  "days_bought": 15.0,
                                                  "policy_extra_expedite_cost_usd": 13500.0,
                                                  "lead_evidence": "measured",
                                                  "ledger_lead_time_days": 20}},
          }
    text = _format_sensitivity_reply(ok)
    assert "先催哪个件（只算量过的）：RM-ELEC-036 → FG-TREAD-001 省 15 天" in text
    assert "整包加急费中位 $13,500" in text and "不是这一个件的价格" in text

    none_measured = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
                     "expedite_price": {"status": "ok", "unverified_parts": ["RM-A", "RM-B"],
                                        "first_escalation": None, "reading": ["现政策…"]}}
    t2 = _format_sensitivity_reply(none_measured)
    assert "给不出" in t2 and "RM-A" in t2 and "先逐单量请购→到货" in t2

    not_run = {"factory_id": "FAC", "models": ["M-1"], "has_data": True, "base": {},
               "expedite_not_sampled_because": "没点要件级加急报价（with_expedite_price=true 才逐档真跑）"}
    assert "加急报价：没算 —— 没点要件级加急报价" in _format_sensitivity_reply(not_run)


def test_lead_draws_are_anchored_at_the_declared_centre_not_always_one():
    base = ss._risk_draws(20, 11, lead_band=0.2, hours_band=0.0, base_equip=0.9)
    assert all(abs(d["lead_multiplier"] - 1.0) <= 0.2 + 1e-9 for d in base), "默认按台账无偏"
    anchored = ss._risk_draws(20, 11, lead_band=0.2, hours_band=0.0, base_equip=0.9, lead_center=3.0)
    assert ([d["hours_multiplier"] for d in anchored] == [d["hours_multiplier"] for d in base]), "只挪提前期的中心"
    assert all(2.8 <= d["lead_multiplier"] <= 3.2 for d in anchored)
    shifted = [round(d["lead_multiplier"] - 1.0, 2) for d in anchored][:3]
    plain = [round(d["lead_multiplier"] - 1.0, 2) for d in base][:3]
    assert shifted != plain, "同种子同带宽但中心不同，偏移序列必须跟着挪"


def test_rescale_narrows_around_the_anchored_centre():
    """锚在 3× 时把带宽收到 0 必须回到 3.0，不是回到 1.0 —— 回 1.0 等于顺手改了中心。"""
    draws = ss._risk_draws(6, 3, lead_band=0.5, hours_band=0.0, base_equip=0.9, lead_center=3.0)
    out = ss._rescale_draws(draws, 0.9, narrowed={"purchase_lead_time": 0.0}, lead_center=3.0)
    assert all(d["lead_multiplier"] == 3.0 for d in out)


def test_card_reports_the_anchor_check_and_default_stays_on_the_ledger(monkeypatch):
    import asyncio
    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 60.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        d = perturb or {}
        late = round(20.0 * float(d.get("lead_multiplier", 1.0)) * (2.0 - float(attendance)) - 20.0, 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "days_late_per_model": {"M-1": late},
                "labor_cost_usd": 100.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "bottleneck_parts": {}, "lines_used": [],
                "material_arrival_days": {}, "capacity_line_declared_max": 0.0,
                "crew_before_staffing_sum": 100.0, "crew_effective_sum": 90.0}

    async def no_calibration(db, fid):
        return {"rows": 3, "zero_ratio_rows": 3, "median_ratio_nonzero": None,
                "reliable_rows": 0, "anchor": None, "spread_nonzero": {}, "examples": []}

    async def anchored(db, factory_id, models, *, samples=12, seed=20261008, policy=None):
        return {"status": "ok", "anchor": 2.5, "calibration": {"reliable_rows": 4, "zero_ratio_rows": 3},
                "reading": ["校准依据…", "按台账锚…", "差值：P50 后移 9 天、P90 后移 14 天、准点概率掉 30.0pp"]}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    monkeypatch.setattr(ss, "lead_calibration", no_calibration)
    monkeypatch.setattr(ss, "calibration_impact", anchored)

    out = asyncio.run(ss.delivery_blockers(None, "FAC", ["M-1"], samples=6, seed=2))
    line = [x for x in out["reading"] if x.startswith("锚定核对")]
    assert line and "P90 后移 14 天" in line[0] and "排除 3 条实测 0 天" in line[0]
    assert out["calibration"]["anchor"] == 2.5
    assert out["calibration"]["status"] == "ok", "卡只报差值，默认锚定不在这儿改"

    off = asyncio.run(ss.delivery_blockers(None, "FAC", ["M-1"], samples=6, seed=2,
                                           with_calibration=False))
    assert off["calibration"] is None and not [x for x in off["reading"] if x.startswith("锚定核对")]


def _calib_env(monkeypatch, *, anchor=2.0, rows=6):
    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 600, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 60.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None, factor_map=None):
        d = perturb or {}
        # 假件按 map 的平均倍数放大（真引擎是逐料号各按自己的实测÷台账）
        fm = (sum((factor_map or {}).values()) / len(factor_map)) if factor_map else 1.0
        late = round(20.0 * float(d.get("lead_multiplier", 1.0)) * float(fm)
                     * (2.0 - float(attendance)) - 25.0, 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "days_late_per_model": {"M-1": late},
                "labor_cost_usd": 100.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "bottleneck_parts": {}, "lines_used": [],
                "material_arrival_days": {}, "capacity_line_declared_max": 0.0,
                "crew_before_staffing_sum": 100.0, "crew_effective_sum": 90.0}

    async def fake_factors(db, fid, *, min_po=2):
        return {"factors": {"RM-A": 2.0, "RM-B": 4.0}, "measured_days": {}, "codes": 2,
                "ledger_rows_with_lead": 6, "coverage": 2 / 6, "min_po": min_po,
                "caveat": "map 里每条都是自己的实测÷台账"}

    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", fake_factors)

    async def fake_cal(db, fid):
        if anchor is None:
            return {"rows": 3, "zero_ratio_rows": 3, "median_ratio_nonzero": None,
                    "reliable_rows": 0, "anchor": None, "spread_nonzero": {}, "examples": []}
        return {"rows": rows, "zero_ratio_rows": 2, "median_ratio_all_rows": 7.17,
                "median_ratio_nonzero": anchor, "reliable_rows": rows - 2, "anchor": anchor,
                "spread_nonzero": {"p25": anchor / 2, "p75": anchor * 2, "min": 0.05, "max": 38.7},
                "examples": [{"material_code": "RM-CAST-01", "ledger_days": 15,
                              "measured_median_days": 95.5, "po_count": 4, "ratio": 6.37}]}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    monkeypatch.setattr(ss, "lead_calibration", fake_cal)


def test_calibration_impact_shifts_the_centre_not_the_band(monkeypatch):
    """真跑一遍 calibration_impact：读数是在构造字面量里自引用的，只有跑起来才炸得出来。"""
    import asyncio

    _calib_env(monkeypatch, anchor=2.0)
    out = asyncio.run(ss.calibration_impact(None, "FAC", ["M-1"], samples=10, seed=5))
    assert out["status"] == "ok" and out["anchor"] == 2.0
    assert out["default_unchanged"] is True, "这一格只报差值，不许偷偷改默认锚"
    assert out["p50_shift_days"] > 0 and out["p90_shift_days"] > 0
    assert out["at_measured"]["p50"] > out["at_ledger"]["p50"], "实测说台账偏乐观 → 锚过去日期必须后移"
    assert any("系统性偏差" in x for x in out["reading"])
    assert any("默认锚定没改" in x for x in out["reading"])
    assert "中心是" in out["method"] and "带宽是" in out["method"], "中心与带宽必须分开说"
    modes = {m["mode"]: m for m in out["modes"]}
    assert set(modes) == {"ledger", "global_measured", "hybrid"} and modes["hybrid"]["p90"]
    assert out["hybrid"]["map_codes"] == 2 and out["hybrid"]["ledger_rows_with_lead"] == 6


def test_calibration_impact_refuses_to_anchor_without_evidence(monkeypatch):
    import asyncio

    _calib_env(monkeypatch, anchor=None)
    out = asyncio.run(ss.calibration_impact(None, "FAC", ["M-1"], samples=6, seed=1))
    assert out["status"] == "no_calibration" and out["calibration"]["anchor"] is None
    assert any("只能按『台账无偏』抽" in x for x in out["reading"]), "没实测也要把默认锚定的性质说出去"
