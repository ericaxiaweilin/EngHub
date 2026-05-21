"""
Database persistence helpers for Sim-ERP audit records.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.sim_erp.models import AuditRecord
from database.models import SimERPAuditLog


class SimERPAuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_audit_log(self, record: AuditRecord) -> SimERPAuditLog:
        snapshot = record.snapshot.model_dump(mode="json")
        plugin_records = [item.model_dump(mode="json") for item in record.plugin_records]
        arbiter_result = record.arbiter_result.model_dump(mode="json")

        entity = SimERPAuditLog(
            simulation_id=record.simulation_id,
            worker_ref=record.snapshot.worker_ref,
            shift_id=record.snapshot.shift_id,
            task_type=record.snapshot.task_type,
            zone_id=record.snapshot.zone_id,
            final_status=record.arbiter_result.final_status,
            legal_blocked=record.arbiter_result.legal_blocked,
            total_cost_delta=record.arbiter_result.total_cost_delta,
            max_required_break_minutes=record.arbiter_result.max_required_break_minutes,
            total_penalty_score=record.arbiter_result.total_penalty_score,
            simulation_input_hash=record.simulation_input_hash,
            physics_core_version=record.physics_core_version,
            plugin_manifest_hash=record.plugin_manifest_hash,
            legislation_pack_hash=record.legislation_pack_hash,
            arbiter_version=record.arbiter_version,
            optimizer_version=record.optimizer_version,
            snapshot_payload=snapshot,
            plugin_records_payload=plugin_records,
            arbiter_result_payload=arbiter_result,
            created_at=record.created_at,
        )
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def get_latest_audit_log(self) -> Optional[SimERPAuditLog]:
        result = await self.db.execute(
            select(SimERPAuditLog).order_by(SimERPAuditLog.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_audit_log_by_simulation_id(self, simulation_id: str) -> Optional[SimERPAuditLog]:
        result = await self.db.execute(
            select(SimERPAuditLog).where(SimERPAuditLog.simulation_id == simulation_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_audit_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        worker_ref: Optional[str] = None,
        final_status: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
    ) -> tuple[List[SimERPAuditLog], int]:
        query = select(SimERPAuditLog)

        if worker_ref:
            query = query.where(SimERPAuditLog.worker_ref == worker_ref)
        if final_status:
            query = query.where(SimERPAuditLog.final_status == final_status)
        if created_from:
            query = query.where(SimERPAuditLog.created_at >= created_from)
        if created_to:
            query = query.where(SimERPAuditLog.created_at <= created_to)

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query)

        offset = (page - 1) * page_size
        query = query.order_by(SimERPAuditLog.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        return list(result.scalars().all()), int(total or 0)
