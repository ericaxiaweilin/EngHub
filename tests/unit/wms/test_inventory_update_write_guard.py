"""库存更新接口不能绕过冻结：PUT/PATCH 不许改数量，也不许碰锁。

为什么单开一个文件（2026-10-11 审计）：
  · `update_inventory_full`（PUT）已经挡了数量三字段 —— 那半有人修过；
    但**没有挡 `status`**。而 `status` 就是冻结字段：写入原语
    `movements.frozen_stock_error` 认的是它（`FROZEN_STATUS = "locked"`）。
    所以 `PUT {"status": "available"}` 能把一行冻着的货当场放行，
    绕过 `/wms/freeze/release`（那条要 reason_code、要落名）。
  · `update_inventory_partial`（PATCH）连数量的守卫都没有 —— 整扇门是开的。
  · 反方向同样要挡：`status='locked'` 若能由这里写进去，就出现"锁了没记"的行
    （`wms_freezes.sync_check` 专门对这本账），冻结记录表里查无此锁。

两个方向都验（只验"会拦"就会把正常改元数据一起拦死）。
这里用内存 SQLite 真跑服务调用，不是 grep 源码。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from api.services.wms_service import InventoryService
from database.models import Inventory

TABLES = [Inventory.__table__]


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


async def _row(db):
    return (await db.execute(select(Inventory))).scalars().first()


@pytest.mark.asyncio
async def test_patch_cannot_write_quantity_directly(db):
    """PATCH 写数量 = 没有流水、没有操作人、也不认冻结 —— 这扇门必须关掉。"""
    db.add(_inv(status="available"))
    await db.commit()

    result = await InventoryService(db).update_inventory_partial(
        inventory_id="inv-1", updates={"available_qty": 999}, updated_by="eric")

    assert result.get("success") is False, f"PATCH 居然直接改了数量：{result}"
    inv = await _row(db)
    assert inv.available_qty == 100, f"被拒的更新却把数量改了：{inv.available_qty}"


@pytest.mark.asyncio
async def test_patch_cannot_release_a_freeze(db):
    """把 locked 改成 available 就是放行 —— 而放行必须走 /wms/freeze/release。"""
    db.add(_inv(status="locked", lock_reason="来料待检"))
    await db.commit()

    result = await InventoryService(db).update_inventory_partial(
        inventory_id="inv-1", updates={"status": "available"}, updated_by="eric")

    assert result.get("success") is False, f"一次 PATCH 就把冻结放了：{result}"
    inv = await _row(db)
    assert (inv.status or "").lower() == "locked", f"冻结被解开了：{inv.status}"


@pytest.mark.asyncio
async def test_patch_cannot_set_the_lock(db):
    """反方向也要挡：从这儿写进 locked 会造出"锁了没记"的行。"""
    db.add(_inv(status="available"))
    await db.commit()

    result = await InventoryService(db).update_inventory_partial(
        inventory_id="inv-1", updates={"status": "locked"}, updated_by="eric")

    assert result.get("success") is False, f"绕过 /wms/freeze 就把行锁上了：{result}"
    inv = await _row(db)
    assert (inv.status or "").lower() != "locked", f"行被锁上但没有冻结记录：{inv.status}"


@pytest.mark.asyncio
async def test_put_cannot_release_a_freeze(db):
    db.add(_inv(status="locked", lock_reason="来料待检"))
    await db.commit()

    result = await InventoryService(db).update_inventory_full(
        inventory_id="inv-1", data={"status": "available"}, updated_by="eric")

    assert result.get("success") is False, f"PUT 把冻结放了：{result}"
    inv = await _row(db)
    assert (inv.status or "").lower() == "locked", f"冻结被解开了：{inv.status}"


@pytest.mark.asyncio
async def test_put_cannot_set_the_lock(db):
    db.add(_inv(status="available"))
    await db.commit()

    result = await InventoryService(db).update_inventory_full(
        inventory_id="inv-1", data={"status": "locked"}, updated_by="eric")

    assert result.get("success") is False, f"PUT 绕过 /wms/freeze 锁了行：{result}"
    inv = await _row(db)
    assert (inv.status or "").lower() != "locked", f"锁了没记：{inv.status}"


@pytest.mark.asyncio
async def test_put_cannot_write_quantity(db):
    """PUT 那半已有守卫，这里钉住别回退。"""
    db.add(_inv(status="available"))
    await db.commit()

    result = await InventoryService(db).update_inventory_full(
        inventory_id="inv-1", data={"total_qty": 999}, updated_by="eric")

    assert result.get("success") is False, f"PUT 直接改了数量：{result}"
    inv = await _row(db)
    assert inv.total_qty == 100, f"被拒的更新却改了数量：{inv.total_qty}"


@pytest.mark.asyncio
async def test_benign_metadata_update_still_works(db):
    """正向对照：改库位/批次/单价这类元数据不能被一起拦死。"""
    db.add(_inv(status="available", location_id=None, unit_cost=None))
    await db.commit()

    result = await InventoryService(db).update_inventory_partial(
        inventory_id="inv-1", updates={"location_id": "LOC-9", "batch_code": "B-9"},
        updated_by="eric")

    assert result.get("success") is True, f"正常改元数据被拦了：{result}"
    inv = await _row(db)
    assert inv.location_id == "LOC-9", inv.location_id
    assert inv.batch_code == "B-9", inv.batch_code


@pytest.mark.asyncio
async def test_non_lock_status_still_updates(db):
    """正向对照：status 里非锁的取值（active/available/shortage）照常能改。

    冻结上线的常见翻车是"顺手把 status 整个封掉"，把正常状态流转一起锁死。
    """
    db.add(_inv(status="active"))
    await db.commit()

    result = await InventoryService(db).update_inventory_partial(
        inventory_id="inv-1", updates={"status": "shortage"}, updated_by="eric")

    assert result.get("success") is True, f"非锁状态被误拦：{result}"
    inv = await _row(db)
    assert inv.status == "shortage", inv.status
