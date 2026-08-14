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
    ChatMessage, ChatMessageAttachment, ChatSession, ChatSessionEvent, ChatTelemetry, FileRecord, generate_uuid,
)

HISTORY_LIMIT = 50

# 自动压缩压力阈值：会话普通事件数超过该值且可折叠事件数超过 COMPACTION_KEEP_RECENT 时，
# 新请求进入前自动折叠旧历史（对齐 DSH after-call compaction pressure）。
COMPACTION_PRESSURE_EVENTS = 40
# 每次压缩保留的最近普通事件数（未折叠的尾部）。
COMPACTION_KEEP_RECENT = 8


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


# ──────────────────────────────────────────────
# Chat 会话事件流（DSH SessionEvent 对齐）
# ──────────────────────────────────────────────
#
# 一个会话维护一段连续事件流（type/seq/time/data）。Trajectory 视图
# 从该事件流组装读模型（注入 / 用户消息 / 工具调用 / 回复成节点），
# 不再维护第二条独立历史源。

async def append_session_events(
    db: AsyncSession,
    *,
    session_id: str,
    request_id: str,
    events: List[Dict[str, Any]],
) -> None:
    """把本次请求产生的事件追加进会话事件流。

    events: [{"type": ..., "data": {...}}, ...]，seq 在会话内自增。
    幂等：同一 request_id 已存在事件时跳过，避免 persist_hook 重放。
    """
    if not events:
        return
    existing = await db.execute(
        select(ChatSessionEvent.request_id)
        .where(ChatSessionEvent.request_id == request_id)
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return
    last_seq = await _session_last_seq(db, session_id)
    for evt in events:
        seq = last_seq + 1
        last_seq = seq
        db.add(ChatSessionEvent(
            id=generate_uuid(),
            session_id=session_id,
            request_id=request_id,
            seq=seq,
            event_type=evt.get("type", "generic"),
            data=evt.get("data") or {},
        ))
    await db.flush()


async def _session_last_seq(db: AsyncSession, session_id: str) -> int:
    row = (await db.execute(
        select(ChatSessionEvent.seq)
        .where(ChatSessionEvent.session_id == session_id)
        .order_by(ChatSessionEvent.seq.desc())
        .limit(1)
    )).scalar_one_or_none()
    return int(row) if row else 0


async def compact_session_events(
    db: AsyncSession,
    session_id: str,
    *,
    user: Any = None,
    factory_id: Optional[str] = None,
    compaction_id: Optional[str] = None,
    fold_from: Optional[int] = None,
    fold_to: Optional[int] = None,
    keep_recent: int = COMPACTION_KEEP_RECENT,
    reason: str = "manual",
) -> Dict[str, Any]:
    """折叠一段历史事件为一条摘要（对齐 DSH compaction bracket）。

    落库三个事件（同一 compaction_id，atomic）：
      compaction_start  → {compaction_id, fold_from, fold_to, reason}
      compaction_summary→ {compaction_id, summary, source_event_seqs}
      compaction_end    → {compaction_id, status, replacement_checkpoint}

    锁：存在尚未闭合的 compaction_start（无对端 compaction_end）时拒绝（busy）。
    幂等：同一 compaction_id 已应用则直接返回已有结果。
    source_event_seqs 记录被折叠的每个源事件 seq，供 replay 校验替换覆盖全部来源。
    """
    session = await _get_session(db, session_id)
    if session is None:
        raise ChatSessionAccessError("会话不存在")
    if user is not None:
        user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
        if (
            session.user_id != user_id
            or (factory_id is not None and session.factory_id != factory_id)
        ):
            raise ChatSessionAccessError("无权操作该会话")

    rows = (await db.execute(
        select(ChatSessionEvent)
        .where(ChatSessionEvent.session_id == session_id)
        .order_by(ChatSessionEvent.seq.asc())
    )).scalars().all()

    compaction_id = compaction_id or generate_uuid()

    # 幂等：同一 compaction_id 已存在则返回其结果
    existing = [e for e in rows if e.request_id == compaction_id]
    if existing:
        return {
            "folded": True,
            "compaction_id": compaction_id,
            "status": "exists",
            "seq_from": existing[0].seq,
            "seq_to": existing[-1].seq,
        }

    # 锁：存在尚未闭合的 compaction_start（无对端 compaction_end）时拒绝
    pending = {e.request_id for e in rows if e.event_type == "compaction_start"}
    closed = {e.request_id for e in rows if e.event_type == "compaction_end"}
    open_locks = pending - closed
    if open_locks:
        return {
            "folded": False,
            "compaction_id": compaction_id,
            "status": "busy",
            "lock_compaction_id": sorted(open_locks)[0],
        }

    # 折叠区间：普通（非 compaction_*）事件，按 seq 升序。
    if fold_from is None or fold_to is None:
        plain_rows = [e for e in rows if e.event_type not in (
            "compaction_start", "compaction_summary", "compaction_end",
        )]
        # 自动压力门槛：仅当会话普通事件足够多时才压力折叠（对齐 DSH 阈值触发），
        # 避免小会话因 keep_recent 而过早折叠可读历史。
        if reason == "pressure" and len(plain_rows) < COMPACTION_PRESSURE_EVENTS:
            return {
                "folded": False,
                "compaction_id": compaction_id,
                "status": "no_pressure",
                "total_events": len(plain_rows),
                "pressure_threshold": COMPACTION_PRESSURE_EVENTS,
            }
        # 已被先前折叠引用的事件不再重复折叠
        already_folded = set()
        for e in rows:
            if e.event_type == "compaction_summary":
                already_folded.update(e.data.get("source_event_seqs") or ())
        foldable = [e for e in plain_rows if e.seq not in already_folded]
        if len(foldable) <= keep_recent:
            return {
                "folded": False,
                "compaction_id": compaction_id,
                "status": "nothing_to_fold",
                "foldable": len(foldable),
                "keep_recent": keep_recent,
            }
        cut = foldable[-keep_recent - 1]
        fold_from = foldable[0].seq
        fold_to = cut.seq

    folded = [e for e in rows if fold_from <= e.seq <= fold_to]
    source_event_seqs = [e.seq for e in folded]
    if not source_event_seqs:
        return {
            "folded": False,
            "compaction_id": compaction_id,
            "status": "empty_range",
            "fold_from": fold_from,
            "fold_to": fold_to,
        }

    summary = _build_compaction_summary(folded)
    replacement_checkpoint = (folded[-1].seq if folded else fold_from) + 1

    await append_session_events(db, session_id=session_id, request_id=compaction_id, events=[
        {
            "type": "compaction_start",
            "data": {
                "compaction_id": compaction_id,
                "fold_from": fold_from,
                "fold_to": fold_to,
                "reason": reason,
            },
        },
        {
            "type": "compaction_summary",
            "data": {
                "compaction_id": compaction_id,
                "summary": summary,
                "source_event_seqs": source_event_seqs,
            },
        },
        {
            "type": "compaction_end",
            "data": {
                "compaction_id": compaction_id,
                "status": "ok",
                "replacement_checkpoint": replacement_checkpoint,
            },
        },
    ])
    return {
        "folded": True,
        "compaction_id": compaction_id,
        "status": "ok",
        "fold_from": fold_from,
        "fold_to": fold_to,
        "folded_count": len(source_event_seqs),
        "source_event_seqs": source_event_seqs,
        "summary": summary,
    }


def _build_compaction_summary(events: List[ChatSessionEvent]) -> str:
    """本地降级摘要：把被折叠事件折叠为简洁要点（LLM 摘要失败时兜底）。

    按 request 分组：用户消息 → 工具序列 → 回复要点。
    """
    by_request: Dict[str, List[str]] = {}
    order: List[str] = []
    for evt in events:
        data = evt.data or {}
        rid = evt.request_id or "-"
        if rid not in by_request:
            by_request[rid] = []
            order.append(rid)
        if evt.event_type == "user_message":
            content = (data.get("content") or "").strip()
            by_request[rid].append(f"问：{content[:60]}" if content else "问：（图片/附件）")
        elif evt.event_type == "tool_call":
            tool = data.get("tool") or data.get("label") or ""
            ok = data.get("success", True)
            by_request[rid].append(f"工具[{tool}]{'✓' if ok else '✗'}")
        elif evt.event_type == "assistant_reply":
            reply = (data.get("reply") or "").strip()
            by_request[rid].append(f"答：{reply[:60]}" if reply else "")
        elif evt.event_type == "context_injection":
            src = data.get("source") or "context"
            by_request[rid].append(f"注入({src})")
    lines = []
    for rid in order:
        seg = "；".join([p for p in by_request[rid] if p])
        if seg:
            lines.append(seg)
    if not lines:
        return f"已折叠 {len(events)} 个事件"
    summary = "；".join(lines)
    return summary[:2000]


async def get_trajectory(
    db: AsyncSession,
    session_id: str,
    *,
    user: Any = None,
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """组装会话 Trajectory：按 seq 从事件流读取，并重放为节点序列。

    对齐 DSH Trajectory view：事件流是唯一来源，读模型按业务折叠——
      context_injection → 注入节点（source/label/content）
      user_message     → 用户消息节点
      tool_call        → 工具调用节点（tool/arguments/result 摘要）
      assistant_reply  → 回复节点（reply/模型名/耗时）
    """
    session = await _get_session(db, session_id)
    if session is None:
        raise ChatSessionAccessError("会话不存在")
    if user is not None:
        user_id = str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"
        if (
            session.user_id != user_id
            or (factory_id is not None and session.factory_id != factory_id)
        ):
            raise ChatSessionAccessError("无权访问该会话轨迹")

    rows = (await db.execute(
        select(ChatSessionEvent)
        .where(ChatSessionEvent.session_id == session_id)
        .order_by(ChatSessionEvent.seq.asc())
    )).scalars().all()

    # DSH compaction：识别 compaction_start/summary/end 三元组，
    # 把被折叠的源事件（source_event_seqs 并集）从节点流中移除，
    # 折叠为一条 compaction 节点（含摘要）。
    compactions: List[Dict[str, Any]] = []
    active: Optional[Dict[str, Any]] = None
    for evt in rows:
        data = evt.data or {}
        if evt.event_type == "compaction_start":
            active = {
                "kind": "compaction",
                "seq": evt.seq,
                "request_id": evt.request_id,
                "compaction_id": data.get("compaction_id"),
                "fold_from": data.get("fold_from"),
                "fold_to": data.get("fold_to"),
                "reason": data.get("reason"),
                "summary": "",
                "source_event_seqs": [],
                "folded_count": 0,
                "status": "started",
            }
            compactions.append(active)
        elif evt.event_type == "compaction_summary" and active is not None:
            active["summary"] = data.get("summary") or ""
            active["source_event_seqs"] = data.get("source_event_seqs") or []
            active["folded_count"] = len(active["source_event_seqs"])
            active["status"] = "summarized"
        elif evt.event_type == "compaction_end" and active is not None:
            active["status"] = "ok"
            active["replacement_checkpoint"] = data.get("replacement_checkpoint")
            active = None
        elif evt.event_type in ("compaction_start", "compaction_summary", "compaction_end"):
            active = None

    # 被折叠的源事件 = 全部 compaction 的 source_event_seqs 并集
    compacted_seqs: set = set()
    for c in compactions:
        compacted_seqs.update(c.get("source_event_seqs") or [])

    nodes: List[Dict[str, Any]] = []
    context_requests: Dict[str, Dict[str, Any]] = {}
    next_compaction = 0
    for evt in rows:
        data = evt.data or {}
        if evt.seq in compacted_seqs:
            continue
        if evt.event_type == "context_injection":
            node = {
                "kind": "context_injection",
                "seq": evt.seq,
                "request_id": evt.request_id,
                "source": data.get("source") or "unknown",
                "label": data.get("label") or "上下文",
                "content": data.get("content") or "",
            }
            nodes.append(node)
            context_requests.setdefault(evt.request_id, {})["injections"] = (
                context_requests.get(evt.request_id, {}).get("injections", 0) + 1
            )
        elif evt.event_type == "user_message":
            nodes.append({
                "kind": "user_message",
                "seq": evt.seq,
                "request_id": evt.request_id,
                "content": data.get("content") or "",
            })
        elif evt.event_type == "tool_call":
            nodes.append({
                "kind": "tool_call",
                "seq": evt.seq,
                "request_id": evt.request_id,
                "tool": data.get("tool") or "",
                "label": data.get("label") or data.get("tool") or "",
                "args": data.get("args"),
                "result": data.get("result"),
                "success": data.get("success", True),
                "is_write": data.get("is_write", False),
            })
        elif evt.event_type == "assistant_reply":
            nodes.append({
                "kind": "assistant_reply",
                "seq": evt.seq,
                "request_id": evt.request_id,
                "reply": data.get("reply") or "",
                "model": data.get("model"),
                "duration_ms": data.get("duration_ms"),
                "degraded": data.get("degraded", False),
                "tool_count": data.get("tool_count", 0),
            })
        elif evt.event_type == "compaction_start":
            if (
                next_compaction < len(compactions)
                and compactions[next_compaction]["source_event_seqs"]
            ):
                nodes.append(compactions[next_compaction])
                next_compaction += 1
        elif evt.event_type in ("compaction_summary", "compaction_end"):
            pass

    return {
        "session_id": session.id,
        "factory_id": session.factory_id,
        "title": session.title,
        "event_count": len(rows),
        "nodes": nodes,
        "injection_requests": context_requests,
        "compactions": compactions,
        "overview": _trajectory_overview(nodes),
    }


def _trajectory_overview(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """阶段导向读模型（DSH stage-oriented）：每次请求折叠为紧凑摘要。

    每个 request 一条：注入 sources / 用户消息 / 工具调用序列 / 回复 / 模型 /
    耗时 / 是否降级。Overview 不复制原始事件，仅引用折叠后的阶段事实。
    """
    by_request: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for node in nodes:
        rid = node.get("request_id") or "-"
        if rid not in by_request:
            by_request[rid] = {
                "request_id": rid,
                "seq_from": node["seq"],
                "seq_to": node["seq"],
                "injections": [],
                "user_message": None,
                "tools": [],
                "tool_count": 0,
                "reply": None,
                "model": None,
                "duration_ms": None,
                "degraded": False,
            }
            order.append(rid)
        stage = by_request[rid]
        stage["seq_from"] = min(stage["seq_from"], node["seq"])
        stage["seq_to"] = max(stage["seq_to"], node["seq"])
        kind = node.get("kind")
        if kind == "context_injection":
            stage["injections"].append({
                "source": node.get("source"),
                "label": node.get("label"),
            })
        elif kind == "user_message":
            stage["user_message"] = node.get("content")
        elif kind == "tool_call":
            stage["tools"].append({
                "tool": node.get("tool"),
                "label": node.get("label") or node.get("tool"),
                "success": node.get("success", True),
                "is_write": node.get("is_write", False),
            })
            stage["tool_count"] += 1
        elif kind == "assistant_reply":
            stage["reply"] = node.get("reply")
            stage["model"] = node.get("model")
            stage["duration_ms"] = node.get("duration_ms")
            stage["degraded"] = node.get("degraded", False)
        elif kind == "compaction":
            stage["compaction"] = True
            stage["summary"] = node.get("summary")
            stage["fold_from"] = node.get("fold_from")
            stage["fold_to"] = node.get("fold_to")
            stage["folded_count"] = len(node.get("source_event_seqs") or [])
            stage["reason"] = node.get("reason")

    out = [by_request[r] for r in order]
    # 工具序列简化为名称列表（前端可直接展示），保留完整数组供展开。
    for stage in out:
        stage["tool_sequence"] = [t["tool"] for t in stage["tools"]]
    return out
