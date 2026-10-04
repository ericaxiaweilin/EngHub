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


@router.get("/engine/health")
async def engine_health(current_user: User = Depends(get_current_user)):
    """引擎（后台循环）到底有没有在跑 —— 心跳表实测，不再靠"应该在下一次调度里"。

    循环已搬进独立进程 enghub-engine，这里只读它写的心跳；
    停摆时 API 依然全是 200，所以这个接口是唯一能证伪"无人"的地方。
    """
    from api.services.engine_heartbeat import read_states

    states = await read_states()
    heart = next((s for s in states if s["loop"] == "periodic-scheduler"), None)
    return {
        "engine_alive": bool(heart and heart.get("alive")),
        "reason": (
            "心跳表里没有 periodic-scheduler 记录：引擎进程没起来或迁移 097 未执行"
            if heart is None
            else ("心跳新鲜" if heart["alive"] else
                  f"心跳已 {heart['stale_seconds']} 秒未更新（阈值 {heart['interval_seconds'] * 2} 秒）")
        ),
        "loops": states,
        "engine_endpoint": "http://<host>:18889/health",
    }


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
