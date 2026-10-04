"""虚拟工厂时钟/事件队列的兜底后端回归 —— 这层必须纯内存、不下盘。"""

import inspect
import time

import pytest

# 显式 asyncio 标记：pytest.ini 写的是 [tool:pytest] 段，pytest 9 不读它，
# 里面的 asyncio_mode = auto 实际从未生效。
pytestmark = [pytest.mark.unit]

from api.services import virtual_factory_clock as vfc
from api.services.virtual_factory_clock import VirtualFactoryClock

FID = "test-factory"


@pytest.fixture()
def clock(monkeypatch):
    """强制走进程内兜底后端（没有 Redis 时的真实形态）。"""
    monkeypatch.setenv("REDIS_URL", "")
    c = VirtualFactoryClock()
    assert c.backend == "memory"
    return c


@pytest.mark.asyncio
async def test_now_freezes_origin_before_any_advance(clock):
    """起点第一次读到就得冻住：否则两次 now() 之间时钟会跟着真实时间走。"""
    assert await clock.now(FID) == await clock.now(FID)


@pytest.mark.asyncio
async def test_advance_steps_exactly_the_requested_hours(clock):
    origin = await clock.now(FID)
    after = await clock.advance(FID, 2.0)
    assert (after - origin).total_seconds() == pytest.approx(2 * 3600)
    again = await clock.advance(FID, 0.5)
    assert (again - after).total_seconds() == pytest.approx(0.5 * 3600)
    assert await clock.now(FID) == again


@pytest.mark.asyncio
async def test_advance_before_first_now_steps_from_frozen_origin(clock):
    after = await clock.advance(FID, 1.0)
    assert (after - await clock.now(FID)).total_seconds() == pytest.approx(0)
    assert abs(after.timestamp() - time.time()) < 4 * 3600  # 起点是真实时间，不是 epoch


@pytest.mark.asyncio
async def test_claim_is_one_shot_until_released(clock):
    assert await clock.claim(FID, "seed:products", 60) is True
    assert await clock.claim(FID, "seed:products", 60) is False
    await clock.release(FID, "seed:products")
    assert await clock.claim(FID, "seed:products", 60) is True


@pytest.mark.asyncio
async def test_expired_claim_can_be_taken_again(clock):
    slot = "alert:low_stock"
    assert await clock.claim(FID, slot, 60) is True
    clock._local_flags[clock._key(FID, f"claim:{slot}")] = time.time() - 1
    assert await clock.claim(FID, slot, 60) is True


@pytest.mark.asyncio
async def test_event_queue_is_bounded_and_newest_first(clock):
    await clock.push_events(
        FID, [{"seq": i} for i in range(5)], max_len=3
    )
    kept = await clock.recent_events(FID, limit=10)
    assert [e["seq"] for e in kept] == [4, 3, 2]
    assert len(kept) <= 3


@pytest.mark.asyncio
async def test_reset_clears_clock_events_and_claims(clock):
    await clock.advance(FID, 5.0)
    await clock.push_events(FID, [{"seq": 1}])
    await clock.claim(FID, "seed:products", 60)
    await clock.reset(FID)
    assert await clock.recent_events(FID) == []
    assert await clock.claim(FID, "seed:products", 60) is True
    assert abs((await clock.now(FID)).timestamp() - time.time()) < 60  # 回到真实时间起点


def test_clock_module_never_touches_db_or_disk():
    """时钟层没有审计价值也不该有：一旦引到 DB/文件就等于把每轮 pulse 变成写放大。"""
    src = inspect.getsource(vfc)
    for forbidden in ("sqlalchemy", "AsyncSession", "db.execute", "session.commit", "open("):
        assert forbidden not in src, f"时钟层出现了持久化调用：{forbidden}"
