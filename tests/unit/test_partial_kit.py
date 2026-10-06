"""分批投产读数的断言：台数要加得对，没有机会时也要报 0 而不是含糊过去。

真正的"能开几台"在 SQL 里（可用量 ÷ 单件用量，封顶在还欠几台），线上实测已在
probe/心跳里对撞过；这里守的是汇总层不出假合计。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.partial_kit import summarize


def test_units_start_and_waiting_add_up():
    orders = [
        {"remaining_qty": 68.0, "startable_units": 21.0},
        {"remaining_qty": 136.0, "startable_units": 12.0},
    ]
    out = summarize(orders)
    assert out["orders_with_partial_option"] == 2
    assert out["units_startable_now"] == 33.0
    assert out["units_still_waiting"] == 171.0
    # 两个数加起来必须等于还欠的总量，不然台账对不上
    assert out["units_startable_now"] + out["units_still_waiting"] == 68.0 + 136.0


def test_no_opportunity_reports_zeros_not_none():
    out = summarize([])
    assert out == {"orders_with_partial_option": 0, "units_startable_now": 0,
                   "units_still_waiting": 0}


def test_full_startable_order_does_not_fabricate_waiting_units():
    """startable == remaining 时等待量是 0，不能因为浮点误差报出负数。"""
    out = summarize([{"remaining_qty": 10.0, "startable_units": 10.0}])
    assert out["units_still_waiting"] == 0


def test_missing_fields_are_treated_as_zero():
    out = summarize([{"remaining_qty": None, "startable_units": None}])
    assert out["units_startable_now"] == 0
    assert out["units_still_waiting"] == 0
