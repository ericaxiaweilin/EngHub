"""Factory-scoped manufacturing intelligence overview.

The endpoints expose only operational state and evidence summaries.  They do
not disclose model gateway URLs and inherit the normal user/factory boundary.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.security import get_current_user
from core.intelligence import (
    IntelligenceHealth,
    IntelligenceOverview,
    ManufacturingIntelligenceService,
    get_manufacturing_intelligence_service,
)
from database.db_config import get_db
from database.models import User

router = APIRouter(prefix="/api/v1/intelligence", tags=["manufacturing-intelligence"])


def _factory_id_for_user(requested_factory_id: Optional[str], current_user: User) -> str:
    active_factory_id = (
        getattr(current_user, "active_factory_id", None)
        or getattr(current_user, "factory_id", None)
    )
    if (
        requested_factory_id
        and active_factory_id
        and requested_factory_id != active_factory_id
        and not bool(getattr(current_user, "is_superuser", False))
    ):
        raise HTTPException(status_code=403, detail="无权查看其他工厂的制造智能状态")
    factory_id = requested_factory_id or active_factory_id
    if not factory_id:
        raise HTTPException(status_code=422, detail="请先选择工厂或传入 factory_id")
    return str(factory_id)


@router.get("/overview", response_model=IntelligenceOverview)
async def get_overview(
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ManufacturingIntelligenceService = Depends(get_manufacturing_intelligence_service),
):
    """Aggregate current operational evidence and deterministic risk signals."""
    return await service.build_overview(db, _factory_id_for_user(factory_id, current_user))


@router.get("/health", response_model=IntelligenceHealth)
async def get_health(
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ManufacturingIntelligenceService = Depends(get_manufacturing_intelligence_service),
):
    """Probe components independently; optional failures return degraded state."""
    return await service.build_health(db, _factory_id_for_user(factory_id, current_user))
