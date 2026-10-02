"""Durable-shaped events for the EngHub chat harness.

The Codex App Server model is deliberately small: a thread contains turns,
and a turn produces items whose lifecycle can be replayed by any client.  The
business payloads remain EngHub-specific; this module only owns the runtime
envelope and an in-process fan-out bus used by HTTP/SSE adapters.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Set

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - requirements.txt includes redis
    Redis = None  # type: ignore[assignment,misc]


EventPersistFn = Callable[["HarnessEvent"], Awaitable[None]]


class RedisEventSequence:
    """Atomically allocate per-thread event cursors across workers."""

    _NEXT_SCRIPT = """
    local current = tonumber(redis.call('get', KEYS[1]) or '0')
    local floor = tonumber(ARGV[1])
    if current < floor then
        redis.call('set', KEYS[1], floor)
    end
    return redis.call('incr', KEYS[1])
    """

    def __init__(self, url: str, *, key_prefix: str = "enghub:chat:event-sequence") -> None:
        if Redis is None:  # pragma: no cover - guarded by _default_sequence_backend
            raise RuntimeError("redis package is not installed")
        self.key_prefix = key_prefix.rstrip(":")
        self._redis = Redis.from_url(url, decode_responses=True)

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}:{session_id}"

    async def next(self, session_id: str, floor: int) -> int:
        return int(await self._redis.eval(self._NEXT_SCRIPT, 1, self._key(session_id), floor))


def _default_sequence_backend() -> Optional[RedisEventSequence]:
    url = os.getenv("REDIS_URL", "").strip()
    enabled = os.getenv("CHAT_EVENT_DISTRIBUTED_SEQUENCE_ENABLED", "1").lower()
    if not url or enabled in {"0", "false", "no", "off"} or Redis is None:
        return None
    try:
        return RedisEventSequence(
            url,
            key_prefix=os.getenv(
                "CHAT_EVENT_SEQUENCE_KEY_PREFIX",
                "enghub:chat:event-sequence",
            ),
        )
    except Exception:  # pragma: no cover - configuration fallback
        return None


def _json_safe(value: Any, *, max_bytes: int = 48_000) -> Any:
    """Keep event rows bounded without losing the event envelope."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)
    if len(encoded.encode("utf-8")) <= max_bytes:
        return value
    # Tool results can contain a complete workbook or a large table.  The
    # canonical result is still stored in the message/tool trace; event rows
    # are for live UI and replay navigation, so truncation is intentional.
    budget = max(256, max_bytes - 160)
    return {
        "truncated": True,
        "preview": encoded[:budget],
        "original_bytes": len(encoded.encode("utf-8")),
    }


@dataclass(frozen=True)
class HarnessEvent:
    """One replayable runtime event.

    ``session_id`` is the durable thread id and ``request_id`` is the turn id
    for the current compatibility layer.  This mapping lets existing clients
    keep using ChatSession while new clients can reason in Thread/Turn/Item
    terms.
    """

    event_id: str
    event_type: str
    session_id: str
    request_id: str
    sequence: int
    item_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["thread_id"] = self.session_id
        payload["turn_id"] = self.request_id
        return payload


class HarnessEventBus:
    """Small process-local event bus with bounded history and replay.

    Postgres is the source of truth after the event persistence callback runs;
    this ring is intentionally only the low-latency delivery path for the
    current process.  A bounded queue also prevents a slow browser from
    holding the agent loop indefinitely.
    """

    def __init__(
        self,
        *,
        history_limit: int = 2000,
        queue_limit: int = 256,
        sequence_backend: Any = None,
    ) -> None:
        self.history_limit = max(100, history_limit)
        self.queue_limit = max(16, queue_limit)
        self._history: Dict[str, deque[HarnessEvent]] = defaultdict(
            lambda: deque(maxlen=self.history_limit)
        )
        self._sequence_backend = (
            sequence_backend if sequence_backend is not None else _default_sequence_backend()
        )
        # Start from a time-based cursor so a process restart cannot reuse
        # sequence numbers already committed for the same durable thread.
        # The cursor remains strictly increasing inside this process.
        self._sequence: Dict[str, int] = defaultdict(lambda: time.time_ns() // 1_000)
        self._subscribers: Dict[str, Set[asyncio.Queue[HarnessEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def _next_sequence(self, session_id: str) -> int:
        local_floor = self._sequence[session_id] + 1
        if self._sequence_backend is not None:
            try:
                sequence = await self._sequence_backend.next(session_id, local_floor - 1)
                self._sequence[session_id] = max(self._sequence[session_id], sequence)
                return sequence
            except Exception:  # noqa: BLE001
                # Redis is a coordination optimization, not a chat availability
                # dependency.  Continue with the process cursor if it is down.
                self._sequence_backend = None
        self._sequence[session_id] = local_floor
        return local_floor

    async def emit(
        self,
        *,
        session_id: str,
        request_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None,
        persist: Optional[EventPersistFn] = None,
    ) -> HarnessEvent:
        """Publish one event and optionally persist it.

        Persistence failures are deliberately isolated from the live bus.  A
        missing/lagging event table must not turn a successful PMC answer into
        a chatbot outage; the caller may log the failure in its callback.
        """
        sid = str(session_id or "unknown")
        async with self._lock:
            sequence = await self._next_sequence(sid)
            event = HarnessEvent(
                event_id=str(uuid.uuid4()),
                event_type=event_type,
                session_id=sid,
                request_id=str(request_id or ""),
                sequence=sequence,
                item_id=item_id,
                data=_json_safe(data or {}),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._history[sid].append(event)
            subscribers = tuple(self._subscribers.get(sid, set()))

        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A reconnecting client can replay from Postgres.  Dropping a
                # live notification is safer than blocking the agent loop.
                pass

        if persist is not None:
            try:
                await persist(event)
            except Exception:  # noqa: BLE001
                # The event is still available to the current subscriber.
                pass
        return event

    def history(self, session_id: str, *, after: int = 0, limit: int = 200) -> list[HarnessEvent]:
        events = list(self._history.get(str(session_id), ()))
        return [event for event in events if event.sequence > after][-max(1, min(limit, 1000)):]

    async def subscribe(
        self,
        session_id: str,
        *,
        after: int = 0,
    ) -> AsyncIterator[HarnessEvent]:
        """Replay in-memory history, then wait for live events."""
        sid = str(session_id)
        queue: asyncio.Queue[HarnessEvent] = asyncio.Queue(maxsize=self.queue_limit)
        async with self._lock:
            self._subscribers[sid].add(queue)
            replay = [event for event in self._history.get(sid, ()) if event.sequence > after]
        try:
            for event in replay:
                yield event
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.get(sid, set()).discard(queue)


_EVENT_BUS = HarnessEventBus()


def get_harness_event_bus() -> HarnessEventBus:
    return _EVENT_BUS


def new_item_id(prefix: str = "item") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
