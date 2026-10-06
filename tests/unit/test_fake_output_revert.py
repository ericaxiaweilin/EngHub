"""虚假产出冲回的边界：有领料流水的绝不冲、冲不回的如实报、备份写不出就不动库。

这段逻辑的代价是"把真实数据冲掉"，所以断言全打在护栏上：
候选判据必须是两条同时成立（无齐套依据 + 零领料），只有前者的单子是快照缺数据（#46），
拿冲库存去修数据缺口会把数据问题变成经营问题。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services import fake_output_revert as fo


def _order(code="WO-CMP-1", status="completed", issues=0, inbound_lines=1,
           inbound_qty=24.0, now_available=24.0, reported_good=24.0):
    return {
        "work_order_id": f"id-{code}", "work_order_code": code, "wo_type": "component",
        "status": status, "product_id": "1000366546", "planned_qty": 24,
        "reported_good": reported_good, "issue_lines": issues, "issued_qty": issues * 10,
        "kit_req_lines": 0, "inbound_lines": inbound_lines, "inbound_qty": inbound_qty,
        "revertible_qty": min(inbound_qty, now_available),
        "inbound": [{
            "txn_id": f"tx-{code}", "inventory_id": f"inv-{code}", "material_id": "m1",
            "batch_code": f"B-{code}", "quantity": inbound_qty, "material_code": "1000366546",
            "factory_id": "FAC_MECH_001", "now_available": now_available, "now_total": now_available,
        }] * inbound_lines,
    }


def test_order_that_did_issue_material_is_never_reverted():
    """②有领料流水 → 保护住。这些单只是齐套快照缺行，是数据缺口不是造假。"""
    issued = _order("WO-VF-MASTER", status="in_progress", issues=3, inbound_lines=0)
    buckets = fo.classify([issued])
    assert buckets["revert_stock"] == [] and buckets["revert_status_only"] == []
    assert [o["work_order_code"] for o in buckets["protected_has_issues"]] == ["WO-VF-MASTER"]


def test_zero_input_orders_split_by_whether_they_touched_stock():
    buckets = fo.classify([
        _order("WO-CMP-STOCK"),                                  # 零领料 + 有入库
        _order("WO-TREAD-004", status="completed", inbound_lines=0),   # 已标完工但没入库
        _order("WO-VF-OP01", status="in_progress", inbound_lines=0),   # 仿真执行中
    ])
    assert [o["work_order_code"] for o in buckets["revert_stock"]] == ["WO-CMP-STOCK"]
    assert [o["work_order_code"] for o in buckets["revert_status_only"]] == ["WO-TREAD-004"]
    assert [o["work_order_code"] for o in buckets["execution_history"]] == ["WO-VF-OP01"]


class _Res:
    def __init__(self, first=None, all_rows=None, rowcount=0):
        self._first, self._all, self.rowcount = first, all_rows, rowcount

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all or []


class _FakeDB:
    def __init__(self, orders, *, inventory_available=None, shortage_series=None):
        self.orders = orders
        self.writes = []
        self.commits = 0
        self.inventory_available = inventory_available
        self.shortage_series = list(shortage_series or [
            {"shortage_qty": 40.0, "short_rows": 5, "lines": 20}])

    async def execute(self, statement, params=None):
        sql = str(statement)
        head = sql.strip().upper()
        if head.startswith(("UPDATE", "INSERT", "DELETE")):
            self.writes.append((head.split()[0], sql, params))
            return _Res(rowcount=1)
        if "WITH produced AS" in sql:
            return _Res(all_rows=self.orders)
        if "t.transaction_type = 'production_in'" in sql:
            return _Res(all_rows=(self.orders[0]["inbound"] if self.orders else []))
        if "AND m.material_code = ANY" in sql:
            row = self.shortage_series.pop(0) if self.shortage_series else {"shortage_qty": 0.0,
                                                                            "short_rows": 0, "lines": 0}
            return _Res(first=row)
        return _Res()

    async def get(self, model, pk):
        qty = self.inventory_available if self.inventory_available is not None else 24
        return type("Inv", (), {"id": pk, "factory_id": "FAC_MECH_001",
                                "batch_code": "B-1", "total_qty": qty, "available_qty": qty})()

    def add(self, obj):
        self.writes.append(("ADD", type(obj).__name__, None))

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_preview_writes_nothing():
    db = _FakeDB([_order()])
    out = await fo.revert(db, "FAC_MECH_001", apply=False)
    assert out["status"] == "preview_only"
    assert out["planned_orders"] == 1 and out["planned_qty"] == 24.0
    assert db.writes == [] and db.commits == 0
    assert "领料流水" in out["message"]
    assert out["shortage_now"]["shortage_qty"] == 40.0


@pytest.mark.asyncio
async def test_hidden_gap_is_measured_not_modelled(monkeypatch):
    """被掩盖的缺口 = 权威刷新前后两次读数之差；这个工具自己不另算一份分配模型。"""
    readings = [{"shortage_qty": 40.0, "short_rows": 5, "lines": 20},    # scan() 先读一次
                {"shortage_qty": 40.0, "short_rows": 5, "lines": 20},    # 冲回后、重算前
                {"shortage_qty": 72.0, "short_rows": 7, "lines": 20}]    # snapshot_supply 重算后
    db = _FakeDB([_order()], shortage_series=readings)

    async def fake_apply(db_, *, inventory, transaction_type, quantity, **kw):
        return object()

    async def fake_refresh(db_, **kw):
        return {"refreshed": 6}

    monkeypatch.setattr(fo, "apply_movement", fake_apply)
    monkeypatch.setattr("api.services.snapshot_supply.refresh_snapshot_supply", fake_refresh)
    monkeypatch.setattr(fo, "_write_backup", lambda path, rows: path)

    out = await fo.revert(db, "FAC_MECH_001", apply=True)

    assert out["shortage_before"]["shortage_qty"] == 40.0
    assert out["shortage_after"]["shortage_qty"] == 72.0
    assert out["revealed_gap_qty"] == 32.0
    assert "被虚假库存藏起来的 32 件" in out["message"]


@pytest.mark.asyncio
async def test_reversal_is_capped_at_what_is_still_in_stock(monkeypatch):
    """批次已被下游领走大半 → 只冲还在的那部分，差额如实记 unrecoverable，不写负库存。"""
    order = _order(inbound_qty=24.0, now_available=9.0)
    order["revertible_qty"] = 9.0
    db = _FakeDB([order], inventory_available=9)
    calls = []

    async def fake_apply(db_, *, inventory, transaction_type, quantity, **kw):
        calls.append({"type": transaction_type, "qty": quantity, "kw": kw})
        return object()

    async def fake_refresh(db_, **kw):
        return {"refreshed": 0}

    monkeypatch.setattr(fo, "apply_movement", fake_apply)
    monkeypatch.setattr("api.services.snapshot_supply.refresh_snapshot_supply", fake_refresh)
    monkeypatch.setattr(fo, "_write_backup", lambda path, rows: path)

    out = await fo.revert(db, "FAC_MECH_001", apply=True)

    assert calls and calls[0]["qty"] == 9                  # 只冲 9 件，不是 24
    assert calls[0]["type"] == "adjustment_out"
    row = out["reverted"][0]
    assert row["reversed_qty"] == 9.0 and row["unrecoverable_qty"] == 15.0
    assert row["reports_undone"] == 1 and row["order_reopened"] == 1


@pytest.mark.asyncio
async def test_fully_consumed_batch_is_reported_not_faked(monkeypatch):
    """批次已经空了：一件都冲不动，但必须留下"冲不回"的读数，不能假装平账。"""
    order = _order(inbound_qty=24.0, now_available=0.0)
    order["revertible_qty"] = 0.0
    db = _FakeDB([order], inventory_available=0)
    called = []

    async def fake_apply(db_, **kw):
        called.append(kw)
        return object()

    async def fake_refresh(db_, **kw):
        return {"refreshed": 0}

    monkeypatch.setattr(fo, "apply_movement", fake_apply)
    monkeypatch.setattr("api.services.snapshot_supply.refresh_snapshot_supply", fake_refresh)
    monkeypatch.setattr(fo, "_write_backup", lambda path, rows: path)

    out = await fo.revert(db, "FAC_MECH_001", apply=True)

    assert called == []                                     # 不记 0 数量流水
    row = out["reverted"][0]
    assert row["reversed_qty"] == 0.0 and row["unrecoverable_qty"] == 24.0
    assert "已被下游领走或清空" in row["moves"][0]["reason"]


@pytest.mark.asyncio
async def test_backup_failure_aborts_before_touching_the_db(monkeypatch):
    def boom(path, rows):
        raise RuntimeError("备份写入失败，已中止冲回：read-only")

    monkeypatch.setattr(fo, "_write_backup", boom)
    db = _FakeDB([_order()])
    with pytest.raises(RuntimeError):
        await fo.revert(db, "FAC_MECH_001", apply=True)
    assert db.writes == [] and db.commits == 0


def test_scope_requires_both_missing_kit_evidence_and_zero_issues():
    """判据写在 SQL 里就要能被读到：两条缺一个都不算虚假产出。"""
    sql = str(fo.SCOPE_SQL)
    assert "COALESCE(k.req_lines, 0) = 0" in sql           # ①齐套表没有带需求量的行
    assert "issued" in sql and "issue_lines" in sql         # ②领料流水带进分类
    src = fo.__doc__
    assert "有领料流水的单绝不碰" in src
