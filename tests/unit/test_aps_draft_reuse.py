"""APS 写量刹车：输入没变的第二次调用必须零写入，而不是再抄一份任务明细。

这里盯三件事：
1. 复用判定走的是"输入指纹"，不是时间或调用者——所以第二次同输入不落新行；
2. 指纹覆盖排程读到的每一段输入，任一段变化都要能看出指纹变了；
3. 复用回来的诊断明细来自草案生成时写的快照；快照不存在就说"没有"，不补一份新的冒充。
"""

from datetime import datetime

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services.aps_service import ApsService

DRAFT = {
    "id": "sch-1",
    "schedule_code": "APS-FAC_ME-20261005062928-1A2B",
    "version_number": 295,
    "created_at": datetime(2026, 10, 5, 6, 29, 28),
    "created_by": "eric",
    "status": "draft",
    "total_tasks": 961,
    "unscheduled_count": 71,
    "on_time_rate": 85.4,
    "avg_utilization": 38.0,
    "avg_cycle_hours": 1.2,
    "total_setup_minutes": 300,
}

SNAPSHOT = {
    "success": False,
    "message": "有 6 个工单缺少可用工艺路线",
    "unscheduled_orders": ["wo-1", "wo-2"],
    "constraint_violation_count": 12,
    "diagnostics": {
        "unscheduled": [{"order_id": "wo-1", "reasons": ["工位排满"]}],
        "unscheduled_total": 71,
        "constraint_violations": [{"order_id": "wo-1", "reason": "产能不足"}],
        "violations_total": 12,
        "data_integrity": [{"station_code": "ST-ASSY-LINE", "issue": "owned_by_other_factory"}],
        "snapshot_limit": 60,
    },
    "station_loads": [{"station_id": "ST-JG-01", "task_count": 30}],
    "rule_explanation": "先按工单优先级，再按交期排序。",
}


def _db(fp_rows=None, draft=None, snapshot=SNAPSHOT, task_rows=961):
    """按 SQL 片段分发的假会话：只记录有没有发生写入。"""
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "AS fp, count(*) AS rows_in" in sql:
            key = next((k for k in ("work_orders wo", "routing_template_steps", "station_capacity",
                                    "equipment eq", "aps_work_calendars", "work_order_materials",
                                    "aps_schedule_tasks t")
                        if k in sql), "other")
            fp = (fp_rows or {}).get(key, f"fp-{key}")
            r.mappings.return_value.first.return_value = {"fp": fp, "rows_in": 3}
        elif "FROM aps_schedules" in sql and "input_fingerprint = :fp" in sql:
            r.mappings.return_value.first.return_value = draft if draft is not None else DRAFT
        elif "count(*) FROM aps_schedule_tasks" in sql:
            r.scalar.return_value = task_rows
        elif "FROM aps_plan_events" in sql:
            r.mappings.return_value.first.return_value = (
                None if snapshot is None else {"payload": snapshot}
            )
        else:
            r.mappings.return_value.first.return_value = None
            r.scalar.return_value = 0
        return r

    db = MagicMock()
    db.execute = execute
    db.add = MagicMock()
    db.commit = MagicMock()
    db.flush = MagicMock()
    db.calls = calls
    return db


@pytest.mark.asyncio
async def test_second_identical_call_reuses_draft_and_writes_nothing():
    # 草案列上的 total_tasks 与实表行数不一致时，交出去的必须是实表行数
    svc = ApsService(_db(task_rows=123))
    result = await svc.generate_schedule("FAC_MECH_001", created_by="scheduler",
                                         change_reason="auto")
    assert result["reused"] is True
    assert result["schedule_id"] == "sch-1"
    assert result["total_tasks"] == 123          # 来自实际行数，不是 aps_schedules.total_tasks
    assert result["unscheduled_orders"] == ["wo-1", "wo-2"]
    assert result["message"].startswith("输入未变，复用草案")
    db = svc.db
    assert db.add.call_count == 0, "复用路径不能新增任何 ORM 对象"
    assert db.commit.call_count == 0, "复用路径不能提交任何写入"
    joined = "".join(db.calls)
    assert "INSERT" not in joined.upper().replace("input_fingerprint", "")


@pytest.mark.asyncio
async def test_fingerprint_covers_every_input_segment():
    base = ApsService(_db())
    fp_base, parts = await base._input_fingerprint(
        "FAC_MECH_001", mode="hybrid", optimize_for="delivery", horizon_days=30,
        horizon_start=datetime(2026, 10, 5, 8),
        horizon_end=datetime(2026, 11, 4, 8), excluded=set(),
    )
    assert set(parts) == {"orders", "routes", "capacity", "equipment", "calendar",
                          "material_readiness", "pinned_steps", "request"}
    assert all(p["fingerprint"] for p in parts.values()), "每段都要真的比到过"

    # 只改一处输入（工单池），指纹必须变；其余段保持不变
    shifted = ApsService(_db(fp_rows={"work_orders wo": "other-fp"}))
    fp_shifted, _ = await shifted._input_fingerprint(
        "FAC_MECH_001", mode="hybrid", optimize_for="delivery", horizon_days=30,
        horizon_start=datetime(2026, 10, 5, 8),
        horizon_end=datetime(2026, 11, 4, 8), excluded=set(),
    )
    assert fp_shifted != fp_base

    # 停用某个工位也是输入变化（自动改派那类触发不能被当成"没变"复用掉）
    excluded_run = ApsService(_db())
    fp_excluded, _ = await excluded_run._input_fingerprint(
        "FAC_MECH_001", mode="hybrid", optimize_for="delivery", horizon_days=30,
        horizon_start=datetime(2026, 10, 5, 8),
        horizon_end=datetime(2026, 11, 4, 8), excluded={"ST-JG-01"},
    )
    assert fp_excluded != fp_base


@pytest.mark.asyncio
async def test_reuse_without_snapshot_says_so_instead_of_inventing_reasons():
    svc = ApsService(_db(snapshot=None))
    result = await svc.generate_schedule("FAC_MECH_001")
    assert result["reused"] is True
    diag = result["diagnostics"]
    assert diag["snapshot_available"] is False
    assert diag["unscheduled"] == [] and diag["unscheduled_total"] == 0
    assert "没有留存的诊断快照" in result["message"]


@pytest.mark.asyncio
async def test_reuse_reports_truncation_instead_of_passing_partial_list_as_complete():
    svc = ApsService(_db())
    result = await svc.generate_schedule("FAC_MECH_001")
    diag = result["diagnostics"]
    assert len(diag["unscheduled"]) == 1 and diag["unscheduled_total"] == 71
    assert diag["snapshot_capped_at"] == 60


@pytest.mark.asyncio
async def test_force_skips_the_reuse_gate():
    """force=True 是指纹门的出口：覆盖不到的主数据变了，人还能强制重排。

    假会话只喂得起指纹/复用这两类查询，再往下取工单就会炸，所以这里不比返回值，
    只比"有没有去查可复用草案"——它必须没查。
    """
    db = _db()
    svc = ApsService(db)
    try:
        await svc.generate_schedule("FAC_MECH_001", force=True)
    except Exception:  # noqa: BLE001
        pass
    assert not any("input_fingerprint = :fp" in c for c in db.calls), "force 不该走复用查询"
    assert any("AS fp, count(*) AS rows_in" in c for c in db.calls), "指纹仍然要算，供这版方案落库"

@pytest.mark.asyncio
async def test_a_released_plan_of_the_same_inputs_is_reused_too():
    """逐单门会把方案置成 released；这时同输入不能再逼出一版新草案（自激环）。"""
    released = dict(DRAFT, status="released", is_current=True)
    db = _db(draft=released)
    result = await ApsService(db).generate_schedule("FAC_MECH_001")
    assert result["reused"] is True
    assert result["schedule_status"] == "released"
    assert "released计划" in result["message"]
    assert db.add.call_count == 0

