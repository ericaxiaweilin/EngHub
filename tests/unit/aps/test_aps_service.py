"""APS 服务状态机与负荷口径回归：只测真实存在的方法，不 mock 不存在的类。"""

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from api.services.aps_service import PRIORITY_MAP, ApsService
from database.models import ApsSchedule, WorkOrder


@pytest.fixture(scope="function")
def mock_aps_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _empty_scalars(db):
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    res.scalar_one_or_none.return_value = None
    res.mappings.return_value.all.return_value = []
    res.mappings.return_value.first.return_value = None
    res.rowcount = 0
    res.all.return_value = []
    db.execute = AsyncMock(return_value=res)
    return db


def _schedule(status="draft"):
    s = SimpleNamespace(
        id="sched-001", factory_id="F001", status=status,
        unscheduled_count=0, version_number=3,
        confirmed_by=None, approved_by=None, is_current=False,
        released_by=None, released_at=None, updated_at=None,
    )
    return s


@pytest.mark.asyncio
async def test_confirm_schedule_draft_to_confirmed(mock_aps_db):
    sched = _schedule("draft")
    mock_aps_db.get = AsyncMock(return_value=sched)
    _empty_scalars(mock_aps_db)
    out = await ApsService(mock_aps_db).confirm_schedule("sched-001", "planner")
    assert out["success"] is True
    assert sched.status == "confirmed"
    assert out["updated_orders"] == 0


@pytest.mark.asyncio
async def test_confirm_schedule_rejects_non_draft(mock_aps_db):
    mock_aps_db.get = AsyncMock(return_value=_schedule("released"))
    out = await ApsService(mock_aps_db).confirm_schedule("sched-001", "planner")
    assert out["success"] is False


@pytest.mark.asyncio
async def test_release_schedule_requires_confirmed_then_releases(mock_aps_db):
    mock_aps_db.get = AsyncMock(return_value=_schedule("draft"))
    _empty_scalars(mock_aps_db)
    svc = ApsService(mock_aps_db)
    denied = await svc.release_schedule("sched-001")
    assert denied["success"] is False

    sched = _schedule("confirmed")
    mock_aps_db.get = AsyncMock(return_value=sched)
    ok = await svc.release_schedule("sched-001")
    assert ok["success"] is True
    assert sched.status == "released"
    assert sched.is_current is True
    assert ok["released_orders"] == 0


@pytest.mark.asyncio
async def test_release_plan_does_not_release_orders_the_kit_gate_held(mock_aps_db):
    """整版下达不许越过逐单就绪门 —— 这条是补第二条弱口子用的。

    原来 release_schedule 只看"这单在版里出现过"就把工单写成 released，
    于是缺料单跟着整版一起变成"已下达"；而回收假放行的 audit_false_releases
    只认 released_by 是门的那批，这条路放出去的它自己看不见。
    """
    sched = _schedule("confirmed")
    tasks = [
        SimpleNamespace(work_order_id="WO-READY", material_ready=True, status="planned"),
        SimpleNamespace(work_order_id="WO-SHORT", material_ready=False, status="planned"),
    ]
    orders = {
        "WO-READY": SimpleNamespace(id="WO-READY", factory_id="F001", status="pending"),
        "WO-SHORT": SimpleNamespace(id="WO-SHORT", factory_id="F001", status="pending"),
    }

    async def fake_get(model, pk):
        if model is ApsSchedule:
            return sched
        return orders.get(str(pk))

    mock_aps_db.get = AsyncMock(side_effect=fake_get)
    res = MagicMock()
    res.scalars.return_value.all.return_value = tasks
    res.rowcount = 0
    mock_aps_db.execute = AsyncMock(return_value=res)

    gate = AsyncMock(return_value={"ready_ids": ["WO-READY"], "hold_reason_counts": {}})
    with patch("api.services.plan_commit_gate.evaluate_commit_gate", gate):
        out = await ApsService(mock_aps_db).release_schedule(
            "sched-001", released_by="planner", allow_partial=True
        )

    assert out["success"] is True
    assert out["released_orders"] == 1, "只有就绪门点头的那张算新下达"
    assert out["held_by_kit_gate"] == 1, "没过门的单要数出来，不能静静消失"
    assert orders["WO-READY"].status == "released"
    assert orders["WO-SHORT"].status == "pending", "缺料单不许跟着整版变成已下达"
    assert tasks[1].status == "planned", "单没过门，它的工序行也不许写已下达"
    assert tasks[0].status == "released"


@pytest.mark.asyncio
async def test_release_plan_demotes_previous_current_before_promoting(mock_aps_db):
    """一厂只许一版生效是部分唯一索引；顺序错了整笔事务回滚，下达看上去就失败。"""
    sched = _schedule("confirmed")
    mock_aps_db.get = AsyncMock(return_value=sched)
    _empty_scalars(mock_aps_db)
    with patch("api.services.plan_commit_gate.evaluate_commit_gate",
               AsyncMock(return_value={"ready_ids": []})):
        out = await ApsService(mock_aps_db).release_schedule(
            "sched-001", released_by="planner", allow_partial=True
        )
    assert out["success"] is True
    sqls = [str(c.args[0]) for c in mock_aps_db.execute.await_args_list]
    demote = [i for i, q in enumerate(sqls) if "UPDATE aps_schedules" in q and "is_current = FALSE" in q]
    assert demote, "必须有一条显式把旧版退下来的 UPDATE"
    assert sched.is_current is True


@pytest.mark.asyncio
async def test_reschedule_rejects_foreign_work_order(mock_aps_db):
    wo = SimpleNamespace(id="WO-1", factory_id="OTHER", status="pending")
    mock_aps_db.get = AsyncMock(return_value=wo)
    out = await ApsService(mock_aps_db).reschedule("F001", insert_wo_id="WO-1")
    assert out["success"] is False
    assert out["schedule_id"] is None


@pytest.mark.asyncio
async def test_reschedule_delegates_to_generate_schedule(mock_aps_db):
    wo = SimpleNamespace(id="WO-1", factory_id="F001", status="pending")
    mock_aps_db.get = AsyncMock(return_value=wo)
    svc = ApsService(mock_aps_db)
    with patch.object(
        ApsService, "generate_schedule",
        AsyncMock(return_value={"success": True, "schedule_id": "s-new"}),
    ) as gen:
        out = await svc.reschedule("F001", insert_wo_id="WO-1", created_by="planner")
    assert out["schedule_id"] == "s-new"
    assert gen.await_count == 1
    assert mock_aps_db.commit.await_count >= 1


class _Model:
    """StationModel 的替身：字段要跟真数据类一起走（漏字段就是假绿，读数的形状对不上）。"""

    daily_pieces = 10.0
    oee = 0.9
    oee_kind = "declared"
    oee_source = "station_capacity 填报 0.9（没有验证标记）"
    max_concurrent = 1
    calendar_source = "aps_work_calendars"

    def slots_on(self, day):
        return [(time(8, 0), time(20, 0))]

    def capacity_hours_on(self, day):
        return 12.0 * self.oee


@pytest.mark.asyncio
async def test_get_capacity_load_empty_factory_has_no_resources(mock_aps_db):
    _empty_scalars(mock_aps_db)
    with patch(
        "api.services.aps_service.load_station_models", AsyncMock(return_value={})
    ):
        out = await ApsService(mock_aps_db).get_capacity_load("F001", days=7)
    assert out["resources"] == []
    assert out["data_integrity"] == []


@pytest.mark.asyncio
async def test_get_capacity_load_zero_load_math(mock_aps_db):
    res = MagicMock()
    res.scalar_one_or_none.return_value = None  # 无生效版本
    res.scalars.return_value.all.return_value = []  # 无任务、无工位
    res.mappings.return_value.all.return_value = [
        {"station_id": "ST-A", "available_hours_per_day": 10}
    ]
    res.all.return_value = []
    mock_aps_db.execute = AsyncMock(return_value=res)
    with patch(
        "api.services.aps_service.load_station_models",
        AsyncMock(return_value={"ST-A": _Model()}),
    ):
        out = await ApsService(mock_aps_db).get_capacity_load("F001", days=7)
    assert [r["station_id"] for r in out["resources"]] == ["ST-A"]
    row = out["resources"][0]
    assert row["avg_utilization"] == 0.0
    assert row["is_bottleneck"] is False
    assert row["daily_capacity_pieces"] == 10.0
    assert all(d["is_rest_day"] is False for d in row["daily_load"])
    assert out["data_integrity"] == [
        w for w in out["data_integrity"] if w["issue"] == "not_registered"
    ]


@pytest.mark.asyncio
async def test_priority_map_covers_all_levels():
    assert set(PRIORITY_MAP) == {"low", "medium", "high", "urgent", "emergency"}
    assert PRIORITY_MAP["urgent"].value > PRIORITY_MAP["high"].value
