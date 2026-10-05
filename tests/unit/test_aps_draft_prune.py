"""旧草案回收的合约：白名单之外一律不动，预演不许真的删，锁不能跟着草案一起掉。"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import aps_draft_prune as prune


NOW = datetime(2026, 10, 5, 14, 0, 0)


def _row(i, code, rows=1000, lock=False):
    return {
        "id": f"sch-{i}", "factory_id": "FAC_MECH_001", "schedule_code": code,
        "version_number": 100 + i, "created_at": NOW - timedelta(minutes=i),
        "rn": 4 + i, "task_rows": rows, "holds_live_lock": lock,
    }


def _db(rows=None, tasks_before=9_500_000, schedules_before=300_000,
        tasks_after=3_000_000, schedules_after=60_000):
    calls = []
    state = {"tasks": tasks_before, "schedules": schedules_before}

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "ROW_NUMBER() OVER (PARTITION BY s.factory_id" in sql:
            r.mappings.return_value.all.return_value = (
                [_row(1, "APS-A"), _row(2, "APS-B", rows=50), _row(3, "APS-LOCK", rows=1035, lock=True)]
                if rows is None else rows
            )
        elif "FROM aps_schedules WHERE (:fid = ''" in sql:
            r.mappings.return_value.first.return_value = {
                "draft_marked_current": 0, "confirmed_or_released": 1, "archived": 8, "drafts": 295,
            }
        elif "pg_total_relation_size('aps_schedule_tasks') AS tasks_bytes" in sql:
            r.mappings.return_value.first.return_value = {
                "tasks_bytes": state["tasks"], "schedules_bytes": state["schedules"],
            }
            state["tasks"] = tasks_after
            state["schedules"] = schedules_after
        elif "DELETE FROM aps_schedule_tasks" in sql:
            r.rowcount = sum(int(x["task_rows"]) for x in (rows if rows is not None else
                                  [_row(1, "APS-A"), _row(2, "APS-B", rows=50),
                                   _row(3, "APS-LOCK", rows=1035, lock=True)]) if not x["holds_live_lock"])
        elif "DELETE FROM aps_schedules" in sql:
            r.rowcount = 2
        else:
            r.mappings.return_value.first.return_value = None
            r.rowcount = 0
        return r

    db = MagicMock()
    db.execute = execute
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.calls = calls
    return db


@pytest.mark.asyncio
async def test_plan_separates_prunable_from_drafts_holding_live_locks():
    out = await prune.plan_prune(_db(), factory_id="FAC_MECH_001", keep=3)
    assert out["candidates"] == 3
    assert out["prunable"] == 2 and out["prunable_task_rows"] == 1050
    assert out["held_by_live_lock"] == 1 and out["held_by_live_lock_task_rows"] == 1035
    assert out["ids"] == ["sch-1", "sch-2"], "压着锁定工序的那份绝不能进删除清单"
    assert out["protected_untouched"]["confirmed_or_released"] == 1
    assert out["protected_untouched"]["archived"] == 8


@pytest.mark.asyncio
async def test_dry_run_emits_no_delete_statements_at_all():
    db = _db()
    # 预演本身也不该出现删除语句
    out = await prune.prune_superseded_drafts(db, keep=3, apply=False)
    assert out["status"] == "dry_run" and out["dry_run"] is True
    assert not any("DELETE" in c.upper() for c in db.calls), "预演路径不许出现删除语句"
    assert db.commit.await_count == 0 and db.add.call_count == 0
    assert not any("DELETE" in c.upper() for c in db.calls)


@pytest.mark.asyncio
async def test_apply_deletes_children_first_and_writes_one_audit_event():
    db = _db()
    out = await prune.prune_superseded_drafts(db, keep=3, apply=True)
    upper = [c.upper() for c in db.calls]
    assert out["status"] == "ok"
    assert out["deleted_task_rows"] == 1050 and out["deleted_schedules"] == 2
    assert any("DELETE FROM APS_SCHEDULE_TASKS" in c for c in upper)
    assert any("DELETE FROM APS_SCHEDULES" in c for c in upper)
    first = lambda needle: next(i for i, c in enumerate(upper) if needle in c)
    assert first("DELETE FROM APS_SCHEDULE_TASKS") < first("DELETE FROM APS_SCHEDULES"), \
        "先删子表再删父表，否则撞外键"
    assert out["reclaimed_bytes"] == (9_500_000 + 300_000) - (3_000_000 + 60_000)
    events = [c.args[0] for c in db.add.call_args_list]
    assert len(events) == 1 and events[0].event_type == "drafts_pruned"
    assert events[0].payload["pruned_schedule_ids"] == ["sch-1", "sch-2"]
    assert events[0].payload["pruned_total"] == 2
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_nothing_outside_the_window_reports_cleanly_without_touching_data():
    db = _db(rows=[])
    out = await prune.prune_superseded_drafts(db, keep=3, apply=True)
    assert out["status"] == "nothing_to_prune"
    assert not any("DELETE" in c.upper() for c in db.calls)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_lock_holding_drafts_available_still_nothing_deleted():
    db = _db(rows=[_row(9, "APS-LOCK-ONLY", rows=1035, lock=True)])
    out = await prune.prune_superseded_drafts(db, keep=3, apply=True)
    assert out["prunable"] == 0 and out["held_by_live_lock"] == 1
    assert out["status"] == "nothing_to_prune"
    assert not any("DELETE" in c.upper() for c in db.calls), "全被锁守住时一份都不能删"
