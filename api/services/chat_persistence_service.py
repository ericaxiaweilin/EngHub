"""Chat 持久化服务（Phase 3）。

提供会话/消息/遥测的落库与读取，供 Harness Kernel、Trace/Replay 消费。
所有写操作由调用方控制事务（与现有 get_db 依赖一致：yield 后 commit）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    ChatMessage, ChatSession, ChatTelemetry, generate_uuid,
)

HISTORY_LIMIT = 50


# ──────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────

async def get_or_create_session(
    db: AsyncSession,
    *,
    factory_id: str,
    user: Any,
    session_id: Optional[str] = None,
    title: Optional[str] = None,
) -> ChatSession:
    """按 session_id 取既有会话；无则新建。返回的 session 不强制 flush。"""
    user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
    if session_id:
        cached = await _get_session(db, session_id)
        if cached is not None:
            return cached
    session = ChatSession(
        id=session_id or generate_uuid(),
        factory_id=factory_id,
        user_id=user_id,
        title=title or _title_from_first_message(None),
    )
    db.add(session)
    await db.flush()
    return session


async def _get_session(db: AsyncSession, session_id: str) -> Optional[ChatSession]:
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    return result.scalar_one_or_none()


def _title_from_first_message(content: Optional[str]) -> str:
    if not content:
        return "新会话"
    text = content.strip().replace("\n", " ")[:30]
    return text or "新会话"


async def list_sessions(
    db: AsyncSession,
    *,
    user: Any,
    factory_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """列出某用户最近的会话（供前端会话栏）。"""
    user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    if factory_id:
        stmt = stmt.where(ChatSession.factory_id == factory_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "session_id": s.id,
            "factory_id": s.factory_id,
            "title": s.title or "新会话",
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else None,
            "updated_at": s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else None,
        }
        for s in rows
    ]


# ──────────────────────────────────────────────
# Message
# ──────────────────────────────────────────────

async def append_message(
    db: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_results: Optional[Any] = None,
    model: Optional[str] = None,
    tokens_used: int = 0,
    duration_ms: float = 0,
    request_id: Optional[str] = None,
) -> ChatMessage:
    """追加一条消息（user/assistant/tool/system）。"""
    msg = ChatMessage(
        id=generate_uuid(),
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=_json_safe(tool_results),
        model=model,
        tokens_used=int(tokens_used),
        duration_ms=int(duration_ms),
        request_id=request_id,
    )
    db.add(msg)
    await db.flush()
    # 会话 touched → 前端会话栏排序
    session = await _get_session(db, session_id)
    if session is not None:
        session.updated_at = session.updated_at
    return msg


async def get_history(
    db: AsyncSession,
    session_id: str,
    *,
    limit: int = HISTORY_LIMIT,
    include_tools: bool = True,
) -> List[Dict[str, Any]]:
    """按时间序返回可视历史（OpenAI messages 风格，供 Kernel 注入）。"""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    messages: List[Dict[str, Any]] = []
    for m in rows:
        entry: Dict[str, Any] = {"role": m.role}
        if m.role == "tool" and not include_tools:
            continue
        if m.role == "tool":
            entry["content"] = _format_tool_content(m.tool_results or {})
            if m.tool_calls:
                entry["tool_call_id"] = m.tool_calls.get("id", m.tool_calls.get("tool_call_id"))
            messages.append(entry)
            continue
        entry["content"] = m.content or ""
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        messages.append(entry)
    return messages


def _format_tool_content(result: Any) -> str:
    """工具结果 → model 可见文本。"""
    if isinstance(result, dict):
        return result.get("content") or result.get("result") or str(result)
    return str(result)


# ──────────────────────────────────────────────
# Telemetry / Trace
# ──────────────────────────────────────────────

async def save_telemetry(
    db: AsyncSession,
    *,
    request_id: str,
    session_id: Optional[str] = None,
    phase: str = "total",
    duration_ms: float = 0,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    tools_called: Optional[List[str]] = None,
    rounds: int = 0,
    success: bool = True,
    error: Optional[str] = None,
) -> ChatTelemetry:
    """保存一次请求的遥测事件。"""
    evt = ChatTelemetry(
        id=generate_uuid(),
        request_id=request_id,
        session_id=session_id,
        phase=phase,
        duration_ms=duration_ms,
        model=model,
        provider=provider,
        tools_called=tools_called or [],
        rounds=rounds,
        success=success,
        error=error,
    )
    db.add(evt)
    await db.flush()
    return evt


async def get_trace(
    db: AsyncSession,
    request_id: Optional[str] = None,
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """重建一次完整请求的 Trace：会话 + 消息链 + 遥测。

    优先按 request_id（一次请求），退化为 session 内全部遥测。
    """
    stmt_tel = select(ChatTelemetry).order_by(ChatTelemetry.created_at.asc())
    if request_id:
        stmt_tel = stmt_tel.where(ChatTelemetry.request_id == request_id)
    elif session_id:
        stmt_tel = stmt_tel.where(ChatTelemetry.session_id == session_id)
    tels = (await db.execute(stmt_tel)).scalars().all()

    session = None
    messages: List[Dict[str, Any]] = []
    sid = session_id
    msg_request_id = request_id
    if msg_request_id:
        # 最近一条含 request_id 的消息定位会话
        stmt_msg = (
            select(ChatMessage)
            .where(ChatMessage.request_id == msg_request_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        anchor = (await db.execute(stmt_msg)).scalar_one_or_none()
        if anchor is not None:
            sid = anchor.session_id
            session = await _get_session(db, sid)
    elif sid:
        session = await _get_session(db, sid)

    if sid:
        messages = await get_history(db, sid, include_tools=True)

    return {
        "request_id": request_id,
        "session_id": sid,
        "session": {
            "id": session.id,
            "factory_id": session.factory_id,
            "user_id": session.user_id,
            "title": session.title,
        } if session else None,
        "messages": messages,
        "telemetry": [
            {
                "phase": t.phase,
                "duration_ms": float(t.duration_ms or 0),
                "model": t.model,
                "tools_called": t.tools_called or [],
                "rounds": t.rounds,
                "success": t.success,
                "error": t.error,
            }
            for t in tels
        ],
    }


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    return value


# ──────────────────────────────────────────────
# 便捷聚合（写会话一次完成）
# ──────────────────────────────────────────────

async def persist_round(
    db: AsyncSession,
    *,
    session_id: str,
    user_content: str,
    reply: str,
    model: Optional[str] = None,
    actions: Optional[List[Any]] = None,
    request_id: Optional[str] = None,
    duration_ms: float = 0,
) -> None:
    """一次请求的完整落库：user 消息 + assistant 回复（含工具动作轨迹）。"""
    await append_message(
        db, session_id=session_id, role="user", content=user_content,
        request_id=request_id,
    )
    tool_trace = [_action_to_json(a) for a in (actions or [])] if actions else None
    await append_message(
        db, session_id=session_id, role="assistant", content=reply,
        tool_calls=tool_trace, model=model,
        duration_ms=duration_ms, request_id=request_id,
    )


def _action_to_json(action: Any) -> Dict[str, Any]:
    """把 ToolAction（Pydantic）序列化为消息内的工具轨迹。"""
    if hasattr(action, "model_dump"):
        return action.model_dump()
    return {
        "tool": getattr(action, "tool", ""),
        "label": getattr(action, "label", ""),
        "arguments": getattr(action, "arguments", None),
        "result": getattr(action, "result", None),
        "success": getattr(action, "success", True),
    }