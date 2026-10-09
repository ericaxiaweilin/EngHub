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


def test_a_measured_number_without_a_threshold_is_reported_not_missing():
    """量出来了但没有判线 → reported。以前这格写 not_computable，"峰值内存 191.8 MB"
    明明有数却在报告里说算不出，读的人会去补一个本来就有的数。"""
    m = el._metric("峰值内存", 191.8, None, "lte", "MB", "只报数不判线")
    assert m["state"] == "reported" and m["pass"] is None and m["value"] == 191.8
    assert m["missing"] is None


def test_reported_metrics_keep_the_layer_computable():
    """只有 reported + pass 的层不能因为"没判线"就被当成整层没数。"""
    def layer(*states):
        return {"metrics": [{"metric": f"m{i}", "state": st} for i, st in enumerate(states)]}
    report = {"L1": layer("pass", "reported"), "L2A": layer("pass"), "L2B": layer("pass"),
              "L3": layer("pass"), "L4": layer("pass")}
    out = el.gate(report)
    assert out["first_unmet_layer"] is None and len(out["reportable_through"]) == 5


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


# ── 人工采纳率的归属：只有"人的账号写过处置日志"才算人表过态 ────────────────
def _disp(status, actor=None, reason=""):
    return {"status": status, "actor": actor, "block_reason": reason}


def test_engine_superseded_closures_are_not_rejections():
    rows = [_disp("cancelled", "virtual_factory", "已被更新的推演推荐取代") for _ in range(23)]
    out = el.adoption_from_dispositions(rows)
    assert out["judged"] == 0 and out["rate"] is None
    assert out["engine_churn"] == 23


def test_a_single_unlogged_closure_does_not_become_zero_adoption():
    """10-08 实测的形状：23 条引擎自关 + 1 条没有日志 —— 上一版据此报采纳率 0.0。"""
    rows = [_disp("cancelled", "virtual_factory", "已被更新的推演推荐取代") for _ in range(23)]
    rows.append(_disp("cancelled", None))
    out = el.adoption_from_dispositions(rows)
    assert out["judged"] == 0 and out["rate"] is None, "没有人的处置记录就不该出一个比率"
    assert out["unlogged"] == 1


def test_real_human_dispositions_are_counted_in_both_directions():
    rows = [_disp("done", "eric"), _disp("cancelled", "eric"), _disp("done", "vf_mec_pmc_01")]
    out = el.adoption_from_dispositions(rows)
    assert out["adopted"] == 2 and out["rejected"] == 1 and out["judged"] == 3
    assert out["rate"] == round(2 / 3, 3)


def test_below_three_dispositions_is_not_judged():
    rows = [_disp("done", "eric"), _disp("cancelled", "eric")]
    assert el.adoption_from_dispositions(rows)["rate"] is None
    assert el.adoption_from_dispositions(rows)["judged"] == 2


def test_machine_accounts_are_churn_even_without_the_supersede_note():
    rows = [_disp("cancelled", "system"), _disp("cancelled", "night-watch"),
            _disp("done", "pmc_agent")]
    out = el.adoption_from_dispositions(rows)
    assert out["judged"] == 0 and out["engine_churn"] == 3


def test_row_coverage_is_the_row_sum_ruler_not_the_median_ratio():
    """同名只许一把尺：判线用的必须是逐单求和之比。

    这组数是 10-09 实测形状：多数单台账≈引擎（中位数之比因此读 0.961），
    另有几张单的引擎缺口行完全没登记 —— 求和口径 0.821 才说明还差多少行没写。
    """
    assert el.row_coverage(15895, 19352) == 0.821
    assert el.row_coverage(146, 152) == 0.961, "两张中位数之比会明显乐观，所以它不判线"


def test_row_coverage_without_engine_rows_is_none_not_zero():
    """引擎没展开出缺口件时无从计算 —— 报 0 会被读成"台账一行都没登记"。"""
    assert el.row_coverage(120, 0) is None
    assert el.row_coverage(0, 0) is None
    assert el.row_coverage(0, 500) == 0.0, "引擎有缺口行而台账零行，这才是真的 0"


def test_worst_ci_row_names_the_widest_curve_and_direction_test_is_decidable():
    """「最差」必须指到具体一条曲线；区间跨 0 与不跨 0 是两种不同的缺陷。"""
    rows = [
        {"lever": "外购提前期", "ci_width_steps": 1.2, "ci90": [-0.4, 0.8], "step": 0.1},
        {"lever": "到岗率", "ci_width_steps": 44.71, "ci90": [-3.1, 41.6], "step": 0.05},
        {"lever": "设备节拍", "ci_width_steps": 0.3, "ci90": [1.0, 1.3], "step": 0.1},
    ]
    assert el.worst_ci_row(rows)["lever"] == "到岗率"
    assert el.worst_ci_row([]) is None
    # 不跨 0 的那条是"幅值不定"，跨 0 的那条才是"方向没定"
    assert not (rows[2]["ci90"][0] <= 0.0 <= rows[2]["ci90"][1])
    assert rows[1]["ci90"][0] <= 0.0 <= rows[1]["ci90"][1]
