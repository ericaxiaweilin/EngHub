"""冻结是控制，不是装饰品：冻着的行扣不走也搬不走，没冻的行照常动。

10-09 实测的起点：`inventory_freezes` 0 行，而 `inventory.status / lock_reason /
qualified_status` 三列在**读取侧一处都没用到** —— 标记"待检"之后领料照样把它领走。
所以这一格的判据不是"有没有冻结记录"，而是"领不领得走"。守卫放在写入原语里
（20 多处选行查询各自补过滤 = 一张会随写入方漂移的手抄清单，漏一处那处就能领走）。

三个方向都要钉住（只验"会拦"就等于拦住所有人）：
· locked 的行：消耗、搬出都当场拒，且不留下半条账；
· status 为空 / 'available' 的行：照常过账 —— 冻结上线不能锁死正常出入库；
· 往冻着的行**入库**要允许：收货→待检→放行本来就是正常流程，拒收就把仓库堵死了。
"""
import asyncio

import pytest

from api.services.wms_architecture.movements import (
    FROZEN_STATUS,
    MovementError,
    apply_movement,
    apply_transfer_pair,
    frozen_stock_error,
)
from api.services.wms_freezes import partition_by_status, sync_check


class _Inv:
    """台账行的形状：分配路径拿到的是 ORM 对象，这里只给判据要读的字段。"""

    def __init__(self, id="i1", total=100, avail=100, status=None, lock_reason=None,
                 material_id="RM-0007", batch="B-2409", factory_id="FAC_MECH_001"):
        self.id, self.total_qty, self.available_qty = id, total, avail
        self.status, self.lock_reason = status, lock_reason
        self.material_id, self.batch_code, self.factory_id = material_id, batch, factory_id
        self.unit = "pcs"
        self.last_movement_at = None
        self.updated_at = None


class _Db:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def _run(fn, *a, **kw):
    return asyncio.run(fn(*a, **kw))


# ── 分配层的排除：挡住多少就要报出多少，不许静默少发 ──────────────────────
def test_frozen_rows_are_excluded_and_the_blocked_quantity_is_reported():
    rows = [_Inv("i1", avail=60), _Inv("i2", avail=40, status=FROZEN_STATUS, lock_reason="IQC-PENDING"),
            _Inv("i3", avail=25)]
    split = partition_by_status(rows)
    assert [r.id for r in split["allocatable"]] == ["i1", "i3"]
    assert split["held_rows"] == 1
    # 报的是"被挡了多少件"，不是"挡了几行"：欠料话术要能说出 40 件在货架上但领不走
    assert split["held_qty"] == 40
    assert split["held_reasons"] == ["IQC-PENDING"]
    assert sum(int(r.available_qty) for r in split["allocatable"]) == 85


def test_no_freeze_leaves_every_row_allocatable():
    """反向：没冻结时一条都不许挡。status 为空是线上绝大多数行，误伤就等于锁死仓库。"""
    rows = [_Inv("i1", avail=10), _Inv("i2", avail=20), _Inv("i3", avail=30)]
    split = partition_by_status(rows)
    assert len(split["allocatable"]) == 3
    assert split["held"] == [] and split["held_rows"] == 0 and split["held_qty"] == 0


def test_partition_accepts_dict_rows_too():
    """探测脚本和读侧拿到的常是 mapping（dict），判据不能只认 ORM 对象。"""
    split = partition_by_status(
        [{"id": "a", "available_qty": 5, "status": "available"},
         {"id": "b", "available_qty": 7, "status": "locked", "lock_reason": "ACCIDENT"}])
    assert [r["id"] for r in split["allocatable"]] == ["a"]
    assert split["held_qty"] == 7 and split["held_reasons"] == ["ACCIDENT"]


# ── 写入原语上的硬门 ────────────────────────────────────────────────────
def test_consuming_a_locked_row_is_refused_and_leaves_no_half_posted_ledger():
    db, inv = _Db(), _Inv(total=100, avail=100, status=FROZEN_STATUS, lock_reason="IQC-PENDING")
    with pytest.raises(MovementError):
        _run(apply_movement, db, inventory=inv, transaction_type="production_out", quantity=30,
             reference_type="outbound_order", reference_id="ob-1", reference_doc_no="OB-0001",
             work_order_id="wo-9")
    assert inv.total_qty == 100 and inv.available_qty == 100
    assert db.added == []          # 拒了就不许留下流水


def test_the_refusal_names_the_reason_code_batch_and_quantity():
    """报错要带它自己的实体：只说"不许出库"，现场还是不知道该找谁放行。"""
    err = frozen_stock_error(_Inv(id="i-77", material_id="RM-0007", batch="B-2409",
                                 status=FROZEN_STATUS, lock_reason="NONCONFORMING"),
                            30, doing="扣减")
    text = str(err)
    for needle in ("i-77", "RM-0007", "B-2409", "30", "NONCONFORMING", "freeze/release"):
        assert needle in text, f"报错缺 {needle}：{text}"


def test_blank_or_available_status_still_posts():
    """反向：线上绝大多数行的 status 是空或 available，一个都不许被误伤。"""
    for status in (None, "", "available", "Available "):
        db, inv = _Db(), _Inv(total=50, avail=50, status=status)
        txn = _run(apply_movement, db, inventory=inv, transaction_type="production_out",
                   quantity=10, reference_type="outbound_order", reference_id="ob-x",
                   reference_doc_no="OB-X", work_order_id="wo-x")
        assert (inv.total_qty, inv.available_qty) == (40, 40), f"status={status!r} 被误挡"
        assert db.added == [txn]


def test_locked_status_survives_case_and_padding():
    """有人手输了 ' LOCKED ' 也算冻着 —— 守卫判的是能力，不是字符串长得对不对。"""
    assert frozen_stock_error(_Inv(status=" LOCKED "), 5) is not None


def test_receiving_into_a_locked_row_is_allowed():
    """第三个方向：收货→待检→放行是正常流程，拒收等于把仓库堵死。"""
    db, inv = _Db(), _Inv(total=0, avail=0, status=FROZEN_STATUS, lock_reason="IQC-PENDING")
    _run(apply_movement, db, inventory=inv, transaction_type="purchase_in", quantity=50,
         reference_type="inbound_order", reference_id="in-1", reference_doc_no="IN-0001")
    assert (inv.total_qty, inv.available_qty) == (50, 50)
    assert len(db.added) == 1


def test_transfer_refuses_to_move_out_of_a_locked_source():
    db, src, dst = _Db(), _Inv(id="i1", total=40, avail=40, status=FROZEN_STATUS), _Inv(id="i2", total=0, avail=0)
    with pytest.raises(MovementError):
        _run(apply_transfer_pair, db, source=src, target=dst, quantity=15,
             reference_type="transfer_request", reference_id="TR-1", reference_doc_no="TR-1")
    # 单边都没动：不能出现"源扣了、目标没加"
    assert (src.total_qty, src.available_qty) == (40, 40)
    assert (dst.total_qty, dst.available_qty) == (0, 0)
    assert db.added == []


def test_transfer_still_works_when_the_source_is_free():
    db, src, dst = _Db(), _Inv(id="i1", total=40, avail=40), _Inv(id="i2", total=5, avail=5)
    _run(apply_transfer_pair, db, source=src, target=dst, quantity=15,
         reference_type="transfer_request", reference_id="TR-2", reference_doc_no="TR-2")
    assert (src.total_qty, dst.total_qty) == (25, 20)
    assert len(db.added) == 2


# ── 两笔账的对账：冻结记录 vs 行上的锁 ───────────────────────────────────
def test_sync_check_accepts_when_both_books_agree():
    assert sync_check(3, 3)["in_sync"] is True


def test_sync_check_flags_lock_without_record():
    """只锁不记 = 没人知道这批料被谁冻、凭什么冻。"""
    out = sync_check(1, 4)
    assert out["in_sync"] is False and "4" in out["note"]


def test_sync_check_flags_record_without_lock():
    """只记不锁 = 表里看着冻着、货照样被领走 —— 那正是这一格要根除的装饰品。"""
    assert sync_check(4, 1)["in_sync"] is False
