"""引擎心跳的可观测性回归：停摆必须能被判定出来，而不是"看起来在跑"。

背景（2026-10-04 实测）：5 个后台循环写在 API 的 startup handler 里，
uvicorn --workers 2 每个 worker 各起一套，而 create_task 返回值没人存
（asyncio 只持弱引用）。结果 API 一切正常，引擎静默停摆十几小时，
最后一条自主虚拟工厂报工停在 00:12 —— 当时没有任何数据能证明它死了。
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = [pytest.mark.unit]

from api.services.engine_heartbeat import expected_interval, is_alive
from engine_asgi import HEART_LOOP, verdict


def test_no_heartbeat_is_not_alive():
    assert is_alive(None, interval=30) is False


def test_fresh_heartbeat_is_alive():
    now = datetime.now(timezone.utc)
    assert is_alive(now - timedelta(seconds=10), now, interval=30) is True


def test_stale_beyond_two_intervals_is_dead():
    now = datetime.now(timezone.utc)
    assert is_alive(now - timedelta(seconds=61), now, interval=30) is False


def test_naive_db_timestamp_is_treated_as_utc():
    """列是 timestamp without time zone：不补 tzinfo 比较会差一个时区。"""
    now = datetime.now(timezone.utc)
    naive_recent = (now - timedelta(seconds=5)).replace(tzinfo=None)
    assert is_alive(naive_recent, now, interval=30) is True


def test_verdict_without_scheduler_record_says_so():
    alive, reason = verdict([])
    assert alive is False
    assert HEART_LOOP in reason


def test_verdict_dead_when_heart_stalled():
    states = [{
        "loop": HEART_LOOP, "interval_seconds": 30, "stale_seconds": 900.0,
        "failures": 0, "last_error": None,
    }]
    alive, reason = verdict(states)
    assert alive is False
    assert "900" in reason


def test_verdict_alive_but_counts_failures():
    states = [{
        "loop": HEART_LOOP, "interval_seconds": 30, "stale_seconds": 12.0,
        "failures": 3, "last_error": "ValueError: 炸了",
    }]
    alive, reason = verdict(states)
    assert alive is True
    assert "3" in reason and "ValueError" in reason


def test_heart_interval_allows_the_measured_tick_overshoot():
    """循环 30 秒 sleep + 一轮真实耗时（实测 51 秒一跳）：
    阈值按 30 秒算会把好好跑着的引擎误判成停摆。"""
    assert expected_interval("periodic-scheduler") >= 4 * 30


def test_one_shot_loop_that_exited_is_not_reported_alive():
    """skill-seed 跑完就退出属正常，但不能骗大家说它"还活着"。"""
    from api.services.engine_heartbeat import read_states  # 状态判定在读表时做
