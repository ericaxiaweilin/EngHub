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
    assert out["computable"] and out["measured_between"] == [1.0, 0.9]
    assert out["days_per_step"] == -2.0            # 每 −10% 提前期 → 早 2 天
    assert out["on_time_models_per_step"] == 2.0   # 每 −10% → 多 2 台准点
    assert out["money_per_day_saved"] == 500.0


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
