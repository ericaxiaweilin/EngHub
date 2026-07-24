"""
WMS 仓储增强服务 - 盘点/追溯/FIFO/预警/库存流水
"""
import uuid
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Inventory, InboundOrder, OutboundOrder,
    InventoryTransaction, InventoryCount, InventoryCountItem,
)

logger = logging.getLogger(__name__)


class WmsService:
    """WMS 仓储增强服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============== 库存流水 ==============

    async def record_transaction(
        self,
        factory_id: str,
        material_id: str,
        transaction_type: str,
        quantity: int,
        inventory_id: Optional[str] = None,
        batch_code: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        operator: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> InventoryTransaction:
        """记录库存流水"""
        before_qty = None
        after_qty = None
        if inventory_id:
            inv = await self.db.get(Inventory, inventory_id)
            if inv:
                before_qty = inv.total_qty
                after_qty = inv.total_qty + quantity

        txn = InventoryTransaction(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            inventory_id=inventory_id,
            material_id=material_id,
            batch_code=batch_code,
            transaction_type=transaction_type,
            quantity=quantity,
            before_qty=before_qty,
            after_qty=after_qty,
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark,
        )
        self.db.add(txn)
        return txn

    # ============== 盘点管理 ==============

    async def create_count_order(
        self,
        factory_id: str,
        warehouse_id: str,
        count_type: str = "periodic",
        planned_date: Optional[date] = None,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建盘点单（自动快照系统库存）"""
        now = datetime.utcnow()
        count_code = f"IC-{factory_id[:4]}-{now.strftime('%Y%m%d%H%M')}"

        count_order = InventoryCount(
            id=str(uuid.uuid4()),
            count_code=count_code,
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            count_type=count_type,
            status="draft",
            planned_date=planned_date,
            remark=remark,
        )
        self.db.add(count_order)

        # 快照该仓库所有库存
        inv_stmt = select(Inventory).where(
            Inventory.warehouse_id == warehouse_id,
            Inventory.factory_id == factory_id,
        )
        inv_result = await self.db.execute(inv_stmt)
        inventories = inv_result.scalars().all()

        item_count = 0
        for inv in inventories:
            item = InventoryCountItem(
                id=str(uuid.uuid4()),
                count_id=count_order.id,
                inventory_id=inv.id,
                material_id=inv.material_id,
                batch_code=inv.batch_code,
                system_qty=inv.total_qty,
            )
            self.db.add(item)
            item_count += 1

        count_order.total_items = item_count
        await self.db.commit()

        return {"success": True, "count_id": count_order.id, "count_code": count_code, "total_items": item_count}

    async def submit_count_item(
        self,
        count_id: str,
        item_id: str,
        counted_qty: int,
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """录入实盘数"""
        item = await self.db.get(InventoryCountItem, item_id)
        if not item or item.count_id != count_id:
            return {"success": False, "message": "盘点明细不存在"}

        item.counted_qty = counted_qty
        item.diff_qty = counted_qty - item.system_qty
        if remark:
            item.remark = remark

        # 更新盘点单状态
        count_order = await self.db.get(InventoryCount, count_id)
        if count_order and count_order.status == "draft":
            count_order.status = "counting"

        await self.db.commit()
        return {"success": True, "diff_qty": item.diff_qty}

    async def approve_count(
        self,
        count_id: str,
        approved_by: str,
    ) -> Dict[str, Any]:
        """审批盘点 → 自动调整库存 + 写流水"""
        count_order = await self.db.get(InventoryCount, count_id)
        if not count_order:
            return {"success": False, "message": "盘点单不存在"}
        if count_order.status not in ("counting", "pending_approval"):
            return {"success": False, "message": f"状态 {count_order.status} 不可审批"}

        # 加载明细
        items_stmt = select(InventoryCountItem).where(InventoryCountItem.count_id == count_id)
        items_result = await self.db.execute(items_stmt)
        items = items_result.scalars().all()

        adjusted_count = 0
        total_diff = 0
        for item in items:
            if item.counted_qty is None:
                continue
            diff = item.counted_qty - item.system_qty
            if diff != 0 and item.inventory_id:
                # 调整库存
                inv = await self.db.get(Inventory, item.inventory_id)
                if inv:
                    inv.total_qty = item.counted_qty
                    inv.available_qty = item.counted_qty - (inv.reserved_qty or 0)
                    inv.updated_at = datetime.utcnow()

                # 写流水
                await self.record_transaction(
                    factory_id=count_order.factory_id,
                    material_id=item.material_id,
                    transaction_type="count_diff",
                    quantity=diff,
                    inventory_id=item.inventory_id,
                    batch_code=item.batch_code,
                    reference_type="count_order",
                    reference_id=count_id,
                    operator=approved_by,
                    remark=f"盘点调整: {item.system_qty} → {item.counted_qty}",
                )
                item.adjusted = True
                adjusted_count += 1
                total_diff += abs(diff)

        # 更新盘点单
        count_order.status = "approved"
        count_order.approved_by = approved_by
        count_order.completed_at = datetime.utcnow()
        count_order.diff_items = adjusted_count
        count_order.total_diff_qty = total_diff

        await self.db.commit()
        return {"success": True, "message": f"盘点已审批，调整 {adjusted_count} 项", "adjusted_items": adjusted_count}

    # ============== 物料追溯 ==============

    async def trace_material(
        self,
        factory_id: str,
        material_id: str,
        batch_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """正向/反向追溯"""
        # 入库记录
        in_stmt = select(InboundOrder).where(
            InboundOrder.factory_id == factory_id,
            InboundOrder.material_id == material_id,
        )
        if batch_code:
            in_stmt = in_stmt.where(InboundOrder.batch_code == batch_code)
        in_stmt = in_stmt.order_by(InboundOrder.created_at.desc()).limit(20)
        in_result = await self.db.execute(in_stmt)
        inbound_records = in_result.scalars().all()

        # 出库记录
        out_stmt = select(OutboundOrder).where(
            OutboundOrder.factory_id == factory_id,
            OutboundOrder.material_id == material_id,
        )
        if batch_code:
            out_stmt = out_stmt.where(OutboundOrder.batch_code == batch_code)
        out_stmt = out_stmt.order_by(OutboundOrder.created_at.desc()).limit(20)
        out_result = await self.db.execute(out_stmt)
        outbound_records = out_result.scalars().all()

        # 库存流水
        txn_stmt = select(InventoryTransaction).where(
            InventoryTransaction.factory_id == factory_id,
            InventoryTransaction.material_id == material_id,
        )
        if batch_code:
            txn_stmt = txn_stmt.where(InventoryTransaction.batch_code == batch_code)
        txn_stmt = txn_stmt.order_by(InventoryTransaction.created_at.desc()).limit(30)
        txn_result = await self.db.execute(txn_stmt)
        transactions = txn_result.scalars().all()

        return {
            "material_id": material_id,
            "batch_code": batch_code,
            "inbound_records": [
                {
                    "id": r.id, "code": r.inbound_code, "quantity": r.quantity,
                    "batch_code": r.batch_code, "supplier_id": r.supplier_id,
                    "type": r.inbound_type, "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in inbound_records
            ],
            "outbound_records": [
                {
                    "id": r.id, "code": r.outbound_code, "quantity": r.quantity,
                    "batch_code": r.batch_code, "type": r.outbound_type,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in outbound_records
            ],
            "transactions": [
                {
                    "id": t.id, "type": t.transaction_type, "quantity": t.quantity,
                    "before_qty": t.before_qty, "after_qty": t.after_qty,
                    "batch_code": t.batch_code, "operator": t.operator,
                    "remark": t.remark,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in transactions
            ],
        }

    # ============== FIFO 检查 ==============

    async def check_fifo(self, factory_id: str, material_id: Optional[str] = None) -> Dict[str, Any]:
        """FIFO 合规检查"""
        # 查找该物料的批次（按入库时间排序）
        stmt = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.total_qty > 0,
        )
        if material_id:
            stmt = stmt.where(Inventory.material_id == material_id)
        result = await self.db.execute(stmt)
        inventories = result.scalars().all()

        # 按物料分组，检查批次顺序
        violations = []
        by_material: Dict[str, List] = {}
        for inv in inventories:
            if inv.batch_code:
                by_material.setdefault(inv.material_id, []).append(inv)

        for mat_id, batches in by_material.items():
            if len(batches) <= 1:
                continue
            # 按创建时间排序
            batches.sort(key=lambda x: x.created_at or datetime.min)
            # 如果有多个批次且最早批次仍有库存，标记为潜在 FIFO 风险
            oldest = batches[0]
            if oldest.total_qty > 0 and len(batches) > 1:
                violations.append({
                    "material_id": mat_id,
                    "oldest_batch": oldest.batch_code,
                    "oldest_qty": oldest.total_qty,
                    "newer_batches": len(batches) - 1,
                    "risk": "旧批次仍有库存，新批次已入库",
                })

        return {
            "factory_id": factory_id,
            "material_id": material_id,
            "violations": violations,
            "is_compliant": len(violations) == 0,
        }

    # ============== 库存预警 ==============

    async def get_stock_alerts(self, factory_id: str) -> Dict[str, Any]:
        """库存预警（零库存 / 低库存）"""
        # 零库存
        zero_stmt = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.total_qty <= 0,
        )
        zero_result = await self.db.execute(zero_stmt)
        zero_items = zero_result.scalars().all()

        # 低库存（available_qty < 10 作为默认安全库存）
        low_stmt = select(Inventory).where(
            Inventory.factory_id == factory_id,
            Inventory.available_qty > 0,
            Inventory.available_qty < 10,
        )
        low_result = await self.db.execute(low_stmt)
        low_items = low_result.scalars().all()

        return {
            "factory_id": factory_id,
            "zero_stock": [
                {"material_id": i.material_id, "material_code": i.material_code, "batch_code": i.batch_code}
                for i in zero_items
            ],
            "low_stock": [
                {"material_id": i.material_id, "material_code": i.material_code, "available_qty": i.available_qty, "batch_code": i.batch_code}
                for i in low_items
            ],
            "alert_count": len(zero_items) + len(low_items),
        }
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
        material_id: Optional[str] = None,
        warehouse_id: Optional[str] = None,
    ) -> List[Inventory]:
        """获取库存信息"""
        query = select(Inventory).where(
            Inventory.factory_id == factory_id,
        )

        if material_id:
            query = query.where(Inventory.material_id == material_id)
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
