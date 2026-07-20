"""
Unified routes for EngHub intelligence capabilities.
"""

from fastapi import APIRouter, Depends

from core.intelligence import (
    IntelligenceHealth,
    IntelligenceOverview,
    ManufacturingIntelligenceHub,
    get_intelligence_hub,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


@router.get("/overview", response_model=IntelligenceOverview)
async def get_overview(
    hub: ManufacturingIntelligenceHub = Depends(get_intelligence_hub),
):
    return hub.build_overview()


@router.get("/health", response_model=IntelligenceHealth)
async def get_health(
    hub: ManufacturingIntelligenceHub = Depends(get_intelligence_hub),
):
    return await hub.build_health_snapshot()
