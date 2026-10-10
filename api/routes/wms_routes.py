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


# ============== Warehouse Pydantic Models ==============

class WarehouseUpdatePartial(BaseModel):
    """部分更新仓库（PATCH）"""
    warehouse_name: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None
    warehouse_type: Optional[str] = None


class WarehouseUpdateFull(BaseModel):
    """完全替换更新仓库（PUT）"""
    warehouse_code: str
    warehouse_name: str
    factory_id: str
    warehouse_type: str
    address: Optional[str] = None
    status: str = "active"


class WarehouseDeleteResponse(BaseModel):
    """删除响应"""
    message: str


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
    # 端点文档写着支持采购/生产/退货入库，但模型一直没这个字段，
    # 调用方传了会被 pydantic 丢掉、一律按 purchase 走 IQC 门。
    inbound_type: str = "purchase"


class OutboundCreate(BaseModel):
    factory_id: str
    warehouse_id: str
    material_id: str
    # 原来只有 3 个字段，而路由读 outbound.quantity -> AttributeError，
    # 线上 POST /inventory/outbound 恒 500（实测 500 "'OutboundCreate' object has no attribute 'quantity'"）
    quantity: float
    work_order_id: Optional[str] = None
    batch_code: Optional[str] = None
    outbound_type: str = "production"

# ============== Inventory Pydantic Models ==============

class InventoryUpdatePartial(BaseModel):
    """部分更新库存（PATCH）"""
    location_id: Optional[str] = None
    batch_code: Optional[str] = None
    total_qty: Optional[int] = None
    available_qty: Optional[int] = None
    reserved_qty: Optional[int] = None
    unit_cost: Optional[float] = None
    status: Optional[str] = None


class InventoryUpdateFull(BaseModel):
    """更新库存主数据（PUT）—— 数量不在这里改

    给默认值不是为了省事，是为了分得开"没送这个字段"和"送了"：
    路由按 model_fields_set 判，送数量就直接拒（见 update_inventory_full）。
    """
    location_id: Optional[str] = None
    batch_code: Optional[str] = None
    total_qty: Optional[int] = None
    available_qty: Optional[int] = None
    reserved_qty: Optional[int] = None
    unit_cost: Optional[float] = None
    status: Optional[str] = None


class InventoryDeleteResponse(BaseModel):
    """删除响应"""
    message: str


# --- Existing models continue below ---
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


# ============== Warehouse RESTful Endpoints (PUT/PATCH/DELETE) ==============


@router.put("/warehouses/{warehouse_id}")
async def update_warehouse_full(
    warehouse_id: str,
    req: WarehouseUpdateFull,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完全替换更新仓库信息（PUT）"""
    try:
        service = WarehouseService(db)
        result = await service.update_warehouse_full(
            warehouse_id=warehouse_id,
            data=req.dict(),
            updated_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"仓库更新失败: {str(e)}")


@router.patch("/warehouses/{warehouse_id}")
async def update_warehouse_partial(
    warehouse_id: str,
    req: WarehouseUpdatePartial,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部分更新仓库信息（PATCH /warehouses/{id}）"""
    updates = {k: v for k, v in req.dict().items() if v is not None}
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    try:
        service = WarehouseService(db)
        result = await service.update_warehouse_partial(
            warehouse_id=warehouse_id,
            updates=updates,
            updated_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"仓库更新失败: {str(e)}")


@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除仓库（DELETE）"""
    try:
        service = WarehouseService(db)
        result = await service.delete_warehouse_soft(
            warehouse_id=warehouse_id,
            deleted_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return {"message": result["message"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"仓库删除失败: {str(e)}")


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
    material_code: Optional[str] = None,
    status: Optional[str] = None,
    page: Optional[int] = None,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取库存信息

    以前只回 8 个字段：`InventoryItem` 在前端声明了 status/unit_cost/created_at，
    后端一个都没发 —— 于是"状态"列永远空、"冻结"筛了等于没筛。
    """
    service = InventoryService(db)

    inventories = await service.get_inventory(
        factory_id=factory_id,
        material_id=material_id,
        warehouse_id=warehouse_id,
        material_code=material_code,
        status=status,
    )
    total = len(inventories)
    if page and page > 0:
        start = (page - 1) * max(1, int(page_size))
        inventories = inventories[start:start + max(1, int(page_size))]

    return {
        "items": [
            {
                "id": inv.id,
                "material_id": inv.material_id,
                "material_code": inv.material_code,
                "material_name": inv.material_name,
                "warehouse_id": str(inv.warehouse_id),
                "location_id": inv.location_id,
                "batch_code": inv.batch_code,
                "total_qty": inv.total_qty,
                "available_qty": inv.available_qty,
                "reserved_qty": inv.reserved_qty,
                "unit": inv.unit,
                "unit_cost": float(inv.unit_cost) if inv.unit_cost is not None else None,
                "status": inv.status,
                "lock_reason": inv.lock_reason,
                "qualified_status": inv.qualified_status,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
            }
            for inv in inventories
        ],
        "total": total,
        "page": page,
        "page_size": page_size if page else None,
    }


# ============== Inventory RESTful Endpoints (PUT/PATCH/DELETE) ==============


@router.put("/inventory/{inventory_id}")
async def update_inventory_full(
    inventory_id: str,
    req: InventoryUpdateFull,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完全替换更新库存记录（PUT）

    数量三个字段不在这里改：PUT 直接写 total/available/reserved 等于绕过记账原语 ——
    没有流水、没有操作人、也不认质量冻结，事后账实对不上时没人知道是哪一次改的。
    要改数量走 POST /api/v1/wms/inbound（收货）/wms/outbound（出库）/wms/transfer（调拨），
    盘点差异走 GET+POST /api/v1/inventory/count/{id}/items 再审批。
    """
    quantity_fields = ({"total_qty", "available_qty", "reserved_qty"}
                       & set(req.model_fields_set))
    if quantity_fields:
        raise HTTPException(
            status_code=400,
            detail=f"库存数量不能由 PUT 直接改（动了 {'、'.join(sorted(quantity_fields))}）；"
                   "要改数量请走出入库/调拨/盘点审批 —— 那三条都会在台账留下单据号和流水")
    try:
        service = InventoryService(db)
        result = await service.update_inventory_full(
            inventory_id=inventory_id,
            data=req.model_dump(exclude_unset=True),
            updated_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"库存更新失败: {str(e)}")


@router.patch("/inventory/{inventory_id}")
async def update_inventory_partial(
    inventory_id: str,
    req: InventoryUpdatePartial,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部分更新库存记录（PATCH）"""
    # 构建只包含已提供字段的更新字典（排除None值）
    updates = {k: v for k, v in req.dict().items() if v is not None}
    
    try:
        service = InventoryService(db)
        result = await service.update_inventory_partial(
            inventory_id=inventory_id,
            updates=updates,
            updated_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"库存更新失败: {str(e)}")


@router.delete("/inventory/{inventory_id}")
async def delete_inventory(
    inventory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除库存记录（DELETE）"""
    try:
        service = InventoryService(db)
        result = await service.delete_inventory_soft(
            inventory_id=inventory_id,
            deleted_by=current_user.username,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return {"message": result["message"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"库存删除失败: {str(e)}")


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
            inbound_type=inbound.inbound_type,
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
            outbound_type=outbound.outbound_type,
            created_by=current_user.username,
        )
        
        return {
            "id": result.id,
            "outbound_code": result.outbound_code,
            "status": result.status,
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


@router.get("/inventory/count/{count_id}/items", summary="盘点明细（带料号/批次/库位，供录入）")
async def list_count_items(
    count_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """没有这条，POST .../items 要的 item_id 对人就是不可得的，盘点流程走不通。"""
    del current_user
    return await WmsService(db).get_count_items(count_id)


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


@router.get("/inventory/health", summary="库存专业健康度汇总（只读）")
async def inventory_health(
    factory_id: str,
    dead_stock_days: int = 60,
    expiry_warn_days: int = 30,
    turnover_days: int = 90,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """编排已有 WMS 分析执行器，并披露覆盖率与不可计算项。

    不在这里重复实现口径：ABC、周转、呆滞、效期、低库存、过量、补货建议
    全部来自 wms_architecture/executors。
    """
    del current_user
    from api.services.wms_inventory_health_service import WmsInventoryHealthService
    return await WmsInventoryHealthService(db).collect(
        factory_id,
        dead_stock_days=max(7, min(int(dead_stock_days or 60), 730)),
        expiry_warn_days=max(1, min(int(expiry_warn_days or 30), 365)),
        turnover_days=max(7, min(int(turnover_days or 90), 365)),
    )


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


@router.get("/wms/capability", summary="WMS 能力矩阵：每一格是活的、空的、还是缺外部新数（只读）")
async def wms_capability(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把"仓储功能很弱"变成可核对的读数：15 张表里哪几格 0 行、哪几格缺新数据。

    判词分 live / thin / empty / blocked_on_source 四种 —— "空表"和"坏了"和"外部源没新数"
    是三件事，混成一个"弱"字就没法修。
    """
    del current_user
    from api.services.wms_audit import capability_matrix

    return await capability_matrix(db, factory_id)


@router.get("/wms/location-sync", summary="库位对象化：会登记哪些库位、多少台账行会挂上（默认只算不写）")
async def wms_location_sync(
    factory_id: str,
    apply: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """locations 表现在 0 行，而台账里有上千个库位号 —— 号是字符串，不是能挂东西的对象。

    apply=false 只回报"会建哪些"；只新增，不改不删已有库位档案，容量没声明就留空。
    """
    del current_user
    from api.services.wms_locations import sync_locations

    return await sync_locations(db, factory_id, apply=apply)


@router.get("/wms/location-occupancy", summary="库位占用：每个格子挂了多少料/多少件")
async def wms_location_occupancy(
    factory_id: str,
    limit: int = 12,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    from api.services.wms_locations import location_occupancy

    return await location_occupancy(db, factory_id, limit=max(1, min(50, int(limit))))



@router.get("/wms/count-plan", summary="这轮该盘哪些库存行：按四条范围选，附理由（默认只算不写）")
async def wms_count_plan(
    factory_id: str,
    warehouse_id: Optional[str] = None,
    apply: bool = False,
    max_items: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """`inventory_counts` 0 行 —— 建单/录入/审批的接口都在，但从没人开过一张单。

    apply=false 只回报"会开哪些行、每行为什么该盘"；开单只写盘点表，不动库存。
    """
    del current_user
    from api.services.stock_counts import open_periodic_count

    return await open_periodic_count(db, factory_id, warehouse_id=warehouse_id,
                                     apply=apply, max_items=max(1, min(500, int(max_items))))


@router.post("/wms/count-plan", summary="开一张周期盘点单（把系统数快照进明细，等人录入实测）")
async def wms_count_plan_open(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """谁开的单写进备注：引擎自动开和人开单，将来在盘点完成率上要分得开。"""
    from api.services.stock_counts import open_periodic_count

    return await open_periodic_count(
        db, str(body.get("factory_id") or ""),
        warehouse_id=(body.get("warehouse_id") or None),
        apply=bool(body.get("apply", True)),
        max_items=max(1, min(500, int(body.get("max_items") or 200))),
        actor=str(getattr(current_user, "username", None) or "unknown"))


@router.get("/wms/count-status", summary="盘点这条腿走到哪一步：开了几张、录了几行、审批调差多少")
async def wms_count_status(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    from api.services.stock_counts import count_status

    return await count_status(db, factory_id)



@router.get("/wms/alert-sync", summary="库存报警落库：四把尺各报多少、会新增/关闭几条（默认只算不写）")
async def wms_alert_sync(
    factory_id: str,
    apply: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """`stock_alerts` 一直 0 行：报警是实时算完就丢的，没有"谁处理了"这一格。

    四把尺分开存、不合并 —— 按行声明的补货点只有 111 条会报（94.7% 的补货点是 1），
    代码里写死的 `<10` 会报 1,260 条，这两个数是两件事，合成一个就要替厂里选阈值。
    关闭只发生在本轮评估过、且条件已消失的告警上。
    """
    del current_user
    from api.services.stock_alerts import sync_alerts

    return await sync_alerts(db, factory_id, apply=apply)


@router.get("/wms/alert-summary", summary="落库后的告警分布：开着/自动消/人处理，按类型分开")
async def wms_alert_summary(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    from api.services.stock_alerts import alert_summary

    return await alert_summary(db, factory_id)





@router.post("/wms/freeze", summary="质量冻结：把一批库存行锁住，领料/出库/调拨当场领不走")
async def wms_freeze(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冻结必须落在对象上，而且要有原因码。

    10-09 之前的状态：`inventory_freezes` 0 行，`inventory.status/lock_reason/qualified_status`
    三列在读取侧一处都没用到 —— 标了"待检"照样领得走，那是装饰品不是控制。
    现在写入原语 `apply_movement`/`apply_transfer_pair` 直接认这一行的锁，
    所有扣减/搬出路径都挡，不靠各处 SQL 各自记得加过滤。
    """
    from datetime import datetime

    from api.services.wms_freezes import freeze

    raw_until = body.get("freeze_until")
    until = None
    if isinstance(raw_until, str) and raw_until.strip():
        try:
            until = datetime.fromisoformat(raw_until.strip().replace("Z", "+00:00"))
            until = until.replace(tzinfo=None) if until.tzinfo is None else until.astimezone().replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"freeze_until 不是 ISO 时间：{raw_until!r}")
    ids = body.get("inventory_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="inventory_ids 必须是库存行 id 的数组")
    out = await freeze(
        db, str(body.get("factory_id") or ""), [str(i) for i in ids],
        reason_code=str(body.get("reason_code") or ""),
        reason_text=str(body.get("reason_text") or ""),
        until=until, actor=str(getattr(current_user, "username", None) or "unknown"),
        auto_unfreeze=bool(body.get("auto_unfreeze", False)),
        apply=bool(body.get("apply", True)))
    if out.get("error"):
        raise HTTPException(status_code=400, detail=out["error"])
    return out


@router.post("/wms/freeze/release", summary="放行冻结：谁放的、为什么都要落名（人放的和到期自动放分两本账）")
async def wms_freeze_release(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """这个端点只写 `released`（人主动放的）。

    `expired` 是到期由系统放的，只有 expire_due 会写 —— 两者混成一个数，
    "质量放行"就会被系统的到期动作冒充，事后没人看得出这批料是谁批的。
    """
    from api.services.wms_freezes import release

    out = await release(
        db, str(body.get("factory_id") or ""),
        freeze_id=(str(body["freeze_id"]) if body.get("freeze_id") else None),
        inventory_id=(str(body["inventory_id"]) if body.get("inventory_id") else None),
        actor=str(getattr(current_user, "username", None) or "unknown"),
        note=str(body.get("note") or ""), kind="released",
        apply=bool(body.get("apply", True)))
    if out.get("error"):
        raise HTTPException(status_code=400, detail=out["error"])
    return out


@router.get("/wms/freeze-status", summary="冻结这格走到哪一步：活动/人放/到期放，以及两笔账对不对得上")
async def wms_freeze_status(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """除了三态计数，还报 `sync_check`：冻结记录数 vs 行上锁数。

    对不上就是有一边漏写 —— "有记录没锁"意味着领料照样走得掉（装饰品回来了），
    "有锁没记录"意味着没人知道这批料被谁冻、凭什么冻。
    """
    del current_user
    from sqlalchemy import text

    from api.services.wms_freezes import freeze_status, sync_check

    st = await freeze_status(db, factory_id)
    agg = await db.execute(text("""
        SELECT (SELECT COUNT(*) FROM inventory_freezes
                 WHERE factory_id=:fid AND LOWER(status)='active') AS 记录,
               (SELECT COUNT(*) FROM inventory
                 WHERE factory_id=:fid AND LOWER(COALESCE(status,''))='locked') AS 行锁
    """), {"fid": factory_id})
    row = dict(agg.mappings().first() or {})
    await db.rollback()
    st["ledger"] = sync_check(int(row.get("记录") or 0), int(row.get("行锁") or 0))
    return st


__all__ = ["router"]
