"""虚拟工厂的时间数学：进度 = 映射日产能 × 仿真过了多久，不陪真实日历等。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.virtual_factory_service import progress_qty, units_makeable


@pytest.mark.parametrize("daily,step,remaining,expect", [
    (10, 24, 100, 10),      # 一拍仿真一天：出一天的量
    (10, 12, 100, 5),       # 半拍出一半
    (10, 2, 100, 1),        # 2 小时不到 1 件时至少推进 1 件（否则永远出不来）
    (10, 24, 4, 4),         # 不超过剩余量
    (0.6, 24, 100, 1),      # 日产能是小数（实测成品检验工位配 0.6 件/日）也要动
    (0, 24, 100, 0),        # 映射不到工位 = 不推进（0 由调用方跳过），不再编一个产量出来
])
def test_progress_follows_the_simulated_clock_not_the_calendar(daily, step, remaining, expect):
    assert progress_qty(daily, step, remaining) == expect


def test_one_piece_floor_keeps_small_orders_from_stalling():
    assert progress_qty(0.01, 1, 1) == 1


@pytest.mark.parametrize("planned,done,required,short,expect", [
    (100, 0, 1000, 0, 100),        # 材料齐全：整单都做得动
    (100, 0, 1000, 900, 10),       # 缺 90% 料 → 只能做 10%
    (100, 40, 1000, 600, 0),       # 已做 40 件，剩下刚好被欠料挡住 → 这张单停在这儿
    (100, 90, 1000, 50, 5),        # 缺口吃掉一部分，还能做 5 件
    (100, 0, 0, 0, 0),             # 没有物料行＝没有依据，不猜产量
    (100, 100, 1000, 0, 0),        # 做完的不再重复产出
])
def test_shortage_caps_output_instead_of_faking_completion(planned, done, required, short, expect):
    assert units_makeable(planned, done, required, short) == expect


def test_short_material_never_stocks_in_and_falsely_clears_the_parent_kit():
    """这是上一版最脏的一条：欠料也照样做完入库，母单缺口就此假清零。"""
    assert units_makeable(100, 0, 1000, 1000) == 0
    assert progress_qty(10, 24, 0) == 0


@pytest.mark.asyncio
async def test_readings_state_the_sim_clock_and_its_offset(monkeypatch):
    """仿真推进后，读数必须自己讲清"这是仿真时间"，并给出与真实时间的差。"""
    from datetime import datetime, timedelta, timezone
    from api.services import chain_convergence as cc_mod

    class FakeClock:
        async def now(self, fid):
            return datetime.now(timezone.utc) + timedelta(hours=36)

    monkeypatch.setattr("api.services.virtual_factory_clock.get_clock", lambda: FakeClock())
    out = await cc_mod.sim_clock_reading("FAC_MECH_001")
    assert out["clock_available"] is True
    assert 35.0 <= out["sim_offset_hours"] <= 37.0
    assert "T" in out["sim_now"]


@pytest.mark.asyncio
async def test_sim_clock_unavailable_is_reported_not_invented(monkeypatch):
    from api.services import chain_convergence as cc_mod

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("api.services.virtual_factory_clock.get_clock", boom)
    out = await cc_mod.sim_clock_reading("FAC_MECH_001")
    assert out == {"sim_now": None, "sim_offset_hours": None, "clock_available": False}
