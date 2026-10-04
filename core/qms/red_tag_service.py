"""
Quality Red Tag Service
Handles the creation, management, and disposition of quality red tags (质量红单)
for defective products in the QMS module.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from database.models import QualityRedTag, QualityRedTagAttachment, DefectRecord, Inspection
from database.db_config import get_async_session


class RedTagService:
    """Service for managing quality red tags"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_red_tag(
        self,
        factory_id: str,
        defect_id: str,
        red_tag_type: str,
        defect_description: Optional[str] = None,
        nonconforming_qty: float = 0.0,
        batch_no: Optional[str] = None,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        discovered_by: Optional[str] = None,
        severity: str = "MINOR",
        created_by: Optional[str] = None
    ) -> QualityRedTag:
        """Create a new quality red tag"""
        
        # Generate red tag number: RT-YYYYMMDD-NNNN
        today = datetime.now().strftime("%Y%m%d")
        seq = await self._get_sequence_for_date(today)
        red_tag_no = f"RT-{today}-{seq:04d}"
        
        red_tag = QualityRedTag(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            red_tag_no=red_tag_no,
            defect_id=defect_id,
            red_tag_type=red_tag_type,
            defect_description=defect_description,
            nonconforming_qty=nonconforming_qty,
            batch_no=batch_no,
            work_order_id=work_order_id,
            station_id=station_id,
            discovered_by=discovered_by,
            discovered_at=datetime.now(),
            severity=severity,
            quarantine_status="SEATED",
            created_by=created_by,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self.db.add(red_tag)
        await self.db.commit()
        await self.db.refresh(red_tag)
        
        return red_tag
    
    async def get_red_tag(self, red_tag_id: str) -> Optional[Dict[str, Any]]:
        """Get red tag by ID with related defect info"""
        
        result = await self.db.execute(
            select(QualityRedTag)
            .where(
                and_(
                    QualityRedTag.id == red_tag_id,
                    QualityRedTag.is_deleted == False
                )
            )
            .options(
                selectinload(QualityRedTag.attachments)
            )
        )
        red_tag = result.scalar_one_or_none()
        
        if not red_tag:
            return None
        
        # Get defect info
        defect_result = await self.db.execute(
            select(DefectRecord).where(DefectRecord.id == red_tag.defect_id)
        )
        defect = defect_result.scalar_one_or_none()
        
        return {
            "id": red_tag.id,
            "factory_id": red_tag.factory_id,
            "red_tag_no": red_tag.red_tag_no,
            "defect_id": red_tag.defect_id,
            "inspection_id": red_tag.inspection_id,
            "red_tag_type": red_tag.red_tag_type,
            "defect_description": red_tag.defect_description,
            "nonconforming_qty": float(red_tag.nonconforming_qty),
            "batch_no": red_tag.batch_no,
            "work_order_id": red_tag.work_order_id,
            "station_id": red_tag.station_id,
            "discovered_by": red_tag.discovered_by,
            "discovered_at": red_tag.discovered_at.isoformat() if red_tag.discovered_at else None,
            "severity": red_tag.severity,
            "quarantine_status": red_tag.quarantine_status,
            "disposition": red_tag.disposition,
            "disposition_by": red_tag.disposition_by,
            "disposition_date": red_tag.disposition_date.isoformat() if red_tag.disposition_date else None,
            "disposition_notes": red_tag.disposition_notes,
            "created_at": red_tag.created_at.isoformat() if red_tag.created_at else None,
            "updated_at": red_tag.updated_at.isoformat() if red_tag.updated_at else None,
            "created_by": red_tag.created_by,
            "defect": {
                "id": defect.id,
                "defect_type": defect.defect_type,
                "severity": defect.severity,
                "description": defect.description,
                "status": defect.status
            } if defect else None,
            "attachments": [
                {
                    "id": att.id,
                    "file_id": att.file_id,
                    "attachment_type": att.attachment_type,
                    "created_at": att.created_at.isoformat() if att.created_at else None
                }
                for att in red_tag.attachments
            ]
        }
    
    async def list_red_tags(
        self,
        factory_id: str,
        limit: int = 50,
        offset: int = 0,
        red_tag_type: Optional[str] = None,
        quarantine_status: Optional[str] = None,
        disposition: Optional[str] = None,
        severity: Optional[str] = None,
        defect_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """List red tags with filtering"""
        
        query = select(QualityRedTag).where(
            and_(
                QualityRedTag.factory_id == factory_id,
                QualityRedTag.is_deleted == False
            )
        )
        
        if red_tag_type:
            query = query.where(QualityRedTag.red_tag_type == red_tag_type)
        if quarantine_status:
            query = query.where(QualityRedTag.quarantine_status == quarantine_status)
        if disposition:
            query = query.where(QualityRedTag.disposition == disposition)
        if severity:
            query = query.where(QualityRedTag.severity == severity)
        if defect_id:
            query = query.where(QualityRedTag.defect_id == defect_id)
        if date_from:
            query = query.where(QualityRedTag.created_at >= date_from)
        if date_to:
            query = query.where(QualityRedTag.created_at <= date_to)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()
        
        # Get records
        query = query.order_by(QualityRedTag.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        red_tags = result.scalars().all()
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "red_tags": [
                {
                    "id": rt.id,
                    "red_tag_no": rt.red_tag_no,
                    "defect_id": rt.defect_id,
                    "red_tag_type": rt.red_tag_type,
                    "defect_description": rt.defect_description,
                    "nonconforming_qty": float(rt.nonconforming_qty),
                    "severity": rt.severity,
                    "quarantine_status": rt.quarantine_status,
                    "disposition": rt.disposition,
                    "created_at": rt.created_at.isoformat() if rt.created_at else None
                }
                for rt in red_tags
            ]
        }
    
    async def update_red_tag(
        self,
        red_tag_id: str,
        **kwargs
    ) -> Optional[QualityRedTag]:
        """Update red tag fields"""
        
        red_tag = await self._get_red_tag_db(red_tag_id)
        if not red_tag:
            return None
        
        for key, value in kwargs.items():
            if hasattr(red_tag, key) and value is not None:
                setattr(red_tag, key, value)
        
        red_tag.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(red_tag)
        
        return red_tag
    
    async def delete_red_tag(self, red_tag_id: str) -> bool:
        """Soft delete red tag"""
        
        red_tag = await self._get_red_tag_db(red_tag_id)
        if not red_tag:
            return False
        
        red_tag.is_deleted = True
        red_tag.updated_at = datetime.now()
        await self.db.commit()
        
        return True
    
    async def submit_disposition(
        self,
        red_tag_id: str,
        disposition: str,
        disposition_by: str,
        disposition_notes: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Submit disposition for red tag"""
        
        # Validate disposition type
        valid_dispositions = ["SCRAP", "REWORK", "USE_AS_IS", "RTV", "NO_DEFECT"]
        if disposition not in valid_dispositions:
            raise ValueError(f"Invalid disposition type. Must be one of: {valid_dispositions}")
        
        red_tag = await self._get_red_tag_db(red_tag_id)
        if not red_tag:
            return None
        
        # Update quarantine status and disposition
        red_tag.quarantine_status = "RELEASED"
        red_tag.disposition = disposition
        red_tag.disposition_by = disposition_by
        red_tag.disposition_date = datetime.now()
        red_tag.disposition_notes = disposition_notes
        red_tag.updated_at = datetime.now()
        
        await self.db.commit()
        await self.db.refresh(red_tag)
        
        return await self.get_red_tag(red_tag_id)
    
    async def get_red_tags_by_defect(self, defect_id: str) -> List[Dict[str, Any]]:
        """Get all red tags for a specific defect"""
        
        result = await self.db.execute(
            select(QualityRedTag)
            .where(
                and_(
                    QualityRedTag.defect_id == defect_id,
                    QualityRedTag.is_deleted == False
                )
            )
            .order_by(QualityRedTag.created_at.desc())
        )
        red_tags = result.scalars().all()
        
        return [
            {
                "id": rt.id,
                "red_tag_no": rt.red_tag_no,
                "defect_id": rt.defect_id,
                "red_tag_type": rt.red_tag_type,
                "defect_description": rt.defect_description,
                "nonconforming_qty": float(rt.nonconforming_qty),
                "severity": rt.severity,
                "quarantine_status": rt.quarantine_status,
                "disposition": rt.disposition,
                "created_at": rt.created_at.isoformat() if rt.created_at else None
            }
            for rt in red_tags
        ]
    
    async def get_statistics(self, factory_id: str) -> Dict[str, Any]:
        """Get red tag statistics"""
        
        # Total count by status
        status_query = await self.db.execute(
            select(
                QualityRedTag.quarantine_status,
                func.count().label('count')
            )
            .where(
                and_(
                    QualityRedTag.factory_id == factory_id,
                    QualityRedTag.is_deleted == False
                )
            )
            .group_by(QualityRedTag.quarantine_status)
        )
        status_stats = {row[0]: row[1] for row in status_query.all()}
        
        # Count by disposition
        disposition_query = await self.db.execute(
            select(
                QualityRedTag.disposition,
                func.count().label('count')
            )
            .where(
                and_(
                    QualityRedTag.factory_id == factory_id,
                    QualityRedTag.is_deleted == False,
                    QualityRedTag.disposition.isnot(None)
                )
            )
            .group_by(QualityRedTag.disposition)
        )
        disposition_stats = {row[0]: row[1] for row in disposition_query.all()}
        
        # Count by type
        type_query = await self.db.execute(
            select(
                QualityRedTag.red_tag_type,
                func.count().label('count')
            )
            .where(
                and_(
                    QualityRedTag.factory_id == factory_id,
                    QualityRedTag.is_deleted == False
                )
            )
            .group_by(QualityRedTag.red_tag_type)
        )
        type_stats = {row[0]: row[1] for row in type_query.all()}
        
        # Count by severity
        severity_query = await self.db.execute(
            select(
                QualityRedTag.severity,
                func.count().label('count')
            )
            .where(
                and_(
                    QualityRedTag.factory_id == factory_id,
                    QualityRedTag.is_deleted == False
                )
            )
            .group_by(QualityRedTag.severity)
        )
        severity_stats = {row[0]: row[1] for row in severity_query.all()}
        
        return {
            "total": sum(status_stats.values()),
            "by_status": status_stats,
            "by_disposition": disposition_stats,
            "by_type": type_stats,
            "by_severity": severity_stats
        }
    
    async def _get_red_tag_db(self, red_tag_id: str) -> Optional[QualityRedTag]:
        """Get red tag from database"""
        
        result = await self.db.execute(
            select(QualityRedTag)
            .where(
                and_(
                    QualityRedTag.id == red_tag_id,
                    QualityRedTag.is_deleted == False
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def _get_sequence_for_date(self, date_str: str) -> int:
        """Get sequence number for red tag on specific date"""
        
        # Get the count of red tags created today
        result = await self.db.execute(
            select(func.count())
            .where(
                and_(
                    QualityRedTag.red_tag_no.like(f"RT-{date_str}-%"),
                    QualityRedTag.is_deleted == False
                )
            )
        )
        count = result.scalar()
        
        return count + 1
