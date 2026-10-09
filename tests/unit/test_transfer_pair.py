"""调拨必须成对：源出一、目标入，同一个单据号，数量恒为正。

这一格立的是"账不能凭空多也不能凭空少"：分两次单边记账，任何一次失败都会留下
扣了没加（货消失）或加了没扣（货变出来）的账。
"""
import asyncio

import pytest

from api.services.wms_architecture.movements import MovementError, apply_transfer_pair


class FakeInv:
    def __init__(self, id, qty, avail, factory_id="F1", material_id="m1", batch="B1"):
        self.id, self.total_qty, self.available_qty = id, qty, avail
        self.factory_id, self.material_id, self.batch_code = factory_id, material_id, batch
        self.unit = "pcs"
        self.last_movement_at = None
        self.updated_at = None


class FakeDb:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _run(**kw):
    db = FakeDb()
    out = asyncio.run(apply_transfer_pair(db, **kw))
    return db, out


def test_pair_writes_two_legs_with_the_same_document():
    src, dst = FakeInv("i1", 100, 100), FakeInv("i2", 5, 5)
    db, (out_txn, in_txn) = _run(source=src, target=dst, quantity=40,
                                 reference_type="transfer_request",
                                 reference_id="TR-1", reference_doc_no="TR-1")
    assert [t.transaction_type for t in (out_txn, in_txn)] == ["transfer_out", "transfer_in"]
    # 两边都挂同一个单据号 —— 否则事后无法证明这两条是同一笔搬移
    assert out_txn.reference_doc_no == in_txn.reference_doc_no == "TR-1"
    assert out_txn.before_qty == 100 and out_txn.after_qty == 60
    assert in_txn.before_qty == 5 and in_txn.after_qty == 45
    # 数量恒为正，方向由类型决定（历史上出库那条写的是 -quantity）
    assert out_txn.quantity == 40 and in_txn.quantity == 40
    assert src.total_qty == 60 and dst.total_qty == 45
    assert src.available_qty == 60 and dst.available_qty == 45
    # 总量守恒：搬移不创造也不消灭库存
    assert src.total_qty + dst.total_qty == 105


def test_pair_requires_a_document_anchor():
    src, dst = FakeInv("i1", 10, 10), FakeInv("i2", 0, 0)
    with pytest.raises(MovementError):
        _run(source=src, target=dst, quantity=5, reference_type="transfer_request",
             reference_id="", reference_doc_no="")


def test_pair_rejects_negative_and_zero_quantity():
    src, dst = FakeInv("i1", 10, 10), FakeInv("i2", 0, 0)
    for bad in (0, -5):
        with pytest.raises(MovementError):
            _run(source=src, target=dst, quantity=bad, reference_type="transfer_request",
                 reference_id="TR-2", reference_doc_no="TR-2")


def test_pair_refuses_to_move_more_than_is_available():
    src, dst = FakeInv("i1", 10, 3), FakeInv("i2", 0, 0)
    with pytest.raises(MovementError):
        _run(source=src, target=dst, quantity=5, reference_type="transfer_request",
             reference_id="TR-3", reference_doc_no="TR-3")
    # 拒了就不许留下半条账
    assert src.total_qty == 10 and dst.total_qty == 0


def test_same_row_is_not_a_move():
    """自己搬给自己会写出两条互相抵消的流水，把"动过"的读数抬高。"""
    only = FakeInv("i1", 10, 10)
    with pytest.raises(MovementError):
        _run(source=only, target=only, quantity=5, reference_type="transfer_request",
             reference_id="TR-4", reference_doc_no="TR-4")
