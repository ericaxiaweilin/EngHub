"""缺料催办生命周期的口径：关闭看台账缺口、空快照不判齐套、催不动只升级一次。

这些判定原来只在 LLM 的一句话里 —— 缺口补平了任务还在每 4 小时催一次人，
模型说"已解决"而台账还写着缺口时也会被标完成。所以断言打在证据上：
关闭必须引用行数与缺口数；0 行快照不许被读成"都齐了"（空集合不等于通过）。
"""

import json

import pytest

pytestmark = [pytest.mark.unit]

from api.services import followup_lifecycle as fl
from api.services import followup_task_service as fts


class _Res:
    def __init__(self, first=None, all_rows=None, scalar=None, rowcount=0):
        self._first, self._all, self._scalar = first, all_rows, scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all or []

    def scalar(self):
        return self._scalar


class _FakeDB:
    def __init__(self, kit_row, *, escalation_exists=False, owner_row=None, closed_rows=None):
        self.kit_row = kit_row
        self.escalation_exists = escalation_exists
        self.owner_row = owner_row
        self.closed_rows = closed_rows or []
        self.writes = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        head = sql.strip().upper()
        if head.startswith(("UPDATE", "INSERT", "DELETE")):
            self.writes.append((head.split()[0], sql, params))
            return _Res(rowcount=1)
        if "FROM work_order_materials m" in sql:
            return _Res(first=self.kit_row)
        if "closed_at >= NOW()" in sql:
            return _Res(all_rows=self.closed_rows)
        if "SELECT 1 FROM followup_tasks" in sql:
            return _Res(first=(1,) if self.escalation_exists else None)
        if "FROM hr_employees" in sql:
            return _Res(first=self.owner_row)
        if "FROM route_station" in sql:
            return _Res(all_rows=[("wo-1", "ST-HJ-01")])
        if "SELECT station_name FROM stations" in sql:
            return _Res(scalar="焊接车间")
        return _Res()

    async def commit(self):
        self.commits += 1


def _task(follow_count=3, recorded=47.0):
    return {
        "id": "t1", "factory_id": "FAC_MECH_001", "created_by": "virtual_factory",
        "title": "催料｜WO-CMP-1 缺 47 件", "assigned_to": "张三", "status": "open",
        "follow_count": follow_count, "max_follows": 10, "progress_pct": 0.0,
        "payload": json.dumps({
            "category": "material_shortage", "work_order_id": "wo-1",
            "work_order_code": "WO-CMP-1", "model_code": "1000366455",
            "planned_qty": 47, "shortage_total": recorded,
            "purchase_lines": 0, "make_lines": 1,
        }),
    }


def _kit(lines, short_lines, short_qty, buy=0, make=1):
    return {"evidence_lines": lines, "shortage_lines": short_lines,
            "shortage_qty": short_qty, "buy_lines": buy, "make_lines": make}


def test_progress_comes_from_the_gap_moving_not_from_a_model_guess():
    assert fl.evidence_progress_pct(47.0, 20.0) == 57.4
    assert fl.evidence_progress_pct(47.0, 47.0) == 0.0
    assert fl.evidence_progress_pct(47.0, 60.0) == 0.0     # 缺得更多也不是进度
    assert fl.evidence_progress_pct(0, 0) is None           # 没有基线就不编一个百分比


def test_stall_needs_both_rounds_and_no_movement():
    assert fl.is_stalled(47.0, 47.0, 3) is True
    assert fl.is_stalled(47.0, 46.9, 3) is False            # 动过一点就还没到"催不动"
    assert fl.is_stalled(47.0, 47.0, 2) is False            # 轮数不够不升级


@pytest.mark.asyncio
async def test_kit_complete_closes_the_task_with_evidence_and_no_llm():
    """缺口归零 → 关闭，结论里必须带行数与"创建时 47 件 → 现在 0 件"。"""
    db = _FakeDB(_kit(lines=3, short_lines=0, short_qty=0.0))
    out = await fl.sync_shortage_task(db, _task(), apply=True)

    assert out["action"] == "close_kit_complete"
    assert out["kit"]["state"] == "complete"
    assert "3 行" in out["note"] and "0 件" in out["note"]
    updates = [w for w in db.writes if w[0] == "UPDATE"]
    assert len(updates) == 1
    assert "status = 'done'" in updates[0][1]
    assert updates[0][2]["id"] == "t1"
    assert any(w[0] == "INSERT" for w in db.writes)          # 留痕 + 通知都发了
    assert db.commits == 1                                   # 早退分支自己提交，不等跟进循环


@pytest.mark.asyncio
async def test_dry_run_reports_the_verdict_without_touching_the_db():
    db = _FakeDB(_kit(lines=3, short_lines=0, short_qty=0.0))
    out = await fl.sync_shortage_task(db, _task(), apply=False)

    assert out["action"] == "close_kit_complete"
    assert db.writes == [] and db.commits == 0


@pytest.mark.asyncio
async def test_empty_kit_snapshot_is_not_read_as_complete(monkeypatch):
    """快照 0 行分不清"都齐了"和"根本没算过" —— 那就继续催，并写明没有依据。"""
    db = _FakeDB(_kit(lines=0, short_lines=0, short_qty=0.0))
    out = await fl.sync_shortage_task(db, _task(), apply=True)

    assert out["action"] == "keep_open_no_evidence"
    assert out["kit"]["state"] == "no_evidence"
    assert db.writes == []                                   # 一行都不许写，更不许标完成


@pytest.mark.asyncio
async def test_stalled_shortage_escalates_once_and_stops_pestering_the_same_person(monkeypatch):
    """缺口三轮没动 → 挂一条升级单（四个裁量选项），原催办转 blocked 不再每 4 小时追人。"""
    db = _FakeDB(_kit(lines=2, short_lines=1, short_qty=47.0))
    captured = {}

    async def fake_create_task(db_, factory_id, created_by, title, **kw):
        captured["title"] = title
        captured["kw"] = kw
        return {"task_id": "esc-1", "assigned_to": kw.get("assigned_to")}

    monkeypatch.setattr(fts, "create_task", fake_create_task)
    out = await fl.sync_shortage_task(db, _task(follow_count=3), apply=True)

    assert out["action"] == "escalated"
    assert captured["title"].startswith("升级｜WO-CMP-1 催 3 轮缺口未动")
    payload = json.loads(captured["kw"]["payload"])
    assert payload["category"] == "material_shortage_escalation"
    assert payload["work_order_id"] == "wo-1"
    assert "改期" in payload["options"] and "停线" in payload["options"]
    blocked = [w for w in db.writes if w[0] == "UPDATE" and "status = 'blocked'" in w[1]]
    assert blocked, "原催办必须停下，否则同一个人被继续催"
    # 升级单第一次跟进提前到几分钟：按 24 小时挂会沉到收件箱第 2 页之后，界面等于没挂
    soon = [w for w in db.writes if w[0] == "UPDATE" and "next_follow_at = NOW() + INTERVAL '5 minutes'" in w[1]]
    assert soon and soon[0][2]["id"] == "esc-1"


@pytest.mark.asyncio
async def test_escalation_is_not_duplicated(monkeypatch):
    """已经有未关闭的升级单 → 不再挂第二条，但原催办要停下（否则人继续被催）。"""
    db = _FakeDB(_kit(lines=2, short_lines=1, short_qty=47.0), escalation_exists=True)

    async def must_not_create(*a, **kw):
        raise AssertionError("已有升级单时不许再挂一条")

    monkeypatch.setattr(fts, "create_task", must_not_create)
    out = await fl.sync_shortage_task(db, _task(follow_count=4), apply=True)

    assert out["action"] == "escalation_already_open"
    assert any(w[0] == "UPDATE" and "status = 'blocked'" in w[1] for w in db.writes)


@pytest.mark.asyncio
async def test_escalation_names_no_borrowed_boss(monkeypatch):
    """承接人从 HR 现存的岗位行里找；找不到就留空并把缺口写进受阻原因，不借个名字填上。"""
    db = _FakeDB(_kit(lines=2, short_lines=1, short_qty=47.0), owner_row=None)
    calls = []

    async def fake_create_task(db_, factory_id, created_by, title, **kw):
        calls.append(kw)
        return {"task_id": "esc-2"}

    monkeypatch.setattr(fts, "create_task", fake_create_task)
    out = await fl.sync_shortage_task(db, _task(follow_count=5), apply=True)

    assert out["action"] == "escalated"
    assert out["escalation_assigned_to"] is None
    assert "找不到可承接升级的岗位" in out["escalation_gap"]
    assert calls[0]["item_type"] == "followup"               # 没承接人就不写 assigned
    assert "HR 岗位台账里找不到" in calls[0]["block_reason"]


@pytest.mark.asyncio
async def test_non_shortage_task_is_left_alone():
    db = _FakeDB(_kit(lines=1, short_lines=0, short_qty=0.0))
    task = _task()
    task["payload"] = json.dumps({"category": "partial_kit", "work_order_id": "wo-1"})
    out = await fl.sync_shortage_task(db, task, apply=True)

    assert out["action"] == "not_applicable"
    assert db.writes == []


@pytest.mark.asyncio
async def test_escalation_owner_lookup_uses_real_positions_only():
    """承接人从 hr_employees 现存的岗位字典里取；库里最高只到 组长/线长，就没有更上一层。"""
    db = _FakeDB(_kit(lines=1, short_lines=1, short_qty=5.0),
                 owner_row={"name": "李四", "position": "线长",
                            "department": "生产一部", "station": "焊接"})
    out = await fl.escalation_owner(db, "FAC_MECH_001", "make", "焊接车间")
    assert out["assigned_to"] == "李四" and out["gap"] is None

    assert fl.rank_of("线长") > fl.rank_of("组长")
    assert fl.rank_of("厂长") == len(fl.POSITION_RANK) - 1
    assert fl.rank_of("副总") == -1                          # 字典外的值不假装排得出高低


def _closed_row():
    return {"id": "c1", "factory_id": "FAC_MECH_001", "created_by": "virtual_factory",
            "title": "催料｜WO-CMP-1", "assigned_to": "张三", "status": "done",
            "follow_count": 2, "max_follows": 10, "progress_pct": 100.0,
            "result_summary": "物料库存可用量已达 9 件，缺口 5 件已补齐，工单已具备投产条件。",
            "follow_interval_minutes": 240, "closed_at": "2026-10-06 03:23:18+00",
            "payload": json.dumps({"category": "material_shortage", "work_order_id": "wo-1",
                                   "work_order_code": "WO-CMP-1", "shortage_total": 47.0})}


@pytest.mark.asyncio
async def test_false_closure_is_reopened_from_ledger_evidence():
    """写着"缺口已补齐"的已完成任务，台账还挂着 5 件 → 复核出来并重开。

    这是线上真实踩到的形状（两条 done 任务，台账分别还缺 5 件和 544 件）。
    """
    db = _FakeDB(_kit(lines=1, short_lines=1, short_qty=5.0), closed_rows=[_closed_row()])
    out = await fl.audit_false_closures(db, "FAC_MECH_001", days=7, limit=10, apply=True)

    assert out["closed_examined"] == 1
    assert out["false_closures"] == 1 and out["reopened"] == 1
    assert "合计 5 件" in out["items"][0]["note"]
    assert "缺口 5 件已补齐" in out["items"][0]["note"]        # 原结论要跟着，便于对账
    updates = [w for w in db.writes if w[0] == "UPDATE"]
    assert "status = 'open'" in updates[0][1] and "closed_at = NULL" in updates[0][1]


@pytest.mark.asyncio
async def test_closed_task_with_no_snapshot_is_not_called_a_false_closure():
    """快照 0 行分不清"真齐了"还是"没算过" → 不冤枉它，只报数量不动库。"""
    db = _FakeDB(_kit(lines=0, short_lines=0, short_qty=0.0), closed_rows=[_closed_row()])
    out = await fl.audit_false_closures(db, "FAC_MECH_001", days=7, limit=10, apply=True)

    assert out["closed_examined"] == 1
    assert out["false_closures"] == 0 and out["reopened"] == 0
    assert db.writes == []


def test_inbox_orders_still_active_tasks_ahead_of_stalled_ones():
    """收件箱只取前 100 条：open 与 blocked 同权重会把刚挂的升级单挤到 216 名开外。"""
    import inspect

    src = inspect.getsource(fts.list_tasks)
    assert "CASE status WHEN 'open' THEN 0 WHEN 'blocked' THEN 1" in src
    assert "(status IN ('open','blocked')) DESC" not in src


def test_model_closure_is_vetoed_when_the_ledger_still_shows_a_gap():
    """关闭权不在模型手里：台账还有缺口就退回 open，两边说法都留在结论里。"""
    conclusion = {"state": "done", "note": "缺口已补齐", "progress_pct": 100}
    lifecycle = {"kit": {"state": "short", "shortage_lines": 8, "evidence_lines": 8,
                         "shortage_qty": 544.0, "basis": "work_order_materials"},
                 "evidence_progress_pct": 0.0}

    assert fl.veto_model_closure("done", conclusion, lifecycle) == "open"
    assert "以台账为准" in conclusion["note"] and "544" in conclusion["note"]
    assert conclusion["state"] == "open"


def test_model_closure_stands_when_kit_is_actually_complete():
    conclusion = {"state": "done", "note": "料到了", "progress_pct": 100}
    lifecycle = {"kit": {"state": "complete", "shortage_lines": 0, "evidence_lines": 4,
                         "shortage_qty": 0.0, "basis": "work_order_materials"}}

    assert fl.veto_model_closure("done", conclusion, lifecycle) == "done"
    assert conclusion["note"] == "料到了"
