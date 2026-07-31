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
