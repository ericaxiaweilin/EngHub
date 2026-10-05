"""逐单下达就绪门的合约：只放行该放的，预演不许写成已下达。

这里最容易被写坏的三件事：
1. 判据放宽一格（比如不比对工序行数）就会把"只排了一半"的单发到车间；
2. 预演路径必须真的不动数据（`apply=False` 时 rollback，且 released_orders 恒 0）；
3. 一张都没放行时不许把方案置成生效计划 —— 空批次悄悄变成"计划已下达"是最难发现的那种假状态。
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock  # noqa: F401

import pytest

pytestmark = [pytest.mark.unit]

from api.services import plan_commit_gate as gate_mod


PLAN_ROW = {
    "id": "sch-1",
    "schedule_code": "APS-FAC_ME-20261005121859-E955",
    "version_number": 295,
    "input_fingerprint": "b74009d2344e7ab2",
    "unscheduled_count": 71,
    "status": "draft",
    "is_current": False,
    "created_at": datetime(2026, 10, 5, 12, 18, 59),
}


def _row(code, *, steps, plan_rows, short=0, station="ST-JG-01", mapped=True,
         status="pending", wo_type="master"):
    return {
        "work_order_id": code, "work_order_code": f"WO-{code}", "wo_type": wo_type,
        "status": status, "product_id": f"P-{code}", "planned_qty": 10,
        "planned_due": datetime(2026, 10, 20), "planned_start": None,
        "route_steps": steps, "plan_rows": plan_rows, "short_rows": short,
        "first_station_code": station, "first_start": datetime(2026, 10, 6, 8, 0),
        "station_mapped": mapped,
    }


ROWS = [
    _row("ok-1", steps=7, plan_rows=7),
    _row("ok-2", steps=1, plan_rows=1),
    _row("short", steps=7, plan_rows=7, short=3),
    _row("partial", steps=7, plan_rows=4),
    _row("not-in-plan", steps=7, plan_rows=0),
    _row("bad-station", steps=7, plan_rows=7, station="ST-ASSY-LINE", mapped=False),
]


def _db(rows=None, plan=PLAN_ROW, apply_side_effects=True):
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "FROM aps_schedules" in sql and "input_fingerprint IS NOT NULL" in sql:
            r.mappings.return_value.first.return_value = plan
        elif "WITH pool AS" in sql:
            r.mappings.return_value.all.return_value = (ROWS if rows is None else rows)
        elif "UPDATE aps_schedule_tasks" in sql:
            r.rowcount = 7
        else:
            r.mappings.return_value.first.return_value = None
            r.mappings.return_value.all.return_value = []
            r.rowcount = 0
        return r

    db = MagicMock()
    db.execute = execute
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.get = _get(apply_side_effects)
    db.calls = calls
    return db


def _get(enabled):
    async def getter(model, pk):
        from database.models import ApsSchedule, WorkOrder

        if model is WorkOrder:
            return SimpleNamespace(id=pk, status="pending", planned_start=None,
                                   assigned_station_id=None, released_by=None, updated_at=None)
        if model is ApsSchedule:
            return SimpleNamespace(id=pk, status="draft", is_current=False,
                                   released_by=None, released_at=None, updated_at=None)
        return None
    return getter


def test_verdict_holds_orders_missing_any_one_of_the_four_rules():
    assert gate_mod._verdict(_row("a", steps=7, plan_rows=7))["ready"] is True
    assert gate_mod._verdict(_row("b", steps=7, plan_rows=7, short=1))["hold_reasons"] == ["shortage"]
    # 只排进一半工序：不能下，车间拿到的是残缺工艺
    assert gate_mod._verdict(_row("c", steps=7, plan_rows=4))["hold_reasons"] == ["partial_steps"]
    assert gate_mod._verdict(_row("d", steps=7, plan_rows=0))["hold_reasons"] == ["not_scheduled"]
    assert gate_mod._verdict(_row("e", steps=7, plan_rows=7, mapped=False))["hold_reasons"] == ["station_unmapped"]
    # 两个条件都不满足时要都点名，别只报第一个
    both = gate_mod._verdict(_row("f", steps=7, plan_rows=3, short=2))
    assert set(both["hold_reasons"]) == {"partial_steps", "shortage"}


@pytest.mark.asyncio
async def test_evaluate_is_read_only_and_caps_the_preview():
    db = _db(rows=[_row(f"o{i}", steps=1, plan_rows=1) for i in range(40)])
    out = await gate_mod.evaluate_commit_gate(db, "FAC_MECH_001")
    assert out["ready_count"] == 40 and len(out["ready"]) == gate_mod.PREVIEW_LIMIT
    assert len(out["ready_ids"]) == 40, "放行清单不能被预览上限截断"
    assert db.add.call_count == 0 and db.commit.await_count == 0
    assert not any("UPDATE" in c or "INSERT" in c for c in db.calls), "预演必须只读"


@pytest.mark.asyncio
async def test_dry_run_releases_nothing_and_says_what_it_would_do():
    db = _db()
    out = await gate_mod.commit_ready_orders(db, "FAC_MECH_001", apply=False, max_orders=5)
    assert out["dry_run"] is True
    assert out["released_orders"] == 0 and out["released_tasks"] == 0
    assert out["would_release"] == 2, "只有 ok-1/ok-2 过得了门"
    assert out["hold_reason_counts"]["shortage"] == 1
    assert out["hold_reason_counts"]["partial_steps"] == 1
    assert out["hold_reason_counts"]["not_scheduled"] == 1
    assert out["hold_reason_counts"]["station_unmapped"] == 1
    db.rollback.assert_awaited()
    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_apply_respects_batch_limit_and_leaves_held_orders_untouched():
    rows = [_row(f"ok{i}", steps=1, plan_rows=1) for i in range(6)] + [_row("h", steps=2, plan_rows=0)]
    db = _db(rows=rows)
    out = await gate_mod.commit_ready_orders(db, "FAC_MECH_001", apply=True, max_orders=4)
    assert out["released_orders"] == 4, "每轮限量是开发尺度的闸门，不是建议"
    assert out["released_tasks"] == 28
    assert out["plan_is_current"] is True
    assert out["held_count"] == 1
    db.commit.assert_awaited()
    events = [c.args[0].event_type for c in db.add.call_args_list]
    assert events.count("order_released_by_gate") == 4
    assert "plan_committed_by_gate" in events


@pytest.mark.asyncio
async def test_empty_batch_does_not_promote_the_plan():
    db = _db(rows=[_row("h1", steps=3, plan_rows=3, short=2), _row("h2", steps=3, plan_rows=1)])
    out = await gate_mod.commit_ready_orders(db, "FAC_MECH_001", apply=True, max_orders=5)
    assert out["status"] == "nothing_ready"
    assert out["plan_is_current"] is False
    assert db.commit.await_count == 0, "一张都没放行时不许提交"
    assert db.add.call_count == 0


@pytest.mark.asyncio
async def test_gate_without_a_plan_says_what_to_run_first():
    db = _db(plan=None)
    out = await gate_mod.evaluate_commit_gate(db, "FAC_MECH_001")
    assert out["status"] == "no_current_draft"
    assert "/api/v1/aps/schedule" in out["reason"]


@pytest.mark.asyncio
async def test_orders_already_acted_are_not_re_released_every_tick():
    """幂等：已 released/in_progress 的单不再被门"放行"第二次（否则每轮重复写状态+事件）。"""
    rows = [
        _row("p1", steps=1, plan_rows=1),
        _row("r1", steps=1, plan_rows=1, status="released"),
        _row("i1", steps=1, plan_rows=1, status="in_progress"),
    ]
    out = await gate_mod.evaluate_commit_gate(_db(rows=rows), "FAC_MECH_001")
    assert out["ready_count"] == 1 and out["already_released_count"] == 2
    assert out["evaluated_orders"] == (out["ready_count"] + out["held_count"]
                                       + out["already_released_count"]), "三桶要对得上总数"
    committed = await gate_mod.commit_ready_orders(_db(rows=rows), "FAC_MECH_001",
                                                   apply=True, max_orders=5)
    assert committed["released_orders"] == 1
