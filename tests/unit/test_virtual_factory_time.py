"""虚拟工厂的时间数学：进度 = 映射日产能 × 仿真过了多久，不陪真实日历等。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.virtual_factory_service import progress_qty


@pytest.mark.parametrize("daily,step,remaining,expect", [
    (10, 24, 100, 10),      # 一拍仿真一天：出一天的量
    (10, 12, 100, 5),       # 半拍出一半
    (10, 2, 100, 1),        # 2 小时不到 1 件时至少推进 1 件（否则永远出不来）
    (10, 24, 4, 4),         # 不超过剩余量
    (0.6, 24, 100, 1),      # 日产能是小数（实测成品检验工位配 0.6 件/日）也要动
    (0, 24, 100, 3),        # 映射不到工位才回落到均分产能，且回落由调用方计数上报
])
def test_progress_follows_the_simulated_clock_not_the_calendar(daily, step, remaining, expect):
    assert progress_qty(daily, step, remaining, fallback_daily=3) == expect


def test_one_piece_floor_keeps_small_orders_from_stalling():
    assert progress_qty(0.01, 1, 1) == 1
