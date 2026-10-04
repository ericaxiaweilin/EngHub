"""路线回填循环的边界测试。

守的是两件事：**只补排不动的工单**（不覆盖人工指定的路线、不碰完工/取消），
以及**套不上就说清为什么**（拒绝原因要进凭据，否则下一轮还是同一批排不动）。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import routing_backfill as rb


class _Result:
    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else None


def _db(targets, derive_results, update_rowcount=3):
    """按 SQL 文本分派的假会话：查目标 / 回填工单，其余交给 derive 自己处理。"""
    db = MagicMock()
    db.calls = []
    state = {"derive": list(derive_results)}

    async def execute(statement, params=None):
        sql = str(statement)
        db.calls.append((sql, params))
        if "DISTINCT wo.factory_id" in sql:
            return _Result(targets)
        if "UPDATE work_orders" in sql:
            return _Result([], rowcount=update_rowcount)
        return _Result([])

    async def commit():
        db.calls.append(("COMMIT", None))

    async def rollback():
        db.calls.append(("ROLLBACK", None))

    db.execute = execute
    db.commit = commit
    db.rollback = rollback
    return db, state


@pytest.mark.asyncio
async def test_backfill_binds_only_when_route_is_available(monkeypatch):
    targets = [{"factory_id": "FAC_MECH_001", "product_id": "A-50-04-F"},
               {"factory_id": "FAC_MECH_001", "product_id": "MG-NO-ROUTE"}]

    async def fake_derive(db, fid, code):
        if code == "A-50-04-F":
            return {"status": "derived", "routing_id": "rt-bom-A-50-04-F"}
        return {"status": "not_derived", "reason": "工序佐证率 1/6", "coverage": 0.17}

    monkeypatch.setattr(rb, "derive_routing_for_product", fake_derive)
    db, _ = _db(targets, [])
    receipt = await rb.backfill_missing_routings(db)

    assert receipt["examined"] == 2
    assert receipt["routed_products"] == 1
    assert receipt["routed_work_orders"] == 3
    assert receipt["by_status"] == {"derived": 1, "not_derived": 1}
    assert receipt["rejected"][0]["product_code"] == "MG-NO-ROUTE"
    assert receipt["rejected"][0]["reason"], "拒绝必须带原因，不然下一轮还是没人知道差什么"
    binds = [c for c in db.calls if "UPDATE work_orders" in c[0]]
    assert len(binds) == 1, "只有拿到路线的产品才回填"
    assert binds[0][1]["routing_id"] == "rt-bom-A-50-04-F"


@pytest.mark.asyncio
async def test_dry_run_does_not_write(monkeypatch):
    async def fake_derive(db, fid, code):
        return {"status": "derived", "routing_id": "rt-bom-X"}

    monkeypatch.setattr(rb, "derive_routing_for_product", fake_derive)
    db, _ = _db([{"factory_id": "FAC_MECH_001", "product_id": "X"}], [])
    receipt = await rb.backfill_missing_routings(db, apply=False)

    assert receipt["dry_run"] is True
    assert receipt["routed_products"] == 1, "预演要说清会回填几个产品"
    assert not [c for c in db.calls if "UPDATE work_orders" in c[0]], "预演不能改工单"
    assert ("ROLLBACK", None) in db.calls


@pytest.mark.asyncio
async def test_target_query_excludes_closed_and_child_orders():
    """取目标的 SQL 要限死：主工单、未关闭、routing_id 为空 —— 否则会覆盖人工指定的路线。"""
    sql = rb.TARGET_WO_SQL.text
    assert "wo.routing_id IS NULL" in sql
    assert "wo.wo_type = 'master'" in sql
    assert "'completed'" in sql and "'cancelled'" in sql
    bind_sql = rb.BIND_WO_SQL.text
    assert "routing_id IS NULL" in bind_sql, "回填语句也不能覆盖已有路线"
