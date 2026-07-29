"""
BOM Sync Service - 从 EngFlow bom_items 同步到 EngHub 本地缓存表
支持全量同步和增量同步（基于 updated_at 水位线）
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EngHubBomItem, EngHubBomSyncLog

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


class BomSyncService:
    """BOM 数据同步服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def full_sync(self) -> dict:
        """全量同步：从 bom_items LEFT JOIN part_master 拉取全部数据"""
        sync_log = EngHubBomSyncLog(
            sync_type="full",
            status="running",
            started_at=datetime.utcnow(),
        )
        self.db.add(sync_log)
        await self.db.commit()
        await self.db.refresh(sync_log)

        try:
            # 清空本地缓存
            await self.db.execute(text("DELETE FROM enghub_bom_items"))
            await self.db.commit()

            total_synced = 0
            max_updated_at = None
            offset = 0

            while True:
                rows = await self._fetch_source_batch(offset, BATCH_SIZE)
                if not rows:
                    break

                items = []
                for row in rows:
                    item = EngHubBomItem(
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
                    items.append(item)
                    if row["updated_at"] and (max_updated_at is None or row["updated_at"] > max_updated_at):
                        max_updated_at = row["updated_at"]

                self.db.add_all(items)
                await self.db.commit()
                total_synced += len(items)
                offset += BATCH_SIZE
                logger.info(f"BOM full_sync progress: {total_synced} records")

            # 更新同步日志
            sync_log.status = "success"
            sync_log.records_synced = total_synced
            sync_log.watermark = max_updated_at
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()

            return {"status": "success", "records_synced": total_synced, "watermark": str(max_updated_at)}

        except Exception as e:
            await self.db.rollback()
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()
            logger.error(f"BOM full_sync failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def incremental_sync(self) -> dict:
        """增量同步：只拉取 watermark 之后变更的记录"""
        # 获取上次水位线
        result = await self.db.execute(
            select(EngHubBomSyncLog)
            .where(EngHubBomSyncLog.status == "success")
            .order_by(EngHubBomSyncLog.finished_at.desc())
            .limit(1)
        )
        last_log = result.scalar_one_or_none()
        watermark = last_log.watermark if last_log and last_log.watermark else datetime(2000, 1, 1)

        sync_log = EngHubBomSyncLog(
            sync_type="incremental",
            status="running",
            started_at=datetime.utcnow(),
            watermark=watermark,
        )
        self.db.add(sync_log)
        await self.db.commit()
        await self.db.refresh(sync_log)

        try:
            total_synced = 0
            max_updated_at = watermark
            offset = 0

            while True:
                rows = await self._fetch_source_batch(offset, BATCH_SIZE, after=watermark)
                if not rows:
                    break

                for row in rows:
                    # UPSERT: 按 source_row_id 查找已有记录
                    existing = await self.db.execute(
                        select(EngHubBomItem).where(EngHubBomItem.source_row_id == row["row_id"])
                    )
                    item = existing.scalar_one_or_none()

                    if item:
                        item.part_number = row["part_number"]
                        item.description = row["description"]
                        item.level = row["level"]
                        item.quantity = row["quantity"]
                        item.unit_price = row["unit_price"]
                        item.total_cost = row["total_cost"]
                        item.vendor_code = row["vendor_code"]
                        item.vendor_name = row["vendor_name"]
                        item.category_l1 = row["category_l1"]
                        item.category_l2 = row["category_l2"]
                        item.material_family = row["material_family"]
                        item.component_type = row["component_type"]
                        item.synced_at = datetime.utcnow()
                        item.source_updated_at = row["updated_at"]
                    else:
                        item = EngHubBomItem(
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
                        self.db.add(item)

                    if row["updated_at"] and row["updated_at"] > max_updated_at:
                        max_updated_at = row["updated_at"]

                await self.db.commit()
                total_synced += len(rows)
                offset += BATCH_SIZE

            sync_log.status = "success"
            sync_log.records_synced = total_synced
            sync_log.watermark = max_updated_at
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()

            return {"status": "success", "records_synced": total_synced, "watermark": str(max_updated_at)}

        except Exception as e:
            await self.db.rollback()
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            sync_log.finished_at = datetime.utcnow()
            await self.db.commit()
            logger.error(f"BOM incremental_sync failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def get_sync_status(self) -> list:
        """获取最近的同步记录"""
        result = await self.db.execute(
            select(EngHubBomSyncLog).order_by(EngHubBomSyncLog.started_at.desc()).limit(10)
        )
        logs = result.scalars().all()
        return [
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

    async def _fetch_source_batch(self, offset: int, limit: int, after: Optional[datetime] = None) -> list:
        """从源表 bom_items LEFT JOIN part_master 拉取一批数据"""
        where_clause = ""
        if after:
            where_clause = f"WHERE bi.updated_at > '{after.isoformat()}'"

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
            {where_clause}
            ORDER BY bi.row_id
            LIMIT :limit OFFSET :offset
        """
        result = await self.db.execute(text(sql), {"limit": limit, "offset": offset})
        rows = result.mappings().all()
        return [dict(r) for r in rows]
