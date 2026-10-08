"""子工单的齐套依据：净缺口才开工单、物料行来自这台组件自己的展开、取消只在显式开关下发生。

写这些用例的起因是两处真实故障：
1. 拆单只看毛需求 → 197/621 张子单开在净缺口为 0 的父件上，永远等不到齐套；
2. 子单的物料行从父单快照往下抄 → 抄到的 required 全是 0，289 张单"没有依据"。
所以断言的重点不是"有没有调用"，而是**字段映射对不对**：
`explode_requirement` 用 on_hand_qty/net_qty，齐套表用 available_qty/shortage_qty ——
映射错位时 shortage 会静默变成 0，看起来"齐套了"，催办和就绪门就一起失效。
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import component_orders as co


def _explosion_result():
    """一台组件（1000472426 車架組）自己的展开结果，字段名照 bom_source 的原样。"""
    return {
        "lines": [
            {"material_code": "1000472426", "material_name": "車架組", "unit": "PCS",
             "level": 1, "required_qty": 24, "on_hand_qty": 4, "allocated_qty": 4,
             "net_qty": 20, "item_type": "make"},
            {"material_code": "2001112223", "material_name": "圓棒料 φ26", "unit": "M",
             "level": 2, "required_qty": 1, "on_hand_qty": 0, "allocated_qty": 0,
             "net_qty": 1, "item_type": "buy"},
            {"material_code": "2001112224", "material_name": "焊接螺母", "unit": "PCS",
             "level": 3, "required_qty": 8, "on_hand_qty": 5, "allocated_qty": 5,
             "net_qty": 3, "item_type": "buy"},
        ],
        "nodes": 3, "parts": 3, "problems": [],
    }


def test_explosion_lines_map_to_kit_columns():
    lines = co._from_explosion(_explosion_result(), exclude_code="1000472426")

    # 组件自己那一行不是它自己的物料
    assert [l["material_code"] for l in lines] == ["2001112223", "2001112224"]
    by_code = {l["material_code"]: l for l in lines}
    # on_hand→available、net→shortage：这两列错位就等于"看起来齐套了"
    assert by_code["2001112224"]["available_qty"] == 5
    assert by_code["2001112224"]["shortage_qty"] == 3
    assert by_code["2001112224"]["allocated_qty"] == 5
    assert by_code["2001112224"]["required_qty"] == 8
    # 层级以这台组件为基准：它的直接下层是 1，不是镜像里的绝对层级 2
    assert by_code["2001112223"]["level"] == 1
    assert by_code["2001112224"]["level"] == 2
    assert all(l["item_type"] for l in lines)


def test_explosion_lines_keep_fractional_requirement():
    """小数用量不能再被 int() 截回 0 —— 那是"没有依据"的另一半根因。"""
    result = {"lines": [{"material_code": "3000000001", "level": 2,
                         "required_qty": Decimal("0.255"), "on_hand_qty": Decimal("0"),
                         "allocated_qty": Decimal("0"), "net_qty": Decimal("0.255")}]}
    line = co._from_explosion(result, exclude_code="1000472426")[0]
    assert line["required_qty"] == pytest.approx(0.255)
    assert line["shortage_qty"] == pytest.approx(0.255)


def test_explosion_missing_or_empty_is_no_lines_so_caller_falls_back():
    assert co._from_explosion(None, exclude_code="X") == []
    assert co._from_explosion({"lines": [], "problems": ["树拼不出"]}, exclude_code="X") == []


def test_snapshot_lines_rebase_level_onto_component():
    """回落口径：快照里的绝对层级要挪到这台组件下面（L3 的行在 L2 组件下是第 1 层）。"""
    rows = [{"material_code": "2001112223", "material_name": "圓棒料", "unit": "M",
             "level": 3, "required_qty": Decimal("24"), "available_qty": Decimal("11"),
             "allocated_qty": Decimal("11"), "shortage_qty": Decimal("13"),
             "item_type": "buy"}]
    line = co._from_snapshot(rows, base_level=2)[0]
    assert line["level"] == 1
    assert line["shortage_qty"] == 13
    assert line["available_qty"] == 11


def _candidate(wo_id="wo-c1", code="WO-CMP-aaa", product="1000472426"):
    return {"work_order_id": wo_id, "work_order_code": code, "product_id": product,
            "planned_qty": 24, "parent_required": 24, "parent_shortage": 0,
            "parent_available": 30}


def _db_for_retire(candidates, live_followups=3):
    sqls = []

    async def execute(statement, params=None):
        sql = str(statement)
        sqls.append((sql, params))
        result = MagicMock()
        if "FROM work_orders c" in sql and "JOIN work_order_materials p" in sql:
            result.mappings.return_value.all.return_value = candidates
        elif "SELECT count(*) FROM followup_tasks" in sql:
            result.scalar.return_value = live_followups
        else:
            result.rowcount = 1
        return result

    async def commit():
        return None

    db = MagicMock()
    db.execute = execute
    db.commit = commit
    db.sqls = sqls
    return db


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.asyncio
async def test_env_gate_decides_whether_cancels_happen(monkeypatch, gate):
    """取消整批工单是删东西：没显式开 ENGINE_RECONCILE_APPLY 就只报数字。"""
    monkeypatch.setattr(co, "RECONCILE_APPLY", gate)
    db = _db_for_retire([_candidate()])
    receipt = await co.retire_covered_child_orders(db, "FAC_MECH_001")
    assert receipt["dry_run"] is not gate
    updates = [s for s, _ in db.sqls if "UPDATE work_orders" in s]
    assert len(updates) == (1 if gate else 0)
    assert receipt["cancelled"] == (1 if gate else 0)


@pytest.mark.asyncio
async def test_retire_cancel_is_guarded_and_stops_schedule_rows():
    db = _db_for_retire([_candidate()])
    receipt = await co.retire_covered_child_orders(db, "FAC_MECH_001", apply=True)
    updates = [s for s, _ in db.sqls if "UPDATE work_orders" in s]
    assert len(updates) == 1
    # 只取消还挂着"待开工、零产出、引擎自己开的"单，条件必须留在 SQL 里
    assert "status IN ('pending', 'released')" in updates[0]
    assert "completed_qty, 0) = 0" in updates[0]
    assert "created_by = 'component_expand'" in updates[0]
    assert receipt["cancelled"] == 1
    assert receipt["schedule_tasks_cancelled"] == 1
    task_updates = [s for s, _ in db.sqls if "UPDATE aps_schedule_tasks" in s]
    assert task_updates and "NOT IN ('completed', 'released'" in task_updates[0]


@pytest.mark.asyncio
async def test_retire_reports_live_followups_without_touching_them():
    """催办条目的收尾归任务中心那条路，这里只报数、不代它改状态。"""
    db = _db_for_retire([_candidate()], live_followups=7)
    receipt = await co.retire_covered_child_orders(db, "FAC_MECH_001", apply=True)
    assert receipt["stale_followup_tasks"] == 7
    assert not [s for s, _ in db.sqls if "followup_tasks" in s and "UPDATE" in s]


@pytest.mark.asyncio
async def test_retire_is_quiet_when_nothing_is_covered():
    db = _db_for_retire([])
    receipt = await co.retire_covered_child_orders(db, "FAC_MECH_001", apply=True)
    assert receipt["status"] == "nothing_to_retire"
    assert receipt["covered_children_found"] == 0
    assert not [s for s, _ in db.sqls if s.strip().upper().startswith("UPDATE")]


# ── 补登的选单闸：max_lines 要真的进到 SQL 参数里（否则"覆盖不足档"是假的）──────
class _RecordingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):        # execute 才是 await 的，mappings()/all() 是同步的
        return self

    def all(self):
        return self._rows


class _RecordingDb:
    """只记参数不执行 SQL：断言的是"传进去的是什么"，不是"能不能跑通"。"""

    def __init__(self):
        self.calls = []

    async def execute(self, stmt, params=None):
        self.calls.append({"sql": str(stmt), "params": dict(params or {})})
        if "WITH o AS" in str(stmt):          # 选单那条 SQL
            return _RecordingResult([])
        return _RecordingResult([])

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _run_reupgrade(**kw):
    import asyncio

    db = _RecordingDb()
    out = asyncio.run(co.reupgrade_stale_kit_lines(db, "FAC_MECH_001", **kw))
    return db, out


def test_default_candidate_window_covers_the_half_registered_ones():
    """默认闸口 400：只捞 ≤80 行会把登记了一半的那批永远留在池子外面。"""
    db, out = _run_reupgrade(apply=False, limit=5)
    pick = db.calls[0]["params"]
    assert pick["max_lines"] == 400, pick
    assert pick["limit"] == 5, pick
    assert out["dry_run"] is True and out["orders_stale"] == 0


def test_narrow_window_is_honoured_when_the_caller_asks_for_it():
    """想只补最薄的那批就把闸收紧到 80：这个数得真的传进 SQL，不能只是文案。"""
    db, _ = _run_reupgrade(apply=False, limit=8, max_lines=80)
    assert db.calls[0]["params"]["max_lines"] == 80


def test_candidate_window_is_clamped_not_trusted():
    # 传 5000 行闸等于"把全厂都当成薄单"，那会把几十万次展开拉进一轮巡检
    db, _ = _run_reupgrade(apply=False, limit=8, max_lines=5000)
    assert db.calls[0]["params"]["max_lines"] == 800
    db2, _ = _run_reupgrade(apply=False, limit=8, max_lines=0)
    assert db2.calls[0]["params"]["max_lines"] == 1
