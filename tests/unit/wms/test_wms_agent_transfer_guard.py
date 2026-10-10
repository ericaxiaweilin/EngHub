"""智能体调拨（TransferExecutor）也必须过同一扇门：冻住的行不许被调走。

10-10 由能力矩阵那条"库存写入是否只走一扇门"点名出来：这个 executor 自己
`src.total_qty -= q`，再手写两条 transaction_type='transfer' 的流水（遗留字面量、
没有单据号），所以质量冻结对它完全不成立 —— 智能体能把待检料搬到别的仓。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from api.services.wms_architecture.executors.transfer_executor import TransferExecutor
from database.models import Inventory, InventoryTransaction

DDL = """
CREATE TABLE wms_transfer_requests (
  id TEXT PRIMARY KEY, factory_id TEXT, request_code TEXT, material_id TEXT,
  material_code TEXT, material_name TEXT, quantity INTEGER,
  from_warehouse_id TEXT, to_warehouse_id TEXT, to_location_id TEXT,
  status TEXT, requested_by TEXT, approved_by TEXT, approved_at TEXT,
  completed_at TEXT, remark TEXT, created_at TEXT, updated_at TEXT
)
"""


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in (Inventory.__table__, InventoryTransaction.__table__):
            await conn.execute(CreateTable(table))
        await conn.execute(text(DDL))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _inv(**kw):
    base = dict(id="src", material_id="M-1", material_code="C-1", material_name="軸承",
                factory_id="F", warehouse_id="W-1", batch_code="B-1",
                total_qty=50, available_qty=50, reserved_qty=0, unit="pcs",
                status="available", created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 1))
    base.update(kw)
    return Inventory(**base)


async def _rows(db, model):
    from sqlalchemy import select
    return list((await db.execute(select(model))).scalars().all())


def _ctx(qty=10):
    return {"factory_id": "F", "material_id": "M-1", "quantity": qty,
            "from_warehouse_id": "W-1", "to_warehouse_id": "W-2", "operator": "agent"}


@pytest.mark.asyncio
async def test_agent_transfer_refuses_frozen_source(db):
    db.add(_inv(status="locked", lock_reason="事故封存"))
    await db.commit()

    out = await TransferExecutor().execute(db, "F", _ctx())

    assert out.get("error") is True, out
    assert "冻结" in out["message"], out
    src = (await _rows(db, Inventory))[0]
    assert (src.total_qty, src.available_qty) == (50, 50), "失败也要改掉数量就是脏账"
    assert await _rows(db, InventoryTransaction) == []


@pytest.mark.asyncio
async def test_agent_transfer_lands_a_paired_anchored_ledger(db):
    db.add(_inv())
    await db.commit()

    out = await TransferExecutor().execute(db, "F", _ctx(10))

    assert out.get("success") is True, out
    code = out["transfer_request_code"]
    assert code and out["after_src"] == 40 and out["after_dst"] == 10, out
    txns = await _rows(db, InventoryTransaction)
    assert sorted(t.transaction_type for t in txns) == ["transfer_in", "transfer_out"], \
        [t.transaction_type for t in txns]
    # 两条流水必须是同一张单、都是正数量 —— 否则证明不了这是同一次搬移
    assert {t.reference_doc_no for t in txns} == {code}
    assert {t.reference_type for t in txns} == {"transfer_request"}
    assert all(int(t.quantity) == 10 for t in txns), [t.quantity for t in txns]
    rows = await _rows(db, Inventory)
    assert {r.warehouse_id: r.total_qty for r in rows} == {"W-1": 40, "W-2": 10}


@pytest.mark.asyncio
async def test_agent_transfer_creates_destination_row_without_precounting(db):
    """目标行建出来时数量是 0 —— 数量只由原语写一次，不能建行写一遍、流水再补一遍。"""
    db.add(_inv())
    await db.commit()

    out = await TransferExecutor().execute(db, "F", _ctx(8))
    assert out.get("success") is True, out
    dst = next(r for r in await _rows(db, Inventory) if r.warehouse_id == "W-2")
    assert (dst.total_qty, dst.available_qty) == (8, 8)
    assert dst.batch_code == "B-1", "搬移要带着批次过去，不然 FIFO 断了"
