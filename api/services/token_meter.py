"""Token 计量服务（对齐 DSH replay token-meter service）。

固定启发式：约 4 字符 / token，外加每条消息的结构化开销（role 等）。
不含模型配置/容量——容量是 provider/adapter 的独立事实（routed policy）。
供 compaction 压力判定、溢出守卫与后续 request-policy 复用同一计量。

measure_session_events(rows) -> {
  "total_tokens": 会话事件流总 token 压力（含注入上下文）
  "surface_tokens": 表面 token（全部事件启发式和）
  "log_revision": 事件流修订号（按最大 seq）
  "nodes": [{seq, kind, tokens}]
}
"""

from __future__ import annotations

from typing import Any, Dict, List

# 固定启发式：约 4 字符 / token（DSH estimateMessage 相同策略）。
CHARS_PER_TOKEN = 4
# 每条消息/事件的固定结构开销（role 标记、边界等）。
STRUCTURAL_OVERHEAD = 4

# 模型容量默认值：从环境读取（容量是路由侧事实，服务本身不配置）。
DEFAULT_CONTEXT_WINDOW = int(
    __import__("os").getenv("CHAT_CONTEXT_WINDOW_TOKENS", "128000").strip() or 128000
)
# 压力阈值比例：事件流 token 达到容量的该比例时触发自动压缩（DSH 默认 0.8）。
PRESSURE_THRESHOLD_RATIO = float(
    __import__("os").getenv("CHAT_PRESSURE_RATIO", "0.8").strip() or 0.8
)


def estimate_text(text: str) -> int:
    """固定启发式：约 4 字符 / token + 结构开销。"""
    if not text:
        return STRUCTURAL_OVERHEAD
    return max(1, len(str(text)) // CHARS_PER_TOKEN) + STRUCTURAL_OVERHEAD


def estimate_message(message: Any) -> int:
    """单条消息估算：文本 + 可选结构化载荷（JSON 序列化后估算）。"""
    if isinstance(message, str):
        return estimate_text(message)
    if isinstance(message, dict):
        text = str(message.get("content") or "")
        payload = message.get("args") or message.get("result") or message.get("data")
        extra = 0
        if payload is not None:
            try:
                import json

                extra = estimate_text(json.dumps(payload, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                extra = estimate_text(str(payload))
        return estimate_text(text) + extra
    return estimate_text(str(message))


def _event_tokens(event: Any) -> int:
    """按事件类型估算单条事件 token 压力。"""
    data = event.data or {} if hasattr(event, "data") else (event.get("data") or {})
    etype = getattr(event, "event_type", None) or event.get("event_type", "generic")
    if etype == "context_injection":
        return estimate_text(data.get("content") or "")
    if etype == "user_message":
        return estimate_text(data.get("content") or "")
    if etype == "tool_call":
        text = str(data.get("tool") or data.get("label") or "")
        args = data.get("args")
        result = data.get("result")
        extra = 0
        if args is not None:
            try:
                import json

                extra += estimate_text(json.dumps(args, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                extra += estimate_text(str(args))
        if result is not None:
            try:
                import json

                extra += estimate_text(json.dumps(result, ensure_ascii=False, default=str)[:4000])
            except Exception:  # noqa: BLE001
                extra += estimate_text(str(result)[:4000])
        return estimate_text(text) + extra
    if etype == "assistant_reply":
        return estimate_text(data.get("reply") or "")
    if etype in ("compaction_start", "compaction_summary", "compaction_end"):
        return estimate_text(data.get("summary") or data.get("compaction_id") or etype)
    return estimate_text("")


def measure_session_events(rows: List[Any]) -> Dict[str, Any]:
    """对齐 DSH measure(session, requestHeader?)：折叠一次返回压力与逐节点价格。

    rows: 会话事件流（ChatSessionEvent 列表，含 seq）。
    返回 detached snapshot：total_tokens / surface_tokens / log_revision / nodes。
    """
    total = 0
    nodes: List[Dict[str, Any]] = []
    max_seq = 0
    for evt in rows:
        seq = int(getattr(evt, "seq", 0) or evt.get("seq", 0))
        kind = getattr(evt, "event_type", None) or evt.get("event_type", "generic")
        tokens = _event_tokens(evt)
        total += tokens
        nodes.append({"seq": seq, "kind": kind, "tokens": tokens})
        if seq > max_seq:
            max_seq = seq
    return {
        "total_tokens": total,
        "surface_tokens": total,
        "log_revision": max_seq,
        "nodes": nodes,
    }
