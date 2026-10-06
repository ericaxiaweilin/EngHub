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
