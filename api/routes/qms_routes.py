"""
QMS API Routes
检验管理、不良品管理 — 真实 DB 查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User, QualityInspection, DefectRecord

router = APIRouter(prefix="/api/v1", tags=["qms"])


# --- Inspection Endpoints ---


@router.get("/inspections")
async def list_inspections(
    factory_id: str,
    inspection_type: Optional[str] = None,
    status: Optional[str] = None,
    work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取检验单列表"""
    query = select(QualityInspection).where(QualityInspection.factory_id == factory_id)

    if inspection_type:
        query = query.where(QualityInspection.inspect_type == inspection_type.upper())
    if status:
        query = query.where(QualityInspection.result == status.upper())
    if work_order_id:
        query = query.where(QualityInspection.work_order_id == work_order_id)

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页
    query = query.order_by(QualityInspection.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    return {
        "items": [
            {
                "id": r.id,
                "inspection_code": f"INS-{r.inspect_type}-{r.id[:8]}",
                "inspection_type": r.inspect_type.lower(),
                "work_order_id": r.work_order_id,
                "routing_step_id": r.routing_step_id,
                "inspector_id": r.inspector_id,
                "sample_size": r.sample_qty,
                "batch_size": r.sample_qty,
                "defect_qty": r.defect_qty,
                "good_qty": r.sample_qty - r.defect_qty,
                "status": r.result.lower(),
                "overall_result": r.result,
                "defect_details": r.defect_details,
                "remark": r.remark,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取检验单详情"""
    r = await db.get(QualityInspection, inspection_id)
    if not r:
        raise HTTPException(status_code=404, detail="检验单不存在")
    return {
        "id": r.id,
        "inspection_code": f"INS-{r.inspect_type}-{r.id[:8]}",
        "inspection_type": r.inspect_type.lower(),
        "factory_id": r.factory_id,
        "work_order_id": r.work_order_id,
        "routing_step_id": r.routing_step_id,
        "inspector_id": r.inspector_id,
        "sample_size": r.sample_qty,
        "batch_size": r.sample_qty,
        "defect_qty": r.defect_qty,
        "good_qty": r.sample_qty - r.defect_qty,
        "status": r.result.lower(),
        "overall_result": r.result,
        "defect_details": r.defect_details,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# --- Defect Endpoints ---


class DispositionSubmit(BaseModel):
    disposition: str  # rework, repair, scrap, concession, return
    disposition_qty: Optional[int] = None
    remark: Optional[str] = None


@router.get("/defects")
async def list_defects(
    factory_id: str,
    status: Optional[str] = None,
    defect_type: Optional[str] = None,
    severity: Optional[str] = None,
    work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取不良品列表"""
    query = select(DefectRecord).where(DefectRecord.factory_id == factory_id)

    if defect_type:
        query = query.where(DefectRecord.defect_type == defect_type)
    if severity:
        query = query.where(DefectRecord.severity == severity)
    if work_order_id:
        query = query.where(DefectRecord.work_order_id == work_order_id)
    if status:
        # status 映射: open=未处置, resolved=已处置
        if status == "open":
            query = query.where(DefectRecord.disposition.is_(None))
        elif status == "resolved":
            query = query.where(DefectRecord.disposition.isnot(None))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(DefectRecord.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    return {
        "items": [_serialize_defect(r) for r in rows],
        "total": total,
    }


@router.get("/defects/statistics")
async def get_defect_statistics(
    factory_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """不良品统计"""
    query = select(DefectRecord).where(DefectRecord.factory_id == factory_id)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    by_type: dict = {}
    by_station: dict = {}
    total_qty = 0
    for r in rows:
        total_qty += r.quantity
        by_type[r.defect_type] = by_type.get(r.defect_type, 0) + r.quantity
        sid = r.station_id or "unknown"
        by_station[sid] = by_station.get(sid, 0) + r.quantity

    return {
        "total_defects": len(rows),
        "total_defect_qty": total_qty,
        "by_type": by_type,
        "by_station": by_station,
    }


@router.get("/defects/{defect_id}")
async def get_defect(
    defect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取不良品详情"""
    r = await db.get(DefectRecord, defect_id)
    if not r:
        raise HTTPException(status_code=404, detail="不良品记录不存在")
    return _serialize_defect(r)


@router.post("/defects/{defect_id}/disposition")
async def submit_disposition(
    defect_id: str,
    disposition: DispositionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交处置方案"""
    r = await db.get(DefectRecord, defect_id)
    if not r:
        raise HTTPException(status_code=404, detail="不良品记录不存在")

    r.disposition = disposition.disposition
    r.disposition_by = current_user.username if current_user else "system"
    r.disposition_at = datetime.utcnow()
    r.disposition_remark = disposition.remark
    r.is_finalized = True
    r.updated_at = datetime.utcnow()
    await db.commit()

    return _serialize_defect(r)


@router.post("/defects/{defect_id}/process")
async def process_defect(
    defect_id: str,
    disposition: DispositionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """处理不良品（兼容前端 process 接口）"""
    return await submit_disposition(defect_id, disposition, db, current_user)


def _serialize_defect(r: DefectRecord) -> dict:
    """序列化缺陷记录，字段对齐前端 Defect 接口"""
    return {
        "id": r.id,
        "defect_code": r.record_code,
        "record_code": r.record_code,
        "factory_id": r.factory_id,
        "work_order_id": r.work_order_id,
        "production_report_id": r.production_report_id,
        "product_id": r.product_id,
        "station_id": r.station_id,
        "equipment_id": r.equipment_id,
        "defect_type": r.defect_type,
        "severity": r.severity,
        "quantity": r.quantity,
        "defect_qty": r.quantity,
        "disposition": r.disposition,
        "disposition_by": r.disposition_by,
        "disposition_at": r.disposition_at.isoformat() if r.disposition_at else None,
        "disposition_remark": r.disposition_remark,
        "ocap_status": r.ocap_status,
        "description": r.description,
        "status": "resolved" if r.disposition else "open",
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


__all__ = ["router"]
