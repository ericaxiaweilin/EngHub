"""
任务中心（待办跟进）路由
- /api/v1/task-center/tasks              任务 CRUD（挂账/更新频率/关单）
- /api/v1/task-center/tasks/{id}/logs    跟进历史时间线
- /api/v1/task-center/tasks/{id}/follow-now  立即跟进一次（不等定期扫描）
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


class FollowupTaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    agent_key: Optional[str] = None
    status: Optional[str] = None  # open / blocked / done / cancelled
    block_reason: Optional[str] = Field(None, max_length=500)
    follow_interval_minutes: Optional[int] = Field(None, ge=15, le=10080)
    progress_pct: Optional[int] = Field(None, ge=0, le=100)
    result_summary: Optional[str] = Field(None, max_length=2000)


@router.get("/tasks")
async def list_followup_tasks(
    request: Request,
    status: Optional[str] = None,
    mine: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """任务列表（默认当前工厂全部；mine=true 只看自己挂的）。"""
    from api.services import followup_task_service as svc
    factory_id = _resolve_factory(request, current_user)
    tasks = await svc.list_tasks(
        db, factory_id, status=status,
        created_by=(current_user.username or current_user.id) if mine else None,
    )
    return {"tasks": tasks}


@router.post("/tasks", status_code=201)
async def create_followup_task(
    payload: FollowupTaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """挂一个跟进任务；未指定 agent_key 时自动归类到对应智能体。"""
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
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
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
               last_follow_note, follow_count, max_follows, progress_pct
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
