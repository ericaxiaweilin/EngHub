"""Interactive approval primitives for write-capable chat tools.

Approvals are part of a turn, so they must survive the HTTP request being
served by a different worker.  The manager keeps a local Future for the
fast path and mirrors request/resolution records to Redis when ``REDIS_URL``
is configured.  Redis failure falls back to the local implementation so a
cache outage does not make read-only chat unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - requirements.txt includes redis
    Redis = None  # type: ignore[assignment,misc]


_logger = logging.getLogger("engflow_approval_manager")
ApprovalNotifyFn = Callable[[Dict[str, Any]], Awaitable[None]]
CancelCheckFn = Callable[[], bool]
CancelWaitFn = Callable[[], Awaitable[None]]


class RedisApprovalStore:
    """Redis records used by approval endpoints on any worker."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 180,
        key_prefix: str = "enghub:chat:approval",
    ) -> None:
        if Redis is None:  # pragma: no cover - guarded by _default_store
            raise RuntimeError("redis package is not installed")
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.key_prefix = key_prefix.rstrip(":")
        self._redis = Redis.from_url(url, decode_responses=True)

    def _request_key(self, approval_id: str) -> str:
        return f"{self.key_prefix}:request:{approval_id}"

    def _resolution_key(self, approval_id: str) -> str:
        return f"{self.key_prefix}:resolution:{approval_id}"

    def _index_key(self, user_id: str, factory_id: str) -> str:
        return f"{self.key_prefix}:index:{user_id}:{factory_id}"

    async def create(self, record: Dict[str, Any]) -> None:
        approval_id = str(record["approval_id"])
        user_id = str(record["user_id"])
        factory_id = str(record["factory_id"])
        await self._redis.set(
            self._request_key(approval_id),
            json.dumps(record, ensure_ascii=False, default=str),
            ex=self.ttl_seconds,
        )
        index = self._index_key(user_id, factory_id)
        await self._redis.sadd(index, approval_id)
        await self._redis.expire(index, self.ttl_seconds)

    async def get_request(self, approval_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._request_key(approval_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    async def set_resolution(self, approval_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        key = self._resolution_key(approval_id)
        encoded = json.dumps(result, ensure_ascii=False, default=str)
        created = await self._redis.set(key, encoded, nx=True, ex=self.ttl_seconds)
        if created:
            return result
        existing = await self.get_resolution(approval_id)
        return existing or result

    async def get_resolution(self, approval_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._resolution_key(approval_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    async def list_for(self, *, user_id: str, factory_id: str) -> list[Dict[str, Any]]:
        index = self._index_key(str(user_id), str(factory_id))
        ids = await self._redis.smembers(index)
        rows: list[Dict[str, Any]] = []
        stale: list[str] = []
        for approval_id in ids:
            record = await self.get_request(str(approval_id))
            if record is None:
                stale.append(str(approval_id))
                continue
            rows.append(record)
        if stale:
            await self._redis.srem(index, *stale)
        return rows

    async def delete(self, record: Dict[str, Any]) -> None:
        approval_id = str(record["approval_id"])
        await self._redis.delete(
            self._request_key(approval_id),
            self._resolution_key(approval_id),
        )
        await self._redis.srem(
            self._index_key(str(record["user_id"]), str(record["factory_id"])),
            approval_id,
        )


def _default_store(timeout_seconds: float) -> Optional[RedisApprovalStore]:
    url = os.getenv("REDIS_URL", "").strip()
    enabled = os.getenv("CHAT_APPROVAL_DISTRIBUTED_ENABLED", "1").lower()
    if not url or enabled in {"0", "false", "no", "off"} or Redis is None:
        return None
    try:
        return RedisApprovalStore(
            url,
            ttl_seconds=max(30, int(timeout_seconds) + 60),
            key_prefix=os.getenv("CHAT_APPROVAL_KEY_PREFIX", "enghub:chat:approval"),
        )
    except Exception:  # pragma: no cover - configuration fallback
        _logger.warning("[approval] Redis store disabled during initialization", exc_info=True)
        return None


@dataclass
class PendingApproval:
    approval_id: str
    user_id: str
    factory_id: str
    session_id: str
    request_id: str
    tool: str
    arguments: Dict[str, Any]
    future: asyncio.Future
    notify: Optional[ApprovalNotifyFn] = None
    created_at: float = 0.0
    expires_at: float = 0.0

    def to_record(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "user_id": self.user_id,
            "factory_id": self.factory_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    def to_public(self) -> Dict[str, Any]:
        record = self.to_record()
        record.pop("user_id", None)
        record.pop("factory_id", None)
        return record


class ApprovalManager:
    """Approval manager with optional cross-worker Redis coordination."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 120.0,
        store: Optional[RedisApprovalStore] = None,
    ) -> None:
        self.timeout_seconds = max(10.0, timeout_seconds)
        self._pending: Dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()
        self._store = store if store is not None else _default_store(self.timeout_seconds)

    async def request(
        self,
        *,
        user_id: str,
        factory_id: str,
        session_id: str,
        request_id: str,
        tool: str,
        arguments: Dict[str, Any],
        notify: Optional[ApprovalNotifyFn] = None,
        cancel_check: Optional[CancelCheckFn] = None,
        cancel_wait: Optional[CancelWaitFn] = None,
    ) -> Dict[str, Any]:
        approval_id = f"approval-{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        now = time.time()
        pending = PendingApproval(
            approval_id=approval_id,
            user_id=str(user_id),
            factory_id=str(factory_id),
            session_id=str(session_id),
            request_id=str(request_id),
            tool=tool,
            arguments=arguments,
            future=loop.create_future(),
            notify=notify,
            created_at=now,
            expires_at=now + self.timeout_seconds,
        )
        async with self._lock:
            self._pending[approval_id] = pending
        await self._store_create(pending)

        await self._notify(
            pending,
            {
                "approval_id": approval_id,
                "status": "pending",
                "tool": tool,
                "arguments": arguments,
                "session_id": session_id,
                "request_id": request_id,
                "expires_at": pending.expires_at,
            },
        )
        try:
            return await self._wait_for_result(
                pending,
                cancel_check=cancel_check,
                cancel_wait=cancel_wait,
            )
        finally:
            async with self._lock:
                self._pending.pop(approval_id, None)
            await self._store_delete(pending)

    async def resolve(
        self,
        approval_id: str,
        *,
        user_id: str,
        factory_id: str,
        approved: bool,
        comment: str = "",
    ) -> Optional[Dict[str, Any]]:
        async with self._lock:
            pending = self._pending.get(approval_id)
        record = pending.to_record() if pending is not None else await self._store_request(approval_id)
        if record is None:
            return None
        if record.get("user_id") != str(user_id) or record.get("factory_id") != str(factory_id):
            raise PermissionError("无权处理该审批请求")
        result = {
            "approved": bool(approved),
            "approval_id": approval_id,
            "status": "approved" if approved else "rejected",
            "comment": comment or "",
        }
        remote_result = await self._store_resolution(approval_id, result)
        result = remote_result or result
        if pending is not None:
            if not pending.future.done():
                pending.future.set_result(result)
            await self._notify(pending, result)
        return result

    async def _wait_for_result(
        self,
        pending: PendingApproval,
        *,
        cancel_check: Optional[CancelCheckFn],
        cancel_wait: Optional[CancelWaitFn],
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            if cancel_check is not None and cancel_check():
                return {
                    "approved": False,
                    "approval_id": pending.approval_id,
                    "status": "cancelled",
                    "reason": "turn 已取消，写操作未执行",
                }
            if pending.future.done():
                return pending.future.result()
            remote = await self._store_resolution(pending.approval_id, read_only=True)
            if remote is not None:
                await self._notify(pending, remote)
                return remote
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "approved": False,
                    "approval_id": pending.approval_id,
                    "status": "expired",
                    "reason": "审批超时，未执行写操作",
                }
            wait_timeout = min(0.5, remaining)
            if cancel_wait is None:
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(pending.future),
                        timeout=wait_timeout,
                    )
                except asyncio.TimeoutError:
                    continue

            future_wait = asyncio.shield(pending.future)
            cancel_task = asyncio.create_task(cancel_wait())
            try:
                done, _ = await asyncio.wait(
                    {future_wait, cancel_task},
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done:
                    return {
                        "approved": False,
                        "approval_id": pending.approval_id,
                        "status": "cancelled",
                        "reason": "turn 已取消，写操作未执行",
                    }
                if future_wait in done:
                    return future_wait.result()
            finally:
                if not cancel_task.done():
                    cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)

    async def _store_create(self, pending: PendingApproval) -> None:
        if self._store is None:
            return
        try:
            await self._store.create(pending.to_record())
        except Exception:  # noqa: BLE001
            _logger.warning("[approval] Redis create failed; using local approval", exc_info=True)
            self._store = None

    async def _store_request(self, approval_id: str) -> Optional[Dict[str, Any]]:
        if self._store is None:
            return None
        try:
            return await self._store.get_request(approval_id)
        except Exception:  # noqa: BLE001
            _logger.debug("[approval] Redis request lookup failed", exc_info=True)
            return None

    async def _store_resolution(
        self,
        approval_id: str,
        result: Optional[Dict[str, Any]] = None,
        *,
        read_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if self._store is None:
            return None
        try:
            if read_only:
                return await self._store.get_resolution(approval_id)
            if result is None:
                return None
            return await self._store.set_resolution(approval_id, result)
        except Exception:  # noqa: BLE001
            _logger.debug("[approval] Redis resolution operation failed", exc_info=True)
            return None

    async def _store_delete(self, pending: PendingApproval) -> None:
        if self._store is None:
            return
        try:
            await self._store.delete(pending.to_record())
        except Exception:  # noqa: BLE001
            _logger.debug("[approval] Redis cleanup failed", exc_info=True)

    async def _notify(self, pending: PendingApproval, data: Dict[str, Any]) -> None:
        if pending.notify is None:
            return
        try:
            await pending.notify(data)
        except Exception:  # noqa: BLE001
            pass

    async def pending_for(self, *, user_id: str, factory_id: str) -> list[Dict[str, Any]]:
        async with self._lock:
            local = {
                pending.approval_id: pending.to_public()
                for pending in self._pending.values()
                if pending.user_id == str(user_id) and pending.factory_id == str(factory_id)
            }
        if self._store is not None:
            try:
                for record in await self._store.list_for(user_id=user_id, factory_id=factory_id):
                    local.setdefault(
                        str(record["approval_id"]),
                        {key: value for key, value in record.items() if key not in {"user_id", "factory_id"}},
                    )
            except Exception:  # noqa: BLE001
                _logger.debug("[approval] Redis pending lookup failed", exc_info=True)
        return list(local.values())


_APPROVAL_MANAGER = ApprovalManager()


def get_approval_manager() -> ApprovalManager:
    return _APPROVAL_MANAGER
