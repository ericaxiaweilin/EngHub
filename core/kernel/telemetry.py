"""Telemetry - 结构化遥测。

Phase 1: 写入内存 ring + logger。Phase 3 持久化到 chat_telemetry 表。
记录一次 Chat V2 请求的关键过程指标，供 Engineering Surface 的 Trace /
Failure Analysis 消费。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("engflow_telemetry")

_TELEMETRY_RING_MAX = 1000


@dataclass
class TelemetryEvent:
    request_id: str
    phase: str                     # resolve_route | intent | tool_loop | grounding | response
    duration_ms: float = 0.0
    model: str = ""
    tools_called: List[str] = field(default_factory=list)
    rounds: int = 0
    success: bool = True
    error: Optional[str] = None
    provider: str = ""
    task_id: str = ""
    event_id: str = field(default_factory=lambda: f"tl-{uuid.uuid4().hex[:12]}")
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Telemetry:
    """进程内遥测聚合器（单例）。"""

    _instance: Optional["Telemetry"] = None

    def __init__(self) -> None:
        self._ring: List[TelemetryEvent] = []
        self._max = _TELEMETRY_RING_MAX

    @classmethod
    def get_instance(cls) -> "Telemetry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record(self, event: TelemetryEvent) -> None:
        self._ring.append(event)
        if len(self._ring) > self._max:
            self._ring = self._ring[-self._max:]
        _logger.debug(
            "[telemetry] %s phase=%s du=%.1fms rounds=%d success=%s model=%s err=%s",
            event.request_id, event.phase, event.duration_ms, event.rounds,
            event.success, event.model, event.error or "-",
        )

    def timed(self, request_id: str, phase: str, **kwargs: Any) -> "TelTimer":
        return TelTimer(self, request_id, phase, **kwargs)

    def query(self, request_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        events = self._ring
        if request_id:
            events = [e for e in events if e.request_id == request_id]
        return [e.to_dict() for e in events[-limit:]]

    def failures(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [
            e.to_dict()
            for e in self._ring
            if not e.success and e.error
        ][-limit:]


class TelTimer:
    """上下文计时器：with 块结束自动记录一个 TelemetryEvent。"""

    def __init__(self, telemetry: Telemetry, request_id: str, phase: str, **fields: Any) -> None:
        self._tel = telemetry
        self._evt = TelemetryEvent(request_id=request_id, phase=phase, **fields)
        self._start = time.monotonic()

    def __enter__(self) -> "TelTimer":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._evt.duration_ms = (time.monotonic() - self._start) * 1000
        self._evt.success = exc is None
        if exc is not None:
            self._evt.error = f"{type(exc).__name__}: {exc}"
        self._tel.record(self._evt)