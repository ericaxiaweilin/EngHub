"""工厂指挥官 API：chatbot 顶部开关 + 态势感知循环。"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user
from api.services import commander_service as svc

router = APIRouter(prefix="/api/v1/commander", tags=["commander"])


def _resolve_factory(request: Request, user: User, body_factory_id: Optional[str] = None) -> str:
    return (
        body_factory_id
        or request.headers.get("x-factory-id")
        or getattr(user, "active_factory_id", None)
        or user.factory_id
        or "FAC_MECH_001"
    )


def _uid(user: User) -> str:
    return str(user.username or user.id)


class ToggleBody(BaseModel):
    enabled: bool = True
    factory_id: Optional[str] = None


class CycleBody(BaseModel):
    factory_id: Optional[str] = None
    auto_execute: bool = Field(True, description="是否自动执行低风险决策")


@router.get("/my-status")
async def my_status(
    request: Request,
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = _resolve_factory(request, current_user, factory_id)
    return await svc.get_status(db, _uid(current_user), fid)


@router.post("/toggle")
async def toggle(
    body: ToggleBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = _resolve_factory(request, current_user, body.factory_id)
    return await svc.toggle(db, _uid(current_user), fid, body.enabled)


@router.post("/cycle")
async def cycle(
    body: CycleBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = _resolve_factory(request, current_user, body.factory_id)
    return await svc.run_cycle(
        db, _uid(current_user), fid, auto_execute=body.auto_execute
    )
