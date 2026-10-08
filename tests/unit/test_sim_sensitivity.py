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
                                           against=against_value, db=None, current_user=None)

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
