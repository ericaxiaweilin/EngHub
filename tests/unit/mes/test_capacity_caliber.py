"""产能口径回归单测：无产能unknown / 超产不钳位 / 交期溢出拒给日期 / 旧路线单位。

锁死 2026-10-03 口径治理的三条红线：
1. 没有 station_capacity 配置的工位不许编利用率（unknown，不参排名）。
2. 超产必须原样暴露（6件/配1件=600%，不许钳到100）。
3. 交期超出 365 天窗口必须 earliest=None，不许钳成窗口最后一天。
4. 旧 routings.steps 的 time_min 是分钟，standard_time 是秒，一律折成小时。
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from api.services.order_decomposition_service import OrderDecompositionService
from core.mes.route_resolution import _legacy_step_hours
from core.rcc.resource_decision import RCCResourceDecisionEngine


# ---------- 4. 旧路线工时单位 ----------

@pytest.mark.asyncio
async def test_legacy_step_hours_time_min_is_minutes():
    assert _legacy_step_hours({"time_min": 30}) == 0.5


@pytest.mark.asyncio
async def test_legacy_step_hours_standard_time_is_seconds():
    assert _legacy_step_hours({"standard_time": 3600}) == 1.0


@pytest.mark.asyncio
async def test_legacy_step_hours_prefers_standard_hours():
    assert _legacy_step_hours({"standard_hours": 2, "time_min": 999}) == 2.0


@pytest.mark.asyncio
async def test_legacy_step_hours_empty_is_zero():
    assert _legacy_step_hours({}) == 0.0


# ---------- 1+2. RCC 瓶颈：unknown 与超产 ----------

def _bottleneck_db(rows):
    """station JOIN 行 + oee 参数位(None) 的 fake session。"""
    db = MagicMock()
    station_res = MagicMock()
    station_res.mappings.return_value.all.return_value = rows
    param_res = MagicMock()
    param_res.scalar.return_value = None

    def _exec(statement, *args, **kwargs):
        if "FROM stations s" in str(statement):
            return station_res
        return param_res

    db.execute = AsyncMock(side_effect=_exec)
    return db


@pytest.mark.asyncio
async def test_bottleneck_over_capacity_is_exposed_not_clamped():
    db = _bottleneck_db([{
        "station_code": "VF-CMECH001-ASSY", "station_name": "装配",
        "today_reports": 3, "today_good_qty": 6, "last_report_time": None,
        "daily_pieces": 1, "efficiency_rate": 0.9,
    }])
    out = await RCCResourceDecisionEngine(db).recommend_bottleneck_resolution("FAC1")
    assert "error" not in out
    assert [s["station_code"] for s in out["bottleneck_stations"]] == ["VF-CMECH001-ASSY"]
    row = out["bottleneck_stations"][0]
    assert row["utilization_pct"] == 600.0
    assert row["is_over_capacity"] is True


@pytest.mark.asyncio
async def test_bottleneck_missing_capacity_is_unknown():
    db = _bottleneck_db([{
        "station_code": "ST-NOCAP-01", "station_name": "无配置",
        "today_reports": 2, "today_good_qty": 5, "last_report_time": None,
        "daily_pieces": None, "efficiency_rate": None,
    }])
    out = await RCCResourceDecisionEngine(db).recommend_bottleneck_resolution("FAC1")
    assert "error" not in out
    assert out["bottleneck_stations"] == []
    assert out["capacity_missing_stations"] == ["ST-NOCAP-01"]
    assert out["balanced_recommendations"] == []


# ---------- 3. 交期：溢出与缺数都拒给日期 ----------

class _AlwaysWorking:
    def is_working_day(self, day):
        return True


def _delivery_db(cap_rows):
    db = MagicMock()

    def _exec(statement, *args, **kwargs):
        res = MagicMock()
        if "station_capacity" in str(statement):
            res.mappings.return_value.all.return_value = cap_rows
        else:  # Routing select：下游走 route_stations 统一口径，这里给空
            res.scalars.return_value.first.return_value = None
        return res

    db.execute = AsyncMock(side_effect=_exec)
    return db


def _patch_routing(stations):
    return patch(
        "core.mes.route_resolution.route_stations_for_product",
        AsyncMock(return_value=list(stations)),
    )


def _patch_models():
    return patch(
        "core.mes.capacity_math.load_station_models",
        AsyncMock(return_value={"ST-A": _AlwaysWorking()}),
    )


@pytest.mark.asyncio
async def test_estimate_delivery_overflow_refuses_date():
    db = _delivery_db([{"station_id": "ST-A", "available_hours_per_day": 0.5}])
    svc = OrderDecompositionService(db)
    with _patch_routing(["ST-A"]), _patch_models():
        out = await svc.estimate_delivery("FAC1", "P1", 2000)
    assert out["estimated_days"] == 4000
    assert out["earliest_delivery"] is None
    assert out["confidence"] == "low"
    assert "365" in out["note"]


@pytest.mark.asyncio
async def test_estimate_delivery_no_capacity_refuses():
    db = _delivery_db([])
    out = await OrderDecompositionService(db).estimate_delivery("FAC1", "P1", 20)
    assert out["earliest_delivery"] is None
    assert out["confidence"] == "unavailable"


@pytest.mark.asyncio
async def test_estimate_delivery_happy_path_counts_shift_days():
    db = _delivery_db([{"station_id": "ST-A", "available_hours_per_day": 10}])
    svc = OrderDecompositionService(db)
    with _patch_routing(["ST-A"]), _patch_models():
        out = await svc.estimate_delivery("FAC1", "P1", 20)
    assert out["estimated_days"] == 2
    assert out["earliest_delivery"] == (date.today() + timedelta(days=1)).isoformat()
    assert out["confidence"] == "medium"
