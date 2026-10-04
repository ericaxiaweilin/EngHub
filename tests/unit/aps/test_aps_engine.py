"""APS 引擎兼容层 + 服务真实行为回归：只调真实存在的方法签名。

上一版用 patch('aps_service.ApsEngine')（模块里没有这个名字）以及
ApsEngine 旧签名（priority/insert_wo_ids/days），10 个全红。
本文件按当前实现重写：ApsEngine 是 ApsService 的轻兼容壳。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from api.services.aps_engine import ApsEngine
from api.services.aps_service import ApsService


@pytest.fixture(scope="function")
def mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _empty_execute(db, scalar_one_or_none=None):
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    res.scalar_one_or_none.return_value = scalar_one_or_none
    res.mappings.return_value.all.return_value = []
    res.first.return_value = None
    res.scalar.return_value = 0
    db.execute = AsyncMock(return_value=res)
    return db


@pytest.mark.asyncio
async def test_engine_schedule_maps_algorithm_and_counts_conflicts(mock_db):
    with patch.object(
        ApsService, "generate_schedule",
        AsyncMock(return_value={"success": True, "schedule_id": "s1", "unscheduled_orders": ["w1"]}),
    ) as gen:
        out = await ApsEngine(mock_db).schedule(factory_id="F1", algorithm="EDD")
    assert out["algorithm"] == "EDD"
    assert out["conflict_count"] == 1
    _, kwargs = gen.call_args
    assert kwargs["mode"] == "hybrid" and kwargs["optimize_for"] == "delivery"


@pytest.mark.asyncio
async def test_engine_schedule_spt_maps_efficiency(mock_db):
    with patch.object(
        ApsService, "generate_schedule",
        AsyncMock(return_value={"success": True, "schedule_id": "s1", "unscheduled_orders": []}),
    ) as gen:
        await ApsEngine(mock_db).schedule(factory_id="F1", algorithm="SPT")
    assert gen.call_args[1]["optimize_for"] == "efficiency"


@pytest.mark.asyncio
async def test_engine_schedule_failure_sets_error(mock_db):
    with patch.object(
        ApsService, "generate_schedule",
        AsyncMock(return_value={"success": False, "message": "爆了"}),
    ):
        out = await ApsEngine(mock_db).schedule(factory_id="F1")
    assert out["error"] == "爆了"


@pytest.mark.asyncio
async def test_engine_reschedule_delegates_with_compat_reason(mock_db):
    with patch.object(
        ApsService, "reschedule",
        AsyncMock(return_value={"success": True}),
    ) as rs:
        out = await ApsEngine(mock_db).reschedule(
            factory_id="F1", insert_wo_id="W1", algorithm="EDD",
        )
    assert out["success"] is True and out["algorithm"] == "EDD"
    assert rs.call_args[1]["change_reason"] == "compat_insert:W1"


@pytest.mark.asyncio
async def test_engine_get_gantt_data_passthrough(mock_db):
    with patch.object(
        ApsService, "get_gantt_data",
        AsyncMock(return_value={"schedule_id": "s1", "total_tasks": 2}),
    ) as g:
        out = await ApsEngine(mock_db).get_gantt_data("F1", schedule_id="s1")
    assert out == {"schedule_id": "s1", "total_tasks": 2}
    assert g.call_args[0] == ("s1",)


@pytest.mark.asyncio
async def test_engine_get_gantt_data_no_current_schedule(mock_db):
    _empty_execute(mock_db)
    out = await ApsEngine(mock_db).get_gantt_data("F1")
    assert out["schedule_id"] is None and out["total_tasks"] == 0


def _conflict_db(tasks=(), work_orders=(), bom_count=0):
    db = MagicMock()
    latest = MagicMock()
    latest.first.return_value = ("sid-1",) if tasks else None
    task_res = MagicMock()
    task_res.mappings.return_value.all.return_value = list(tasks)
    wo_res = MagicMock()
    wo_res.scalars.return_value.all.return_value = list(work_orders)
    bom_res = MagicMock()
    bom_res.scalar.return_value = bom_count

    def _exec(statement, *args, **kwargs):
        s = str(statement)
        if "aps_schedule_tasks" in s:
            return task_res
        if "aps_schedules" in s:
            return latest
        if "bom_items" in s:
            return bom_res
        return wo_res

    db.execute = AsyncMock(side_effect=_exec)
    return db


@pytest.mark.asyncio
async def test_engine_detect_conflicts_empty():
    out = await ApsEngine(_conflict_db()).detect_conflicts("F1")
    assert out == {"conflicts": [], "count": 0}


@pytest.mark.asyncio
async def test_engine_detect_conflicts_delivery_risk():
    now = datetime.utcnow()
    out = await ApsEngine(_conflict_db(tasks=[{
        "planned_end": now, "planned_due": now - timedelta(hours=5),
        "work_order_code": "WO-1", "planned_qty": 10,
    }])).detect_conflicts("F1")
    assert out["count"] == 1
    assert out["conflicts"][0]["type"] == "delivery_risk"
    assert out["conflicts"][0]["delay_hours"] == 5.0


@pytest.mark.asyncio
async def test_engine_detect_conflicts_no_bom():
    wo = SimpleNamespace(product_id="P9", work_order_code="WO-9")
    out = await ApsEngine(_conflict_db(work_orders=[wo], bom_count=0)).detect_conflicts("F1")
    assert out["count"] == 1
    assert out["conflicts"][0]["type"] == "no_bom"


def _task(**kw):
    base = dict(
        id="t1", work_order_id="wo1", order_code="WO-001", station_id="ST-A",
        product_code="P1", operation_seq=10, operation_name="装配",
        planned_start=datetime(2026, 1, 5, 8), planned_end=datetime(2026, 1, 5, 12),
        setup_seconds=300, run_seconds=3600, quantity=20, status="planned",
        material_ready=True, is_locked=False, priority=50,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_service_get_gantt_data_missing_schedule(mock_db):
    mock_db.get = AsyncMock(return_value=None)
    out = await ApsService(mock_db).get_gantt_data("nope")
    assert out == {"error": "排程方案不存在"}
