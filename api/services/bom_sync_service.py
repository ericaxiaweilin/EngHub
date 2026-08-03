"""
BOM Sync Service - 从 EngFlow bom_intelligence 同步到 EngHub 本地缓存表
支持按工厂隔离：EngFlow 全量 BOM 仅同步至机械厂 FAC_MECH_001
"""
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from database.models import EngHubBomItem, EngHubBomSyncLog

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000
MECH_FACTORY_ID = "FAC_MECH_001"
DEFAULT_ENGFLOW_COMPANY = "jvn_enterprise"
DEFAULT_ENGFLOW_BOM_URL = os.getenv(
    "ENGFLOW_BOM_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@engflow-postgres:5432/bom_intelligence",
)


class BomSyncService:
    """BOM 数据同步服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def full_sync(
        self,
        factory_id: str = MECH_FACTORY_ID,
        company_id: str = DEFAULT_ENGFLOW_COMPANY,
    ) -> dict:
        """全量同步：默认从 EngFlow 拉取至机械厂。"""
        if factory_id != MECH_FACTORY_ID:
            return {
                "status": "failed",
                "error": f"EngFlow BOM 仅允许同步至机械厂 {MECH_FACTORY_ID}",
            }
        return await self.sync_from_engflow(
            factory_id=factory_id,
            company_id=company_id,
            sync_type="full",
        )

    async def incremental_sync(
        self,
        factory_id: str = MECH_FACTORY_ID,
        company_id: str = DEFAULT_ENGFLOW_COMPANY,
    ) -> dict:
        """增量同步：基于水位线从 EngFlow 拉取变更。"""
        if factory_id != MECH_FACTORY_ID:
            return {
                "status": "failed",
                "error": f"EngFlow BOM 仅允许同步至机械厂 {MECH_FACTORY_ID}",
            }
        return await self.sync_from_engflow(
            factory_id=factory_id,
            company_id=company_id,
            sync_type="incremental",
        )

    async def sync_from_engflow(
        self,
        *,
        factory_id: str = MECH_FACTORY_ID,
        company_id: str = DEFAULT_ENGFLOW_COMPANY,
        sync_type: str = "full",
    ) -> dict:
        """从 EngFlow PostgreSQL 同步 BOM 到指定工厂（仅机械厂）。"""
        source_url = os.getenv("ENGFLOW_BOM_DATABASE_URL", DEFAULT_ENGFLOW_BOM_URL)
        source_engine = create_async_engine(source_url, pool_pre_ping=True)
        SourceSession = async_sessionmaker(source_engine, expire_on_commit=False)

        watermark = datetime(2000, 1, 1)
        if sync_type == "incremental":
            watermark = await self._last_watermark(factory_id, company_id)

        sync_log = EngHubBomSyncLog(
            factory_id=factory_id,
            source_company_id=company_id,
            sync_type=sync_type,
            status="running",
            started_at=datetime.utcnow(),
            watermark=watermark,
        )
        self.db.add(sync_log)
        await self.db.commit()
        await self.db.refresh(sync_log)

        try:
            if sync_type == "full":
                await self.db.execute(
                    text("DELETE FROM enghub_bom_items WHERE factory_id = :fid"),
                    {"fid": factory_id},
                )
                await self.db.commit()

            total_synced = 0
            max_updated_at = watermark
            offset = 0

            while True:
                async with SourceSession() as source_db:
                    rows = await self._fetch_engflow_batch(
                        source_db,
                        company_id=company_id,
                        offset=offset,
                        limit=BATCH_SIZE,
                        after=watermark if sync_type == "incremental" else None,
                    )
                if not rows:
                    break

                if sync_type == "incremental":
                    for row in rows:
                        await self._upsert_item(factory_id, row)
                else:
                    items = [self._row_to_item(factory_id, row) for row in rows]
                    self.db.add_all(items)

                await self.db.commit()
                total_synced += len(rows)
                offset += BATCH_SIZE

                for row in rows:
                    updated_at = row.get("updated_at")
                    if updated_at and updated_at > max_updated_at:
                        max_updated_at = updated_at

                logger.info(
                    "BOM engflow sync progress factory=%s synced=%s",
                    factory_id,
                    total_synced,
                )

            sync_log.status = "success"
            sync_log.records_synced = total_synced
            sync_log.watermark = max_updated_at
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()

            return {
                "status": "success",
                "factory_id": factory_id,
                "source_company_id": company_id,
                "records_synced": total_synced,
                "watermark": str(max_updated_at),
            }

        except Exception as e:
            await self.db.rollback()
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()
            logger.error("BOM engflow sync failed: %s", e)
            return {"status": "failed", "error": str(e)}
        finally:
            await source_engine.dispose()

    async def get_sync_status(self, factory_id: Optional[str] = None) -> list:
        """获取最近的同步记录"""
        query = select(EngHubBomSyncLog).order_by(EngHubBomSyncLog.started_at.desc()).limit(10)
        if factory_id:
            query = (
                select(EngHubBomSyncLog)
                .where(EngHubBomSyncLog.factory_id == factory_id)
                .order_by(EngHubBomSyncLog.started_at.desc())
                .limit(10)
            )
        result = await self.db.execute(query)
        logs = result.scalars().all()
        return [
            {
                "id": log.id,
                "factory_id": log.factory_id,
                "source_company_id": log.source_company_id,
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

    async def _last_watermark(self, factory_id: str, company_id: str) -> datetime:
        result = await self.db.execute(
            select(EngHubBomSyncLog)
            .where(
                EngHubBomSyncLog.status == "success",
                EngHubBomSyncLog.factory_id == factory_id,
                EngHubBomSyncLog.source_company_id == company_id,
            )
            .order_by(EngHubBomSyncLog.finished_at.desc())
            .limit(1)
        )
        last_log = result.scalar_one_or_none()
        return last_log.watermark if last_log and last_log.watermark else datetime(2000, 1, 1)

    async def _fetch_engflow_batch(
        self,
        source_db: AsyncSession,
        *,
        company_id: str,
        offset: int,
        limit: int,
        after: Optional[datetime] = None,
    ) -> list:
        where_parts = ["bi.company_id = :company_id"]
        params: dict = {"company_id": company_id, "limit": limit, "offset": offset}
        if after:
            where_parts.append("bi.updated_at > :after")
            params["after"] = after
        where_clause = " AND ".join(where_parts)

        sql = f"""
            SELECT
                bi.row_id,
                bi.model_name,
                bi.part_number,
                bi.description,
                bi.level,
                bi.quantity,
                bi.unit,
                bi.unit_price,
                bi.total_cost,
                bi.vendor_code,
                bi.vendor_name,
                bi.parent_sap,
                bi.category_l1,
                bi.category_l2,
                pm.material_family,
                pm.component_type,
                bi.updated_at
            FROM bom_items bi
            LEFT JOIN part_master pm
                ON pm.part_number = bi.part_number
                AND pm.company_id = bi.company_id
            WHERE {where_clause}
            ORDER BY bi.row_id
            LIMIT :limit OFFSET :offset
        """
        result = await source_db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    def _row_to_item(self, factory_id: str, row: dict) -> EngHubBomItem:
        return EngHubBomItem(
            factory_id=factory_id,
            source_row_id=row["row_id"],
            product_model=row["model_name"],
            part_number=row["part_number"],
            description=row["description"],
            level=row["level"],
            quantity=row["quantity"],
            unit=row["unit"],
            unit_price=row["unit_price"],
            total_cost=row["total_cost"],
            vendor_code=row["vendor_code"],
            vendor_name=row["vendor_name"],
            parent_part=row["parent_sap"],
            category_l1=row["category_l1"],
            category_l2=row["category_l2"],
            material_family=row["material_family"],
            component_type=row["component_type"],
            synced_at=datetime.utcnow(),
            source_updated_at=row["updated_at"],
        )

    async def _upsert_item(self, factory_id: str, row: dict) -> None:
        existing = await self.db.execute(
            select(EngHubBomItem).where(
                EngHubBomItem.factory_id == factory_id,
                EngHubBomItem.source_row_id == row["row_id"],
            )
        )
        item = existing.scalar_one_or_none()
        if item:
            item.product_model = row["model_name"]
            item.part_number = row["part_number"]
            item.description = row["description"]
            item.level = row["level"]
            item.quantity = row["quantity"]
            item.unit_price = row["unit_price"]
            item.total_cost = row["total_cost"]
            item.vendor_code = row["vendor_code"]
            item.vendor_name = row["vendor_name"]
            item.parent_part = row["parent_sap"]
            item.category_l1 = row["category_l1"]
            item.category_l2 = row["category_l2"]
            item.material_family = row["material_family"]
            item.component_type = row["component_type"]
            item.synced_at = datetime.utcnow()
            item.source_updated_at = row["updated_at"]
        else:
            self.db.add(self._row_to_item(factory_id, row))
