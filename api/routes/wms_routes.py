"""
WMS API Routes
库存管理、仓库管理
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User
from api.services.wms_service import (
    WarehouseService,
    LocationService,
    InventoryService,
)

router = APIRouter(prefix="/api/v1", tags=["wms"])


# --- Request/Response Models ---

class WarehouseCreate(BaseModel):
    factory_id: str
    warehouse_code: str
    warehouse_name: str
    warehouse_type: str
    address: Optional[str] = None


class LocationCreate(BaseModel):
    warehouse_id: str
    location_code: str
    location_name: str
    location_type: str = "rack"
    zone: Optional[str] = None
    capacity: Optional[int] = None


class InboundCreate(BaseModel):
    factory_id: str
    warehouse_id: str
    material_id: str
    material_code: str
    quantity: float
    batch_code: Optional[str] = None
    supplier_id: Optional[str] = None
    purchase_order_id: Optional[str] = None
    unit_cost: Optional[float] = None
    location_id: Optional[str] = None


class OutboundCreate(BaseModel):
    factory_id: str
    warehouse_id: str
    material_id: str
    quantity: float
    work_order_id: Optional[str] = None
    batch_code: Optional[str] = None


class CountItem(BaseModel):
    material_id: str
    batch_code: Optional[str] = None
    system_qty: float
    counted_qty: float


class CountSubmit(BaseModel):
    items: list[CountItem]


# --- Warehouse Endpoints ---

@router.post("/warehouses")
async def create_warehouse(
    wh: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建仓库"""
    service = WarehouseService(db)
    
    warehouse = await service.create_warehouse(
        factory_id=wh.factory_id,
        warehouse_code=wh.warehouse_code,
        warehouse_name=wh.warehouse_name,
        warehouse_type=wh.warehouse_type,
        address=wh.address,
        created_by=current_user.username,
    )
    
    return {
        "id": warehouse.id,
        "warehouse_code": warehouse.warehouse_code,
        "status": warehouse.status
    }


@router.get("/warehouses")
async def list_warehouses(
    factory_id: str,
    warehouse_type: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取仓库列表"""
    service = WarehouseService(db)
    
    warehouses = await service.list_warehouses(
        factory_id=factory_id,
        warehouse_type=warehouse_type,
        status=status,
    )
    
    return {
        "items": [
            {
                "id": wh.id,
                "warehouse_code": wh.warehouse_code,
                "warehouse_name": wh.warehouse_name,
                "warehouse_type": wh.warehouse_type,
                "status": wh.status,
            }
            for wh in warehouses
        ],
        "total": len(warehouses)
    }


@router.get("/warehouses/{warehouse_id}")
async def get_warehouse(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取仓库详情"""
    service = WarehouseService(db)
    
    warehouse = await service.get_warehouse_by_id(warehouse_id)
    
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    
    return {
        "id": warehouse.id,
        "warehouse_code": warehouse.warehouse_code,
        "warehouse_name": warehouse.warehouse_name,
        "warehouse_type": warehouse.warehouse_type,
        "address": warehouse.address,
        "status": warehouse.status,
    }


@router.post("/warehouses/{warehouse_id}/locations")
async def create_location(
    warehouse_id: str,
    loc: LocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建库位"""
    service = LocationService(db)
    
    location = await service.create_location(
        warehouse_id=warehouse_id,
        location_code=loc.location_code,
        location_name=loc.location_name,
        location_type=loc.location_type,
        zone=loc.zone,
        capacity=loc.capacity,
    )
    
    return {
        "id": location.id,
        "location_code": location.location_code,
        "status": location.status
    }


@router.get("/warehouses/{warehouse_id}/locations")
async def list_locations(
    warehouse_id: str,
    zone: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取库位列表"""
    service = LocationService(db)
    
    locations = await service.list_locations(
        warehouse_id=warehouse_id,
        zone=zone,
        status=status,
    )
    
    return {
        "items": [
            {
                "id": loc.id,
                "location_code": loc.location_code,
                "location_name": loc.location_name,
                "zone": loc.zone,
                "status": loc.status,
            }
            for loc in locations
        ],
        "total": len(locations)
    }


# --- Inventory Endpoints ---

@router.get("/inventory")
async def get_inventory(
    factory_id: str,
    material_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取库存信息"""
    service = InventoryService(db)
    
    if not material_id:
        return {"items": [], "total": 0}
    
    inventories = await service.get_inventory(
        factory_id=factory_id,
        material_id=material_id,
        warehouse_id=warehouse_id,
    )
    
    return {
        "items": [
            {
                "id": inv.id,
                "material_id": inv.material_id,
                "material_code": inv.material_code,
                "warehouse_id": str(inv.warehouse_id),
                "batch_code": inv.batch_code,
                "total_qty": inv.total_qty,
                "available_qty": inv.available_qty,
                "reserved_qty": inv.reserved_qty,
            }
            for inv in inventories
        ],
        "total": len(inventories)
    }


@router.get("/inventory/available")
async def check_available(
    factory_id: str,
    material_id: str,
    warehouse_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """检查物料可用量"""
    service = InventoryService(db)
    
    result = await service.check_available(
        factory_id=factory_id,
        material_id=material_id,
        warehouse_id=warehouse_id,
    )
    
    return result


# --- Inbound/Outbound Endpoints ---

@router.post("/inventory/inbound")
async def create_inbound(
    inbound: InboundCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    入库操作
    
    - 采购入库
    - 生产入库
    - 退货入库
    - 自动生成批次号
    """
    service = InventoryService(db)
    
    try:
        result = await service.create_inbound(
            factory_id=inbound.factory_id,
            warehouse_id=inbound.warehouse_id,
            material_id=inbound.material_id,
            material_code=inbound.material_code,
            quantity=int(inbound.quantity),
            batch_code=inbound.batch_code,
            supplier_id=inbound.supplier_id,
            purchase_order_id=inbound.purchase_order_id,
            unit_cost=inbound.unit_cost,
            location_id=inbound.location_id,
            created_by=current_user.username,
        )
        
        return {
            "id": result.id,
            "inbound_code": result.inbound_code,
            "batch_code": result.batch_code,
            "status": result.status
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/inventory/outbound")
async def create_outbound(
    outbound: OutboundCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    出库操作
    
    - 生产领料
    - 销售出库
    - FIFO 策略
    """
    service = InventoryService(db)
    
    try:
        result = await service.create_outbound(
            factory_id=outbound.factory_id,
            warehouse_id=outbound.warehouse_id,
            material_id=outbound.material_id,
            quantity=int(outbound.quantity),
            work_order_id=outbound.work_order_id,
            batch_code=outbound.batch_code,
            created_by=current_user.username,
        )
        
        return {
            "id": result.id,
            "outbound_code": result.outbound_code,
            "status": result.status,
            "outbound_batches": []
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/inventory/reserve")
async def reserve_inventory(
    factory_id: str,
    material_id: str,
    warehouse_id: str,
    quantity: float,
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """预留库存"""
    service = InventoryService(db)
    
    try:
        result = await service.reserve_inventory(
            factory_id=factory_id,
            material_id=material_id,
            warehouse_id=warehouse_id,
            quantity=int(quantity),
            work_order_id=work_order_id,
        )
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Inventory Count Endpoints ---

@router.post("/inventory/count")
async def create_inventory_count(
    factory_id: str,
    warehouse_id: str,
    count_date: date,
    count_type: str = "periodic",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建盘点单"""
    # TODO: Implement inventory count
    return {"id": "cnt-001", "status": "draft"}


@router.post("/inventory/count/{count_id}/submit")
async def submit_count_result(
    count_id: str,
    data: CountSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """提交盘点结果"""
    # TODO: Implement inventory count submission
    return {
        "count_id": count_id,
        "status": "pending_approval",
        "total_difference": 0
    }


# --- Trace Endpoints ---

@router.get("/inventory/material/{material_id}/trace")
async def trace_material(
    material_id: str,
    batch_code: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """物料追溯"""
    # TODO: Implement material traceability
    return {
        "material_id": material_id,
        "batch_code": batch_code,
        "inbound_records": [],
        "outbound_records": []
    }


__all__ = ["router"]
