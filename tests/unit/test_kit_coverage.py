"""齐套行覆盖率：引擎本轮算出的缺口件 vs 台账登记的缺口行。

只测纯汇总函数 coverage_summary —— 展开与配对那一段（kit_coverage_gap）在预演端点里看得到。
分档必须按门自己的判定分，不按"台账有没有行"这种代理信号分：上一版就是拿代理信号
写成"24 张被判齐套"，而门实际一张都没放过。
"""
from api.services.sim_backtest import coverage_summary


def _order(model="A-50-04-F", code="WO-1", engine=10, ledger=3, missing=7, verdict="ready"):
    return {"work_order_id": code, "work_order_code": code, "model": model,
            "engine_short_parts": engine, "ledger_short_parts": ledger,
            "missing_parts": missing, "gate_verdict": verdict}


def test_coverage_rate_is_ledger_over_engine_not_per_order_average():
    out = coverage_summary([_order(engine=10, ledger=8, missing=2),
                            _order(code="WO-2", engine=40, ledger=4, missing=36)])
    assert out["engine_short_part_rows"] == 50
    assert out["ledger_short_rows"] == 12
    assert out["coverage_rate"] == 0.24          # 12/50，不是 (0.8+0.1)/2=0.45
    assert out["rows_to_register"] == 38


def test_coverage_rate_is_none_when_engine_sees_no_shortage():
    # 没缺口 ≠ 覆盖率 0：分母是 0 时这一格算不出，不给 0 分
    out = coverage_summary([_order(engine=0, ledger=0, missing=0)])
    assert out["coverage_rate"] is None
    assert out["engine_short_part_rows"] == 0


def test_release_hole_only_counts_orders_the_gate_called_ready():
    rows = [_order(code="WO-a", verdict="ready"),
            _order(code="WO-b", verdict="already_released"),
            _order(code="WO-c", verdict="no_kit_evidence"),
            _order(code="WO-d", verdict="no_time_basis", engine=5, ledger=0, missing=5)]
    out = coverage_summary(rows)
    assert out["gate_ready_but_engine_short"] == 1
    assert out["already_released_but_engine_short"] == 1
    assert out["held_no_kit_evidence_with_engine_list"] == 1
    # 三档互不混：可举证的放行洞只此一张
    assert [x["work_order_code"] for x in out["gate_ready_proven_samples"]] == ["WO-a"]


def test_verdict_distribution_counts_every_bucket_once():
    out = coverage_summary([_order(code="WO-a", verdict="ready"),
                            _order(code="WO-b", verdict="ready"),
                            _order(code="WO-c", verdict="no_time_basis"),
                            _order(code="WO-d", verdict=None)])
    dist = out["gate_verdict_distribution"]
    assert dist["ready"] == 2 and dist["no_time_basis"] == 1 and dist["unknown"] == 1
    assert sum(dist.values()) == 4


def test_ledger_zero_short_orders_is_reported_separately_from_the_hole():
    # 台账零缺口行只是代理信号；它不等于放行洞（门可能因为别的理由挡住）
    out = coverage_summary([_order(verdict="no_time_basis", ledger=0),
                            _order(code="WO-2", verdict="no_time_basis", ledger=0)])
    assert out["ledger_zero_short_orders"] == 2
    assert out["gate_ready_but_engine_short"] == 0


def test_per_model_breakdown_carries_the_write_cost():
    out = coverage_summary([_order(model="A", engine=10, ledger=2, missing=8),
                            _order(model="B", code="WO-b", engine=4, ledger=1, missing=3)])
    per = {m["orders"] and m["engine"]: m for m in out["per_model"]}
    assert sorted(per) == [4, 10]
    assert out["rows_to_register"] == 11
    assert out["models"] == ["A", "B"]


# ── 按登记深度比"两边各看到多少缺口"：这一对数才承载毛/净那条决策 ──────────
def test_band_labels_follow_the_backfill_gates():
    from api.services.sim_backtest import _band_label

    assert _band_label(1) == "1-99 行（没登记到结构）"
    assert _band_label(80) == "1-99 行（没登记到结构）"
    assert _band_label(99) == "1-99 行（没登记到结构）"
    assert _band_label(100) == "100-399 行"
    assert _band_label(399) == "100-399 行"
    assert _band_label(400) == "≥400 行（登记到位）"


def _deep(code, rows, led_lines, led_qty, eng_lines, eng_qty):
    return {"work_order_id": code, "work_order_code": code, "model": "A",
            "ledger_rows": rows, "ledger_short_parts": led_lines,
            "ledger_short_qty": led_qty, "engine_short_parts": eng_lines,
            "engine_short_qty": eng_qty, "missing_parts": max(0, eng_lines - led_lines),
            "gate_verdict": "already_released"}


def test_registration_bands_report_line_and_qty_ratios():
    out = coverage_summary([
        _deep("WO-full", 620, 1467, 141811, 1533, 160958),
        _deep("WO-thin", 12, 49, 462, 795, 49271),
    ])
    bands = out["short_qty_by_registration_band"]
    full = bands["≥400 行（登记到位）"]
    thin = bands["1-99 行（没登记到结构）"]
    assert full["line_ratio_engine_over_ledger"] == 1.045
    assert full["qty_ratio_engine_over_ledger"] == 1.135
    assert thin["line_ratio_engine_over_ledger"] == 16.224
    # 读数要说清"差的是没登记到的行"，不能读成引擎把缺口算大了
    assert "登记到位" in bands["reading"] and "砍半" in bands["reading"]


def test_band_reading_admits_when_the_full_band_is_missing():
    out = coverage_summary([_deep("WO-thin", 10, 5, 100, 200, 9000)])
    assert "分档样本不足" in out["short_qty_by_registration_band"]["reading"]
