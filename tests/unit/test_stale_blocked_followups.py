"""blocked 积压的台账复判：能不能用现有数据判，判不动的怎么处置。

blocked 有两种，读数上长得一模一样但含义相反：
  ① 有依据的（payload 里有 category/work_order_id）—— 缺口补平了就该关，还没补平就继续挂着；
  ② 没依据的（payload 是空的，8 月那批 agent 待办）—— 引擎无法判断它到底做没做，
     既不能自动关（没证据说做了），也不该永远挂着占收件箱（它不再产生任何动作）。
"""
import asyncio
import json

import pytest

pytestmark = [pytest.mark.unit]

from api.services import followup_lifecycle as fl


def test_recheck_only_moves_in_the_close_direction():
    """复判的写库面只允许"补平了→关闭"；其余判定一律 apply=False。"""
    src = asyncio.run  # noqa: F841 - 这里读源码，不执行
    import inspect

    body = inspect.getsource(fl.sweep_blocked)
    assert 'may_apply = str(probe.get("action")) == "close_kit_complete" and apply' in body
    assert "sync_shortage_task(db, task, apply=may_apply)" in body


def test_stale_blocked_detection_needs_both_evidence_fields():
    """既没有 category 也没有 work_order_id 才算"没依据"；只有 payload 字符串空也算。"""
    assert fl._no_evidence({}) is True
    assert fl._no_evidence({"payload": None}) is True
    assert fl._no_evidence({"payload": "{}"}) is True
    assert fl._no_evidence({"payload": '{"work_order_id": "wo-1"}'}) is False
    assert fl._no_evidence({"payload": '{"category": "material_shortage"}'}) is False


def test_stale_blocked_plan_carries_the_reason_and_does_not_delete(monkeypatch):
    rows = [{"id": f"t{i}", "title": f"待办 {i}", "agent_key": "night_watch",
             "follow_count": 38, "created_at": "2026-08-08", "payload": "{}"}
            for i in range(3)]

    class _Res:
        def mappings(self):
            return self

        def all(self):
            return rows

    class _Db:
        def __init__(self):
            self.executed = []

        async def execute(self, stmt, params=None):
            self.executed.append((str(stmt), params))
            return _Res()

        async def commit(self):
            pass

    db = _Db()
    out = asyncio.run(fl.plan_stale_blocked(db, "FAC_MECH_001", older_than_days=7, apply=False))
    assert out["candidates"] == 3
    assert out["apply"] is False and db.executed, "至少要查一次"
    assert all("UPDATE" not in s for s, _ in db.executed), "预演不许动库"
    # 处置方式是"作废并写明原因"，不是删行：删了以后没人知道这里曾经有过什么
    assert out["action"] == "cancel_with_note"
    assert out["rule"]


def test_stale_blocked_skips_tasks_that_have_evidence(monkeypatch):
    rows = [{"id": "t1", "title": "有依据的", "agent_key": "pmc_agent", "follow_count": 2,
             "created_at": "2026-08-08",
             "payload": json.dumps({"category": "material_shortage", "work_order_id": "wo-1"})}]

    class _Res:
        def mappings(self):
            return self

        def all(self):
            return rows

    class _Db:
        async def execute(self, stmt, params=None):
            return _Res()

    out = asyncio.run(fl.plan_stale_blocked(_Db(), "FAC_MECH_001", older_than_days=7, apply=False))
    assert out["candidates"] == 0, out
