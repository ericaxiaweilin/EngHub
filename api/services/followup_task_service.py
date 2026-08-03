"""
任务中心（待办跟进）服务
========================
工业场景里很多任务无法一次做完（等物料/等审批/等设备恢复），
用户交代后先挂到任务中心，由系统按用户设置的频率定期扫描跟进：
每次跟进以任务归类的智能体身份调用模型+MES工具，产出跟进结论，
有结果推送站内通知；完成/受阻自动更新状态，全程留痕。

与 luaguage 长任务的区别：不引入事件总线/证据仓，直接复用
EngHub 现有 chatbot 工具链（chat_routes 的 LLM 网关 + chat_tools_service 工具）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.agent_supervisor_service import AGENTS

_logger = logging.getLogger("followup_task")

# 允许的跟进频率下限，防止用户设置过密打爆网关（分钟）
MIN_FOLLOW_INTERVAL_MINUTES = 15
# 每轮扫描最多处理的到期任务数（防止堆积时一次拉起太多 LLM 调用）
SCAN_BATCH_SIZE = 5
# 单次跟进最多工具轮次
FOLLOW_MAX_TOOL_ROUNDS = 4

FOLLOWUP_STATUSES = {"open", "blocked", "done", "cancelled"}
# 统一待办条目类型：AI跟进 / 他人指派 / 会议纪要 / 邮件 / 备忘
ITEM_TYPES = {"followup", "assigned", "meeting", "email", "note"}


def _gen_id() -> str:
    return str(uuid.uuid4())


def _agent_name(agent_key: Optional[str]) -> Optional[str]:
    if not agent_key:
        return None
    agent = AGENTS.get(agent_key)
    return agent["name"] if agent else agent_key


# ═══════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════

async def list_tasks(
    db: AsyncSession,
    factory_id: str,
    status: Optional[str] = None,
    created_by: Optional[str] = None,
    item_type: Optional[str] = None,
    involving: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    conditions = ["factory_id = :fid"]
    params: Dict[str, Any] = {"fid": factory_id, "limit": limit}
    if status:
        conditions.append("status = :st")
        params["st"] = status
    if created_by:
        conditions.append("created_by = :cb")
        params["cb"] = created_by
    if item_type:
        conditions.append("item_type = :it")
        params["it"] = item_type
    if involving:  # 与我有关：我挂的 或 指派给我的
        conditions.append("(created_by = :inv OR assigned_to = :inv)")
        params["inv"] = involving
    result = await db.execute(text(f"""
        SELECT id, factory_id, created_by, title, description, agent_key, agent_name,
               status, block_reason, source, conversation_hint,
               follow_interval_minutes, next_follow_at, last_follow_at, last_follow_note,
               follow_count, max_follows, progress_pct, result_summary,
               item_type, assigned_to, ai_summary, ai_suggestion, due_at,
               created_at, updated_at, closed_at
        FROM followup_tasks
        WHERE {' AND '.join(conditions)}
        ORDER BY (status IN ('open','blocked')) DESC, next_follow_at ASC NULLS LAST, created_at DESC
        LIMIT :limit
    """), params)
    return [dict(r._mapping) for r in result.fetchall()]


async def get_task_logs(db: AsyncSession, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    result = await db.execute(text("""
        SELECT id, task_id, trigger_type, note, status_after, progress_pct, created_by, created_at
        FROM followup_task_logs
        WHERE task_id = :tid
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"tid": task_id, "limit": limit})
    return [dict(r._mapping) for r in result.fetchall()]


async def create_task(
    db: AsyncSession,
    factory_id: str,
    created_by: str,
    title: str,
    description: str = "",
    agent_key: Optional[str] = None,
    follow_interval_minutes: int = 120,
    block_reason: str = "",
    source: str = "manual",
    conversation_hint: str = "",
    item_type: str = "followup",
    assigned_to: Optional[str] = None,
    payload: str = "",
    due_at: Optional[str] = None,
) -> Dict[str, Any]:
    """挂一个待办条目。agent_key 为空时自动归类（复用快速命令的归类器）；
    指派给他人时自动推送站内通知。"""
    title = (title or "").strip()[:200]
    if not title:
        return {"error": "任务标题不能为空"}
    if item_type not in ITEM_TYPES:
        return {"error": f"非法条目类型：{item_type}"}
    interval = max(MIN_FOLLOW_INTERVAL_MINUTES, int(follow_interval_minutes or 120))

    if agent_key and agent_key not in AGENTS:
        return {"error": f"未知智能体：{agent_key}"}
    if not agent_key:
        from api.services.quick_command_service import classify_command
        classified = await classify_command(f"{title} {description}".strip())
        agent_key = classified.get("agent_key")

    task_id = _gen_id()
    await db.execute(text("""
        INSERT INTO followup_tasks (id, factory_id, created_by, title, description,
            agent_key, agent_name, status, block_reason, source, conversation_hint,
            follow_interval_minutes, next_follow_at,
            item_type, assigned_to, payload, due_at)
        VALUES (:id, :fid, :cb, :title, :desc, :ak, :an, 'open', :br, :src, :hint,
            :interval, NOW() + make_interval(mins => :interval_next),
            :itype, :assignee, :payload, CAST(:due AS timestamptz))
    """), {
        "id": task_id, "fid": factory_id, "cb": created_by,
        "title": title, "desc": description or "",
        "ak": agent_key, "an": _agent_name(agent_key),
        "br": (block_reason or "")[:500], "src": source,
        "hint": (conversation_hint or "")[:500], "interval": interval,
        "interval_next": interval,
        "itype": item_type, "assignee": assigned_to,
        "payload": (payload or "")[:20000] or None, "due": due_at,
    })
    await _append_log(db, task_id, factory_id, "status",
                      f"任务已挂入任务中心，每 {interval} 分钟跟进一次"
                      + (f"；受阻原因：{block_reason}" if block_reason else "")
                      + (f"；指派给：{assigned_to}" if assigned_to else ""),
                      "open", 0, created_by)
    # 指派给他人 → 站内通知被指派人
    if assigned_to and assigned_to != created_by:
        await _notify(db, factory_id, assigned_to,
                      f"新任务指派：{title}",
                      f"{created_by} 指派给你一个任务：{description or title}"
                      + (f"（截止：{due_at}）" if due_at else ""))
    await db.commit()
    return {
        "task_id": task_id, "title": title, "item_type": item_type,
        "agent_key": agent_key, "agent_name": _agent_name(agent_key),
        "assigned_to": assigned_to,
        "follow_interval_minutes": interval, "status": "open",
    }


async def update_task(
    db: AsyncSession,
    task_id: str,
    factory_id: str,
    operator: str,
    **fields: Any,
) -> Dict[str, Any]:
    """更新任务（频率/状态/进度/标题等）。状态置 done/cancelled 时写 closed_at。"""
    allowed = {
        "title", "description", "agent_key", "status", "block_reason",
        "follow_interval_minutes", "progress_pct", "result_summary",
        "assigned_to", "due_at",
    }
    updates: Dict[str, Any] = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return {"error": "无可更新字段"}
    if "status" in updates and updates["status"] not in FOLLOWUP_STATUSES:
        return {"error": f"非法状态：{updates['status']}"}
    if "agent_key" in updates:
        if updates["agent_key"] and updates["agent_key"] not in AGENTS:
            return {"error": f"未知智能体：{updates['agent_key']}"}
        updates["agent_name"] = _agent_name(updates["agent_key"]) or ""
    if "follow_interval_minutes" in updates:
        updates["follow_interval_minutes"] = max(
            MIN_FOLLOW_INTERVAL_MINUTES, int(updates["follow_interval_minutes"]))

    set_parts = [
        ("due_at = CAST(:due_at AS timestamptz)" if k == "due_at" else f"{k} = :{k}")
        for k in updates
    ]
    set_parts.append("updated_at = NOW()")
    # 调整频率时同步顺延下次跟进；关单时记录 closed_at
    if "follow_interval_minutes" in updates:
        set_parts.append(
            "next_follow_at = NOW() + make_interval(mins => :follow_interval_next)"
        )
    if updates.get("status") in {"done", "cancelled"}:
        set_parts.append("closed_at = NOW()")
    elif "status" in updates:
        set_parts.append("closed_at = NULL")

    params = {**updates, "id": task_id, "fid": factory_id}
    if "follow_interval_minutes" in updates:
        params["follow_interval_next"] = updates["follow_interval_minutes"]
    result = await db.execute(text(f"""
        UPDATE followup_tasks SET {', '.join(set_parts)}
        WHERE id = :id AND factory_id = :fid
        RETURNING id, status, progress_pct
    """), params)
    row = result.first()
    if not row:
        return {"error": "任务不存在"}
    note_bits = [f"{k}={v}" for k, v in updates.items() if k != "agent_name"]
    await _append_log(db, task_id, factory_id, "status",
                      f"用户更新：{'; '.join(note_bits)}", row[1], row[2], operator)
    await db.commit()
    return {"task_id": task_id, "status": row[1], "progress_pct": row[2]}


async def delete_task(db: AsyncSession, task_id: str, factory_id: str) -> Dict[str, Any]:
    result = await db.execute(text(
        "DELETE FROM followup_tasks WHERE id = :id AND factory_id = :fid RETURNING id"
    ), {"id": task_id, "fid": factory_id})
    row = result.first()
    if row:
        await db.execute(text("DELETE FROM followup_task_logs WHERE task_id = :id"), {"id": task_id})
    await db.commit()
    return {"deleted": bool(row)}


# ═══════════════════════════════════════════════════════
# 内容接入 + AI 分诊：会议纪要/邮件/备忘粘进来，AI 自动摘要、
# 提行动项、判断紧急度；纯知会类直接归档不打扰用户
# ═══════════════════════════════════════════════════════

TRIAGE_PROMPT = (
    "你是 EngHub MES 任务中心的分诊器。用户接入了一段内容（会议纪要/邮件/备忘），"
    "请分析后只输出 JSON（不要多余文字）：\n"
    '{"title": "一句话标题(30字内)", "summary": "核心内容摘要(150字内)", '
    '"action_items": ["需要跟进的行动项，没有则空数组"], '
    '"urgency": "high|normal|low", "disposition": "info_only|follow_up|user_action"}\n'
    "disposition 判定：纯通报/知会无需任何后续动作→info_only；"
    "有行动项但可由系统定期核实进展（等物料/等审批/盯数据）→follow_up；"
    "必须用户本人决策或操作（签字/开会/回复对方）→user_action。"
)


async def _triage_content(item_type: str, content: str) -> Dict[str, Any]:
    """LLM 分诊接入内容；失败时降级为保守默认（交用户处理）。"""
    fallback = {
        "title": content.strip().splitlines()[0][:30] if content.strip() else "新接入内容",
        "summary": "", "action_items": [], "urgency": "normal",
        "disposition": "user_action",
    }
    try:
        from api.routes.chat_routes import (
            MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route,
        )
        route = await _resolve_model_route(MODEL_STACK_CHAT_TASK_ID, prompt_tokens=1024)
        type_label = {"meeting": "会议纪要", "email": "邮件", "note": "备忘"}.get(item_type, item_type)
        resp = await _call_llm({
            "model": route["gateway_model"],
            "messages": [
                {"role": "system", "content": TRIAGE_PROMPT},
                {"role": "user", "content": f"内容类型：{type_label}\n\n{content[:6000]}"},
            ],
            "temperature": 0.1,
            "max_tokens": route["max_completion_tokens"],
        }, request_timeout=route["request_timeout"])
        if resp.status_code >= 400:
            return fallback
        reply = ((resp.json().get("choices", [{}])[0] or {}).get("message", {}) or {}).get("content") or ""
        start, end = reply.find("{"), reply.rfind("}")
        data = json.loads(reply[start:end + 1])
        disposition = str(data.get("disposition") or "user_action")
        if disposition not in {"info_only", "follow_up", "user_action"}:
            disposition = "user_action"
        urgency = str(data.get("urgency") or "normal")
        if urgency not in {"high", "normal", "low"}:
            urgency = "normal"
        items = [str(x).strip()[:200] for x in (data.get("action_items") or []) if str(x).strip()][:10]
        return {
            "title": str(data.get("title") or fallback["title"]).strip()[:60] or fallback["title"],
            "summary": str(data.get("summary") or "").strip()[:1000],
            "action_items": items, "urgency": urgency, "disposition": disposition,
        }
    except Exception as exc:  # noqa: BLE001 — 分诊失败不能堵住接入
        _logger.warning("triage failed: %s", exc)
        return fallback


async def ingest_item(
    db: AsyncSession,
    factory_id: str,
    created_by: str,
    item_type: str,
    content: str,
    title: str = "",
    follow_interval_minutes: int = 120,
) -> Dict[str, Any]:
    """接入会议纪要/邮件/备忘 → AI 分诊 → 自动归档或挂跟进。"""
    if item_type not in {"meeting", "email", "note"}:
        return {"error": f"接入类型仅限 meeting/email/note，收到：{item_type}"}
    content = (content or "").strip()
    if not content:
        return {"error": "接入内容不能为空"}

    triage = await _triage_content(item_type, content)
    final_title = (title or "").strip()[:200] or triage["title"]
    suggestion = "\n".join(f"• {x}" for x in triage["action_items"]) or None
    # 高紧急度 → 跟进频率自动提到 1 小时以内
    interval = int(follow_interval_minutes or 120)
    if triage["urgency"] == "high":
        interval = min(interval, 60)

    created = await create_task(
        db, factory_id, created_by=created_by,
        title=final_title,
        description=triage["summary"] or content[:500],
        follow_interval_minutes=interval,
        source="ingest", item_type=item_type, payload=content,
    )
    if "error" in created:
        return created
    task_id = created["task_id"]

    if triage["disposition"] == "info_only":
        # 纯知会：AI 直接归档，不进入跟进循环，不打扰用户
        await db.execute(text("""
            UPDATE followup_tasks
            SET ai_summary = :summ, ai_suggestion = :sugg,
                status = 'done', progress_pct = 100, next_follow_at = NULL,
                result_summary = :summ, closed_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """), {"id": task_id, "summ": triage["summary"] or "纯知会内容", "sugg": suggestion})
        await _append_log(db, task_id, factory_id, "status",
                          "AI 分诊：纯知会内容，无需后续动作，已自动归档", "done", 100, "system")
    else:
        await db.execute(text("""
            UPDATE followup_tasks
            SET ai_summary = :summ, ai_suggestion = :sugg, updated_at = NOW()
            WHERE id = :id
        """), {"id": task_id, "summ": triage["summary"] or None, "sugg": suggestion})
        note = (f"AI 分诊：{'需用户处理' if triage['disposition'] == 'user_action' else '可系统跟进'}"
                f"，紧急度 {triage['urgency']}"
                + (f"；行动项 {len(triage['action_items'])} 项" if triage["action_items"] else ""))
        await _append_log(db, task_id, factory_id, "status", note, "open", 0, "system")
        # 需用户亲自处理 → 站内通知提醒
        if triage["disposition"] == "user_action":
            await _notify(db, factory_id, created_by,
                          f"需你处理：{final_title}",
                          (triage["summary"] or content[:200])
                          + (f"\n行动项：\n{suggestion}" if suggestion else ""),
                          "warning" if triage["urgency"] == "high" else "info")
    await db.commit()
    return {**created, "triage": triage}


async def _append_log(
    db: AsyncSession, task_id: str, factory_id: str, trigger_type: str,
    note: str, status_after: str, progress_pct: int, created_by: str,
) -> None:
    await db.execute(text("""
        INSERT INTO followup_task_logs (id, task_id, factory_id, trigger_type, note,
            status_after, progress_pct, created_by)
        VALUES (:id, :tid, :fid, :tt, :note, :sa, :pp, :cb)
    """), {
        "id": _gen_id(), "tid": task_id, "fid": factory_id, "tt": trigger_type,
        "note": note, "sa": status_after, "pp": progress_pct, "cb": created_by,
    })


async def _notify(db: AsyncSession, factory_id: str, recipient: str, title: str, content: str, severity: str = "info") -> None:
    await db.execute(text("""
        INSERT INTO notifications (id, factory_id, recipient, category, title, content, severity, source_type)
        VALUES (:id, :fid, :rcpt, 'task_followup', :title, :content, :sev, 'followup_task')
    """), {
        "id": _gen_id(), "fid": factory_id, "rcpt": recipient,
        "title": title[:200], "content": content, "sev": severity,
    })


# ═══════════════════════════════════════════════════════════
# 跟进执行：以任务归类智能体身份调 LLM+工具，产出跟进结论
# ═══════════════════════════════════════════════════════════

FOLLOWUP_PROMPT = (
    "你是 EngHub MES 任务中心的跟进执行器。下面是一个此前无法一次完成、挂账跟进的任务。\n"
    "请调用工具核实当前最新状态，然后只输出 JSON（不要多余文字）：\n"
    '{"progress_pct": 0-100 整数, "state": "open|blocked|done", '
    '"note": "本次跟进结论（150字内，说明当前进展/仍受阻原因/完成依据）"}\n'
    "判定规则：任务目标已达成→done；仍在等待外部条件（物料/审批/设备/供应商）→blocked；"
    "有进展但未完成→open。note 必须基于工具返回的真实数据，禁止编造。"
)


def _parse_follow_reply(reply: str) -> Dict[str, Any]:
    """从模型回复中提取跟进结论 JSON，解析失败时降级为纯文本结论。"""
    try:
        start, end = reply.find("{"), reply.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(reply[start:end + 1])
            state = str(data.get("state") or "open")
            if state not in {"open", "blocked", "done"}:
                state = "open"
            pct = max(0, min(100, int(data.get("progress_pct") or 0)))
            note = str(data.get("note") or "").strip()[:1000]
            if note:
                return {"state": state, "progress_pct": pct, "note": note}
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return {"state": "open", "progress_pct": 0, "note": (reply or "跟进无有效结论").strip()[:1000]}


async def run_followup(db: AsyncSession, task: Dict[str, Any], trigger_type: str = "schedule") -> Dict[str, Any]:
    """执行一次跟进：LLM+工具核实 → 更新任务 → 留痕 → 通知。"""
    # 懒加载，避免 service→routes 的启动期循环导入
    from api.routes.chat_routes import (
        MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route,
    )
    from api.services.chat_tools_service import TOOL_DEFINITIONS, WRITE_TOOLS, execute_tool
    from api.services.quick_command_service import build_agent_system_prompt

    task_id = str(task["id"])
    factory_id = task["factory_id"]

    messages: List[Dict[str, Any]] = [{"role": "system", "content": FOLLOWUP_PROMPT}]
    if task.get("agent_key"):
        agent_prompt = build_agent_system_prompt(task["agent_key"])
        if agent_prompt:
            messages.append({"role": "system", "content": agent_prompt})
    context_bits = [
        f"任务标题：{task['title']}",
        f"任务详情：{task.get('description') or '（无）'}",
        f"受阻原因：{task.get('block_reason') or '（未记录）'}",
        f"当前进度：{task.get('progress_pct') or 0}%（已跟进 {task.get('follow_count') or 0} 次）",
        f"上次跟进结论：{task.get('last_follow_note') or '（首次跟进）'}",
    ]
    if task.get("ai_summary"):
        context_bits.append(f"AI 分诊摘要：{task['ai_summary']}")
    if task.get("ai_suggestion"):
        context_bits.append(f"待跟进行动项：\n{task['ai_suggestion']}")
    if task.get("payload"):
        context_bits.append(f"原始内容节选：{str(task['payload'])[:1500]}")
    if task.get("conversation_hint"):
        context_bits.append(f"来源对话：{task['conversation_hint']}")
    messages.append({"role": "user", "content": "\n".join(context_bits)})

    try:
        route = await _resolve_model_route(MODEL_STACK_CHAT_TASK_ID, prompt_tokens=1024)
        payload: Dict[str, Any] = {
            "model": route["gateway_model"],
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": route["max_completion_tokens"],
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
        }
        reply = ""
        for _ in range(FOLLOW_MAX_TOOL_ROUNDS):
            resp = await _call_llm(payload, request_timeout=route["request_timeout"])
            if resp.status_code >= 400:
                reply = f"网关返回 {resp.status_code}，本次跟进未获结论"
                break
            data = resp.json()
            message = (data.get("choices", [{}])[0] or {}).get("message", {}) or {}
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                reply = message.get("content") or ""
                break
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {}) or {}
                tool_name = fn.get("name", "")
                # 定期跟进只做核实，不做写操作（写操作必须由用户在对话里明确触发）
                if tool_name in WRITE_TOOLS:
                    result: Dict[str, Any] = {"error": "任务中心定期跟进为只读核实，不执行写操作"}
                else:
                    try:
                        arguments = json.loads(fn.get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                    result = await execute_tool(db, tool_name, arguments,
                                                operator="task_center", factory_id=factory_id)
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                })
            payload["messages"] = messages
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
        conclusion = _parse_follow_reply(reply)
    except Exception as exc:  # noqa: BLE001 — 单任务跟进失败不能拖垮扫描循环
        _logger.warning("followup run failed for %s: %s", task_id, exc)
        conclusion = {"state": "open", "progress_pct": int(task.get("progress_pct") or 0),
                      "note": f"本次跟进异常（{type(exc).__name__}），下轮重试"}

    new_status = "done" if conclusion["state"] == "done" else conclusion["state"]
    follow_count = int(task.get("follow_count") or 0) + 1
    reached_limit = follow_count >= int(task.get("max_follows") or 60) and new_status not in {"done"}
    if reached_limit:
        new_status = "blocked"
        conclusion["note"] += "（已达最大跟进次数，暂停自动跟进，请人工处理）"

    await db.execute(text("""
        UPDATE followup_tasks
        SET status = :st, progress_pct = :pct, last_follow_at = NOW(), last_follow_note = :note,
            follow_count = :fc, updated_at = NOW(),
            next_follow_at = CASE WHEN :active
                THEN NOW() + (follow_interval_minutes || ' minutes')::interval ELSE NULL END,
            result_summary = CASE WHEN :st = 'done' THEN :note ELSE result_summary END,
            closed_at = CASE WHEN :st = 'done' THEN NOW() ELSE closed_at END
        WHERE id = :id
    """), {
        "st": new_status, "pct": conclusion["progress_pct"], "note": conclusion["note"],
        "fc": follow_count, "active": new_status == "open" and not reached_limit, "id": task_id,
    })
    await _append_log(db, task_id, factory_id, trigger_type,
                      conclusion["note"], new_status, conclusion["progress_pct"], "system")

    # 状态推进 / 完成 / 受阻 → 通知任务所有人
    if new_status == "done":
        await _notify(db, factory_id, task["created_by"],
                      f"任务已完成：{task['title']}", conclusion["note"], "info")
    elif new_status == "blocked":
        await _notify(db, factory_id, task["created_by"],
                      f"任务跟进受阻：{task['title']}", conclusion["note"], "warning")
    await db.commit()
    return {"task_id": task_id, "status": new_status,
            "progress_pct": conclusion["progress_pct"], "note": conclusion["note"]}


# ═══════════════════════════════════════════════════════════
# 定期扫描：到期任务逐个跟进（startup 后台循环调用）
# ═══════════════════════════════════════════════════════════

async def scan_due_tasks(db: AsyncSession) -> Dict[str, Any]:
    """取到期任务执行跟进；FOR UPDATE SKIP LOCKED 防多 worker 重复跟进。"""
    result = await db.execute(text("""
        SELECT id, factory_id, created_by, title, description, agent_key, agent_name,
               status, block_reason, conversation_hint, follow_interval_minutes,
               last_follow_note, follow_count, max_follows, progress_pct,
               item_type, assigned_to, ai_summary, ai_suggestion, payload
        FROM followup_tasks
        WHERE status = 'open' AND next_follow_at IS NOT NULL AND next_follow_at <= NOW()
        ORDER BY next_follow_at ASC
        LIMIT :batch
        FOR UPDATE SKIP LOCKED
    """), {"batch": SCAN_BATCH_SIZE})
    due = [dict(r._mapping) for r in result.fetchall()]
    # 先占位顺延，释放行锁（跟进本身耗时较长，避免锁跨 LLM 调用）
    for t in due:
        await db.execute(text("""
            UPDATE followup_tasks
            SET next_follow_at = NOW() + (follow_interval_minutes || ' minutes')::interval
            WHERE id = :id
        """), {"id": t["id"]})
    await db.commit()

    outcomes = []
    for t in due:
        outcomes.append(await run_followup(db, t, trigger_type="schedule"))
    return {"scanned": len(due), "outcomes": outcomes}


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def followup_scanner_loop() -> None:
    """后台扫描循环（main.py startup 启动）。每分钟看一眼有没有到期任务。"""
    if not _env_flag("FOLLOWUP_SCANNER_ENABLED", True):
        _logger.info("任务中心扫描器已禁用（FOLLOWUP_SCANNER_ENABLED=0）")
        return
    interval = max(15, int(os.getenv("FOLLOWUP_SCAN_INTERVAL_SECONDS", "60") or 60))
    _logger.info("任务中心扫描器启动，每 %s 秒检查到期任务", interval)
    from database.db_config import db_config
    while True:
        try:
            await asyncio.sleep(interval)
            async with db_config.session_factory() as db:
                result = await scan_due_tasks(db)
                if result["scanned"]:
                    _logger.info("任务中心本轮跟进 %s 个任务", result["scanned"])
        except asyncio.CancelledError:
            _logger.info("任务中心扫描器停止")
            return
        except Exception as exc:  # noqa: BLE001 — 扫描循环必须常驻
            _logger.warning("任务中心扫描异常：%s", exc)
