"""库存记账原语回归：数量与流水必须同源，缺锚点就拒。

线上现状（2026-10-04 查账）：inbound_orders 27 张 + outbound_orders 58 张
已 completed，但 inventory_transactions 里一张都找不到对应流水 —— 这个文件
钉住的就是"不会再出现第 86 张有单无账"。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services.wms_architecture.movements import (
    MovementError,
    apply_movement,
    document_movement_type,
)
from api.services.wms_service import InventoryService


class _Inv:
    """够用的库存行替身：只暴露记账原语真正读写的字段。"""

    def __init__(self, total_qty=0, available_qty=0, batch_code="B-1"):
        self.id = "inv-1"
        self.factory_id = "FAC_TEST"
        self.material_id = "MAT-1"
        self.batch_code = batch_code
        self.total_qty = total_qty
        self.available_qty = available_qty
        self.last_movement_at = None


def _db():
    db = MagicMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_receipt_moves_stock_and_posts_positive_ledger():
    db, inv = _db(), _Inv(total_qty=10, available_qty=10)
    txn = await apply_movement(
        db, inventory=inv, transaction_type="purchase_in", quantity=50,
        reference_type="inbound_order", reference_id="in-1", reference_doc_no="IN-0001",
    )
    db.add.assert_called_once_with(txn)
    assert (inv.total_qty, inv.available_qty) == (60, 60)
    # 数量恒为正、方向由类型决定 —— 与线上已有流水同一约定
    assert (txn.quantity, txn.before_qty, txn.after_qty) == (50, 10, 60)
    assert (txn.reference_id, txn.reference_doc_no, txn.inventory_id) == ("in-1", "IN-0001", "inv-1")


@pytest.mark.asyncio
async def test_consumption_moves_stock_down_but_ledger_stays_positive():
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    txn = await apply_movement(
        db, inventory=inv, transaction_type="production_out", quantity=30,
        reference_type="outbound_order", reference_id="out-1",
        reference_doc_no="OUT-0001", work_order_id="WO-7",
    )
    assert (inv.total_qty, inv.available_qty) == (20, 20)
    assert (txn.quantity, txn.before_qty, txn.after_qty) == (30, 50, 20)
    assert txn.work_order_id == "WO-7"


@pytest.mark.asyncio
async def test_material_issue_without_work_order_is_refused():
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    with pytest.raises(MovementError):
        await apply_movement(
            db, inventory=inv, transaction_type="production_out", quantity=10,
            reference_type="outbound_order", reference_id="out-1", reference_doc_no="OUT-0001",
        )
    assert (inv.total_qty, inv.available_qty) == (50, 50)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_movement_without_document_anchor_is_refused():
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    with pytest.raises(MovementError):
        await apply_movement(
            db, inventory=inv, transaction_type="purchase_in", quantity=10,
            reference_type="inbound_order", reference_id="in-1", reference_doc_no="  ",
        )
    assert inv.total_qty == 50
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_short_stock_is_refused_before_any_mutation():
    db, inv = _db(), _Inv(total_qty=5, available_qty=5)
    with pytest.raises(MovementError):
        await apply_movement(
            db, inventory=inv, transaction_type="sales_out", quantity=6,
            reference_type="outbound_order", reference_id="out-1", reference_doc_no="OUT-0001",
        )
    assert (inv.total_qty, inv.available_qty) == (5, 5)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_literal_types_are_not_accepted():
    """读取侧还要认得 inbound/outbound/transfer（历史 183 条流水），
    写入侧一律拒收 —— 否则永远收敛不到一套词。"""
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    for legacy in ("inbound", "outbound", "transfer"):
        with pytest.raises(MovementError):
            await apply_movement(
                db, inventory=inv, transaction_type=legacy, quantity=10,
                reference_type="x", reference_id="y", reference_doc_no="Z-1",
            )
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_non_movement_type_is_not_posted_by_this_primitive():
    """调拨/盘点的成对记账走各自路径：这里放过它等于允许单边账。"""
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    for bad_type in ("transfer_out", "transfer_in", "scenario_hold", "count_diff"):
        with pytest.raises(MovementError):
            await apply_movement(
                db, inventory=inv, transaction_type=bad_type, quantity=10,
                reference_type="x", reference_id="y", reference_doc_no="Z-1",
            )
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_zero_or_negative_quantity_is_refused():
    db, inv = _db(), _Inv(total_qty=50, available_qty=50)
    for bad in (0, -5):
        with pytest.raises(MovementError):
            await apply_movement(
                db, inventory=inv, transaction_type="purchase_in", quantity=bad,
                reference_type="inbound_order", reference_id="in-1", reference_doc_no="IN-0001",
            )
    assert inv.total_qty == 50


def test_document_types_map_to_the_canonical_vocabulary():
    assert document_movement_type("in", "purchase") == "purchase_in"
    assert document_movement_type("in", "Production") == "production_in"
    # 线上 outbound_type 的真实取值是 production / shipment，别再造第三种词
    assert document_movement_type("out", "production") == "production_out"
    assert document_movement_type("out", "shipment") == "sales_out"


def test_unmappable_document_type_is_refused():
    with pytest.raises(MovementError):
        document_movement_type("out", "misc")
    with pytest.raises(MovementError):
        document_movement_type("sideways", "purchase")


def _session_with(rows):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalars.return_value.first.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def test_request_models_expose_the_fields_their_endpoints_read():
    """端点模型曾经被同名类覆盖（wms_routes 里两个 InboundCreate），
    运行时才炸 AttributeError，线上两个出入库写端点全都进不去。"""
    from api.routes.wms_routes import InboundCreate, OutboundCreate

    assert {"factory_id", "warehouse_id", "material_id", "material_code",
            "quantity", "inbound_type"} <= set(InboundCreate.model_fields)
    assert {"factory_id", "warehouse_id", "material_id", "quantity",
            "work_order_id", "outbound_type"} <= set(OutboundCreate.model_fields)


@pytest.mark.asyncio
async def test_no_batch_inbound_matches_existing_row_with_is_null():
    """`= NULL` 永远不成立 —— 原来每笔无批次入库都另起一行库存，账面越拆越碎。"""
    existing = _Inv(total_qty=10, available_qty=10, batch_code=None)
    session = _session_with([existing])

    svc = InventoryService(session)
    row = await svc._resolve_inbound_inventory_row(
        factory_id="FAC_TEST", warehouse_id="WH-1",
        material_id="MAT-1", material_code="MAT-1",
    )
    statement = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": False}))
    assert "IS NULL" in statement
    assert "batch_code = NULL" not in statement
    assert row is existing  # 命中已有行就累加，不再新建
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_fifo_allocation_writes_one_plan_row_per_batch():
    a, b = _Inv(total_qty=40, available_qty=40, batch_code="B-A"), _Inv(
        total_qty=100, available_qty=100, batch_code="B-B"
    )
    svc = InventoryService(_session_with([a, b]))
    allocations = await svc._allocate_fifo_batches(
        factory_id="FAC_TEST", warehouse_id="WH-1", material_id="MAT-1", quantity=120
    )
    assert [(inv.batch_code, qty) for inv, qty in allocations] == [("B-A", 40), ("B-B", 80)]
    # 只分配不动数量：动数量是 apply_movement 的唯一职责
    assert (a.total_qty, b.total_qty) == (40, 100)


@pytest.mark.asyncio
async def test_fifo_allocation_refuses_when_stock_short():
    a = _Inv(total_qty=40, available_qty=40)
    svc = InventoryService(_session_with([a]))
    with pytest.raises(ValueError, match="Short by 60"):
        await svc._allocate_fifo_batches(
            factory_id="FAC_TEST", warehouse_id="WH-1", material_id="MAT-1", quantity=100
        )


@pytest.mark.asyncio
async def test_fifo_allocation_refuses_non_positive_quantity():
    svc = InventoryService(_session_with([]))
    with pytest.raises(ValueError):
        await svc._allocate_fifo_batches(
            factory_id="FAC_TEST", warehouse_id="WH-1", material_id="MAT-1", quantity=0
        )
