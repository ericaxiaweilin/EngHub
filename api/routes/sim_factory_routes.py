"""
车间级 / 工段级负荷仿真路由

- GET  /api/v1/sim-factory/scenarios  获取多工厂场景列表（前端工厂切换器）
- GET  /api/v1/sim-factory/scenario   获取指定工厂场景（?scenario_id=，默认精密机械厂）
- POST /api/v1/sim-factory/run        运行仿真（全部工段/车间/订单参数可控）
"""

from __future__ import annotations

from datetime import datetime, timezone
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

# 仿真结果看板缓存：仿真为按需计算（不落库），看板每次加载不应重跑全量仿真，
# 故按 scenario_id 内存缓存，TTL 内复用。仿真数据与真实生产数据完全分离。
_SIM_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}
_SIM_SUMMARY_TTL = 300  # 秒


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


@router.get("/dashboard-summary")
async def factory_sim_dashboard_summary(
    scenario_id: Optional[str] = Query(default=None, description="工厂场景 ID，缺省为默认精密机械厂"),
) -> Dict[str, Any]:
    """供生产看板使用的仿真结果轻量摘要。

    重要：仿真数据与真实生产数据严格分离，本接口返回结果带 is_simulation=True 标记，
    前端需独立分区展示，不得与实时报工/工单/设备数据混计。
    """
    sid = scenario_id or "enghub-precision-plant"
    now = datetime.now(timezone.utc)
    cached = _SIM_SUMMARY_CACHE.get(sid)
    if cached and (now - cached["ts"]).total_seconds() < _SIM_SUMMARY_TTL:
        return cached["data"]

    meta = get_scenario_meta(sid)
    config = build_scenario(sid)
    try:
        result = engine.run(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    k = result.kpis
    data: Dict[str, Any] = {
        "is_simulation": True,  # 明确标记：仿真数据，非真实生产
        "scenario_id": sid,
        "scenario_name": meta.get("scenario_name", sid),
        "engine_version": result.engine_version,
        "horizon_days": result.horizon_days,
        "order_count": result.order_count,
        "section_count": result.section_count,
        "created_at": result.created_at.isoformat(),
        "kpis": k.model_dump(),
        # 卡点排行 Top5（供看板快速展示瓶颈）
        "blocking_points": [bp.model_dump() for bp in result.blocking_points[:5]],
        "alert_count": len(result.alerts),
        "critical_alert_count": sum(1 for a in result.alerts if a.level == "critical"),
    }
    _SIM_SUMMARY_CACHE[sid] = {"ts": now, "data": data}
    return data
