"""终端写入路径必须走记账原语：质量冻结挡得住出库，出库流水落在规范类型上。

10-10 界面自检抓到：`/wms/outbound` 自己写 `inv.total_qty -= q` + 一条
`transaction_type='outbound'` 的遗留流水，所以一行 status='locked' 的库存
照样出库成功 —— 守卫在 apply_movement 里，这条路径根本没进那扇门。
这里用内存 SQLite 真跑一遍服务调用，不是 grep 源码。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from api.services.wms_operation_service import WmsOperationService
from database.models import Inventory, InventoryTransaction, OutboundOrder

TABLES = [Inventory.__table__, InventoryTransaction.__table__, OutboundOrder.__table__]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in TABLES:
            await conn.execute(CreateTable(table))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _inv(**kw):
    base = dict(id="inv-1", material_id="M-1", material_code="C-1", material_name="軸承",
                factory_id="F", warehouse_id="W-1", location_id=None, batch_code="B-1",
                total_qty=100, available_qty=100, reserved_qty=0, unit="pcs",
                status="available", created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 1), last_movement_at=None)
    base.update(kw)
    return Inventory(**base)


async def _rows(db, model):
    return list((await db.execute(select(model))).scalars().all())


@pytest.mark.asyncio
async def test_frozen_row_cannot_go_out_through_the_terminal(db):
    db.add(_inv(status="locked", lock_reason="来料待检"))
    await db.commit()

    result = await WmsOperationService(db).quick_outbound(
        factory_id="F", material_id="M-1", quantity=5, warehouse_id="W-1",
        operator="eric", outbound_type="sales")

    assert "error" in result, f"被冻住的行居然出得去：{result}"
    assert "冻结" in result["error"], result["error"]
    inv = (await _rows(db, Inventory))[0]
    assert (inv.total_qty, inv.available_qty) == (100, 100), "扣减没成也不能把数量改掉"
    assert await _rows(db, InventoryTransaction) == [], "失败的一笔记了流水就是脏账"


@pytest.mark.asyncio
async def test_unfrozen_row_goes_out_with_typed_anchored_ledger(db):
    db.add(_inv(status="available"))
    await db.commit()

    result = await WmsOperationService(db).quick_outbound(
        factory_id="F", material_id="M-1", quantity=5, warehouse_id="W-1",
        operator="eric", outbound_type="sales")

    assert result.get("success") is True, result
    assert result["outbound_code"], "出库要有单据号"
    assert result["after_qty"] == 95, result
    txn = (await _rows(db, InventoryTransaction))[0]
    # 'outbound' 是原语拒收的遗留字面量：落这一格就说明又绕过去了
    assert txn.transaction_type == "sales_out", txn.transaction_type
    assert txn.reference_type == "outbound_order" and txn.reference_doc_no
    assert (txn.before_qty, txn.after_qty) == (100, 95)


@pytest.mark.asyncio
async def test_terminal_receipt_writes_once_through_the_primitive(db):
    """收货走原语：数量由流水带出来，不能建行时先写一遍、流水再补一遍。"""
    result = await WmsOperationService(db).quick_inbound(
        factory_id="F", material_id="M-9", material_code="C-9", quantity=40,
        warehouse_id="W-1", batch_code="B-9", operator="eric", inbound_type="purchase")

    assert result.get("success") is True, result
    inv = (await _rows(db, Inventory))[0]
    assert (inv.total_qty, inv.available_qty) == (40, 40)
    txn = (await _rows(db, InventoryTransaction))[0]
    assert txn.transaction_type == "purchase_in"
    assert txn.reference_doc_no == result["document_no"] and txn.reference_doc_no
    assert (txn.before_qty, txn.after_qty) == (0, 40)


@pytest.mark.asyncio
async def test_receipt_is_allowed_on_a_frozen_row(db):
    """冻结算的是"领不走"，不是"货不收"：来料本就在手上，收货不该被自己的锁挡死。"""
    db.add(_inv(status="locked", lock_reason="来料待检"))
    await db.commit()

    result = await WmsOperationService(db).quick_inbound(
        factory_id="F", material_id="M-1", material_code="C-1", quantity=7,
        warehouse_id="W-1", batch_code="B-1", operator="eric", inbound_type="return")

    assert result.get("success") is True, result
    assert (await _rows(db, Inventory))[0].total_qty == 107


@pytest.mark.asyncio
async def test_unknown_document_type_is_rejected_not_silently_typed(db):
    result = await WmsOperationService(db).quick_inbound(
        factory_id="F", material_id="M-2", material_code="C-2", quantity=3,
        warehouse_id="W-1", inbound_type="随手一收")

    assert "error" in result and "流水词表" in result["error"], result
    assert await _rows(db, InventoryTransaction) == []
    assert await _rows(db, Inventory) == [], "认不出类型就不该留下半行库存"


@pytest.mark.asyncio
async def test_non_positive_quantity_is_refused(db):
    for bad in (0, -3):
        out = await WmsOperationService(db).quick_outbound(
            factory_id="F", material_id="M-1", quantity=bad, warehouse_id="W-1")
        assert "error" in out and "正整数" in out["error"], out


@pytest.mark.asyncio
async def test_reservation_skips_frozen_rows(db):
    """冻住的料不该被预留：预留了也领不走，工单会卡在"有预留却缺料"。"""
    from api.services.wms_service import InventoryService

    db.add(_inv(id="inv-locked", status="locked", lock_reason="不合格", available_qty=30,
                total_qty=30))
    db.add(_inv(id="inv-free", status="available", available_qty=20, total_qty=20))
    await db.commit()

    out = await InventoryService(db).reserve_inventory(
        factory_id="F", material_id="M-1", warehouse_id="W-1",
        quantity=15, work_order_id="WO-1")
    assert out["reserved_qty"] == 15
    frozen = next(i for i in (await _rows(db, Inventory)) if i.id == "inv-locked")
    free = next(i for i in (await _rows(db, Inventory)) if i.id == "inv-free")
    assert (frozen.reserved_qty, frozen.available_qty) == (0, 30), "冻行被占了预留"
    assert (free.reserved_qty, free.available_qty) == (15, 5)


@pytest.mark.asyncio
async def test_reservation_names_the_frozen_qty_when_it_cannot_cover(db):
    from api.services.wms_service import InventoryService

    db.add(_inv(status="locked", lock_reason="不合格", available_qty=30, total_qty=30))
    await db.commit()

    with pytest.raises(ValueError) as exc:
        await InventoryService(db).reserve_inventory(
            factory_id="F", material_id="M-1", warehouse_id="W-1",
            quantity=5, work_order_id="WO-1")
    assert "冻" in str(exc.value) and "30" in str(exc.value), str(exc.value)

