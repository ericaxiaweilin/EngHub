"""
WMS Service - 仓库管理服务
处理仓库、库位、库存相关的业务逻辑
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import (
    Warehouse,
    Location,
    Inventory,
    InboundOrder,
    OutboundOrder,
)


class WarehouseService:
    """仓库服务类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_warehouse(
        self,
        factory_id: str,
        warehouse_code: str,
        warehouse_name: str,
        warehouse_type: str,
        address: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Warehouse:
        """创建仓库"""
        warehouse = Warehouse(
            warehouse_code=warehouse_code,
            warehouse_name=warehouse_name,
            factory_id=factory_id,
            warehouse_type=warehouse_type,
            address=address,
            created_by=created_by,
        )
        
        self.db.add(warehouse)
        await self.db.commit()
        await self.db.refresh(warehouse)
        
        return warehouse
    
    async def get_warehouse_by_id(self, warehouse_id: str) -> Optional[Warehouse]:
        """根据 ID 获取仓库"""
        result = await self.db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
        return result.scalar_one_or_none()
    
    async def list_warehouses(
        self,
        factory_id: str,
        warehouse_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Warehouse]:
        """获取仓库列表"""
        query = select(Warehouse).where(Warehouse.factory_id == factory_id)
        
        if warehouse_type:
            query = query.where(Warehouse.warehouse_type == warehouse_type)
        if status:
            query = query.where(Warehouse.status == status)
        
        query = query.order_by(Warehouse.created_at.desc())
        result = await self.db.execute(query)
        return result.scalars().all()


class LocationService:
    """库位服务类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_location(
        self,
        warehouse_id: str,
        location_code: str,
        location_name: str,
        location_type: str = "rack",
        zone: Optional[str] = None,
        capacity: Optional[int] = None,
    ) -> Location:
        """创建库位"""
        location = Location(
            location_code=location_code,
            location_name=location_name,
            warehouse_id=warehouse_id,
            location_type=location_type,
            zone=zone,
            capacity=capacity,
        )
        
        self.db.add(location)
        await self.db.commit()
        await self.db.refresh(location)
        
        return location
    
    async def list_locations(
        self,
        warehouse_id: str,
        zone: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Location]:
        """获取库位列表"""
        query = select(Location).where(Location.warehouse_id == warehouse_id)
        
        if zone:
            query = query.where(Location.zone == zone)
        if status:
            query = query.where(Location.status == status)
        
        query = query.order_by(Location.location_code)
        result = await self.db.execute(query)
        return result.scalars().all()


class InventoryService:
    """库存服务类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_inventory(
        self,
        factory_id: str,
        material_id: str,
        warehouse_id: Optional[str] = None,
    ) -> List[Inventory]:
        """获取库存信息"""
        query = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.material_id == material_id
        )
        
        if warehouse_id:
            query = query.where(Inventory.warehouse_id == warehouse_id)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def check_available(
        self,
        factory_id: str,
        material_id: str,
        warehouse_id: Optional[str] = None,
    ) -> dict:
        """检查物料可用量"""
        inventories = await self.get_inventory(factory_id, material_id, warehouse_id)
        
        total_available = sum(inv.available_qty for inv in inventories)
        
        return {
            "material_id": material_id,
            "available_qty": total_available,
            "can_allocate": total_available > 0
        }
    
    async def create_inbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        batch_code: Optional[str] = None,
        supplier_id: Optional[str] = None,
        purchase_order_id: Optional[str] = None,
        unit_cost: Optional[float] = None,
        location_id: Optional[str] = None,
        inbound_type: str = "purchase",
        created_by: Optional[str] = None,
    ) -> InboundOrder:
        """创建入库单并更新库存"""
        # 生成入库单号
        inbound_code = f"IN-{datetime.now().strftime('%Y%m%d')}-{await self._get_next_in_number(factory_id)}"
        
        inbound = InboundOrder(
            inbound_code=inbound_code,
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            material_id=material_id,
            material_code=material_code,
            quantity=quantity,
            batch_code=batch_code,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            unit_cost=unit_cost,
            location_id=location_id,
            inbound_type=inbound_type,
            status="completed",
            created_by=created_by,
            completed_at=datetime.utcnow(),
        )
        
        self.db.add(inbound)
        
        # 更新或创建库存记录
        await self._update_inventory_after_inbound(
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            material_id=material_id,
            material_code=material_code,
            quantity=quantity,
            batch_code=batch_code,
            location_id=location_id,
            unit_cost=unit_cost,
        )
        
        await self.db.commit()
        await self.db.refresh(inbound)
        
        return inbound
    
    async def _update_inventory_after_inbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        batch_code: Optional[str] = None,
        location_id: Optional[str] = None,
        unit_cost: Optional[float] = None,
    ):
        """入库后更新库存"""
        # 查找现有库存记录
        query = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.material_id == material_id,
            Inventory.batch_code == batch_code,
        )
        
        if location_id:
            query = query.where(Inventory.location_id == location_id)
        
        result = await self.db.execute(query)
        inventory = result.scalar_one_or_none()
        
        if inventory:
            inventory.total_qty += quantity
            inventory.available_qty += quantity
        else:
            # 创建新库存记录
            inventory = Inventory(
                material_id=material_id,
                material_code=material_code,
                factory_id=factory_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_code=batch_code,
                total_qty=quantity,
                available_qty=quantity,
                unit_cost=unit_cost,
            )
            self.db.add(inventory)
    
    async def create_outbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        quantity: int,
        work_order_id: Optional[str] = None,
        batch_code: Optional[str] = None,
        outbound_type: str = "production",
        created_by: Optional[str] = None,
    ) -> OutboundOrder:
        """创建出库单并扣减库存"""
        # 生成出库单号
        outbound_code = f"OUT-{datetime.now().strftime('%Y%m%d')}-{await self._get_next_out_number(factory_id)}"
        
        outbound = OutboundOrder(
            outbound_code=outbound_code,
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            material_id=material_id,
            quantity=quantity,
            work_order_id=work_order_id,
            batch_code=batch_code,
            outbound_type=outbound_type,
            status="completed",
            created_by=created_by,
            completed_at=datetime.utcnow(),
        )
        
        self.db.add(outbound)
        
        # 扣减库存
        await self._update_inventory_after_outbound(
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            material_id=material_id,
            quantity=quantity,
            batch_code=batch_code,
        )
        
        await self.db.commit()
        await self.db.refresh(outbound)
        
        return outbound
    
    async def _update_inventory_after_outbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        quantity: int,
        batch_code: Optional[str] = None,
    ):
        """出库后扣减库存"""
        # 查找库存记录（FIFO 策略：优先使用最早批次）
        query = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.material_id == material_id,
            Inventory.available_qty > 0,
        )
        
        if batch_code:
            query = query.where(Inventory.batch_code == batch_code)
        
        query = query.order_by(Inventory.created_at.asc())
        result = await self.db.execute(query)
        inventories = result.scalars().all()
        
        remaining_qty = quantity
        for inventory in inventories:
            if remaining_qty <= 0:
                break
            
            deduct_qty = min(remaining_qty, inventory.available_qty)
            inventory.available_qty -= deduct_qty
            inventory.total_qty -= deduct_qty
            remaining_qty -= deduct_qty
        
        if remaining_qty > 0:
            raise ValueError(f"Insufficient inventory. Short by {remaining_qty}")
    
    async def reserve_inventory(
        self,
        factory_id: str,
        material_id: str,
        warehouse_id: str,
        quantity: int,
        work_order_id: str,
    ) -> dict:
        """预留库存"""
        inventories = await self.get_inventory(factory_id, material_id, warehouse_id)
        
        total_available = sum(inv.available_qty for inv in inventories)
        
        if total_available < quantity:
            raise ValueError(f"Insufficient available inventory. Available: {total_available}, Requested: {quantity}")
        
        # 简单实现：预留第一个有足够库存的记录
        remaining_qty = quantity
        for inventory in inventories:
            if remaining_qty <= 0:
                break
            
            reserve_qty = min(remaining_qty, inventory.available_qty)
            inventory.available_qty -= reserve_qty
            inventory.reserved_qty += reserve_qty
            remaining_qty -= reserve_qty
        
        return {
            "material_id": material_id,
            "reserved_qty": quantity,
            "work_order_id": work_order_id
        }
    
    async def _get_next_in_number(self, factory_id: str) -> int:
        """获取下一个入库单序号"""
        today = datetime.now().date()
        result = await self.db.execute(
            select(func.count(InboundOrder.id)).where(
                InboundOrder.factory_id == factory_id,
                func.date(InboundOrder.created_at) == today
            )
        )
        count = result.scalar() or 0
        return count + 1
    
    async def _get_next_out_number(self, factory_id: str) -> int:
        """获取下一个出库单序号"""
        today = datetime.now().date()
        result = await self.db.execute(
            select(func.count(OutboundOrder.id)).where(
                OutboundOrder.factory_id == factory_id,
                func.date(OutboundOrder.created_at) == today
            )
        )
        count = result.scalar() or 0
        return count + 1


# 导出所有服务
__all__ = [
    "WarehouseService",
    "LocationService",
    "InventoryService",
]
