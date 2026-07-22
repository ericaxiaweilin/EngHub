"""
车间级 / 工段级负荷仿真路由

- GET  /api/v1/sim-factory/scenarios  获取多工厂场景列表（前端工厂切换器）
- GET  /api/v1/sim-factory/scenario   获取指定工厂场景（?scenario_id=，默认精密机械厂）
- POST /api/v1/sim-factory/run        运行仿真（全部工段/车间/订单参数可控）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.sim_factory.engine import FactoryLoadEngine
from core.sim_factory.models import (
    FactorySimConfig,
    FactorySimResult,
    OrderInput,
    RoutingDef,
    SectionConfig,
    WorkshopConfig,
)
from core.sim_factory.scenarios import (
    build_scenario,
    get_scenario_meta,
    list_scenarios,
)

router = APIRouter(prefix="/api/v1/sim-factory", tags=["sim-factory"])
engine = FactoryLoadEngine()


class FactorySimScenarioResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    description: str
    hints: List[str]
    tags: List[str] = Field(default_factory=list)
    config: FactorySimConfig


class FactoryScenarioMeta(BaseModel):
    scenario_id: str
    scenario_name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    hints: List[str] = Field(default_factory=list)


class FactorySimRunRequest(BaseModel):
    horizon_days: int = Field(default=14, ge=5, le=60)
    demand_variability_pct: float = Field(default=0.0, ge=0.0, le=0.5)
    overtime_allowed: bool = True
    seed: int = Field(default=42, ge=0)
    workshops: List[WorkshopConfig]
    sections: List[SectionConfig]
    routings: List[RoutingDef]
    orders: List[OrderInput]


@router.get("/status")
async def factory_sim_status() -> Dict[str, Any]:
    return {
        "status": "running",
        "engine": f"FactoryLoadEngine v{FactoryLoadEngine.VERSION}",
        "model": "finite_capacity_mts_mto",
    }


@router.get("/scenarios", response_model=List[FactoryScenarioMeta])
async def list_factory_scenarios() -> List[Dict[str, Any]]:
    """多工厂场景列表（轻量元信息，供前端工厂切换器）。"""
    return list_scenarios()


@router.get("/scenario", response_model=FactorySimScenarioResponse)
async def get_scenario(
    scenario_id: Optional[str] = Query(default=None, description="工厂场景 ID，缺省为默认精密机械厂"),
) -> FactorySimScenarioResponse:
    """获取指定工厂的完整场景（车间/工段/工艺路线/订单）。"""
    meta = get_scenario_meta(scenario_id) if scenario_id else get_scenario_meta("enghub-precision-plant")
    return FactorySimScenarioResponse(
        scenario_id=meta["scenario_id"],
        scenario_name=meta["scenario_name"],
        description=meta["description"],
        hints=meta["hints"],
        tags=meta.get("tags", []),
        config=build_scenario(meta["scenario_id"]),
    )


@router.post("/run", response_model=FactorySimResult)
async def run_simulation(request: FactorySimRunRequest) -> FactorySimResult:
    config = FactorySimConfig(
        horizon_days=request.horizon_days,
        demand_variability_pct=request.demand_variability_pct,
        overtime_allowed=request.overtime_allowed,
        seed=request.seed,
        workshops=request.workshops,
        sections=request.sections,
        routings=request.routings,
        orders=request.orders,
    )
    try:
        return engine.run(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
