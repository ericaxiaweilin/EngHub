"""EngFlow BOM 镜像同步 —— 源是 engflow 项目的库，不是 EngHub 本地表。

2026-10-05 核对到的事实：

- 源 = engflow-postgres / 库 `bom_intelligence` / 表 `bom_items`：481,557 行、
  473 个 `model_name`、18 层，`updated_at` 最大 2026-07-28；`part_master` 提供
  material_family / component_type。
- 本地镜像 = `enghub_bom_items`：291,398 行（19 万条深层件根本没镜像过来），
  真正的唯一键是**部分索引** `(factory_id, source_row_id) WHERE 两列均非空`。

旧实现有两处致命口径，现在都改掉了：

1. `full_sync` 先 `DELETE FROM enghub_bom_items`，再从 **本地 `bom_items`**
   （MES 那张 1,067 行的表，不是 engflow）拉数据 —— 点一次就把 29 万行镜像
   删成 1 千行。现在不删表，只做 upsert。
2. `incremental_sync` 对每一行发一条 `SELECT ... WHERE source_row_id = ?`
   判存在 —— 48 万行就是 48 万条查询。现在按唯一键 `ON CONFLICT DO UPDATE`，
   并用 `row_id` keyset 分页；旧的 `LIMIT/OFFSET` 在边删边插下会跳行漏采，
   镜像少 19 万条大概率就是这么丢的。

没配 `ENGFLOW_DATABASE_URL` 时明确失败，绝不回落到本地表装作同步成功。
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from database.models import EngHubBomItem, EngHubBomSyncLog

logger = logging.getLogger(__name__)

SOURCE_TABLE = os.getenv("ENGFLOW_BOM_SOURCE_TABLE", "bom_items")
PART_MASTER_TABLE = os.getenv("ENGFLOW_BOM_PART_MASTER_TABLE", "part_master")
BATCH_SIZE = max(100, int(os.getenv("BOM_SYNC_BATCH", "5000")))
# asyncpg 单条语句最多 32,767 个绑定参数：二十几列 × 5,000 行会直接爆，
# 所以 executemany 的块大小按"实际写多少列"反推，而不是跟拉取块一样大。
MIRROR_FACTORY_ID = os.getenv("ENGFLOW_BOM_FACTORY_ID", "FAC_MECH_001")
EPOCH = datetime(2000, 1, 1)

# 表名可以从 env 切换（历史上并存过 bom_item / bom_items），但必须过白名单再拼 SQL
_ALLOWED_TABLES = {"bom_items", "bom_item", "part_master"}


class BomSyncNotConfigured(RuntimeError):
    """没配 engflow 源库连接 —— 这是配置缺失，不是"没有新数据"，必须报出来。"""


def _table_or_die(name: str) -> str:
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"不允许的 BOM 源表名 {name!r}")
    return name


# 镜像里会被覆盖更新的列（factory_id + source_row_id 是冲突键，不参与 SET）
_MUTABLE = (
    "product_model", "part_number", "description", "level", "quantity", "unit",
    "unit_price", "total_cost", "vendor_code", "vendor_name", "parent_part",
    "category_l1", "category_l2", "material_family", "component_type",
    "synced_at", "source_updated_at",
    "source_file", "original_row_number", "l2_parent_group", "l3_context",
)

# executemany 的块大小按"实际写多少列"反推：asyncpg 单条语句上限 32,767 个绑定参数
UPSERT_KEY_COLUMNS = ("source_row_id", "factory_id") + _MUTABLE
UPSERT_CHUNK_ROWS = max(50, 30000 // len(UPSERT_KEY_COLUMNS))


class BomSyncService:
    """把 engflow 的 BOM 镜像进本地 `enghub_bom_items`：只增改，不删表。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._source_engine = None

    # ── 源连接 ────────────────────────────────────────────────────────
    @property
    def source_configured(self) -> bool:
        return bool(os.getenv("ENGFLOW_DATABASE_URL", "").strip())

    def _source(self):
        if self._source_engine is None:
            url = os.getenv("ENGFLOW_DATABASE_URL", "").strip()
            if not url:
                raise BomSyncNotConfigured(
                    "未配置 ENGFLOW_DATABASE_URL：BOM 源在 engflow 项目，"
                    "不能拿 EngHub 本地 bom_items 当源（那是另一套 1,067 行的数据）"
                )
            self._source_engine = create_async_engine(
                url, pool_size=2, max_overflow=0, pool_pre_ping=True
            )
        return self._source_engine

    async def _fetch_page(
        self,
        after_row_id: int,
        limit: int,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """按 row_id keyset 分页拉源表；since 只用于增量水位线过滤。"""
        bom = _table_or_die(SOURCE_TABLE)
        pm = _table_or_die(PART_MASTER_TABLE)
        updated_filter = "AND bi.updated_at > :since" if since else ""
        sql = text(f"""
            SELECT
                bi.row_id, bi.model_name, bi.part_number, bi.description, bi.level,
                bi.quantity, bi.unit, bi.unit_price, bi.total_cost, bi.vendor_code,
                bi.vendor_name, bi.parent_sap, bi.category_l1, bi.category_l2,
                bi.source_file, bi.original_row_number, bi.l2_parent_group, bi.l3_context,
                pm.material_family, pm.component_type, bi.updated_at
            FROM {bom} bi
            LEFT JOIN {pm} pm
                ON pm.part_number = bi.part_number AND pm.company_id = bi.company_id
            WHERE bi.row_id > :after {updated_filter}
            ORDER BY bi.row_id
            LIMIT :limit
        """)
        params: Dict[str, Any] = {"after": after_row_id, "limit": limit}
        if since:
            params["since"] = since
        async with self._source().connect() as conn:
            rows = (await conn.execute(sql, params)).mappings().all()
        return [dict(r) for r in rows]

    async def _source_summary(self) -> Dict[str, Any]:
        async with self._source().connect() as conn:
            row = (await conn.execute(text(f"""
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE level = 1) AS level1,
                       count(DISTINCT model_name) AS models,
                       max(updated_at) AS max_updated_at
                FROM {_table_or_die(SOURCE_TABLE)}
            """))).mappings().first()
        return dict(row or {})

    # ── 镜像写入 ──────────────────────────────────────────────────────
    async def _upsert_page(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = datetime.utcnow()
        values = [{
            "source_row_id": r["row_id"],
            "factory_id": MIRROR_FACTORY_ID,
            "product_model": r["model_name"],
            "part_number": r["part_number"],
            "description": r["description"],
            "level": r["level"],
            "quantity": r["quantity"],
            "unit": r["unit"],
            "unit_price": r["unit_price"],
            "total_cost": r["total_cost"],
            "vendor_code": r["vendor_code"],
            "vendor_name": r["vendor_name"],
            "parent_part": r["parent_sap"],
            "source_file": r.get("source_file"),
            "original_row_number": r.get("original_row_number"),
            "l2_parent_group": r.get("l2_parent_group"),
            "l3_context": r.get("l3_context"),
            "category_l1": r["category_l1"],
            "category_l2": r["category_l2"],
            "material_family": r["material_family"],
            "component_type": r["component_type"],
            "synced_at": now,
            "source_updated_at": r["updated_at"],
        } for r in rows]

        # 用 bindparam + executemany：一次 5,000 行内联进 SQL 会超 asyncpg 的参数上限
        key_cols = ["source_row_id", "factory_id", *_MUTABLE]
        stmt = pg_insert(EngHubBomItem).values(
            {col: bindparam(col) for col in key_cols}
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["factory_id", "source_row_id"],
            # 唯一键是部分索引：冲突目标必须带同样的 WHERE，否则 Postgres 报错
            index_where=text("factory_id IS NOT NULL AND source_row_id IS NOT NULL"),
            set_={col: stmt.excluded[col] for col in _MUTABLE},
        )
        for i in range(0, len(values), UPSERT_CHUNK_ROWS):
            await self.db.execute(stmt, values[i:i + UPSERT_CHUNK_ROWS])
        return len(values)

    async def _mirror_summary(self) -> Dict[str, Any]:
        row = (await self.db.execute(text("""
            SELECT count(*) AS mirrored,
                   count(*) FILTER (WHERE level = 1) AS level1,
                   count(DISTINCT product_model) AS models,
                   max(synced_at) AS last_synced_at
            FROM enghub_bom_items WHERE factory_id = :fid
        """), {"fid": MIRROR_FACTORY_ID})).mappings().first()
        return dict(row or {})

    async def _last_watermark(self) -> datetime:
        log = (await self.db.execute(
            select(EngHubBomSyncLog)
            .where(EngHubBomSyncLog.status == "success")
            .order_by(EngHubBomSyncLog.finished_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        return (log.watermark or EPOCH) if log else EPOCH

    # ── 同步入口 ──────────────────────────────────────────────────────
    async def sync(self, mode: str = "incremental") -> Dict[str, Any]:
        if mode not in ("full", "incremental"):
            raise ValueError(f"未知同步模式 {mode!r}（只支持 full/incremental）")
        if not self.source_configured:
            raise BomSyncNotConfigured(
                "未配置 ENGFLOW_DATABASE_URL，跳过 BOM 同步：拿本地表当源会把镜像写歪"
            )

        watermark = EPOCH if mode == "full" else await self._last_watermark()
        log = EngHubBomSyncLog(
            sync_type=mode,
            status="running",
            started_at=datetime.utcnow(),
            watermark=watermark,
            factory_id=MIRROR_FACTORY_ID,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        try:
            src = await self._source_summary()
            since = None if mode == "full" else watermark
            after_row_id = 0
            pulled = written = 0
            max_updated = watermark

            while True:
                rows = await self._fetch_page(after_row_id, BATCH_SIZE, since=since)
                if not rows:
                    break
                after_row_id = max(int(r["row_id"]) for r in rows)
                written += await self._upsert_page(rows)
                pulled += len(rows)
                for r in rows:
                    if r["updated_at"] and r["updated_at"] > max_updated:
                        max_updated = r["updated_at"]
                await self.db.commit()
                if pulled % 25000 < BATCH_SIZE:
                    logger.info(f"[bom-sync] {mode} 已处理 {pulled} 行（源 {src.get('total')} 行）")
                if len(rows) < BATCH_SIZE:
                    break

            mirrored = await self._mirror_summary()
            log.status = "success"
            log.records_synced = written
            log.watermark = max_updated
            log.finished_at = datetime.utcnow()
            await self.db.commit()
            logger.info(
                f"[bom-sync] {mode} 完成：源 {src.get('total')} 行 / 镜像 {mirrored.get('mirrored')} 行，"
                f"本次写 {written} 行，水位线 {max_updated}"
            )
            return {
                "status": "success",
                "mode": mode,
                "factory_id": MIRROR_FACTORY_ID,
                "source": src,
                "mirror": mirrored,
                "rows_pulled": pulled,
                "rows_upserted": written,
                "watermark": max_updated.isoformat() if max_updated else None,
                "coverage_pct": round(
                    100.0 * int(mirrored.get("mirrored") or 0)
                    / max(1, int(src.get("total") or 1)), 1
                ),
            }
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            log.status = "failed"
            log.error_message = str(exc)[:500]
            log.finished_at = datetime.utcnow()
            await self.db.commit()
            logger.error(f"[bom-sync] {mode} 失败: {exc}")
            return {"status": "failed", "mode": mode, "error": str(exc)}

    async def full_sync(self) -> dict:
        return await self.sync("full")

    async def incremental_sync(self) -> dict:
        return await self.sync("incremental")

    async def get_sync_status(self) -> list:
        logs = (await self.db.execute(
            select(EngHubBomSyncLog).order_by(EngHubBomSyncLog.started_at.desc()).limit(10)
        )).scalars().all()
        out = [
            {
                "id": log.id,
                "sync_type": log.sync_type,
                "status": log.status,
                "records_synced": log.records_synced,
                "watermark": log.watermark.isoformat() if log.watermark else None,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                "error_message": log.error_message,
            }
            for log in logs
        ]
        mirror = await self._mirror_summary() if self.source_configured else {}
        out.append({
            "mirror_summary": mirror,
            "source_configured": self.source_configured,
            "source_table": SOURCE_TABLE,
            "factory_id": MIRROR_FACTORY_ID,
        })
        return out
