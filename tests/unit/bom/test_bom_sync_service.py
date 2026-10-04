"""BOM 镜像同步的口径回归：源必须是 engflow，写必须是分块 upsert。

线上事故口径（2026-10-05）：旧 full_sync 先 `DELETE FROM enghub_bom_items`
再从 **本地** `bom_items`（MES 那 1,067 行）拉数据 —— 点一次就把 29 万行镜像
删成 1 千行。这里钉住"没配源就绝不本地兜底"和"不被 asyncpg 参数上限打断"。
"""

from unittest.mock import AsyncMock, MagicMock

import asyncio

import pytest

pytestmark = [pytest.mark.unit]

from api.services import bom_sync_service as bss
from api.services.bom_sync_service import BomSyncNotConfigured, BomSyncService


def test_missing_source_dsn_fails_loudly_and_reads_nothing(monkeypatch):
    monkeypatch.delenv("ENGFLOW_DATABASE_URL", raising=False)
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    svc = BomSyncService(db)

    svc._source_engine = object()  # 只有配了 DSN 才会被用到
    assert svc.source_configured is False
    with pytest.raises(BomSyncNotConfigured):
        asyncio.run(svc.sync("full"))
    # 失败必须发生在任何本地查询之前：旧实现正是败在这里偷读本地表
    db.execute.assert_not_called()


def test_upsert_chunk_stays_under_asyncpg_argument_limit():
    cols = 2 + len(bss._MUTABLE)
    assert bss.UPSERT_CHUNK_ROWS * cols <= 32767, "分块过大会让整批同步直接报错"


@pytest.mark.asyncio
async def test_upsert_page_splits_into_chunks_not_one_giant_statement():
    db = MagicMock()
    db.execute = AsyncMock()
    svc = BomSyncService(db)
    rows = [{
        "row_id": i, "model_name": "A-30-04-F", "part_number": f"P{i}",
        "description": None, "level": 1, "quantity": 1.0, "unit": "PCS",
        "unit_price": None, "total_cost": None, "vendor_code": None,
        "vendor_name": None, "parent_sap": None, "category_l1": None,
        "category_l2": None, "material_family": None, "component_type": None,
        "updated_at": None,
    } for i in range(bss.UPSERT_CHUNK_ROWS * 2 + 5)]

    written = await svc._upsert_page(rows)

    assert written == len(rows)
    assert db.execute.await_count == 3, "应当按块切成 3 次 executemany"
    for call in db.execute.await_args_list:
        assert len(call.args[1]) <= bss.UPSERT_CHUNK_ROWS


@pytest.mark.asyncio
async def test_source_query_is_paged_by_keyset_not_offset(monkeypatch):
    """OFFSET 分页在边写边读时会跳行 —— 镜像少 19 万条就是这么丢的。"""
    monkeypatch.setenv("ENGFLOW_DATABASE_URL", "postgresql+asyncpg://x:y@h:5432/db")
    captured = {}

    class _Conn:
        async def execute(self, sql, params=None):
            captured["sql"] = str(sql)
            captured["params"] = params
            r = MagicMock()
            r.mappings.return_value.all.return_value = []
            return r

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    svc = BomSyncService(MagicMock())
    svc._source_engine = _Engine()
    await svc._fetch_page(after_row_id=12345, limit=5000)

    assert "bi.row_id > :after" in captured["sql"]
    assert "OFFSET" not in captured["sql"].upper()
    assert captured["params"]["after"] == 12345
