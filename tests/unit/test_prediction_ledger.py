"""交期留痕账本：记账的日期算法、配对取哪一条、样本不够时的说法。

只测纯函数（predicted_finish_for / summarize）—— 动库那两条（record/pair）
在 /api/v1/pmc/delivery-accuracy 的预演里看得到。
"""
from datetime import date

from api.services.prediction_ledger import (
    BASIS,
    MIN_PAIRS_FOR_MAPE,
    predicted_finish_for,
    summarize,
)


def test_partial_day_rounds_up_not_down():
    # 0.11 天不能说成"当天交"：那是把预计说早，配对时会凭空多出误差
    assert predicted_finish_for(date(2026, 10, 8), 0.11) == date(2026, 10, 9)
    assert predicted_finish_for(date(2026, 10, 8), 1.0) == date(2026, 10, 9)
    assert predicted_finish_for(date(2026, 10, 8), 1.2) == date(2026, 10, 10)
    assert predicted_finish_for(date(2026, 10, 8), 3.9) == date(2026, 10, 12)


def test_summarize_refuses_to_score_an_unpaired_ledger():
    out = summarize({"paired": 0, "mape": None, "orders_recorded": 349, "rows_recorded": 349,
                     "still_open": 349, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 8)}, {}, MIN_PAIRS_FOR_MAPE)
    assert out["state"] == "reported"
    assert out["mape"] is None
    assert "成对样本 0 对" in out["missing"]
    # 记账量与配对量是两个数，别把它们并成一个"覆盖率"
    assert out["orders_recorded"] == 349 and out["paired"] == 0


def test_summarize_passes_only_with_enough_pairs_and_low_error():
    ok = summarize({"paired": 12, "mape": 0.11, "mae_days": 1.4, "orders_recorded": 349,
                    "rows_recorded": 400, "still_open": 388,
                    "first_day": date(2026, 10, 8), "last_day": date(2026, 10, 20)},
                   {"c. 准（±2 天）": 9, "d. 晚 3-7 天": 3}, MIN_PAIRS_FOR_MAPE)
    assert ok["state"] == "pass" and ok["missing"] is None
    bad = summarize({"paired": 12, "mape": 0.44, "orders_recorded": 349, "rows_recorded": 400,
                     "still_open": 388, "mae_days": 5.0,
                     "first_day": date(2026, 10, 8), "last_day": date(2026, 10, 20)}, {}, 10)
    assert bad["state"] == "fail"


def test_enough_pairs_but_no_value_still_counts_as_not_judged():
    # 配对数够了但 MAPE 算不出（误差全为空的脏数据）→ 不能当"通过"
    out = summarize({"paired": 15, "mape": None, "orders_recorded": 40, "rows_recorded": 40,
                     "still_open": 25, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 22)}, {}, 10)
    assert out["state"] == "reported" and "成对样本" not in (out["missing"] or "成对样本")


def test_basis_is_a_single_named_method():
    """口径名要固定：账本里混进第二种预计口径，配对就变成两套尺互相打。"""
    assert BASIS == "time_basis_flow"


def test_error_bands_are_carried_into_the_summary():
    out = summarize({"paired": 3, "mape": None, "orders_recorded": 10, "rows_recorded": 12,
                     "still_open": 9, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 9)},
                    {"e. 晚 8 天以上": 2, "c. 准（±2 天）": 1}, 10)
    assert out["error_bands"] == {"e. 晚 8 天以上": 2, "c. 准（±2 天）": 1}
