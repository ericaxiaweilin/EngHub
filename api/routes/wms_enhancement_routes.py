"""WMS 全量增强 API 路由。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_enhancement_service import WmsEnhancementService
from api.services.stock_alert_service import StockAlertService
from core.auth.security import get_current_user
from database.db_config import get_db
from database.models import User

router = APIRouter(prefix="/api/v1/wms/enhancement", tags=["wms-enhancement"])


class BatchExpiryRequest(BaseModel):
    expiry_date: Optional[date] = None
    production_date: Optional[date] = None
    shelf_life_days: Optional[int] = None


class LockRequest(BaseModel):
    reason: str


class Location3DRequest(BaseModel):
    row_num: Optional[int] = None
    col_num: Optional[int] = None
    level_num: Optional[int] = None
    capacity: Optional[int] = None
    occupancy_status: Optional[str] = None


class BarcodeGenerateRequest(BaseModel):
    factory_id: str
    material_id: str
    material_code: str
    batch_code: Optional[str] = None
    barcode_type: str = "CODE128"


class BarcodeScanInboundRequest(BaseModel):
    factory_id: str
    barcode: str
    quantity: int
    warehouse_id: str
    location_id: Optional[str] = None


class RfidTagRequest(BaseModel):
    factory_id: str
    tag_id: str
    material_code: str
    material_id: Optional[str] = None
    inventory_id: Optional[str] = None
    batch_code: Optional[str] = None


class RfidCountStartRequest(BaseModel):
    factory_id: str
    warehouse_id: Optional[str] = None


class RfidScanSubmitRequest(BaseModel):
    tag_ids: List[str]


class AutomationDispatchRequest(BaseModel):
    factory_id: str
    job_type: str
    material_code: Optional[str] = None
    quantity: Optional[int] = None
    source_location: Optional[str] = None
    target_location: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class PoolCreateRequest(BaseModel):
    factory_id: str
    pool_code: str
    pool_name: str
    material_id: str
    material_code: str
    warehouse_ids: List[str]


class TransferRequestCreate(BaseModel):
    factory_id: str
    material_id: str
    material_code: str
    quantity: int
    from_warehouse_id: str
    to_warehouse_id: str
    material_name: Optional[str] = None
    to_location_id: Optional[str] = None
    remark: Optional[str] = None
    submit: bool = True


class TransferRejectRequest(BaseModel):
    reason: str


class FreezeRequest(BaseModel):
    reason_code: str
    reason_text: Optional[str] = None
    freeze_until: Optional[datetime] = None
    auto_unfreeze: bool = False


# ---------- 1. 批次 ----------
@router.put("/batch/{inventory_id}/expiry")
async def set_batch_expiry(
    inventory_id: str,
    body: BatchExpiryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.set_batch_expiry(
        inventory_id,
        expiry_date=body.expiry_date,
        production_date=body.production_date,
        shelf_life_days=body.shelf_life_days,
    )


@router.post("/batch/{inventory_id}/lock")
async def lock_batch(
    inventory_id: str,
    body: LockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.lock_batch(inventory_id, reason=body.reason, operator=current_user.username)


@router.post("/batch/{inventory_id}/unlock")
async def unlock_batch(
    inventory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.unlock_batch(inventory_id, operator=current_user.username)


@router.get("/batch/expiring")
async def expiring_batches(
    factory_id: str,
    within_days: int = Query(30, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.list_expiring_batches(factory_id, within_days)


# ---------- 2. 库位 ----------
@router.put("/locations/{location_id}")
async def update_location(
    location_id: str,
    body: Location3DRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.update_location_3d(
        location_id,
        row_num=body.row_num,
        col_num=body.col_num,
        level_num=body.level_num,
        capacity=body.capacity,
        occupancy_status=body.occupancy_status,
    )


@router.get("/locations")
async def list_locations(
    warehouse_id: str,
    occupancy_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.list_locations_enhanced(warehouse_id, occupancy_status)


@router.post("/locations/sync-occupancy")
async def sync_occupancy(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.sync_location_occupancy(warehouse_id)


# ---------- 3. 预警（触发全量检查含过期/慢销） ----------
@router.post("/alerts/run-full-check")
async def run_full_alert_check(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = StockAlertService(db)
    return await svc.run_alert_check(factory_id)


# ---------- 4. 报表 ----------
@router.get("/reports/turnover")
async def turnover_report(
    factory_id: str,
    days: int = Query(90, ge=7),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.inventory_turnover_report(factory_id, days)


@router.post("/reports/abc")
async def abc_report(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.abc_classification_report(factory_id)


@router.get("/reports/cost")
async def cost_report(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.inventory_cost_report(factory_id)


# ---------- 5. 条码 / RFID ----------
@router.post("/barcode/generate")
async def generate_barcode(
    body: BarcodeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.generate_barcode(
        body.factory_id, body.material_id, body.material_code,
        batch_code=body.batch_code, barcode_type=body.barcode_type,
    )


@router.post("/barcode/scan-inbound")
async def scan_inbound(
    body: BarcodeScanInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.scan_barcode_inbound(
        body.factory_id, body.barcode, body.quantity, body.warehouse_id,
        location_id=body.location_id, operator=current_user.username,
    )


@router.post("/rfid/tags")
async def register_rfid(
    body: RfidTagRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.register_rfid_tag(
        body.factory_id, body.tag_id, body.material_code,
        material_id=body.material_id, inventory_id=body.inventory_id, batch_code=body.batch_code,
    )


@router.post("/rfid/count/start")
async def start_rfid_count(
    body: RfidCountStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.start_rfid_count(
        body.factory_id, body.warehouse_id, created_by=current_user.username,
    )


@router.post("/rfid/count/{session_id}/scan")
async def submit_rfid_scan(
    session_id: str,
    body: RfidScanSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.submit_rfid_scans(session_id, body.tag_ids)


# ---------- 6. 自动化 ----------
@router.post("/automation/dispatch")
async def dispatch_automation(
    body: AutomationDispatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.dispatch_automation_job(
        body.factory_id, body.job_type,
        material_code=body.material_code, quantity=body.quantity,
        source_location=body.source_location, target_location=body.target_location,
        payload=body.payload, created_by=current_user.username,
    )


@router.get("/automation/jobs")
async def list_automation_jobs(
    factory_id: str,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.list_automation_jobs(factory_id, job_type, status)


@router.post("/automation/jobs/{job_id}/complete")
async def complete_automation_job(
    job_id: str,
    success: bool = True,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.complete_automation_job(job_id, success=success, error=error)


# ---------- 7. 多仓 ----------
@router.post("/pools")
async def create_pool(
    body: PoolCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.create_inventory_pool(
        body.factory_id, body.pool_code, body.pool_name,
        body.material_id, body.material_code, body.warehouse_ids,
    )


@router.get("/pools")
async def list_pools(
    factory_id: str,
    material_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.get_shared_inventory(factory_id, material_code)


@router.get("/trace/cross-warehouse")
async def cross_warehouse_trace(
    factory_id: str,
    material_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.cross_warehouse_trace(factory_id, material_code)


# ---------- 8. 调拨审批 ----------
@router.post("/transfers")
async def create_transfer(
    body: TransferRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.create_transfer_request(
        body.factory_id, body.material_id, body.material_code, body.quantity,
        body.from_warehouse_id, body.to_warehouse_id,
        material_name=body.material_name, to_location_id=body.to_location_id,
        requested_by=current_user.username, remark=body.remark, submit=body.submit,
    )


@router.get("/transfers")
async def list_transfers(
    factory_id: str,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.list_transfer_requests(factory_id, status)


@router.post("/transfers/{request_id}/approve")
async def approve_transfer(
    request_id: str,
    execute: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.approve_transfer_request(
        request_id, approved_by=current_user.username, execute=execute,
    )


@router.post("/transfers/{request_id}/reject")
async def reject_transfer(
    request_id: str,
    body: TransferRejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.reject_transfer_request(
        request_id, rejected_by=current_user.username, reason=body.reason,
    )


# ---------- 9. 冻结 ----------
@router.post("/freeze/{inventory_id}")
async def freeze_inventory(
    inventory_id: str,
    body: FreezeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.freeze_inventory(
        inventory_id,
        reason_code=body.reason_code,
        reason_text=body.reason_text,
        freeze_until=body.freeze_until,
        auto_unfreeze=body.auto_unfreeze,
        frozen_by=current_user.username,
    )


@router.post("/freeze/{freeze_id}/release")
async def unfreeze(
    freeze_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.unfreeze_inventory(freeze_id, unfrozen_by=current_user.username)


@router.get("/freeze")
async def list_freezes(
    factory_id: str,
    status: str = "active",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.list_freezes(factory_id, status)


@router.post("/freeze/auto-unfreeze")
async def auto_unfreeze(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.run_auto_unfreeze(factory_id)


# ---------- 10. 盘点差异 ----------
@router.get("/variance/analysis")
async def variance_analysis(
    factory_id: str,
    task_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.variance_analysis(factory_id, task_id)


@router.post("/variance/cycle-count/{task_id}/submit")
async def submit_cycle_variance(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.submit_cycle_count_for_approval(task_id)


@router.post("/variance/cycle-count/{task_id}/approve")
async def approve_cycle_variance(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = WmsEnhancementService(db)
    return await svc.approve_cycle_count_variance(task_id, approved_by=current_user.username)


__all__ = ["router"]
