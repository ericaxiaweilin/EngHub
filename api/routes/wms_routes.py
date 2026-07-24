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
    WmsService,
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


# --- Inventory Count Endpoints (021 增强) ---

class CountCreate(BaseModel):
    factory_id: str
    warehouse_id: str
    count_type: str = "periodic"
    planned_date: Optional[str] = None
    remark: Optional[str] = None


class CountItemSubmit(BaseModel):
    item_id: str
    counted_qty: int
    remark: Optional[str] = None


@router.post("/inventory/count")
async def create_inventory_count(
    req: CountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建盘点单"""
    from datetime import date as ddate
    svc = WmsService(db)
    planned = ddate.fromisoformat(req.planned_date) if req.planned_date else None
    return await svc.create_count_order(
        factory_id=req.factory_id,
        warehouse_id=req.warehouse_id,
        count_type=req.count_type,
        planned_date=planned,
        remark=req.remark,
        created_by=current_user.username,
    )


@router.get("/inventory/count")
async def list_inventory_counts(
    factory_id: str,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """盘点单列表"""
    from sqlalchemy import select
    from database.models import InventoryCount
    query = select(InventoryCount).where(InventoryCount.factory_id == factory_id)
    if status:
        query = query.where(InventoryCount.status == status)
    query = query.order_by(InventoryCount.created_at.desc())
    result = await db.execute(query)
    counts = result.scalars().all()
    return {
        "items": [
            {
                "id": c.id, "count_code": c.count_code,
                "warehouse_id": c.warehouse_id, "count_type": c.count_type,
                "status": c.status, "total_items": c.total_items,
                "diff_items": c.diff_items, "total_diff_qty": c.total_diff_qty,
                "counted_by": c.counted_by, "approved_by": c.approved_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in counts
        ]
    }


@router.post("/inventory/count/{count_id}/items")
async def submit_count_item(
    count_id: str,
    req: CountItemSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """录入盘点明细"""
    svc = WmsService(db)
    result = await svc.submit_count_item(count_id, req.item_id, req.counted_qty, req.remark)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/inventory/count/{count_id}/approve")
async def approve_count(
    count_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审批盘点"""
    svc = WmsService(db)
    result = await svc.approve_count(count_id, approved_by=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# --- Trace & Analytics Endpoints (021 增强) ---


@router.get("/inventory/material/{material_id}/trace")
async def trace_material(
    material_id: str,
    factory_id: str = "F001",
    batch_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """物料追溯"""
    svc = WmsService(db)
    return await svc.trace_material(factory_id, material_id, batch_code)


@router.get("/inventory/transactions")
async def list_transactions(
    factory_id: str,
    material_id: Optional[str] = None,
    transaction_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """库存流水"""
    from sqlalchemy import select
    from database.models import InventoryTransaction
    query = select(InventoryTransaction).where(InventoryTransaction.factory_id == factory_id)
    if material_id:
        query = query.where(InventoryTransaction.material_id == material_id)
    if transaction_type:
        query = query.where(InventoryTransaction.transaction_type == transaction_type)
    query = query.order_by(InventoryTransaction.created_at.desc()).limit(50)
    result = await db.execute(query)
    txns = result.scalars().all()
    return {
        "items": [
            {
                "id": t.id, "material_id": t.material_id,
                "batch_code": t.batch_code, "transaction_type": t.transaction_type,
                "quantity": t.quantity, "before_qty": t.before_qty, "after_qty": t.after_qty,
                "reference_type": t.reference_type, "operator": t.operator,
                "remark": t.remark,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ]
    }


@router.get("/inventory/alerts")
async def stock_alerts(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """库存预警"""
    svc = WmsService(db)
    return await svc.get_stock_alerts(factory_id)


@router.get("/inventory/fifo-check")
async def fifo_check(
    factory_id: str,
    material_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FIFO 合规检查"""
    svc = WmsService(db)
    return await svc.check_fifo(factory_id, material_id)


__all__ = ["router"]
