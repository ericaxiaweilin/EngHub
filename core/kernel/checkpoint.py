"""Checkpoint - Agent Loop 断点保存 / 恢复。

Phase 1: 内存实现（进程内 dict），支撑后续 Phase 3 迁移到 DB。
Checkpoint 记录一轮工具执行完成时的状态快照，失败时可从最近断点重放，
避免从零重跑已验证的工具调用。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional


class CheckpointManager:
    """进程内 Checkpoint 存储。

    - save: 在每轮工具执行完成后写入一条快照
    - restore: 取最近一条满足要求的快照
    - clear: 清空单次请求的全部快照
    """

    def __init__(self, max_per_request: int = 20) -> None:
        self._store: Dict[str, List[Dict[str, Any]]] = {}
        self._max_per_request = max_per_request

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
        }
        buf = self._store.setdefault(request_id, [])
        buf.append(entry)
        if len(buf) > self._max_per_request:
            self._store[request_id] = buf[-self._max_per_request:]
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