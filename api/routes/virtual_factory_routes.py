"""Virtual factory pulse routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.security import get_current_user
from database.db_config import get_db
from database.models import User
from api.services.virtual_factory_service import (
    DEFAULT_FACTORY_ID,
    DEFAULT_MONTHLY_CONTAINERS,
    DEFAULT_ORDER_DAYS,
    PulseConfig,
    VirtualFactoryService,
)

router = APIRouter(prefix="/api/v1/virtual-factory", tags=["virtual-factory"])


class VirtualFactoryPulseRequest(BaseModel):
    factory_id: str | None = None
    monthly_capacity_containers: int = Field(DEFAULT_MONTHLY_CONTAINERS, ge=30, le=3000)
    order_lead_days: int = Field(DEFAULT_ORDER_DAYS, ge=14, le=365)
    target_active_orders: int = Field(6, ge=1, le=30)
    max_new_orders_per_pulse: int = Field(1, ge=0, le=5)


def _resolve_factory_id(req: VirtualFactoryPulseRequest | None, http_request: Request | None, user: User) -> str:
    return (
        (req.factory_id if req else None)
        or (http_request.headers.get("x-factory-id") if http_request else None)
        or getattr(user, "active_factory_id", None)
        or user.factory_id
        or DEFAULT_FACTORY_ID
    )


@router.get("/status")
async def virtual_factory_status(
    factory_id: str | None = Query(default=None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = factory_id or (request.headers.get("x-factory-id") if request else None) or getattr(current_user, "active_factory_id", None) or current_user.factory_id or DEFAULT_FACTORY_ID
    return await VirtualFactoryService(db).status(fid)


@router.post("/pulse")
async def virtual_factory_pulse(
    body: VirtualFactoryPulseRequest,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = _resolve_factory_id(body, request, current_user)
    cfg = PulseConfig(
        factory_id=fid,
        monthly_capacity_containers=body.monthly_capacity_containers,
        order_lead_days=body.order_lead_days,
        target_active_orders=body.target_active_orders,
        max_new_orders_per_pulse=body.max_new_orders_per_pulse,
        operator="virtual_factory",
    )
    return await VirtualFactoryService(db).pulse(cfg)
