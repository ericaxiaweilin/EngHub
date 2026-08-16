"""
任务中心（统一待办工作台）路由
- /api/v1/task-center/tasks              待办 CRUD（挂账/指派/更新频率/关单）
- /api/v1/task-center/tasks/{id}/logs    跟进历史时间线
- /api/v1/task-center/tasks/{id}/follow-now  立即跟进一次（不等定期扫描）
- /api/v1/task-center/ingest             接入会议纪要/邮件/备忘 → AI 分诊
- /api/v1/task-center/inbox              统一收件箱（待办+指派工单+未读通知）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/task-center", tags=["task-center"])


def _resolve_factory(request: Request, user: User) -> str:
    return (
        request.headers.get("x-factory-id")
        or getattr(user, "active_factory_id", None)
        or user.factory_id
        or "FAC_MECH_001"
    )


class FollowupTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    agent_key: Optional[str] = None  # 不传则自动归类
    follow_interval_minutes: int = Field(120, ge=15, le=10080)  # 15分钟 ~ 7天
    block_reason: Optional[str] = Field(None, max_length=500)
    item_type: str = Field("followup")  # followup / assigned / note
    assigned_to: Optional[str] = Field(None, max_length=64)  # 指派给谁（username）
    due_at: Optional[str] = None  # ISO 截止时间


class IngestPayload(BaseModel):
    item_type: str = Field(..., description="meeting / email / note")
    content: str = Field(..., min_length=1, max_length=20000)
    title: Optional[str] = Field(None, max_length=200)
    follow_interval_minutes: int = Field(120, ge=15, le=10080)


class FollowupTaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    agent_key: Optional[str] = None
    status: Optional[str] = None  # open / blocked / done / cancelled
    block_reason: Optional[str] = Field(None, max_length=500)
    follow_interval_minutes: Optional[int] = Field(None, ge=15, le=10080)
    progress_pct: Optional[int] = Field(None, ge=0, le=100)
    result_summary: Optional[str] = Field(None, max_length=2000)
    assigned_to: Optional[str] = Field(None, max_length=64)
    due_at: Optional[str] = None


@router.get("/consistency-audit", summary="数据一致性审查报告（设备/人/任务/工单/chatbot/RCC 自动对账）")
async def get_consistency_audit(db: AsyncSession = Depends(get_db)):
    """自动对账：六方数据自证一致，DRIFT/ERROR 一目了然。"""
    from api.services.consistency_audit import audit_consistency
    from database.db_config import db_config
    results = []
    async with db_config.session_factory() as sdb:
        for fid in ("FAC_MECH_001", "FAC_ELEC_DEMO_2026"):
            try:
                results.append(await audit_consistency(sdb, fid))
            except Exception as e:
                await sdb.rollback()
                results.append({"factory_id": fid, "error": str(e)[:100]})
    return {"success": True, "reports": results}


@router.get("/tasks")
async def list_followup_tasks(
    request: Request,
    status: Optional[str] = None,
    item_type: Optional[str] = None,
    mine: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """待办列表（默认当前工厂全部；mine=true 只看我挂的/指派给我的）。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    tasks = await svc.list_tasks(
        db, factory_id, status=status, item_type=item_type,
        involving=(current_user.username or current_user.id) if mine else None,
    )
    return {"tasks": tasks}


@router.post("/tasks", status_code=201)
async def create_followup_task(
    payload: FollowupTaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """挂一个待办；支持指派给他人（assigned_to）；未指定 agent_key 时自动归类。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.create_task(
        db, factory_id,
        created_by=current_user.username or current_user.id,
        title=payload.title,
        description=payload.description or "",
        agent_key=payload.agent_key,
        follow_interval_minutes=payload.follow_interval_minutes,
        block_reason=payload.block_reason or "",
        source="manual",
        item_type=payload.item_type if payload.item_type in {"followup", "assigned", "note"} else "followup",
        assigned_to=payload.assigned_to,
        due_at=payload.due_at,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/ingest", status_code=201)
async def ingest_content(
    payload: IngestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """接入会议纪要/邮件/备忘 → AI 自动分诊（摘要/行动项/紧急度）；
    纯知会类自动归档，有行动项的进入跟进循环或提醒用户。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.ingest_item(
        db, factory_id,
        created_by=current_user.username or current_user.id,
        item_type=payload.item_type,
        content=payload.content,
        title=payload.title or "",
        follow_interval_minutes=payload.follow_interval_minutes,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/inbox")
async def unified_inbox(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """统一收件箱：待办任务 + 指派给我的工单 + 未读通知，一次拉取。"""
    from sqlalchemy import text as sql
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    username = current_user.username or current_user.id

    tasks = await svc.list_tasks(db, factory_id)

    # 指挥官行动计划（Plan）：active 优先，含子任务
    try:
        plans = await svc.list_plans(db, factory_id, limit=20)
    except Exception:
        plans = []

    # 指派给我的工序工单（未完工）
    wo_rows = await db.execute(sql("""
        SELECT id, work_order_code, status, priority, planned_qty, planned_due,
               process_code, remark
        FROM work_orders
        WHERE factory_id = :fid AND assigned_to = :uid
          AND status IN ('pending', 'released', 'in_progress', 'on_hold')
        ORDER BY priority DESC, planned_due ASC NULLS LAST
        LIMIT 50
    """), {"fid": factory_id, "uid": str(current_user.id)})
    work_orders = [dict(r._mapping) for r in wo_rows.fetchall()]

    # 未读站内通知（广播或发给我的）
    notif_rows = await db.execute(sql("""
        SELECT id, category, title, content, severity, source_type, source_id, created_at
        FROM notifications
        WHERE factory_id = :fid AND is_read = false
          AND (recipient IS NULL OR recipient = :uname)
        ORDER BY created_at DESC
        LIMIT 30
    """), {"fid": factory_id, "uname": username})
    notifications = [dict(r._mapping) for r in notif_rows.fetchall()]

    open_tasks = [t for t in tasks if t["status"] in ("open", "blocked")]
    return {
        "tasks": tasks,
        "plans": plans,
        "work_orders": work_orders,
        "notifications": notifications,
        "stats": {
            "open_tasks": len(open_tasks),
            "my_work_orders": len(work_orders),
            "unread_notifications": len(notifications),
        },
    }


@router.post("/notifications/{notification_id}/to-task", status_code=201)
async def notification_to_task(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把一条通知转为跟进任务（同时标记已读）。"""
    from sqlalchemy import text as sql
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    row = (await db.execute(sql(
        "SELECT id, title, content, category FROM notifications WHERE id = :id AND factory_id = :fid"
    ), {"id": notification_id, "fid": factory_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="通知不存在")
    notif = dict(row._mapping)
    result = await svc.create_task(
        db, factory_id,
        created_by=current_user.username or current_user.id,
        title=notif["title"][:200],
        description=notif.get("content") or "",
        source="notification",
        conversation_hint=f"来自通知（{notif.get('category') or 'system'}）",
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    await db.execute(sql(
        "UPDATE notifications SET is_read = true WHERE id = :id"
    ), {"id": notification_id})
    await db.commit()
    return result


@router.put("/tasks/{task_id}")
async def update_followup_task(
    task_id: str,
    payload: FollowupTaskUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新任务（跟进频率/状态/进度等）。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.update_task(
        db, task_id, factory_id,
        operator=current_user.username or current_user.id,
        **payload.model_dump(exclude_unset=True),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/tasks/{task_id}")
async def delete_followup_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除任务（连带跟进历史）。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    result = await svc.delete_task(db, task_id, factory_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.get("/tasks/{task_id}/logs")
async def get_followup_task_logs(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """跟进历史时间线（最新在前）。"""
    from api.services import followup_task_service as svc
    return {"logs": await svc.get_task_logs(db, task_id)}


@router.get("/tasks/{task_id}/map")
def _humanize_note(raw) -> str:
    """把跟进记录清洗成人类可读文本：
    - 若 note 是 JSON（如 {"progress_pct":75,"state":"blocked","note":"..."}）→ 提取其中的 note 字段
    - 去掉残留 XML 标签 / 系统代码痕迹
    """
    import json as _j, re as _re
    text = str(raw or "").strip()
    if not text:
        return text
    # 若整体是 JSON → 提取可读字段
    if text.startswith("{") and text.rstrip().endswith("}"):
        try:
            d = _j.loads(text)
            if isinstance(d, dict):
                note = d.get("note") or ""
                state = d.get("state") or ""
                if note:
                    text = str(note).strip()
                    if state:
                        state_label = {"blocked": "受阻", "done": "已完成", "open": "跟进中"}.get(state, state)
                        text = f"{text}"
        except Exception:
            pass
    # 去掉 XML 工具标签残留
    text = _re.sub(r"<tool_call>|</tool_call>|<function=[^>]*>|</function>|<parameter[^>]*>|</parameter>", "", text)
    text = _re.sub(r"\s+", " ", text).strip()
    return text[:300]


async def get_followup_task_map(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """任务处理地图：把任务的完整处理路径结构化（生命周期节点 + 跟进步骤 + 卡点归因），
    像人类员工的项目汇报一样直观展示：从挂账 → 智能体接管 → 每轮跟进 → 受阻卡点 → 闭环。"""
    from sqlalchemy import text
    from api.services import followup_task_service as svc

    row = (await db.execute(text("""
        SELECT id, factory_id, created_by, title, description, agent_key, agent_name,
               status, block_reason, blocked_by, block_category, conversation_hint,
               follow_interval_minutes, last_follow_note, follow_count, max_follows,
               progress_pct, item_type, assigned_to, ai_summary, ai_suggestion,
               result_summary, due_at, created_at, updated_at, closed_at
        FROM followup_tasks WHERE id = :tid
    """), {"tid": task_id})).mappings().first()
    if not row:
        return {"error": "任务不存在"}

    logs = await svc.get_task_logs(db, task_id, limit=100)
    t = dict(row)

    # ── 生命周期节点 ──
    nodes = []

    # 节点1：挂账
    nodes.append({
        "stage": "created", "label": "任务挂账", "status": "done",
        "at": t.get("created_at"), "by": t.get("created_by"),
        "note": f"任务创建，由 {t.get('agent_name') or t.get('agent_key') or '系统'} 负责跟进"
                + (f"，指派给 {t['assigned_to']}" if t.get("assigned_to") else ""),
    })

    # 节点2：智能体接管（agent 字段存在即视为接管）
    nodes.append({
        "stage": "handoff", "label": "智能体接管", "status": "done",
        "at": t.get("created_at"), "by": t.get("agent_name") or t.get("agent_key"),
        "note": f"{t.get('agent_name') or t.get('agent_key')} 接管任务"
                + (f"（{t.get('follow_interval_minutes')} 分钟/次跟进）" if t.get("follow_interval_minutes") else ""),
    })

    # 节点3：跟进步骤（从 logs 反序 = 时间正序）
    _TRIGGER_LABELS = {
        "schedule": "定期扫描", "manual": "手动跟进", "manual_test": "手动跟进",
        "manual_loop": "手动跟进", "manual_loop_pmc": "手动跟进", "manual_boundary": "手动跟进",
        "manual_e2e": "手动跟进", "manual_full": "手动跟进", "status": "状态变更",
        "auto": "自动", "system": "系统", "commander": "指挥官",
    }
    follow_nodes = []
    for log in reversed(logs):
        note = _humanize_note(log.get("note") or "")
        # 跳过纯状态标记
        if note in ("任务已挂入任务中心，每 60 分钟跟进一次",
                    "任务已挂入任务中心，每 120 分钟跟进一次") or "挂入任务中心" in note and len(note) < 40:
            continue
        st = log.get("status_after") or ""
        trig = str(log.get("trigger_type") or "")
        follow_nodes.append({
            "stage": "follow", "label": f"跟进 #{len(follow_nodes) + 1}",
            "status": "done" if st == "done" else "blocked" if st == "blocked" else "active" if st == "open" else "done",
            "at": log.get("created_at"), "by": _TRIGGER_LABELS.get(trig, trig or "系统"),
            "pct": log.get("progress_pct"),
            "note": note[:300],
        })
    nodes.extend(follow_nodes)

    # 节点4：卡点（blocked 时）
    if t.get("status") == "blocked":
        nodes.append({
            "stage": "blocked", "label": "受阻卡点", "status": "blocked",
            "at": t.get("updated_at"),
            "blocked_by": t.get("blocked_by") or "未归因",
            "block_category": t.get("block_category") or "",
            "note": _humanize_note(t.get("last_follow_note") or t.get("block_reason") or "任务受阻，等待外部条件"),
        })
    # 节点5：闭环（done 时）
    if t.get("status") == "done":
        nodes.append({
            "stage": "closed", "label": "任务闭环", "status": "done",
            "at": t.get("closed_at") or t.get("updated_at"),
            "note": (t.get("result_summary") or t.get("last_follow_note") or "任务已完成")[:300],
        })

    # ── 卡点归因（blocked 时给醒目提示）──
    block_attribution = None
    if t.get("status") == "blocked":
        block_attribution = {
            "blocked_by": t.get("blocked_by") or "未归因",
            "block_category": t.get("block_category") or "",
            "note": (t.get("last_follow_note") or "任务受阻")[:300],
            "next_retry_at": None,
        }
        try:
            from sqlalchemy import text as _t2
            nr = (await db.execute(_t2(
                "SELECT next_follow_at FROM followup_tasks WHERE id=:tid"
            ), {"tid": task_id})).mappings().first()
            if nr and nr["next_follow_at"]:
                block_attribution["next_retry_at"] = nr["next_follow_at"]
        except Exception:
            pass

    # ── 对接工作流引擎：工单生命周期流转映射 ──
    workflow = None
    try:
        from api.services.process_knowledge_service import WORK_ORDER_FLOW, RACI_MATRIX
        import re as _re2
        # 从任务标题提取工单号
        wo_code = None
        m_wo = _re2.search(r"(WO-[\w\-]+)", t.get("title") or "")
        if m_wo:
            wo_code = m_wo.group(1)
        # 查工单真实状态
        wo_row = None
        if wo_code:
            wo_row = (await db.execute(text(
                "SELECT work_order_code, status, current_routing_step FROM work_orders WHERE work_order_code = :c LIMIT 1"
            ), {"c": wo_code})).mappings().first()
        # 当前阶段：优先按 current_routing_step，否则按工单状态匹配
        current_stage_idx = None
        wo_status = (wo_row["status"] if wo_row else None) or ""
        if wo_row and wo_row.get("current_routing_step") is not None:
            current_stage_idx = max(0, min(int(wo_row["current_routing_step"]) - 1, len(WORK_ORDER_FLOW) - 1))
        else:
            for i, st in enumerate(WORK_ORDER_FLOW):
                if st.get("status") == wo_status:
                    current_stage_idx = i
                    break
        # 卡点阶段：blocked 时按 block_category 映射阶段
        block_stage_idx = None
        if t.get("status") == "blocked":
            cat = (t.get("block_category") or "").lower()
            cat_stage = {
                "material": "执行", "supplier": "审批/下达", "approval": "审批/下达",
                "equipment": "执行", "staff": "派工", "data": "报工",
            }.get(cat)
            if cat_stage:
                for i, st in enumerate(WORK_ORDER_FLOW):
                    if st.get("stage") == cat_stage:
                        block_stage_idx = i
                        break
        # RACI owner（当前阶段）
        owner_info = None
        if current_stage_idx is not None:
            stage_name = WORK_ORDER_FLOW[current_stage_idx].get("stage", "")
            raci = RACI_MATRIX.get(stage_name, {})
            responsible = [r for r, v in raci.items() if "R" in v]
            accountable = [r for r, v in raci.items() if "A" in v]
            owner_info = {
                "stage": stage_name,
                "responsible": responsible,
                "accountable": accountable,
            }
        workflow = {
            "title": "生产工单全生命周期",
            "stages": [
                {"stage": s.get("stage", ""), "status": s.get("status", ""),
                 "role": s.get("role", ""), "actions": (s.get("actions") or "")[:120],
                 "blockpoint": (s.get("blockpoint") or "")[:120]}
                for s in WORK_ORDER_FLOW
            ],
            "work_order_code": wo_code,
            "work_order_status": wo_status,
            "current_stage_idx": current_stage_idx,
            "block_stage_idx": block_stage_idx,
            "owner": owner_info,
        }
    except Exception as _wexc:  # 工作流映射失败不阻塞地图主体
        workflow = None

    return {
        "task_id": task_id,
        "title": t.get("title"),
        "status": t.get("status"),
        "workflow": workflow,
        "progress_pct": t.get("progress_pct"),
        "agent_name": t.get("agent_name") or t.get("agent_key"),
        "follow_count": t.get("follow_count"),
        "max_follows": t.get("max_follows"),
        "block_attribution": block_attribution,
        "nodes": nodes,
        "stats": {
            "follow_steps": len(follow_nodes),
            "blocked_count": sum(1 for n in nodes if n["status"] == "blocked"),
        },
    }


@router.post("/tasks/{task_id}/follow-now")
async def follow_now(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """立即跟进一次（不等定期扫描；智能体+工具核实后返回结论）。"""
    from api.services import followup_task_service as svc
    from sqlalchemy import text
    factory_id = _resolve_factory(request, current_user)
    result = await db.execute(text("""
        SELECT id, factory_id, created_by, title, description, agent_key, agent_name,
               status, block_reason, conversation_hint, follow_interval_minutes,
               last_follow_note, follow_count, max_follows, progress_pct,
               item_type, assigned_to, ai_summary, ai_suggestion, payload
        FROM followup_tasks WHERE id = :id AND factory_id = :fid
    """), {"id": task_id, "fid": factory_id})
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = dict(row._mapping)
    if task["status"] not in {"open", "blocked"}:
        raise HTTPException(status_code=400, detail="任务已关闭，无需跟进")
    return await svc.run_followup(db, task, trigger_type="manual")


__all__ = ["router"]
