"""生产看板 payload 形状契约：返回必须 ⊇ 生产数据页共用 UI 的硬读字段。

回归 2026-10-03 白屏事故：共用看板 UI 对 k.total_unmet_hours /
section.unmet_hours 等做 .toFixed 硬读，缺键即抛异常被 ErrorBoundary
兜成“页面渲染失败”，而 deploy_verify 只验 HTTP 200 拦不住。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.routes.production_dashboard_routes import production_dashboard_summary


def _shape_db():
    now = datetime.utcnow()
    station = SimpleNamespace(
        id="SID-1", station_code="ST-A", station_name="A站",
        workshop_id="WS1", capacity_per_hour=10,
    )
    report = SimpleNamespace(
        created_at=now, station_id="ST-A",
        good_qty=5, defect_qty=1, scrap_qty=0, work_order_id=None,
    )
    db = MagicMock()

    def _exec(statement, *args, **kwargs):
        s = str(statement)
        res = MagicMock()
        if "production_reports" in s:
            res.scalars.return_value.all.return_value = [report]
        elif "stations" in s and "station_capacity" not in s:
            res.scalars.return_value.all.return_value = [station]
        elif "hr_employees" in s:
            res.all.return_value = []
        else:
            res.scalars.return_value.all.return_value = []
        return res

    db.execute = AsyncMock(side_effect=_exec)
    return db


@pytest.mark.asyncio
async def test_summary_shape_covers_ui_hard_reads():
    out = await production_dashboard_summary(
        factory_id="F1", horizon_days=14,
        db=_shape_db(), current_user={"username": "t"},
    )
    assert out["is_simulation"] is False
    for key in ("horizon_days", "order_count", "section_count", "kpis",
                "sections", "orders", "alerts", "wip_curve", "workforce",
                "daily_output", "section_outputs", "production_orders",
                "transfers", "blocking_points", "outbound_orders", "realtime"):
        assert key in out, "top-level missing " + key

    # 当年 crash 点：k.total_unmet_hours.toFixed(0)
    k = out["kpis"]
    assert isinstance(k["total_unmet_hours"], (int, float))
    round(k["total_unmet_hours"], 0)

    assert len(out["sections"]) == 1
    s = out["sections"][0]
    for field, typ in (("demand_hours", (int, float)),
                       ("unmet_hours", (int, float)),
                       ("pressure_rate", (int, float)),
                       ("binding_resource", str),
                       ("wip_peak", (int, float)),
                       ("overload_days", int)):
        assert field in s, "section missing " + field
        assert isinstance(s[field], typ), field
    # 口径：demand=实际负荷，unmet=超额定部分，pressure 不钳位
    assert s["demand_hours"] == s["total_load_hours"]
    assert s["unmet_hours"] == round(max(0.0, s["total_load_hours"] - s["total_capacity_hours"]), 1)
    assert s["pressure_rate"] == round(s["total_load_hours"] / s["total_capacity_hours"], 3)
    round(s["unmet_hours"], 0)
    "%g%%" % (s["pressure_rate"] * 100)

    # 告警中心直接 .length
    assert isinstance(out["alerts"], list)
