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

    def scalars(self):
        # 回填链路会经 virtual_run.default_models，那条查询用的是 .scalars().all()
        return self

    def first(self):
        # mappings().first() 要的是"一行记录"，本桩只喂得出列表行 —— 列表行不是记录，返回 None。
        for row in self._rows:
            if isinstance(row, dict):
                return row
        return None


def _db(targets, derive_results, update_rowcount=3, existing_derived=0):
    """按 SQL 文本分派的假会话：查目标 / 回填工单，其余交给 derive 自己处理。"""
    db = MagicMock()
    db.calls = []
    state = {"derive": list(derive_results)}

    async def execute(statement, params=None):
        sql = str(statement)
        db.calls.append((sql, params))
        if "count(*) FROM routings" in sql:
            return _Result([[(existing_derived if existing_derived is not None else 0)]])
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


def _stub_tail(monkeypatch):
    """把链条后半段"要读真库"的步骤换成明说被跳过的桩。

    本文件守的是路线回填的两条边界（只补排不动的工单、套不上要说清原因）。
    后半段（BOM 体检、工时口径、数据源台账、排程、草案回收、催料、线组比较、自我核对）读的是
    工单/路线/产能/草案这些真表行，桩喂不出可信结果 —— 让它们进测试只会红在
    和被测行为无关的地方。桩返回值写 skipped_in_test，心跳里一眼看得出是没跑。
    """
    async def _skip(db, *args, **kwargs):
        return {"status": "skipped_in_test", "reason": "这一步要读真实库，本测试不覆盖"}

    for name in ("scan_plant", "time_basis_review", "data_authority_report", "commit_plan_ready",
                 "prune_superseded_drafts", "chase_material_shortages",
                 "advise_line_strategy", "convergence_report"):
        monkeypatch.setattr(rb, name, _skip)


@pytest.mark.asyncio
async def test_backfill_binds_only_when_route_is_available(monkeypatch):
    targets = [{"factory_id": "FAC_MECH_001", "product_id": "A-50-04-F"},
               {"factory_id": "FAC_MECH_001", "product_id": "MG-NO-ROUTE"}]

    async def fake_derive(db, fid, code):
        if code == "A-50-04-F":
            return {"status": "derived", "routing_id": "rt-bom-A-50-04-F"}
        return {"status": "not_derived", "reason": "工序佐证率 1/6", "coverage": 0.17}

    monkeypatch.setattr(rb, "derive_routing_for_product", fake_derive)
    _stub_tail(monkeypatch)
    db, _ = _db(targets, [])
    receipt = await rb.backfill_missing_routings(db)
    assert receipt["status"] == "ok"

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
    _stub_tail(monkeypatch)
    db, _ = _db([{"factory_id": "FAC_MECH_001", "product_id": "X"}], [])
    receipt = await rb.backfill_missing_routings(db, apply=False)

    assert receipt["dry_run"] is True
    assert receipt["routed_products"] == 1, "预演要说清会回填几个产品"
    assert not [c for c in db.calls if "UPDATE work_orders" in c[0]], "预演不能改工单"
    assert ("ROLLBACK", None) in db.calls


@pytest.mark.asyncio
async def test_derived_route_budget_stops_the_loop_from_going_full_scale(monkeypatch):
    """开发/测试阶段不能后台把 473 个型号全推一遍：用完预算就停，并说明为什么没干活。"""
    calls = []

    async def fake_derive(db, fid, code):
        calls.append(code)
        return {"status": "derived", "routing_id": f"rt-bom-{code}"}

    monkeypatch.setattr(rb, "derive_routing_for_product", fake_derive)
    db, _ = _db([{"factory_id": "F", "product_id": "X"}], [], existing_derived=999)
    receipt = await rb.backfill_missing_routings(db)

    assert receipt["status"] == "budget_exhausted"
    assert receipt["examined"] == 0 and calls == [], "预算满了就不该再去读源数据"
    assert receipt["route_budget"] == rb.MAX_DERIVED_ROUTES
    assert receipt["derived_routes_in_db"] == 999, "心跳里要能看出已经推了多少条"


@pytest.mark.asyncio
async def test_target_query_excludes_closed_and_child_orders():
    """取目标的 SQL 要限死：主工单、未关闭、routing_id 为空 —— 否则会覆盖人工指定的路线。"""
    sql = rb.TARGET_WO_SQL.text
    assert "wo.routing_id IS NULL" in sql
    assert "wo.wo_type = 'master'" in sql
    assert "'completed'" in sql and "'cancelled'" in sql
    bind_sql = rb.BIND_WO_SQL.text
    assert "routing_id IS NULL" in bind_sql, "回填语句也不能覆盖已有路线"
