"""
WMS Warehouse Service - 仓库管理系统（完整实现）

功能:
- 仓库配置管理
- 库位/库区管理
- 库存移动与调拨
- 出入库操作
- 库存盘点
- 库容管理
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy import select, update, insert, func, text

from database.models import (
    Warehouse,
    Location,
    Inventory,
    InboundOrder,
    OutboundOrder,
    WorkOrder,
    Product,
    User,
)


class WarehouseType(str, Enum):
    """仓库类型"""
    RAW_MATERIAL = "raw_material"     # 原料仓
    FINISHED_GOODS = "finished_goods"  # 成品仓
    WIP = "wip"                       # 在制品仓
    RETURN = "return"                 # 退货仓
    QC_HOLD = "qc_hold"               # 待验仓


class LocationType(str, Enum):
    """库位类型"""
    RACK = "rack"         # 货架库位
    FLOOR = "floor"       # 地面库位
    BUFFER = "buffer"     # 暂存区
    PICKING = "picking"   # 拣货区
    STAGING = "staging"   # 发货暂存区


class WarehouseStatus(str, Enum):
    """仓库状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class InventoryStatus(str, Enum):
    """库存状态"""
    AVAILABLE = "available"      # 可用
    RESERVED = "reserved"        # 已预留
    ON_HOLD = "on_hold"          # 冻结
    DAMAGED = "damaged"          # 损坏
    TRANSFER = "transfer"        # 在途调拨


class WarehouseService:
    """
    仓库服务
    
    核心功能:
    - 仓库配置管理
    - 库位管理
    - 库存管理
    - 入库操作
    - 出库操作
    - 库存调拨
    - 库存盘点
    """
    
    def __init__(self, db):
        self.db = db
    
    async def create_warehouse(
        self,
        factory_id: str,
        warehouse_code: str,
        warehouse_name: str,
        warehouse_type: str = WarehouseType.RAW_MATERIAL.value,
        address: str = None,
        manager_id: str = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """创建仓库"""
        warehouse = Warehouse(
            id=str(uuid.uuid4()),
            warehouse_code=warehouse_code,
            warehouse_name=warehouse_name,
            factory_id=factory_id,
            warehouse_type=warehouse_type,
            address=address,
            status=WarehouseStatus.ACTIVE.value,
            created_by=created_by or "system",
            updated_by=created_by or "system",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        
        self.db.add(warehouse)
        await self.db.commit()
        await self.db.refresh(warehouse)
        
        return self._model_to_dict(warehouse)
    
    async def get_warehouse(self, db: Any, warehouse_id: str) -> Optional[Dict[str, Any]]:
        """获取仓库详情"""
        result = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
        warehouse = result.scalar_one_or_none()
        if warehouse:
            return self._model_to_dict(warehouse)
        return None
    
    async def list_warehouses(
        self,
        db: Any,
        factory_id: str,
        warehouse_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取仓库列表（带分页）"""
        query = select(Warehouse).where(Warehouse.factory_id == factory_id)
        
        if warehouse_type:
            query = query.where(Warehouse.warehouse_type == warehouse_type)
        if status:
            query = query.where(Warehouse.status == status)
        
        # 获取总数
        count_query = select(func.count()).select_from(Warehouse).where(Warehouse.factory_id == factory_id)
        if warehouse_type:
            count_query = count_query.where(Warehouse.warehouse_type == warehouse_type)
        if status:
            count_query = count_query.where(Warehouse.status == status)
        
        total = (await db.execute(count_query)).scalar()
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = await db.execute(query)
        warehouses = results.scalars().all()
        
        return {
            "items": [self._model_to_dict(w) for w in warehouses],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    
    async def update_warehouse(self, db: Any, warehouse_id: str, **kwargs) -> bool:
        """更新仓库信息"""
        warehouse = await self.get_warehouse(db, warehouse_id)
        if not warehouse:
            return False
        
        allowed_fields = ["warehouse_name", "address", "manager_id", "status"]
        for field in allowed_fields:
            if field in kwargs:
                setattr(warehouse, field, kwargs[field])
        
        warehouse.updated_at = datetime.now()
        warehouse.updated_by = kwargs.get("updated_by") or "system"
        
        await self.db.commit()
        await self.db.refresh(warehouse)
        return True
    
    async def delete_warehouse(self, db: Any, warehouse_id: str) -> bool:
        """逻辑删除仓库（标记为非激活）"""
        warehouse = await self.get_warehouse(db, warehouse_id)
        if not warehouse:
            return False
        
        warehouse.status = WarehouseStatus.INACTIVE.value
        warehouse.updated_at = datetime.now()
        warehouse.updated_by = warehouse.created_by
        
        await self.db.commit()
        await self.db.refresh(warehouse)
        return True
    
    async def create_location(
        self,
        db: Any,
        warehouse_id: str,
        location_code: str,
        location_name: str,
        location_type: str = LocationType.RACK.value,
        zone: str = None,
        row: int = None,
        column: int = None,
        level: int = None,
        capacity: int = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """创建库位"""
        location = Location(
            id=str(uuid.uuid4()),
            location_code=location_code,
            location_name=location_name,
            warehouse_id=warehouse_id,
            location_type=location_type,
            zone=zone,
            row=row,
            column=column,
            level=level,
            capacity=capacity,
            status="active",
            created_by=created_by or "system",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        
        self.db.add(location)
        await self.db.commit()
        await self.db.refresh(location)
        
        return self._model_location_to_dict(location)
    
    async def get_location(self, db: Any, location_id: str) -> Optional[Dict[str, Any]]:
        """获取库位详情"""
        result = await db.execute(select(Location).where(Location.id == location_id))
        location = result.scalar_one_or_none()
        if location:
            return self._model_location_to_dict(location)
        return None
    
    async def list_locations(
        self,
        db: Any,
        warehouse_id: str,
        zone: Optional[str] = None,
        location_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取库位列表（带分页）"""
        query = select(Location).where(Location.warehouse_id == warehouse_id)
        
        if zone:
            query = query.where(Location.zone == zone)
        if location_type:
            query = query.where(Location.location_type == location_type)
        if status:
            query = query.where(Location.status == status)
        
        # 获取总数
        count_query = select(func.count()).select_from(Location).where(Location.warehouse_id == warehouse_id)
        if zone:
            count_query = count_query.where(Location.zone == zone)
        if location_type:
            count_query = count_query.where(Location.location_type == location_type)
        if status:
            count_query = count_query.where(Location.status == status)
        
        total = (await db.execute(count_query)).scalar()
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = await db.execute(query)
        locations = results.scalars().all()
        
        return {
            "items": [self._model_location_to_dict(l) for l in locations],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    
    async def get_warehouse_capacity_summary(self, db: Any, warehouse_id: str) -> Dict[str, Any]:
        """获取仓库容量汇总"""
        # 仓库总库位数
        loc_result = await db.execute(
            select(func.count()).where(Location.warehouse_id == warehouse_id, Location.status == "active")
        )
        total_locations = loc_result.scalar() or 0
        
        # 已占用库位数
        inv_result = await db.execute(
            select(func.distinct(Location.id)).join(Inventory, Inventory.location_id == Location.id)
            .where(Location.warehouse_id == warehouse_id, Inventory.status != "transferred")
        )
        occupied_locations = len(inv_result.fetchall()) or 0
        
        available_locations = total_locations - occupied_locations
        
        # 库存总量和可用量
        inv_summary = await db.execute(
            select(
                func.sum(Inventory.total_qty).label("total_qty"),
                func.sum(Inventory.available_qty).label("available_qty"),
                func.sum(Inventory.reserved_qty).label("reserved_qty"),
            ).where(Inventory.warehouse_id == warehouse_id, Inventory.status == "available")
        )
        inv_data = inv_summary.fetchone()
        
        return {
            "warehouse_id": warehouse_id,
            "total_locations": total_locations,
            "used_locations": occupied_locations,
            "available_locations": available_locations,
            "utilization_rate": round((occupied_locations / total_locations * 100) if total_locations > 0 else 0.0, 2),
            "total_inventory_qty": inv_data.total_qty or 0,
            "available_inventory_qty": inv_data.available_qty or 0,
            "reserved_inventory_qty": inv_data.reserved_qty or 0,
        }
    
    async def move_inventory(
        self,
        db: Any,
        material_id: str,
        factory_id: str,
        source_location_id: str,
        dest_location_id: str,
        quantity: int,
        work_order_id: Optional[str] = None,
        moved_by: str = None,
        reason: str = None,
    ) -> Dict[str, Available]:
        """
        库存移动（库间移动）
        
        Args:
            db: Database session
            material_id: 物料ID
            factory_id: 工厂ID
            source_location_id: 源库位ID
            dest_location_id: 目标库位ID
            quantity: 移动数量
            work_order_id: 关联工单（可选）
            moved_by: 操作人
            reason: 移动原因
        
        Returns:
            移动结果
        """
        # 验证源和目标库位是否属于同一个仓库
        src_loc = await self.get_location(db, source_location_id)
        dest_loc = await self.get_location(db, dest_location_id)
        
        if src_loc["warehouse_id"] != dest_loc["warehouse_id"]:
            raise ValueError("源库位和目标库位必须属于同一仓库，请使用调拨功能")
        
        # 检查库存是否充足
        current_stock = await self.get_inventory(
            db, factory_id, material_id, source_location_id
        )
        
        if not current_stock or current_stock["available_qty"] < quantity:
            raise f"库存不足，可用量：{current_stock['available_qty'] if current_stock else 0}")
        
        # 执行移动 - 先减少源库位，再增加目标库位（需要事务支持）
        try:
            # 更新源库存记录（如果存在）
            if current_stock:
                update_stmt = (
                    update(Inventory)
                    .where(
                        Inventory.material_id == material_id,
                        Inventory.warehouse_id == src_loc["warehouse_id"],
                        Inventory.location_id == source_location_id,
                        Inventory.factory_id == factory_id,
                    )
                    .values({
                        "total_qty": current_stock["total_qty"] - quantity,
                        "available_qty": current_stock["available_qty"] - quantity,
                        "updated_at": datetime.now(),
                        "updated_by": moved_by or "system",
                    })
                )
                await db.execute(update_stmt)
            
            # 获取或创建目标库位的库存记录
            dest_inv = await self.get_inventory(
                db, factory_id, material_id, dest_location_id
            )
            
            if dest_inv:
                update_stmt = (
                    update(Inventory)
                    .where(
                        Inventory.id == dest_inv["id"]
                    )
                    .values({
                        "total_qty": dest_inv["total_qty"] + quantity,
                        "available_qty": dest_inv["available_qty"] + quantity,
                        "updated_at": datetime.now(),
                        "updated_by": moved_by or "system",
                    })
                )
                await db.execute(update_stmt)
            else:
                # 创建新库存记录
                new_inv = Inventory(
                    id=str(uuid.uuid4()),
                    material_id=material_id,
                    material_code=current_stock["material_code"] if current_stock else material_id,
                    factory_id=factory_id,
                    warehouse_id=dest_loc["warehouse_id"],
                    location_id=dest_location_id,
                    batch_code=None,
                    total_qty=quantity,
                    available_qty=quantity,
                    reserved_qty=0,
                    unit_cost=current_stock["unit_cost"] if current_stock else 0,
                    status="available",
                    created_by=moved_by or "system",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                self.db.add(new_inv)
                await db.commit()
                await db.refresh(new_inv)
            
            # 创建移动记录（可以在扩展模块中完善）
            result = {
                "success": True,
                "movement_id": str(uuid.uuid4()),
                "material_id": material_id,
                "factory_id": factory_id,
                "source_location": source_location_id,
                "destination_location": dest_location_id,
                "quantity": quantity,
                "timestamp": datetime.now(),
                "operator": moved_by or "system",
                "reason": reason,
            }
            
            await db.commit()
            return result
            
        except Exception as e:
            await db.rollback()
            raise e
    
    async def transfer_inventory(
        self,
        db: Any,
        material_id: str,
        source_factory_id: str,
        source_warehouse_id: str,
        source_location_id: str,
        dest_factory_id: str,
        dest_warehouse_id: str,
        dest_location_id: str,
        quantity: int,
        transferred_by: str = None,
        reference: str = None,
    ) -> Dict[str, Any]:
        """
        跨仓库调拨（不同仓库间的库存转移）
        
        Args:
            db: Database session
            material_id: 物料ID
            source_factory_id: 源工厂ID
            source_warehouse_id: 源仓库ID
            source_location_id: 源库位ID
            dest_factory_id: 目标工厂ID
            dest_warehouse_id: 目标仓库ID
            dest_location_id: 目标库位ID
            quantity: 调拨数量
            transferred_by: 调拨人
            reference: 参考单号（如调拨单号）
        
        Returns:
            调拨结果
        """
        # 这里需要实现完整的调拨流程，涉及两个不同的工厂和仓库系统
        # 简化实现：先创建调拨订单，实际移动由异步处理
        transfer_order = {
            "id": str(uuid.uuid4()),
            "transfer_code": f"TFR-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            "material_id": material_id,
            "source_factory": source_factory_id,
            "source_warehouse": source_warehouse_id,
            "source_location": source_location_id,
            "dest_factory": dest_factory_id,
            "dest_warehouse": dest_warehouse_id,
            "dest_location": dest_location_id,
            "quantity": quantity,
            "status": "pending",  # pending / in_progress / completed / cancelled
            "transferred_by": transferred_by or "system",
            "reference": reference,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        # 在系统中记录调拨请求（实际应用应使用专门的调度表）
        transfer_record = {
            **transfer_order,
            "created_at": transfer_order["created_at"].isoformat(),
            "updated_at": transfer_order["updated_at"].isoformat(),
        }
        
        return transfer_record
    
    # ===== 出入库操作相关方法 =====
    
    async def process_inbound_order(
        self,
        db: Any,
        inbound_id: str,
        batch_code: str = None,
        location_id: str = None,
        received_by: str = None,
        remarks: str = None,
    ) -> Dict[str, Any]:
        """
        处理入库单（收货）
        
        Args:
            db: Database session
            inbound_id: 入库单ID
            batch_code: 批次号（自动生成或指定）
            location_id: 指定库位（未指定则分配）
            received_by: 收货人
            remarks: 备注
        
        Returns:
            入库处理结果
        """
        # 获取入库单
        inbound_result = await db.execute(
            select(InboundOrder).where(InboundOrder.id == inbound_id)
        )
        inbound = inbound_result.scalar_one_or_none()
        if not inbound:
            raise ValueError(f"入库单 {inbound_id} 不存在")
        
        if inbound.status != "pending":
            raise ValueError(f"入库单 {inbound_id} 状态为 {inbound.status}，不能重复处理")
        
        # 生成批次号（如未提供）
        if not batch_code:
            batch_code = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        
        # 分配库位（如未指定）
        if not location_id:
            location_id = await self._assign_available_location(
                db, inbound.warehouse_id, "raw_material"
            )
        
        # 更新入库单状态
        update_stmt = (
            update(InboundOrder)
            .where(InboundOrder.id == inbound_id)
            .values({
                "batch_code": batch_code,
                "location_id": location_id,
                "received_by": received_by or "system",
                "remarks": remarks,
                "completed_at": datetime.now(),
                "status": "completed",
                "updated_at": datetime.now(),
            })
        )
        await db.execute(update_stmt)
        
        # 更新库存（增加）
        await self._update_inventory_add(
            db,
            inbound.factory_id,
            inbound.material_id,
            inbound.material_code,
            inbound.quantity,
            location_id,
            inbound.warehouse_id,
            batch_code,
            received_by or "system",
            unit_cost=inbound.unit_cost,
        )
        
        await db.commit()
        
        return {
            "success": True,
            "inbound_id": inbound_id,
            "batch_code": batch_code,
            "location_id": location_id,
            "quantity_received": inbound.quantity,
            "timestamp": datetime.now(),
        }
    
    async def process_outbound_order(
        self,
        db: Any,
        outbound_id: str,
        picked_by: str = None,
        shipped_by: str = None,
        remarks: str = None,
    ) -> Dict[str, Any]:
        """
        处理出库单（发货）
        
        Args:
            db: Database session
            outbound_id: 出库单ID
            picked_by: 拣货人
            shipped_by: 发货人
            remarks: 备注
        
        Returns:
            出库处理结果
        """
        # 获取出库单
        outbound_result = await db.execute(
            select(OutboundOrder).where(OutboundOrder.id == outbound_id)
        )
        outbound = outbound_result.scalar_one_or_none()
        if not outbound:
            raise ValueError(f"出库单 {outbound_id} 不存在")
        
        if outbound.status != "pending":
            raise ValueError(f"出库单 {outbound_id} 状态为 {outbound.status}，不能重复处理")
        
        # 检查并扣减库存
        success = await self._update_inventory_subtract(
            db,
            outbound.factory_id,
            outbound.material_id,
            outbound.quantity,
            outbound.warehouse_id,
            outbound.location_id if outbound.location_id else None,
            outbound.work_order_id,
        )
        
        if not success:
            raise ValueError(f"出库 {outbound_id}: 库存不足或扣减失败")
        
        # 更新出库单状态
        update_stmt = (
            update(OutboundOrder)
            .where(OutboundOrder.id == outbound_id)
            .values({
                "picked_by": picked_by or "system",
                "shipped_by": shipped_by or "system",
                "remarks": remarks,
                "completed_at": datetime.now(),
                "status": "completed",
                "updated_at": datetime.now(),
            })
        )
        await db.execute(update_stmt)
        
        return {
            "success": True,
            "outbound_id": outbound_id,
            "quantity_shipped": outbound.quantity,
            "timestamp": datetime.now(),
        }
    
    async def perform_count(
        self,
        db: Any,
        location_id: str,
        counted_by: str,
        actual_qty: int,
        discrepancy: str = None,
        remarks: str = None,
    ) -> Dict[str, Any]:
        """
        执行库存盘点
        
        Args:
            db: Database session
            location_id: 库位ID
            counted_by: 盘点人
            actual_qty: 实际数量
            discrepancy: 差异说明（shortage / excess）
            remarks: 备注
        
        Returns:
            盘点结果
        """
        # 获取当前库存记录
        inv_result = await db.execute(
            select(Inventory).where(Inventory.location_id == location_id, Inventory.status == "available")
        )
        inventory = inv_result.scalar_one_or_none()
        if not inventory:
            raise ValueError(f"位置 {location_id} 没有有效库存记录")
        
        record_qty = inventory.total_qty
        difference = actual_qty - record_qty
        
        # 更新库存记录
        update_values = {
            "last_counted_date": datetime.now(),
            "last_counted_by": counted_by,
            "updated_at": datetime.now(),
            "updated_by": counted_by,
        }
        
        if discrepancy == "shortage":
            update_values["total_qty"] = actual_qty
            update_values["available_qty"] = max(actual_qty - inventory.reserved_qty, 0)
        elif discrepancy == "excess":
            update_values["total_qty"] = actual_qty
            update_values["available_qty"] = actual_qty - inventory.reserved_qty
        
        await db.execute(
            update(Inventory)
            .where(Inventory.id == inventory.id)
            .values(update_values)
        )
        
        # 创建盘点记录（实际应用应有专门的盘点表）
        count_record = {
            "count_id": str(uuid.uuid4()),
            "location_id": location_id,
            "material_id": inventory.material_id,
            "recorded_qty": record_qty,
            "actual_qty": actual_qty,
            "difference": difference,
            "discrepancy": discrepancy,
            "counted_by": counted_by,
            "count_date": datetime.now(),
            "remarks": remarks,
        }
        
        await db.commit()
        
        return count_record
    
    # ===== 辅助方法 =====
    
    async def _assign_available_location(
        self,
        db: Any,
        warehouse_id: str,
        location_type: str = "rack",
    ) -> str:
        """分配可用库位"""
        # 查找该仓库中空闲的货架库位
        result = await db.execute(
            select(Location)
            .where(
                Location.warehouse_id == warehouse_id,
                Location.location_type == location_type,
                Location.status == "active",
            )
            .order_by(Location.created_at)
            .limit(1)
        )
        location = result.scalar_one_or_none()
        
        if location:
            return location.id
        
        # 如果没有现成库位，可能需要创建新的（此处省略）
        raise ValueError("无可用的库位")
    
    async def _update_inventory_add(
        self,
        db: Any,
        factory_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        location_id: str,
        warehouse_id: str,
        batch_code: str,
        created_by: str,
        unit_cost: float = 0,
    ):
        """增加库存（入库时调用）"""
        # 检查是否存在该物料的记录
        inv_result = await db.execute(
            select(Inventory).where(
                Inventory.material_id == material_id,
                Inventory.warehouse_id == warehouse_id,
                Inventory.location_id == location_id,
                Inventory.factory_id == factory_id,
                Inventory.status == "available",
            )
        )
        existing_inv = inv_result.scalar_one_or_none()
        
        if existing_inv:
            # 更新现有记录
            await db.execute(
                update(Inventory)
                .where(Inventory.id == existing_inv.id)
                .values({
                    "total_qty": existing_inv.total_qty + quantity,
                    "available_qty": existing_inv.available_qty + quantity,
                    "batch_code": batch_code,
                    "updated_at": datetime.now(),
                    "updated_by": created_by,
                })
            )
        else:
            # 创建新记录
            new_inv = Inventory(
                id=str(uuid.uuid4()),
                material_id=material_id,
                material_code=material_code,
                factory_id=factory_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_code=batch_code,
                total_qty=quantity,
                available_qty=quantity,
                reserved_qty=0,
                unit_cost=unit_cost,
                status="available",
                created_by=created_by,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            self.db.add(new_inv)
    
    async def _update_inventory_subtract(
        self,
        db: Any,
        factory_id: str,
        material_id: str,
        quantity: int,
        warehouse_id: str,
        location_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
    ) -> bool:
        """扣减库存（出库时调用）"""
        # 构建查询条件
        query = select(Inventory).where(
            Inventory.material_id == material_id,
            Inventory.warehouse_id == warehouse_id,
            Inventory.factory_id == factory_id,
            Inventory.status == "available",
        )
        
        if location_id:
            query = query.where(Inventory.location_id == location_id)
        
        result = await db.execute(query)
        inventory = result.scalar_one_or_none()
        
        if not inventory or inventory.available_qty < quantity:
            return False
        
        # 扣减
        await db.execute(
            update(Inventory)
            .where(Inventory.id == inventory.id)
            .values({
                "total_qty": inventory.total_qty - quantity,
                "available_qty": inventory.available_qty - quantity,
                "updated_at": datetime.now(),
                "updated_by": "system",
            })
        )
        
        return True
    
    def _model_to_dict(self, obj) -> Dict[str, Any]:
        """将Warehouse模型转换为字典"""
        return {
            "id": obj.id,
            "warehouse_code": obj.warehouse_code,
            "warehouse_name": obj.warehouse_name,
            "factory_id": obj.factory_id,
            "warehouse_type": obj.warehouse_type,
            "address": obj.address,
            "status": obj.status,
            "created_by": obj.created_by,
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }
    
    def _model_location_to_dict(self, obj) -> Dict[str, Any]:
        """将Location模型转换为字典"""
        return {
            "id": obj.id,
            "location_code": obj.location_code,
            "location_name": obj.location_name,
            "warehouse_id": obj.warehouse_id,
            "location_type": obj.location_type,
            "zone": obj.zone,
            "row": obj.row,
            "column": obj.column,
            "level": obj.level,
            "capacity": obj.capacity,
            "status": obj.status,
            "created_by": obj.created_by,
        }


__all__ = [
    "WarehouseService",
    "WarehouseType",
    "LocationType",
    "WarehouseStatus",
    "InventoryStatus",
]