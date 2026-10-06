"""分层验收的判据本身要能测：闸门、置信区间、方向、样本不足都不能被糊过去。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services import engine_layers as el


def test_metric_with_too_few_samples_is_not_computable_not_zero():
    """n 不够时报"算不出"，不许报 0% —— 0% 会被读成"命中率差"，那是两回事。"""
    m = el._metric("瓶颈位置命中率", 0.0, 0.7, "gte", "", "口径说明", n=1, min_n=3)
    assert m["state"] == "not_computable" and m["pass"] is None
    assert "少于判据需要" in m["missing"]


def test_metric_without_source_is_not_computable():
    m = el._metric("回测 MAPE", None, 0.2, "lte", "", "需要成对样本", missing="没有排程行")
    assert m["state"] == "not_computable" and "没有排程行" in m["missing"]


def test_gate_blocks_everything_above_the_first_failing_layer():
    """L1 崩了，上面四层再漂亮都不许引用 —— 这是这份验收唯一的目的。"""
    def layer(*states):
        return {"metrics": [{"metric": f"m{i}", "state": s} for i, s in enumerate(states)]}
    report = {"L1": layer("fail"), "L2A": layer("pass"), "L2B": layer("pass"),
              "L3": layer("pass"), "L4": layer("pass")}
    out = el.gate(report)
    assert out["first_unmet_layer"] == "L1" and out["reportable_through"] == ["（无）"]
    assert report["L2A"]["reportable"] is False and "L1" in report["L2A"]["quote_rule"]


def test_gate_blocks_from_a_layer_that_cannot_be_measured_at_all():
    report = {"L1": layer_pass(), "L2A": layer_pass(),
              "L2B": {"metrics": [{"metric": "回测 MAPE", "state": "not_computable"}]},
              "L3": layer_pass(), "L4": layer_pass()}
    out = el.gate(report)
    assert out["first_unmet_layer"] == "L2B"
    assert report["L3"]["reportable"] is False and report["L1"]["reportable"] is True


def layer_pass():
    return {"metrics": [{"metric": "x", "state": "pass"}]}


def test_bootstrap_slope_ci_is_narrow_on_clean_line_and_refuses_flat_curve():
    lin = el.boot_ci_slope([0.8, 0.9, 1.0, 1.1, 1.2], [-4, -2, 0, 2, 4], 0.1)
    assert lin["computable"] and abs(lin["slope_per_step"] - 2.0) < 0.35
    assert lin["ci_width_steps"] <= 1.5, "干净的线性曲线不该被判成量不出来"
    # 完全平的曲线是"测出来不敏感"，不是"测不出来"：斜率 0、区间宽度 0，照实报
    flat = el.boot_ci_slope([0.8, 0.9, 1.0, 1.1], [0, 0, 0, 0], 0.1)
    assert flat["computable"] is True and flat["slope_per_step"] == 0.0 and flat["ci_width_steps"] == 0.0
    # 档位全挤在同一个值上才是真的测不出来（没有横轴跨度可拟合）
    same = el.boot_ci_slope([1.0, 1.0, 1.0], [0, 2, 4], 0.1)
    assert same["computable"] is False
    assert el.boot_ci_slope([1.0, 2.0], [0, 3], 0.1)["computable"] is False


def test_direction_checks_catch_a_sign_flip():
    assert el.check_direction("lte", 100.0, 95.0) and el.check_direction("lte", 100.0, 100.0)
    assert not el.check_direction("lte", 100.0, 105.0)
    assert not el.check_direction("gte", 100.0, None)      # 跑不出结果不许算通过


def test_every_layer_has_thresholds_and_a_golden_question_set():
    for lid in el.LAYER_ORDER:
        assert el.THRESHOLDS.get(lid), f"{lid} 没有阈值"
        assert lid in el.LAYER_NAMES and lid in el.LAYER_QUESTIONS
    expected = {t for _, t in el.ROUTING_GOLDEN}
    assert len(el.ROUTING_GOLDEN) >= 10 and "query_simulation_sensitivity" in expected


def test_probes_cover_both_directions():
    signs = {p["sign"] for p in el.direction_expectations()}
    assert signs == {"lte", "gte"}, "只测一个方向的冲击，符号反了也测不出来"
