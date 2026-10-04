"""虚拟工厂的仿真时钟与事件队列 —— **纯内存，不下盘**。

为什么不放数据库：
- 时钟和事件队列是"仿真过程状态"，不是业务数据，没有审计价值；
- 每次 pulse 都写库会放大 WAL 和表膨胀 —— 这正是要压掉的写入放大；
- 不新增表，省掉一次迁移。

放 Redis（内存、可跨 worker 共享；uvicorn `--workers 2` 时进程内 dict 会不一致）。
没有 Redis 时退回进程内 dict —— **仍然不下盘**，只是多 worker 之间不共享，
最坏结果是时钟多走几次，不影响业务数据正确性。

所有键都带 TTL，Redis 内存有界。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - requirements.txt includes redis
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore[assignment]


KEY_PREFIX = os.getenv("VF_CLOCK_KEY_PREFIX", "enghub:vf")
# 时钟键的兜底 TTL（秒）。每次 pulse 都会续，正常不会被清。
CLOCK_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_EVENT_QUEUE_MAX = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VirtualFactoryClock:
    """仿真时钟 + 事件队列（Redis 优先，进程内 dict 兜底）。"""

    def __init__(self) -> None:
        self._redis: Optional[Any] = None
        self._redis_failed = False
        # 兜底：进程内状态。仅在没有 Redis 时用，不写磁盘。
        self._local_clock: Dict[str, float] = {}
        self._local_events: Dict[str, List[Dict[str, Any]]] = {}
        self._local_flags: Dict[str, float] = {}

    # ── 后端 ──────────────────────────────────────────────────────────
    def _client(self) -> Optional[Any]:
        if self._redis is not None or self._redis_failed:
            return self._redis
        url = os.getenv("REDIS_URL", "").strip()
        if not url or Redis is None:
            self._redis_failed = True
            return None
        try:
            self._redis = Redis.from_url(url, decode_responses=True)
        except Exception:  # noqa: BLE001 - 配置兜底，退回进程内
            self._redis_failed = True
            self._redis = None
        return self._redis

    @property
    def backend(self) -> str:
        return "redis" if self._client() is not None else "memory"

    def _key(self, factory_id: str, suffix: str) -> str:
        return f"{KEY_PREFIX}:{factory_id}:{suffix}"

    # ── 时钟 ──────────────────────────────────────────────────────────
    async def now(self, factory_id: str) -> datetime:
        """当前仿真时间。未初始化时以真实时间为起点。"""
        client = self._client()
        key = self._key(factory_id, "clock")
        if client is not None:
            try:
                raw = await client.get(key)
                if raw is None:
                    ts = time.time()
                    await client.set(key, ts, nx=True, ex=CLOCK_TTL_SECONDS)
                    raw = await client.get(key)
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
        ts = self._local_clock.get(factory_id)
        if ts is None:
            # 与 Redis 分支的 set(nx=True) 同口径：起点第一次读到就冻结，
            # 否则没 advance 之前 now() 会跟着真实时间一起走。
            ts = time.time()
            self._local_clock[factory_id] = ts
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    async def advance(self, factory_id: str, step_hours: float) -> datetime:
        """把仿真时钟推进 step_hours 小时，返回推进后的时间。"""
        client = self._client()
        key = self._key(factory_id, "clock")
        delta = float(step_hours) * 3600.0
        if client is not None:
            try:
                await self.now(factory_id)  # 确保已初始化
                new_ts = float(await client.incrbyfloat(key, delta))
                await client.expire(key, CLOCK_TTL_SECONDS)
                return datetime.fromtimestamp(new_ts, tz=timezone.utc)
            except Exception:  # noqa: BLE001
                pass
        cur = (await self.now(factory_id)).timestamp()
        self._local_clock[factory_id] = cur + delta
        return datetime.fromtimestamp(self._local_clock[factory_id], tz=timezone.utc)

    async def reset(self, factory_id: str) -> None:
        """清空时钟/事件/标记（测试与手动重来用）。"""
        client = self._client()
        claim_prefix = self._key(factory_id, "claim:")
        if client is not None:
            try:
                await client.delete(
                    self._key(factory_id, "clock"),
                    self._key(factory_id, "events"),
                )
                async for slot_key in client.scan_iter(match=f"{claim_prefix}*"):
                    await client.delete(slot_key)
            except Exception:  # noqa: BLE001
                pass
        self._local_clock.pop(factory_id, None)
        self._local_events.pop(factory_id, None)
        for slot_key in [k for k in self._local_flags if k.startswith(claim_prefix)]:
            self._local_flags.pop(slot_key, None)

    # ── 事件队列（有界，纯内存）────────────────────────────────────────
    async def push_events(
        self,
        factory_id: str,
        events: List[Dict[str, Any]],
        max_len: int = DEFAULT_EVENT_QUEUE_MAX,
    ) -> int:
        """入队事件。队列有上界，超出部分丢弃最旧的 —— 不让它变成新的写入放大源。"""
        if not events:
            return 0
        client = self._client()
        key = self._key(factory_id, "events")
        payload = [
            json.dumps(e, ensure_ascii=False, default=str) for e in events
        ]
        if client is not None:
            try:
                await client.lpush(key, *payload)
                await client.ltrim(key, 0, max_len - 1)
                await client.expire(key, CLOCK_TTL_SECONDS)
                return len(payload)
            except Exception:  # noqa: BLE001
                pass
        buf = self._local_events.setdefault(factory_id, [])
        buf[:0] = list(reversed(events))
        del buf[max_len:]
        return len(events)

    async def recent_events(self, factory_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """取最近事件（新的在前）。"""
        client = self._client()
        key = self._key(factory_id, "events")
        if client is not None:
            try:
                raw = await client.lrange(key, 0, max(0, limit) - 1)
                out: List[Dict[str, Any]] = []
                for item in raw:
                    try:
                        out.append(json.loads(item))
                    except Exception:  # noqa: BLE001
                        continue
                return out
            except Exception:  # noqa: BLE001
                pass
        return list(self._local_events.get(factory_id, []))[:limit]

    # ── 去重用的一次性标记 ────────────────────────────────────────────
    async def claim(self, factory_id: str, slot: str, ttl_seconds: int) -> bool:
        """抢占一个带 TTL 的标记。抢到返回 True（该做某事），已被占返回 False（跳过）。

        用于两类去写：
        - 种子数据（product/station/IE）已就绪就别每轮再查一遍；
        - 预警在 TTL 内只发一次，别每轮插一条 Notification。
        """
        client = self._client()
        key = self._key(factory_id, f"claim:{slot}")
        if client is not None:
            try:
                return bool(await client.set(key, "1", nx=True, ex=max(1, int(ttl_seconds))))
            except Exception:  # noqa: BLE001
                pass
        now = time.time()
        until = self._local_flags.get(key, 0.0)
        if until > now:
            return False
        self._local_flags[key] = now + max(1, int(ttl_seconds))
        return True

    async def release(self, factory_id: str, slot: str) -> None:
        client = self._client()
        key = self._key(factory_id, f"claim:{slot}")
        if client is not None:
            try:
                await client.delete(key)
            except Exception:  # noqa: BLE001
                pass
        self._local_flags.pop(key, None)


# 进程内单例：时钟/队列是进程级共享状态，不需要按请求新建。
_clock = VirtualFactoryClock()


def get_clock() -> VirtualFactoryClock:
    return _clock
