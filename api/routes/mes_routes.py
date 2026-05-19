"""
MES API Routes
工单管理、生产报工、工艺路线、工位管理、设备管理
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from api.services.work_order_service import WorkOrderService
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


# --- Work Order Endpoints ---

@router.post("/work-orders")
async def create_work_order(
    wo: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建工单"""
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
        
        return {
            "id": work_order.id,
            "work_order_code": work_order.work_order_code,
            "status": work_order.status,
            "created_at": work_order.created_at.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/work-orders")
async def list_work_orders(
    factory_id: str,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工单列表"""
    service = WorkOrderService(db)
    
    skip = (page - 1) * page_size
    work_orders = await service.list_work_orders(
        factory_id=factory_id,
        status=status,
        product_id=product_id,
        skip=skip,
        limit=page_size
    )
    
    total = len(work_orders)
    
    return {
        "items": [
            {
                "id": wo.id,
                "work_order_code": wo.work_order_code,
                "status": wo.status,
                "product_id": wo.product_id,
                "planned_qty": wo.planned_qty,
                "completed_qty": wo.completed_qty,
                "created_at": wo.created_at.isoformat()
            }
            for wo in work_orders
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/work-orders/{work_order_id}")
async def get_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工单详情"""
    service = WorkOrderService(db)
    work_order = await service.get_work_order_by_id(work_order_id)
    
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    return {
        "id": work_order.id,
        "work_order_code": work_order.work_order_code,
        "status": work_order.status,
        "product_id": work_order.product_id,
        "planned_qty": work_order.planned_qty,
        "completed_qty": work_order.completed_qty,
        "good_qty": work_order.good_qty,
        "defect_qty": work_order.defect_qty,
        "priority": work_order.priority,
        "planned_due": work_order.planned_due.isoformat() if work_order.planned_due else None,
        "created_at": work_order.created_at.isoformat()
    }


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str,
    wo: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
        
        return {
            "id": work_order.id,
            "status": work_order.status,
            "warning": None
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/release")
async def release_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """下达工单"""
    service = WorkOrderService(db)
    
    try:
        work_order = await service.release_work_order(work_order_id)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return {"status": work_order.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/start")
async def start_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """开始工单"""
    service = WorkOrderService(db)
    
    try:
        work_order = await service.start_work_order(work_order_id)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return {"status": work_order.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/complete")
async def complete_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """完成工单"""
    service = WorkOrderService(db)
    
    try:
        work_order = await service.complete_work_order(work_order_id)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return {"status": work_order.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/cancel")
async def cancel_work_order(
    work_order_id: str,
    reason: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """取消工单"""
    service = WorkOrderService(db)
    
    try:
        work_order = await service.cancel_work_order(work_order_id, reason)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return {"status": work_order.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/split")
async def split_work_order(
    work_order_id: str,
    data: WorkOrderSplit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    拆分工单
    
    规则:
    - 只能拆分 draft/pending 状态的工单
    - 拆分数量 >= 计划数的 50%
    """
    service = WorkOrderService(db)
    
    try:
        original_wo, new_wo = await service.split_work_order(
            work_order_id=work_order_id,
            split_qty=data.split_qty,
            remark=data.remark,
            created_by=current_user.username,
        )
        
        return {
            "original_work_order_id": original_wo.id,
            "new_work_order_id": new_wo.id,
            "split_qty": data.split_qty
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Production Report Endpoints ---

@router.post("/production-reports")
async def create_production_report(
    report: ProductionReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
            "created_at": production_report.created_at.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/production-reports")
async def list_production_reports(
    factory_id: str,
    work_order_id: Optional[str] = None,
    station_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取报工列表"""
    service = ProductionReportService(db)
    
    skip = (page - 1) * page_size
    reports = await service.list_reports(
        factory_id=factory_id,
        work_order_id=work_order_id,
        station_id=station_id,
        skip=skip,
        limit=page_size
    )
    
    total = len(reports)
    
    return {
        "items": [
            {
                "id": r.id,
                "report_code": r.report_code,
                "work_order_id": str(r.work_order_id),
                "station_id": r.station_id,
                "good_qty": r.good_qty,
                "defect_qty": r.defect_qty,
                "scrap_qty": r.scrap_qty,
                "shift": r.shift,
                "created_at": r.created_at.isoformat()
            }
            for r in reports
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/production-reports/{report_id}")
async def get_production_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取报工详情"""
    service = ProductionReportService(db)
    report = await service.get_report_by_id(report_id)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {
        "id": report.id,
        "report_code": report.report_code,
        "work_order_id": str(report.work_order_id),
        "station_id": report.station_id,
        "good_qty": report.good_qty,
        "defect_qty": report.defect_qty,
        "scrap_qty": report.scrap_qty,
        "report_type": report.report_type,
        "shift": report.shift,
        "operator_id": report.operator_id,
        "remark": report.remark,
        "is_modified": report.is_modified,
        "comments": [
            {"comment": c.comment, "created_by": c.created_by, "created_at": c.created_at.isoformat()}
            for c in report.comments
        ],
        "created_at": report.created_at.isoformat()
    }


@router.post("/production-reports/{report_id}/comment")
async def add_production_report_comment(
    report_id: str,
    data: ProductionReportComment,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """添加报工评论"""
    service = ProductionReportService(db)
    
    comment = await service.add_comment(
        report_id=report_id,
        comment=data.comment,
        created_by=current_user.username,
    )
    
    return {
        "id": comment.id,
        "comment": comment.comment,
        "created_at": comment.created_at.isoformat()
    }


@router.patch("/production-reports/{report_id}")
async def modify_production_report(
    report_id: str,
    good_qty: Optional[int] = None,
    defect_qty: Optional[int] = None,
    remark: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """修改报工"""
    service = ProductionReportService(db)
    
    report = await service.modify_report(
        report_id=report_id,
        good_qty=good_qty,
        defect_qty=defect_qty,
        remark=remark,
        modified_by=current_user.username,
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {
        "id": report.id,
        "is_modified": report.is_modified,
        "modified_at": report.modified_at.isoformat() if report.modified_at else None
    }


# --- Station Endpoints ---

@router.post("/stations")
async def create_station(
    station: StationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建工位"""
    service = StationService(db)
    
    try:
        new_station = await service.create_station(
            factory_id=station.factory_id,
            station_code=station.station_code,
            station_name=station.station_name,
            station_type=station.station_type,
            capacity_per_hour=station.capacity_per_hour,
            workshop_id=station.workshop_id,
            created_by=current_user.username,
        )
        
        return {
            "id": new_station.id,
            "station_code": new_station.station_code,
            "status": "active"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stations")
async def list_stations(
    factory_id: str,
    station_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工位列表"""
    service = StationService(db)
    
    skip = (page - 1) * page_size
    stations = await service.list_stations(
        factory_id=factory_id,
        station_type=station_type,
        status=status,
        skip=skip,
        limit=page_size
    )
    
    total = len(stations)
    
    return {
        "items": [
            {
                "id": s.id,
                "station_code": s.station_code,
                "station_name": s.station_name,
                "station_type": s.station_type,
                "capacity_per_hour": s.capacity_per_hour,
                "status": s.status,
            }
            for s in stations
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/stations/{station_id}")
async def get_station(
    station_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工位详情"""
    service = StationService(db)
    station = await service.get_station_by_id(station_id)
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    return {
        "id": station.id,
        "station_code": station.station_code,
        "station_name": station.station_name,
        "station_type": station.station_type,
        "workshop_id": station.workshop_id,
        "capacity_per_hour": station.capacity_per_hour,
        "equipment_ids": station.equipment_ids,
        "status": station.status,
    }


@router.put("/stations/{station_id}")
async def update_station(
    station_id: str,
    station: StationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新工位"""
    service = StationService(db)
    
    updated = await service.update_station(
        station_id=station_id,
        station_name=station.station_name,
        station_type=station.station_type,
        capacity_per_hour=station.capacity_per_hour,
        workshop_id=station.workshop_id,
    )
    
    if not updated:
        raise HTTPException(status_code=404, detail="Station not found")
    
    return {"id": updated.id, "status": updated.status}


@router.delete("/stations/{station_id}")
async def delete_station(
    station_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除工位"""
    service = StationService(db)
    success = await service.delete_station(station_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Station not found")
    
    return {"message": "Station deleted"}


# --- Routing Endpoints ---

@router.post("/routings")
async def create_routing(
    routing: RoutingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建工艺路线"""
    service = RoutingService(db)
    
    try:
        new_routing = await service.create_routing(
            factory_id=routing.factory_id,
            product_id=routing.product_id,
            version=routing.version,
            steps=routing.steps,
            created_by=current_user.username,
        )
        
        return {
            "id": new_routing.id,
            "routing_code": new_routing.routing_code,
            "product_id": new_routing.product_id,
            "version": new_routing.version,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/routings")
async def list_routings(
    factory_id: str,
    product_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工艺路线列表"""
    service = RoutingService(db)
    
    skip = (page - 1) * page_size
    routings = await service.list_routings(
        factory_id=factory_id,
        product_id=product_id,
        skip=skip,
        limit=page_size
    )
    
    total = len(routings)
    
    return {
        "items": [
            {
                "id": r.id,
                "routing_code": r.routing_code,
                "product_id": r.product_id,
                "version": r.version,
                "steps_count": len(r.steps),
                "is_active": r.is_active,
            }
            for r in routings
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/routings/{routing_id}")
async def get_routing(
    routing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取工艺路线详情"""
    service = RoutingService(db)
    routing = await service.get_routing_by_id(routing_id)
    
    if not routing:
        raise HTTPException(status_code=404, detail="Routing not found")
    
    return {
        "id": routing.id,
        "routing_code": routing.routing_code,
        "product_id": routing.product_id,
        "version": routing.version,
        "steps": routing.steps,
        "is_active": routing.is_active,
    }


@router.put("/routings/{routing_id}")
async def update_routing(
    routing_id: str,
    version: Optional[str] = None,
    steps: Optional[List[dict]] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新工艺路线"""
    service = RoutingService(db)
    
    updated = await service.update_routing(
        routing_id=routing_id,
        version=version,
        steps=steps,
        is_active=is_active,
    )
    
    if not updated:
        raise HTTPException(status_code=404, detail="Routing not found")
    
    return {"id": updated.id, "version": updated.version, "is_active": updated.is_active}


@router.post("/routings/{routing_id}/deactivate")
async def deactivate_routing(
    routing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """停用工艺路线"""
    service = RoutingService(db)
    success = await service.deactivate_routing(routing_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Routing not found")
    
    return {"message": "Routing deactivated"}


# --- Equipment Endpoints ---

class EquipmentCreate(BaseModel):
    factory_id: str
    equipment_code: str
    equipment_name: str
    equipment_type: Optional[str] = None
    station_id: Optional[str] = None
    spec: Optional[dict] = None


@router.post("/equipment")
async def create_equipment(
    equipment: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建设备"""
    service = EquipmentService(db)
    
    try:
        new_equipment = await service.create_equipment(
            factory_id=equipment.factory_id,
            equipment_code=equipment.equipment_code,
            equipment_name=equipment.equipment_name,
            equipment_type=equipment.equipment_type,
            station_id=equipment.station_id,
            spec=equipment.spec,
        )
        
        return {
            "id": new_equipment.id,
            "equipment_code": new_equipment.equipment_code,
            "status": "available"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/equipment")
async def list_equipment(
    factory_id: str,
    equipment_type: Optional[str] = None,
    status: Optional[str] = None,
    station_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取设备列表"""
    service = EquipmentService(db)
    
    skip = (page - 1) * page_size
    equipment_list = await service.list_equipment(
        factory_id=factory_id,
        equipment_type=equipment_type,
        status=status,
        station_id=station_id,
        skip=skip,
        limit=page_size
    )
    
    total = len(equipment_list)
    
    return {
        "items": [
            {
                "id": e.id,
                "equipment_code": e.equipment_code,
                "equipment_name": e.equipment_name,
                "equipment_type": e.equipment_type,
                "station_id": e.station_id,
                "status": e.status,
            }
            for e in equipment_list
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/equipment/{equipment_id}")
async def get_equipment(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取设备详情"""
    service = EquipmentService(db)
    equipment = await service.get_equipment_by_id(equipment_id)
    
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")
    
    return {
        "id": equipment.id,
        "equipment_code": equipment.equipment_code,
        "equipment_name": equipment.equipment_name,
        "equipment_type": equipment.equipment_type,
        "station_id": equipment.station_id,
        "status": equipment.status,
        "spec": equipment.spec,
    }


@router.put("/equipment/{equipment_id}")
async def update_equipment(
    equipment_id: str,
    equipment_name: Optional[str] = None,
    equipment_type: Optional[str] = None,
    station_id: Optional[str] = None,
    status: Optional[str] = None,
    spec: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新设备"""
    service = EquipmentService(db)
    
    updated = await service.update_equipment(
        equipment_id=equipment_id,
        equipment_name=equipment_name,
        equipment_type=equipment_type,
        station_id=station_id,
        status=status,
        spec=spec,
    )
    
    if not updated:
        raise HTTPException(status_code=404, detail="Equipment not found")
    
    return {"id": updated.id, "status": updated.status}


@router.post("/equipment/{equipment_id}/status")
async def update_equipment_status(
    equipment_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新设备状态"""
    service = EquipmentService(db)
    success = await service.update_status(equipment_id, status)
    
    if not success:
        raise HTTPException(status_code=404, detail="Equipment not found")
    
    return {"equipment_id": equipment_id, "status": status}


__all__ = ["router"]
