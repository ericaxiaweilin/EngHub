"""Checkpoint - Agent Loop 断点保存 / 恢复。

Phase 1: 内存实现（进程内 dict），支撑后续 Phase 3 迁移到 DB。
Checkpoint 记录一轮工具执行完成时的状态快照，失败时可从最近断点重放，
避免从零重跑已验证的工具调用。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional


_logger = logging.getLogger("engflow_checkpoint")


class CheckpointManager:
    """Checkpoint 存储。

    - save: 在每轮工具执行完成后写入一条快照
    - restore: 取最近一条满足要求的快照
    - clear: 清空单次请求的全部快照
    - save_async / restore_async: 可选 DB 冷存储，失败时保持内存行为
    """

    def __init__(
        self,
        max_per_request: int = 20,
        session_factory: Optional[Callable[[], Any]] = None,
        persistence_enabled: bool = False,
    ) -> None:
        self._store: Dict[str, List[Dict[str, Any]]] = {}
        self._max_per_request = max_per_request
        self._session_factory = session_factory
        self._persistence_enabled = bool(persistence_enabled and session_factory)

    def configure_persistence(
        self,
        session_factory: Optional[Callable[[], Any]],
        *,
        enabled: bool = True,
    ) -> None:
        """配置可选的异步数据库持久化。"""
        self._session_factory = session_factory
        self._persistence_enabled = bool(enabled and session_factory)

    @property
    def persistence_enabled(self) -> bool:
        return self._persistence_enabled

    @staticmethod
    def fingerprint(messages: List[Dict[str, Any]]) -> str:
        """对当前 messages 计算指纹，用于检测是否有新区块。"""
        serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def save(self, request_id: str, *, messages: List[Dict[str, Any]], actions_count: int) -> str:
        """保存一条断点。返回 checkpoint_key。"""
        key = f"chk-{uuid.uuid4().hex[:12]}"
        entry = {
            "key": key,
            "request_id": request_id,
            "ts": time.time(),
            "messages_fp": self.fingerprint(messages),
            "message_count": len(messages),
            "actions_count": actions_count,
            # Phase 1 先保存在进程内；后续迁移 DB 时可直接用此快照重建 loop。
            "messages": deepcopy(messages),
        }
        buf = self._store.setdefault(request_id, [])
        buf.append(entry)
        if len(buf) > self._max_per_request:
            self._store[request_id] = buf[-self._max_per_request:]
        return key

    async def save_async(
        self,
        request_id: str,
        *,
        messages: List[Dict[str, Any]],
        actions_count: int,
    ) -> str:
        """保存热快照，并在启用时写入 ``agent_checkpoints``。"""
        key = self.save(request_id, messages=messages, actions_count=actions_count)
        if not self._persistence_enabled or self._session_factory is None:
            return key

        entry = self.restore(request_id, up_to_key=key)
        if entry is None:
            return key
        try:
            from database.models import AgentCheckpointRecord

            async with self._session_factory() as db:
                db.add(
                    AgentCheckpointRecord(
                        checkpoint_key=entry["key"],
                        request_id=request_id,
                        messages=entry["messages"],
                        messages_fp=entry["messages_fp"],
                        message_count=entry["message_count"],
                        actions_count=entry["actions_count"],
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[checkpoint] DB save failed for %s: %s", request_id, exc)
        return key

    def latest(self, request_id: str) -> Optional[Dict[str, Any]]:
        """取最近一条断点。"""
        buf = self._store.get(request_id, [])
        return buf[-1] if buf else None

    def has(self, request_id: str) -> bool:
        return bool(self._store.get(request_id))

    def clear(self, request_id: str) -> None:
        self._store.pop(request_id, None)

    def restore(
        self, request_id: str, *, up_to_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """从最近的断点恢复（可选指定断点 key）。"""
        buf = self._store.get(request_id, [])
        if not buf:
            return None
        if up_to_key is None:
            return buf[-1]
        for entry in reversed(buf):
            if entry["key"] == up_to_key:
                return entry
        return None

    async def restore_async(
        self,
        request_id: str,
        *,
        up_to_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """先查内存；进程重启后从 DB 恢复最近断点。"""
        entry = self.restore(request_id, up_to_key=up_to_key)
        if entry is not None or not self._persistence_enabled or self._session_factory is None:
            return entry

        try:
            from sqlalchemy import select
            from database.models import AgentCheckpointRecord

            async with self._session_factory() as db:
                result = await db.execute(
                    select(AgentCheckpointRecord)
                    .where(AgentCheckpointRecord.request_id == request_id)
                    .order_by(AgentCheckpointRecord.created_at.desc())
                    .limit(self._max_per_request)
                )
                rows = list(result.scalars().all())
            for row in rows:
                if up_to_key is not None and row.checkpoint_key != up_to_key:
                    continue
                entry = {
                    "key": row.checkpoint_key,
                    "request_id": row.request_id,
                    "ts": row.created_at.timestamp() if row.created_at else time.time(),
                    "messages_fp": row.messages_fp,
                    "message_count": row.message_count,
                    "actions_count": row.actions_count,
                    "messages": deepcopy(row.messages or []),
                }
                buf = self._store.setdefault(request_id, [])
                buf.append(entry)
                self._store[request_id] = buf[-self._max_per_request:]
                return entry
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[checkpoint] DB restore failed for %s: %s", request_id, exc)
        return None

    async def clear_async(self, request_id: str) -> None:
        """清理内存及 DB 中指定请求的断点。"""
        self.clear(request_id)
        if not self._persistence_enabled or self._session_factory is None:
            return
        try:
            from sqlalchemy import delete
            from database.models import AgentCheckpointRecord

            async with self._session_factory() as db:
                await db.execute(
                    delete(AgentCheckpointRecord).where(
                        AgentCheckpointRecord.request_id == request_id
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[checkpoint] DB clear failed for %s: %s", request_id, exc)
