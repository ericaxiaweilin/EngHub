"""Chat 持久化服务（Phase 3）。

提供会话/消息/遥测的落库与读取，供 Harness Kernel、Trace/Replay 消费。
所有写操作由调用方控制事务（与现有 get_db 依赖一致：yield 后 commit）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    ChatMessage, ChatMessageAttachment, ChatSession, ChatTelemetry, FileRecord, generate_uuid,
)

HISTORY_LIMIT = 50


class ChatSessionAccessError(PermissionError):
    """会话不存在或不属于当前用户/工厂。"""


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
    """按 session_id 取既有会话；无 session_id 才允许新建。

    不能把不存在或不属于当前用户的 session_id 静默创建/复用，否则会造成
    会话串线或跨用户读取历史。
    """
    user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
    if session_id:
        cached = await _get_session(db, session_id)
        if cached is None:
            raise ChatSessionAccessError("会话不存在或已失效")
        if cached.user_id != user_id or cached.factory_id != factory_id:
            raise ChatSessionAccessError("无权访问该会话")
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


async def get_session_for_user(
    db: AsyncSession,
    session_id: str,
    *,
    user: Any,
    factory_id: str,
) -> ChatSession:
    """读取并校验会话归属，供历史加载、Trace 和 Replay 共用。"""
    user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
    session = await _get_session(db, session_id)
    if session is None or session.user_id != user_id or session.factory_id != factory_id:
        raise ChatSessionAccessError("无权访问该会话")
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
    attachment_ids: Optional[List[str]] = None,
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
    for ordinal, file_id in enumerate(dict.fromkeys(str(v) for v in (attachment_ids or []) if v)):
        file_record = (
            await db.execute(select(FileRecord).where(FileRecord.id == file_id))
        ).scalar_one_or_none()
        if file_record is None:
            continue
        db.add(ChatMessageAttachment(
            message_id=msg.id,
            session_id=session_id,
            file_id=file_id,
            kind="image" if (file_record.content_type or "").startswith("image/") else "file",
            ordinal=ordinal,
        ))
    if attachment_ids:
        await db.flush()
    # 会话 touched → 前端会话栏排序
    session = await _get_session(db, session_id)
    if session is not None:
        session.updated_at = datetime.utcnow()
    return msg


async def get_history(
    db: AsyncSession,
    session_id: str,
    *,
    limit: int = HISTORY_LIMIT,
    include_tools: bool = True,
    include_tool_calls: bool = True,
    include_attachments: bool = True,
) -> List[Dict[str, Any]]:
    """按时间序返回历史（OpenAI messages 风格）。

    `include_tool_calls=False` 用于把持久化的 ToolAction 轨迹排除在模型上下文
    外；这些轨迹不是 OpenAI 原生 tool_calls，直接回灌会破坏下一轮请求格式。
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    messages: List[Dict[str, Any]] = []
    for m in rows:
        entry: Dict[str, Any] = {"role": m.role}
        if m.role == "tool" and not include_tools:
            continue
        if m.role == "tool":
            entry["content"] = _format_tool_content(m.tool_results or {})
            if m.tool_calls:
                if isinstance(m.tool_calls, dict):
                    entry["tool_call_id"] = m.tool_calls.get(
                        "id", m.tool_calls.get("tool_call_id")
                    )
                elif isinstance(m.tool_calls, list):
                    first = m.tool_calls[0] if m.tool_calls else {}
                    if isinstance(first, dict):
                        entry["tool_call_id"] = first.get(
                            "id", first.get("tool_call_id")
                        )
            messages.append(entry)
            continue
        entry["content"] = m.content or ""
        if include_attachments:
            attachment_rows = (
                await db.execute(
                    select(ChatMessageAttachment, FileRecord)
                    .join(FileRecord, FileRecord.id == ChatMessageAttachment.file_id)
                    .where(ChatMessageAttachment.message_id == m.id)
                    .order_by(ChatMessageAttachment.ordinal.asc())
                )
            ).all()
            if attachment_rows:
                entry["attachments"] = [
                    {
                        "file_id": link.file_id,
                        "filename": file.filename,
                        "content_type": file.content_type,
                        "size": file.size,
                        "kind": link.kind or (
                            "image" if (file.content_type or "").startswith("image/") else "file"
                        ),
                        "is_image": (file.content_type or "").startswith("image/"),
                        "download_url": f"/api/v1/files/{file.id}",
                        "preview_url": f"/api/v1/files/{file.id}"
                        if (file.content_type or "").startswith("image/") else None,
                    }
                    for link, file in attachment_rows
                ]
        if include_tool_calls and m.tool_calls:
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
    user: Any = None,
    factory_id: Optional[str] = None,
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

    if user is not None:
        user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
        if (
            session is None
            or session.user_id != user_id
            or (factory_id is not None and session.factory_id != factory_id)
        ):
            raise ChatSessionAccessError("无权访问该会话 Trace")

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
    attachment_ids: Optional[List[str]] = None,
) -> None:
    """一次请求的完整落库：user 消息 + assistant 回复（含工具动作轨迹）。"""
    if request_id:
        existing = await db.execute(
            select(ChatMessage.id)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.request_id == request_id,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return
    await append_message(
        db, session_id=session_id, role="user", content=user_content,
        request_id=request_id, attachment_ids=attachment_ids,
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
