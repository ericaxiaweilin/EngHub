"""Thread/Turn ownership for the chat harness.

The first migration slice used an in-process dictionary, which is enough for a
single Uvicorn worker but not for the production compose file where multiple
workers may share one Redis service.  This module keeps the same small API and
adds an optional Redis lease:

* ``REDIS_URL`` configured: acquire a renewable distributed lease first;
* Redis unavailable: fail open to the process-local lock so model availability
  is not turned into a hard outage;
* cancellation is mirrored through Redis and watched by the owning worker;
* lease loss is treated as cancellation to avoid continuing after ownership
  may have expired.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - requirements.txt includes redis
    Redis = None  # type: ignore[assignment,misc]


_logger = logging.getLogger("engflow_thread_manager")


@dataclass(frozen=True)
class LeaseHandle:
    thread_id: str
    turn_id: str
    token: str
    key: str


class RedisThreadLease:
    """Small Redis SET NX lease with token-checked renew/release operations."""

    _RENEW_SCRIPT = """
    local value = redis.call('get', KEYS[1])
    if value and string.find(value, '"token":"' .. ARGV[1] .. '"', 1, true) then
        return redis.call('expire', KEYS[1], ARGV[2])
    end
    return 0
    """
    _RELEASE_SCRIPT = """
    local value = redis.call('get', KEYS[1])
    if value and string.find(value, '"token":"' .. ARGV[1] .. '"', 1, true) then
        return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 900,
        key_prefix: str = "enghub:chat:thread",
    ) -> None:
        if Redis is None:  # pragma: no cover - guarded by create_default
            raise RuntimeError("redis package is not installed")
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.key_prefix = key_prefix.rstrip(":")
        self._redis = Redis.from_url(url, decode_responses=True)

    def _key(self, thread_id: str) -> str:
        return f"{self.key_prefix}:{thread_id}:lease"

    def _cancel_key(self, thread_id: str, turn_id: str) -> str:
        return f"{self.key_prefix}:{thread_id}:cancel:{turn_id}"

    def _steer_key(self, thread_id: str, turn_id: str) -> str:
        return f"{self.key_prefix}:{thread_id}:steer:{turn_id}"

    async def acquire(
        self,
        thread_id: str,
        turn_id: str,
    ) -> Tuple[Optional[LeaseHandle], Optional[Dict[str, Any]]]:
        token = uuid.uuid4().hex
        key = self._key(thread_id)
        value = json.dumps(
            {
                "token": token,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "started_at": time.time(),
            },
            separators=(",", ":"),
        )
        acquired = await self._redis.set(
            key,
            value,
            nx=True,
            ex=self.ttl_seconds,
        )
        if acquired:
            return LeaseHandle(thread_id, turn_id, token, key), None
        return None, await self.owner(thread_id)

    async def owner(self, thread_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._key(thread_id))
        if not raw:
            return None
        try:
            owner = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            owner = {"turn_id": "unknown"}
        owner["thread_id"] = thread_id
        return owner

    async def renew(self, handle: LeaseHandle) -> bool:
        result = await self._redis.eval(
            self._RENEW_SCRIPT,
            1,
            handle.key,
            handle.token,
            self.ttl_seconds,
        )
        return bool(result)

    async def release(self, handle: LeaseHandle) -> bool:
        result = await self._redis.eval(
            self._RELEASE_SCRIPT,
            1,
            handle.key,
            handle.token,
        )
        return bool(result)

    async def request_cancel(
        self,
        thread_id: str,
        turn_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        current = await self.owner(thread_id)
        if current is None:
            return None
        owner_turn = str(current.get("turn_id") or "")
        if turn_id and owner_turn != turn_id:
            return None
        target_turn = turn_id or owner_turn
        await self._redis.set(
            self._cancel_key(thread_id, target_turn),
            "1",
            ex=self.ttl_seconds,
        )
        current["cancel_requested"] = True
        current["state"] = "cancelling"
        return current

    async def is_cancelled(self, thread_id: str, turn_id: str) -> bool:
        return bool(await self._redis.exists(self._cancel_key(thread_id, turn_id)))

    async def clear_cancel(self, thread_id: str, turn_id: str) -> None:
        await self._redis.delete(self._cancel_key(thread_id, turn_id))

    async def request_steer(
        self,
        thread_id: str,
        turn_id: Optional[str],
        messages: list[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Queue mid-turn input for the worker that owns the Redis lease."""
        current = await self.owner(thread_id)
        if current is None:
            return None
        owner_turn = str(current.get("turn_id") or "")
        if turn_id and owner_turn != turn_id:
            return None
        target_turn = turn_id or owner_turn
        key = self._steer_key(thread_id, target_turn)
        await self._redis.rpush(
            key,
            json.dumps(messages, ensure_ascii=False, separators=(",", ":")),
        )
        await self._redis.expire(key, self.ttl_seconds)
        current["steer_requested"] = True
        current["state"] = "steering"
        return current

    async def drain_steer(
        self,
        thread_id: str,
        turn_id: str,
    ) -> list[Dict[str, Any]]:
        """Atomically take all queued steering messages for an active turn."""
        key = self._steer_key(thread_id, turn_id)
        script = """
        local items = redis.call('lrange', KEYS[1], 0, -1)
        redis.call('del', KEYS[1])
        return items
        """
        raw_items = await self._redis.eval(script, 1, key)
        messages: list[Dict[str, Any]] = []
        for raw in raw_items or []:
            try:
                item = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(item, list):
                messages.extend(part for part in item if isinstance(part, dict))
        return messages

    async def clear_steer(self, thread_id: str, turn_id: str) -> None:
        await self._redis.delete(self._steer_key(thread_id, turn_id))

    async def close(self) -> None:
        await self._redis.aclose()


def _default_lease() -> Optional[RedisThreadLease]:
    url = os.getenv("REDIS_URL", "").strip()
    enabled = os.getenv("CHAT_THREAD_DISTRIBUTED_LEASE_ENABLED", "1").lower()
    if not url or enabled in {"0", "false", "no", "off"} or Redis is None:
        return None
    try:
        return RedisThreadLease(
            url,
            ttl_seconds=int(os.getenv("CHAT_THREAD_LEASE_TTL_SECONDS", "900")),
            key_prefix=os.getenv("CHAT_THREAD_LEASE_KEY_PREFIX", "enghub:chat:thread"),
        )
    except Exception:  # pragma: no cover - configuration failure fallback
        _logger.warning("[thread-lease] Redis lease disabled during initialization", exc_info=True)
        return None


@dataclass
class ThreadRun:
    thread_id: str
    turn_id: str
    state: str = "running"  # running | cancelling | completed | failed | cancelled
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    lease_backend: str = "process"
    lease_lost: bool = False
    lease_handle: Optional[LeaseHandle] = field(default=None, repr=False, compare=False)
    heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    cancel_watch_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    steer_watch_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    steer_queue: asyncio.Queue = field(
        default_factory=asyncio.Queue, repr=False, compare=False,
    )
    steer_count: int = 0

    @property
    def cancel_requested(self) -> bool:
        return self.cancel_event.is_set()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        if self.state == "running":
            self.state = "cancelling"
        self.updated_at = time.time()

    def enqueue_steer(self, messages: list[Dict[str, Any]]) -> None:
        if not messages:
            return
        self.steer_queue.put_nowait(list(messages))
        self.steer_count += len(messages)
        self.updated_at = time.time()

    async def drain_steer(self) -> list[Dict[str, Any]]:
        messages: list[Dict[str, Any]] = []
        while True:
            try:
                messages.extend(self.steer_queue.get_nowait())
            except asyncio.QueueEmpty:
                return messages

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "state": self.state,
            "cancel_requested": self.cancel_requested,
            "lease_backend": self.lease_backend,
            "lease_lost": self.lease_lost,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "steer_pending": self.steer_queue.qsize(),
            "steer_count": self.steer_count,
        }


class ThreadBusyError(RuntimeError):
    """A thread already has an active turn."""


class ThreadManager:
    """Own one active turn per durable chat thread.

    The process-local map remains the fast path.  A configured Redis lease
    extends ownership across workers; any Redis failure deliberately falls
    back to the local map so a cache outage cannot take down chat.
    """

    def __init__(self, *, lease_backend: Optional[RedisThreadLease] = None) -> None:
        self._active: Dict[str, ThreadRun] = {}
        self._last: Dict[str, ThreadRun] = {}
        self._lock = asyncio.Lock()
        self._lease = lease_backend if lease_backend is not None else _default_lease()

    async def begin(self, thread_id: str, turn_id: str) -> ThreadRun:
        async with self._lock:
            current = self._active.get(thread_id)
            if current is not None and current.state in {"running", "cancelling"}:
                raise ThreadBusyError(
                    f"thread {thread_id} already has active turn {current.turn_id}"
                )

            handle = None
            lease_backend_name = "process"
            if self._lease is not None:
                try:
                    handle, owner = await self._lease.acquire(thread_id, turn_id)
                except Exception:  # noqa: BLE001
                    # Availability wins over a cache dependency.  The state
                    # endpoint exposes the fallback so operators can see it.
                    _logger.warning(
                        "[thread-lease] Redis unavailable; using process lock for %s",
                        thread_id,
                        exc_info=True,
                    )
                    self._lease = None
                else:
                    if handle is None:
                        owner_turn = (owner or {}).get("turn_id") or "unknown"
                        raise ThreadBusyError(
                            f"thread {thread_id} already has active turn {owner_turn}"
                        )
                    lease_backend_name = "redis"

            run = ThreadRun(
                thread_id=thread_id,
                turn_id=turn_id,
                lease_backend=lease_backend_name,
                lease_handle=handle,
            )
            self._active[thread_id] = run
            if handle is not None:
                run.heartbeat_task = asyncio.create_task(self._heartbeat(run))
                run.cancel_watch_task = asyncio.create_task(self._watch_cancel(run))
                run.steer_watch_task = asyncio.create_task(self._watch_steer(run))
            return run

    async def finish(self, thread_id: str, turn_id: str, state: str) -> None:
        async with self._lock:
            current = self._active.get(thread_id)
            if current is None or current.turn_id != turn_id:
                return
            current.state = state if state in {
                "completed", "failed", "cancelled", "cancelling"
            } else "failed"
            current.updated_at = time.time()
            self._last[thread_id] = current
            self._active.pop(thread_id, None)

        if self._lease is not None and current.lease_handle is not None:
            try:
                # Release ownership before awaiting watcher cancellation.  A
                # slow Redis poller must never leave a completed turn locked
                # for the full lease TTL.
                await self._lease.release(current.lease_handle)
                await self._lease.clear_cancel(thread_id, turn_id)
                await self._lease.clear_steer(thread_id, turn_id)
            except Exception:  # noqa: BLE001
                _logger.debug("[thread-lease] release failed for %s", thread_id, exc_info=True)
        await self._stop_background_tasks(current)

    async def steer(
        self,
        thread_id: str,
        messages: list[Dict[str, Any]],
        turn_id: Optional[str] = None,
    ) -> Optional[ThreadRun]:
        """Inject user input into the active turn, locally or via Redis."""
        if not messages:
            return None
        async with self._lock:
            current = self._active.get(thread_id)
            if current is not None:
                if current.state not in {"running", "steering"}:
                    return None
                if turn_id and current.turn_id != turn_id:
                    return None
                current.enqueue_steer(messages)
                return current

        if self._lease is None:
            return None
        try:
            owner = await self._lease.request_steer(thread_id, turn_id, messages)
        except Exception:  # noqa: BLE001
            _logger.debug("[thread-lease] cross-worker steer failed", exc_info=True)
            return None
        if owner is None:
            return None
        return ThreadRun(
            thread_id=thread_id,
            turn_id=str(owner.get("turn_id") or turn_id or ""),
            state="steering",
            started_at=float(owner.get("started_at") or time.time()),
            lease_backend="redis",
            steer_count=len(messages),
        )

    async def drain_steer(self, run: ThreadRun) -> list[Dict[str, Any]]:
        """Drain local and cross-worker steering input at a round boundary."""
        messages = await run.drain_steer()
        if self._lease is None or run.lease_handle is None:
            return messages
        try:
            messages.extend(await self._lease.drain_steer(run.thread_id, run.turn_id))
        except Exception:  # noqa: BLE001
            _logger.debug("[thread-lease] direct steer drain failed", exc_info=True)
        return messages

    async def cancel(self, thread_id: str, turn_id: Optional[str] = None) -> Optional[ThreadRun]:
        async with self._lock:
            current = self._active.get(thread_id)
            if current is not None:
                if turn_id and current.turn_id != turn_id:
                    return None
                current.request_cancel()
                local_result = current
            else:
                local_result = None

        # The request may arrive on a different worker.  Mirror the signal in
        # Redis; the owning worker's watcher turns it into its local Event.
        if self._lease is not None and local_result is None:
            try:
                owner = await self._lease.request_cancel(thread_id, turn_id)
            except Exception:  # noqa: BLE001
                _logger.debug("[thread-lease] cross-worker cancel failed", exc_info=True)
                owner = None
            if owner is not None:
                return ThreadRun(
                    thread_id=thread_id,
                    turn_id=str(owner.get("turn_id") or turn_id or ""),
                    state="cancelling",
                    started_at=float(owner.get("started_at") or time.time()),
                    lease_backend="redis",
                )

        if local_result is not None and self._lease is not None:
            try:
                await self._lease.request_cancel(thread_id, local_result.turn_id)
            except Exception:  # noqa: BLE001
                _logger.debug("[thread-lease] cancel mirror failed", exc_info=True)
        return local_result

    async def describe(self, thread_id: str) -> dict:
        async with self._lock:
            current = self._active.get(thread_id)
            last = self._last.get(thread_id)
            if current is not None:
                return current.to_dict()

        if self._lease is not None:
            try:
                owner = await self._lease.owner(thread_id)
            except Exception:  # noqa: BLE001
                owner = None
            if owner is not None:
                return {
                    "thread_id": thread_id,
                    "turn_id": owner.get("turn_id"),
                    "state": "running",
                    "cancel_requested": False,
                    "lease_backend": "redis",
                    "started_at": owner.get("started_at"),
                }
        if last is not None:
            return last.to_dict()
        return {
            "thread_id": thread_id,
            "state": "idle",
            "cancel_requested": False,
            "lease_backend": "redis" if self._lease is not None else "process",
        }

    async def _heartbeat(self, run: ThreadRun) -> None:
        if self._lease is None or run.lease_handle is None:
            return
        interval = max(5.0, self._lease.ttl_seconds / 3)
        try:
            while not run.cancel_event.is_set():
                await asyncio.sleep(interval)
                if not await self._lease.renew(run.lease_handle):
                    run.lease_lost = True
                    run.request_cancel()
                    _logger.error(
                        "[thread-lease] ownership lost; cancelling thread=%s turn=%s",
                        run.thread_id,
                        run.turn_id,
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            run.lease_lost = True
            run.request_cancel()
            _logger.exception("[thread-lease] heartbeat failed for %s", run.thread_id)

    async def _watch_cancel(self, run: ThreadRun) -> None:
        if self._lease is None or run.lease_handle is None:
            return
        while not run.cancel_event.is_set():
            try:
                await asyncio.sleep(0.5)
                if await self._lease.is_cancelled(run.thread_id, run.turn_id):
                    run.request_cancel()
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # Heartbeat is the ownership safety net; a transient read
                # error should not cancel a healthy request. Keep watching so
                # a later remote cancellation is not lost.
                _logger.debug("[thread-lease] cancel watcher failed", exc_info=True)
                await asyncio.sleep(0.5)

    async def _watch_steer(self, run: ThreadRun) -> None:
        if self._lease is None or run.lease_handle is None:
            return
        while not run.cancel_event.is_set():
            try:
                messages = await self._lease.drain_steer(run.thread_id, run.turn_id)
                if messages:
                    run.enqueue_steer(messages)
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _logger.debug("[thread-lease] steer watcher failed", exc_info=True)
                await asyncio.sleep(0.5)

    @staticmethod
    async def _stop_background_tasks(run: ThreadRun) -> None:
        tasks = [run.heartbeat_task, run.cancel_watch_task, run.steer_watch_task]
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        active = [task for task in tasks if task is not None]
        if active:
            await asyncio.gather(*active, return_exceptions=True)


_THREAD_MANAGER = ThreadManager()


def get_thread_manager() -> ThreadManager:
    return _THREAD_MANAGER
