"""
MES API Routes
工单管理、生产报工、工艺路线、工位管理、设备管理
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.db_config import get_db
from database.models import User, Product
from api.services.work_order_service import WorkOrderService, WOStatus, WoPermissionError
from api.services.mes_services import (
    ProductionReportService,
    StationService,
    RoutingService,
    EquipmentService,
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1", tags=["mes"])


# --- Request/Response Models ---

class WorkOrderCreate(BaseModel):
    factory_id: str
    product_id: str
    planned_qty: int
    planned_due: str
    priority: str = "medium"
    station_id: Optional[str] = None
    bom_version: Optional[str] = None
    remark: Optional[str] = None


class WorkOrderUpdate(BaseModel):
    planned_qty: Optional[int] = None
    planned_due: Optional[str] = None
    priority: Optional[str] = None
    station_id: Optional[str] = None
    remark: Optional[str] = None


class WorkOrderSplit(BaseModel):
    split_qty: int
    remark: Optional[str] = None


class WorkOrderAction(BaseModel):
    reason: Optional[str] = None


class ProductionReportCreate(BaseModel):
    factory_id: str
    work_order_id: str
    station_id: str
    good_qty: int
    defect_qty: int = 0
    report_type: str = "normal"
    shift: str = "day"
    operator_id: Optional[str] = None
    remark: Optional[str] = None


class ProductionReportComment(BaseModel):
    comment: str


class StationCreate(BaseModel):
    factory_id: str
    station_code: str
    station_name: str
    station_type: str
    capacity_per_hour: int
    workshop_id: Optional[str] = None


class RoutingCreate(BaseModel):
    factory_id: str
    product_id: str
    version: str = "v1"
    steps: List[dict]


# ============================================================
# Work Order Endpoints
# ============================================================

@router.post("/work-orders", status_code=201)
async def create_work_order(
    wo: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工单（草稿状态）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.create_work_order(
            factory_id=wo.factory_id,
            product_id=wo.product_id,
            planned_qty=wo.planned_qty,
            planned_due=datetime.fromisoformat(wo.planned_due.replace('Z', '+00:00')),
            priority=wo.priority,
            assigned_station_id=wo.station_id,
            bom_version=wo.bom_version,
            remark=wo.remark,
            created_by=current_user.username,
        )
        return service.to_dict(work_order)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/work-orders")
async def list_work_orders(
    factory_id: str,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    priority: Optional[str] = None,
    station_id: Optional[str] = None,
    wo_type: Optional[str] = Query("master", description="工单层级：master=主工单 / operation=工序工单 / all=全部"),
    parent_work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单列表（含进度信息）。默认只返回主工单，传 wo_type=all 含工序工单。"""
    service = WorkOrderService(db)
    skip = (page - 1) * page_size
    work_orders = await service.list_work_orders(
        factory_id=factory_id,
        status=status,
        product_id=product_id,
        priority=priority,
        station_id=station_id,
        wo_type=wo_type,
        parent_work_order_id=parent_work_order_id,
        skip=skip,
        limit=page_size,
    )
    total = len(work_orders)

    items = []
    for wo in work_orders:
        d = service.to_dict(wo)
        progress = await service.get_progress(wo)
        d.update(progress)
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/work-orders/stats")
async def get_work_order_stats(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单统计卡片数据"""
    service = WorkOrderService(db)
    return await service.get_stats(factory_id)


@router.get("/work-orders/{work_order_id}")
async def get_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单详情"""
    service = WorkOrderService(db)
    work_order = await service.get_work_order_by_id(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    reports = []
    if hasattr(work_order, 'production_reports') and work_order.production_reports:
        reports = [
            {
                "id": str(r.id), "report_code": r.report_code,
                "work_order_id": str(r.work_order_id) if r.work_order_id else None,
                "station_id": r.station_id, "good_qty": r.good_qty,
                "defect_qty": r.defect_qty, "scrap_qty": r.scrap_qty,
                "report_type": r.report_type, "shift": r.shift,
                "operator_id": r.operator_id, "remark": r.remark,
                "is_modified": r.is_modified,
                "modified_at": r.modified_at.isoformat() if r.modified_at else None,
                "modified_by": r.modified_by,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in work_order.production_reports
        ]

    result = service.to_dict(work_order)
    result["production_reports"] = reports
    result["progress"] = await service.get_progress(work_order)
    return result


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str,
    wo: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新工单"""
    service = WorkOrderService(db)
    try:
        work_order = await service.update_work_order(
            work_order_id=work_order_id,
            planned_qty=wo.planned_qty,
            planned_due=datetime.fromisoformat(wo.planned_due.replace('Z', '+00:00')) if wo.planned_due else None,
            priority=wo.priority,
            assigned_station_id=wo.station_id,
            remark=wo.remark,
        )
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/release")
async def release_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """待下发 → 已下达（审核门槛：管理角色 + 创建人不能下达自己的工单）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.release_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/start")
async def start_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """已下达 → 生产中（父子约束：已拆分的主工单由子工单分别开工）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.start_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/pause")
async def pause_work_order(
    work_order_id: str,
    data: WorkOrderAction = WorkOrderAction(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中 → 暂停"""
    service = WorkOrderService(db)
    try:
        work_order = await service.pause_work_order(work_order_id, data.reason or "", user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/resume")
async def resume_work_order(
    work_order_id: str,
    data: WorkOrderAction = WorkOrderAction(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停 → 生产中"""
    service = WorkOrderService(db)
    try:
        work_order = await service.resume_work_order(work_order_id, data.reason or "", user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/pending-inbound")
async def mark_pending_inbound(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中 → 待入库"""
    service = WorkOrderService(db)
    try:
        work_order = await service.mark_pending_inbound(work_order_id, user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/complete")
async def complete_work_order(
    work_order_id: str,
    completed_qty: Optional[int] = None,
    good_qty: Optional[int] = None,
    defect_qty: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中/待入库 → 已完成（审核门槛：品质角色 + 实际产出 + 子工单全部完工）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.complete_work_order(
            work_order_id, completed_qty, good_qty, defect_qty, user=current_user
        )
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/close")
async def close_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """已完成 → 已关闭（审核门槛：厂长 / 管理员）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.close_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/cancel")
async def cancel_work_order(
    work_order_id: str,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消工单"""
    service = WorkOrderService(db)
    try:
        work_order = await service.cancel_work_order(work_order_id, reason, user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/split")
async def split_work_order(
    work_order_id: str,
    data: WorkOrderSplit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """拆分工单"""
    service = WorkOrderService(db)
    try:
        original_wo, new_wo = await service.split_work_order(
            work_order_id=work_order_id,
            split_qty=data.split_qty,
            remark=data.remark,
            created_by=current_user.username,
            user=current_user,
        )
        return {
            "original_work_order": service.to_dict(original_wo),
            "new_work_order": service.to_dict(new_wo),
            "split_qty": data.split_qty,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/work-orders/{work_order_id}/status-logs")
async def get_work_order_status_logs(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """状态操作日志（审核追溯：谁/什么角色/何时/做了什么）"""
    service = WorkOrderService(db)
    logs = await service.get_status_logs(work_order_id)
    return {"items": logs, "total": len(logs)}


@router.get("/work-orders/{work_order_id}/children")
async def get_work_order_children(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """子工单列表（含进度，主工单详情页使用）"""
    service = WorkOrderService(db)
    children = await service.get_children_detail(work_order_id)
    return {"items": children, "total": len(children)}


# ============================================================
# Production Report Endpoints
# ============================================================

@router.get("/production-reports")
async def list_production_reports(
    factory_id: str,
    work_order_id: Optional[str] = None,
    station_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取生产报工列表（看板/报工页使用）"""
    service = ProductionReportService(db)
    skip = max(page - 1, 0) * page_size
    reports = await service.list_reports(
        factory_id=factory_id,
        work_order_id=work_order_id,
        station_id=station_id,
        skip=skip,
        limit=page_size,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "report_code": r.report_code,
                "factory_id": r.factory_id,
                "work_order_id": str(r.work_order_id) if r.work_order_id else None,
                "station_id": r.station_id,
                "good_qty": r.good_qty,
                "defect_qty": r.defect_qty,
                "scrap_qty": r.scrap_qty,
                "report_type": r.report_type,
                "shift": r.shift,
                "operator_id": r.operator_id,
                "remark": r.remark,
                "is_modified": r.is_modified,
                "modified_at": r.modified_at.isoformat() if r.modified_at else None,
                "modified_by": r.modified_by,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "total": len(reports),
    }


@router.post("/production-reports")
async def create_production_report(
    report: ProductionReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建生产报工"""
    service = ProductionReportService(db)
    try:
        production_report = await service.create_report(
            factory_id=report.factory_id,
            work_order_id=report.work_order_id,
            station_id=report.station_id,
            good_qty=report.good_qty,
            defect_qty=report.defect_qty,
            scrap_qty=0,
            report_type=report.report_type,
            shift=report.shift,
            operator_id=report.operator_id,
            remark=report.remark,
            created_by=current_user.username,
        )
        return {
            "id": production_report.id,
            "report_code": production_report.report_code,
            "status": "submitted",
            "created_at": production_report.created_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Station Endpoints ---

@router.post("/stations")
async def create_station(
    station: StationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工位"""
    service = StationService(db)
    try:
        result = await service.create_station(
            factory_id=station.factory_id,
            station_code=station.station_code,
            station_name=station.station_name,
            station_type=station.station_type,
            capacity_per_hour=station.capacity_per_hour,
            workshop_id=station.workshop_id,
            created_by=current_user.username,
        )
        return {"id": str(result.id), "station_code": result.station_code, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stations")
async def list_stations(
    factory_id: str,
    station_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工位列表"""
    service = StationService(db)
    stations = await service.list_stations(factory_id=factory_id, station_type=station_type)
    return {
        "items": [
            {
                "id": str(s.id), "station_code": s.station_code,
                "station_name": s.station_name, "factory_id": s.factory_id,
                "station_type": s.station_type, "capacity_per_hour": s.capacity_per_hour,
                "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in stations
        ],
        "total": len(stations),
    }


@router.get("/stations/{station_id}")
async def get_station(station_id: str, db: AsyncSession = Depends(get_db)):
    """获取工位详情"""
    service = StationService(db)
    station = await service.get_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return {
        "id": str(station.id), "station_code": station.station_code,
        "station_name": station.station_name, "factory_id": station.factory_id,
        "station_type": station.station_type, "capacity_per_hour": station.capacity_per_hour,
        "status": station.status,
    }


# --- Routing Endpoints ---

@router.post("/routings")
async def create_routing(
    routing: RoutingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工艺路线"""
    service = RoutingService(db)
    try:
        result = await service.create_routing(
            factory_id=routing.factory_id,
            product_id=routing.product_id,
            version=routing.version,
            steps=routing.steps,
            created_by=current_user.username,
        )
        return {"id": str(result.id), "routing_code": result.routing_code, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/routings")
async def list_routings(
    factory_id: str,
    product_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工艺路线列表"""
    service = RoutingService(db)
    routings = await service.list_routings(factory_id=factory_id, product_id=product_id)
    return {
        "items": [
            {
                "id": str(r.id), "routing_code": r.routing_code,
                "factory_id": r.factory_id, "product_id": r.product_id,
                "version": r.version, "is_active": r.is_active,
                "steps": r.steps,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in routings
        ],
        "total": len(routings),
    }


@router.get("/routings/{routing_id}")
async def get_routing(
    routing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工艺路线详情（含工序步骤，供工单详情追溯当前工序）"""
    service = RoutingService(db)
    routing = await service.get_routing_by_id(routing_id)
    if not routing:
        raise HTTPException(status_code=404, detail="工艺路线不存在")
    return {
        "id": str(routing.id), "routing_code": routing.routing_code,
        "factory_id": routing.factory_id, "product_id": routing.product_id,
        "version": routing.version, "is_active": routing.is_active,
        "steps": routing.steps,
        "created_by": routing.created_by,
        "created_at": routing.created_at.isoformat() if routing.created_at else None,
        "updated_at": routing.updated_at.isoformat() if routing.updated_at else None,
    }


# --- Equipment Endpoints ---

@router.get("/equipment")
async def list_equipment(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取设备列表"""
    service = EquipmentService(db)
    equipment_list = await service.list_equipment(factory_id=factory_id)
    return {
        "items": [
            {
                "id": str(e.id), "equipment_code": e.equipment_code,
                "equipment_name": e.equipment_name, "factory_id": e.factory_id,
                "equipment_type": e.equipment_type, "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in equipment_list
        ],
        "total": len(equipment_list),
    }


# --- Product Endpoints ---

@router.get("/products")
async def list_products(
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取产品列表（供各页面把 product_id 解析为可读的产品编码/名称）。
    factory_id 可选：不传则返回全部产品，避免跨厂区引用的产品解析不到。"""
    query = select(Product)
    if factory_id:
        query = query.where(Product.factory_id == factory_id)
    query = query.order_by(Product.created_at.desc())
    result = await db.execute(query)
    products = list(result.scalars().all())
    return {
        "items": [
            {
                "id": str(p.id), "product_code": p.product_code,
                "product_name": p.product_name, "factory_id": p.factory_id,
                "category": p.category, "unit": p.unit, "status": p.status,
                "current_bom_version": p.current_bom_version,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in products
        ],
        "total": len(products),
    }


__all__ = ["router"]
