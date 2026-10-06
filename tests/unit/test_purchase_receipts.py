"""采购到货：过了预计到货日要真的变成库存，且只在账上发生一次。

这一格存在的原因（10-06 实测）：31 张 confirmed/in_transit 的 PO 预计到货日已过去 1.5 个月，
`goods_receipts` 最后一行停在 08-16，没有任何代码把在途收成库存 ——
所以 MRP 反复算出同样的缺口、齐套门反复不放行，引擎只能继续拆新单。
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import purchase_receipts as pr
from api.services.bom_source import OPEN_PO_STATUSES


def _po(po_id="po-1", code="PO-0001", material="RM-ELEC-036", qty=600, received=0,
        expected=date(2026, 8, 23), fid="FAC_MECH_001"):
    row = {"id": po_id, "factory_id": fid, "po_code": code, "material_code": material,
           "supplier_id": "SUP-1", "qty": qty, "received_qty": received,
           "outstanding": qty - received, "expected_date": expected,
           "overdue_days": 44}
    return row


def _db(rows, booked_reason="posted"):
    sqls = []

    async def execute(statement, params=None):
        sql = str(statement)
        sqls.append((sql, params))
        result = MagicMock()
        if "FROM purchase_orders po" in sql:
            result.mappings.return_value.all.return_value = rows
        else:
            result.rowcount = 1
            result.scalar.return_value = "WH-1"
            result.mappings.return_value.first.return_value = None
            result.mappings.return_value.all.return_value = []
        return result

    async def commit():
        sqls.append(("COMMIT", None))

    db = MagicMock()
    db.execute = execute
    db.commit = commit
    db.add = lambda obj: sqls.append((f"ADD:{type(obj).__name__}", None))
    db.flush = commit
    db.sqls = sqls
    return db


@pytest.fixture
def fake_wms(monkeypatch):
    calls = []

    class _Wms:
        def __init__(self, db):
            self.db = db

        async def record_purchase_receipt(self, **kw):
            calls.append(kw)
            return {"posted": kw["qty"], "reason": booked_reason_holder["reason"],
                    "gr_code": "GR-test", "goods_receipt_id": "gr-1",
                    "warehouse_id": "WH-1", "material_code": kw["material_code"]}

    booked_reason_holder = {"reason": "posted"}
    monkeypatch.setattr("api.services.wms_service.InventoryService", _Wms)
    fake_wms.calls = calls
    fake_wms.holder = booked_reason_holder
    return fake_wms


@pytest.mark.asyncio
async def test_overdue_po_is_booked_once_with_outstanding_qty(fake_wms):
    db = _db([_po(qty=600, received=120)])
    receipt = await pr.receive_due_purchase_orders(
        db, factory_id="FAC_MECH_001", as_of=date(2026, 10, 6), apply=True)

    assert receipt["received"] == 1
    # 收的是"还没收的数量"，不是整张单的量（否则同一张单会被重复入库）
    assert fake_wms.calls[0]["qty"] == 480
    assert receipt["posted_qty"] == 480
    upd = [s for s, _ in db.sqls if "UPDATE purchase_orders" in s]
    assert upd and "received_qty = COALESCE(received_qty, 0) + :qty" in upd[0]
    # 状态守卫：只在它仍然是"未到货"的那些状态时才改，避免和人工操作抢
    assert "status = ANY(:open_statuses)" in upd[0]


@pytest.mark.asyncio
async def test_dry_run_moves_no_stock(fake_wms):
    db = _db([_po()])
    receipt = await pr.receive_due_purchase_orders(
        db, factory_id="FAC_MECH_001", as_of=date(2026, 10, 6), apply=False)
    assert receipt["dry_run"] is True
    assert receipt["received"] == 0 and fake_wms.calls == []
    assert not [s for s, _ in db.sqls if "UPDATE purchase_orders" in s]
    assert receipt["examples"][0]["overdue_days"] == 44


@pytest.mark.asyncio
async def test_booking_failure_keeps_order_open(fake_wms):
    """收货过账没成功（比如厂区没有可用仓库）就不能把单改成已收货：
    单据说到了、库存没动，比两边都说没到更难查。"""
    fake_wms.holder["reason"] = "no_warehouse"
    db = _db([_po()])
    receipt = await pr.receive_due_purchase_orders(
        db, factory_id="FAC_MECH_001", as_of=date(2026, 10, 6), apply=True)
    assert receipt["received"] == 0
    assert receipt["skipped"]["no_warehouse"] == 1
    assert not [s for s, _ in db.sqls if "UPDATE purchase_orders" in s]


@pytest.mark.asyncio
async def test_clock_basis_is_reported(monkeypatch):
    """到货日用哪把尺子必须写在回执里：仿真时钟读不到时退回真实日期，得看得见。"""
    async def fake_now(fid):
        raise RuntimeError("redis down")
    class _Clock:
        now = staticmethod(fake_now)
    monkeypatch.setattr("api.services.virtual_factory_clock.get_clock", lambda: _Clock())
    db = _db([])
    receipt = await pr.receive_due_purchase_orders(db, factory_id="FAC_MECH_001", apply=False)
    assert receipt["clock_basis"] == "real_date"
    assert receipt["status"] == "nothing_due"


def test_open_po_status_set_covers_every_unreceived_state():
    """在途口径只有一份：confirmed/approved/ordered/in_transit/shipped 都算没到货。
    以前 stock_and_supply 只认两种，14 张 in_transit 对 MRP 等于不存在。"""
    assert set(OPEN_PO_STATUSES) >= {"confirmed", "in_transit", "shipped", "approved", "ordered"}
    assert "received" not in OPEN_PO_STATUSES
