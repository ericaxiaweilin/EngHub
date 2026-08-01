

"""
v2.5 - Data Consistency API Routes
自动对账 + Min-Max补货 + 一物一码追溯
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db

router = APIRouter(prefix="/api/v1/data-consistency", tags=["data-consistency"])


@router.get("/reconciliation/work-orders/{work_order_id}", summary="对账单个工单")
async def reconcile_work_order(work_order_id: str, db: AsyncSession = Depends(get_db)):
    """触发单个工单的自动对账"""
    from api.services.data_consistency_service import DataConsistencyService

    service = DataConsistencyService(db)
    try:
        result = await service.reconcile_work_order(work_order_id)
        return {"success": True, "status": result["status"], "reconciled": result["log"] is not None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reconciliation/batch", summary="批量对账")
async def batch_reconcile(factory_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """对所有进行中的工单执行批量对账"""
    from api.services.data_consistency_service import DataConsistencyService

    service = DataConsistencyService(db)
    try:
        results = await service.batch_reconcile_all(factory_id)
        mismatches = [r for r in results if r.get("status") == "mismatch"]
        return {
            "success": True,
            "total_checked": len(results),
            "mismatches": len(mismatches),
            "results": results,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/replenishment/pending", summary="待处理补货任务")
async def list_pending_replenishments(factory_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """查看线边仓拉动式补货任务列表"""
    from api.services.data_consistency_service import DataConsistencyService

    service = DataConsistencyService(db)
    tasks = await service.list_pending_replenishments(factory_id)
    return {"items": [
        {
            "id": t.id, "task_code": t.task_code, "material_id": t.material_id,
            "requested_qty": t.requested_qty, "fulfilled_qty": t.fulfilled_qty,
            "status": t.status, "trigger_type": t.trigger_type,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in tasks
    ], "total": len(tasks)}


@router.post("/replenishment/check", summary="检查并创建补货任务")
async def check_and_create_replenishment_tasks(db: AsyncSession = Depends(get_db)):
    """扫描所有阈值，自动创建低于水位线的补货任务"""
    from api.services.data_consistency_service import DataConsistencyService

    service = DataConsistencyService(db)
    try:
        tasks = await service.check_and_create_replenishment_tasks()
        return {"success": True, "created_tasks": len(tasks), "tasks": [
            {"id": t.id, "task_code": t.task_code, "material_id": t.material_id, "requested_qty": t.requested_qty} for t in tasks
        ]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/traceability/items", summary="按批次/工单追溯")
async def trace_by_batch(
    factory_id: str = Query(...),
    work_order_id: Optional[str] = None,
    batch_code: Optional[str] = None,
    item_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """一物一码正反向追溯链（简化版）"""
    from database.models import ItemTraceability

    stmt = select(ItemTraceability).where(ItemTraceability.factory_id == factory_id)

    if work_order_id:
        stmt = stmt.where(ItemTraceability.work_order_id == work_order_id)
    if batch_code:
        stmt = stmt.where(ItemTraceability.material_batch_id == batch_code)
    if item_code:
        stmt = stmt.where(ItemTraceability.item_code == item_code)

    items = list((await db.execute(stmt)).scalars().all())
    return {
        "items": [{
            "item_code": i.item_code, "item_type": i.item_type,
            "work_order_id": i.work_order_id, "product_id": i.product_id,
            "material_batch_id": i.material_batch_id, "station_id": i.station_id,
            "operator_id": i.operator_id, "quality_check_result": i.quality_check_result,
            "serial_number": i.serial_number, "metadata_": i.metadata_,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        } for i in items]
    }


__all__ = ["router"]


