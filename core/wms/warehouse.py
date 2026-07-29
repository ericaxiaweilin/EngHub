"""
WMS Warehouse Service - 仓库管理服务 (优化版)
仓库管理模块

功能:
- 仓库配置
- 库位管理
- 库区管理
集成方式: 使用数据库中的 warehouses 和 locations 表
"""

import uuid
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import select, update, delete, insert, and_, func, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Warehouse, Location


class WarehouseType(str, Enum):
    """仓库类型"""
    RAW_MATERIAL = "raw_material"     # 原料仓
    FINISHED_GOODS = "finished_goods"  # 成品仓
    WIP = "wip"                       # 在制品仓
    RETURN = "return"                 # 退货仓
    QC_HOLD = "qc_hold"               # 待验仓


class LocationType(str, Enum):
    """库位类型"""
    RACK = "rack"         # 货架
    FLOOR = "floor"       # 地面
    BUFFER = "buffer"     # 暂存区


class WarehouseStatus(str, Enum):
    """仓库状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class WarehouseService:
    """
    仓库服务 (数据库集成版)
    
    核心功能:
    - 仓库配置 (持久化到数据库)
    - 库位管理
    - 库区管理
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
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
        """创建仓库 - 持久化到数据库"""
        warehouse_id = str(uuid.uuid4())
        
        warehouse_data = {
            "id": warehouse_id,
            "factory_id": factory_id,
            "warehouse_code": warehouse_code,
            "warehouse_name": warehouse_name,
            "warehouse_type": warehouse_type,
            "address": address,
            "manager_id": manager_id,
            "status": WarehouseStatus.ACTIVE.value,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        # 持久化到 warehouses 表
        from database.models import Warehouse
        insert_stmt = insert(Warehouse).values(**warehouse_data)
        result = await self.db.execute(insert_stmt)
        await self.db.commit()
        
        return warehouse_data
    
    async def create_location(
        self,
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
        """创建库位 - 持久化到数据库"""
        location_id = str(uuid.uuid4())
        
        location_data = {
            "id": location_id,
            "warehouse_id": warehouse_id,
            "location_code": location_code,
            "location_name": location_name,
            "location_type": location_type,
            "zone": zone,
            "row": row,
            "column": column,
            "level": level,
            "capacity": capacity,
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        # 持久化到 locations 表
        insert_stmt = insert(Location).values(**location_data)
        result = await self.db.execute(insert_stmt)
        await self.db.commit()
        
        return location_id
    
    async def get_warehouse(self, warehouse_id: str) -> Optional[Dict[str, Any]]:
        """获取仓库详情 - 从数据库查询"""
        query = select(Warehouse).where(Warehouse.id == warehouse_id)
        result = await self.db.execute(query)
        warehouse = result.scalar_one_or_none()
        
        if warehouse:
            return {
                "id": warehouse.id,
                "warehouse_code": warehouse.warehouse_code,
                "warehouse_name": warehouse.warehouse_name,
                "factory_id": warehouse.factory_id,
                "warehouse_type": warehouse.warehouse_type,
                "address": warehouse.address,
                "status": warehouse.status,
                "manager_id": warehouse.manager_id,
                "created_by": warehouse.created_by,
                "created_at": warehouse.created_at,
                "updated_at": warehouse.updated_at,
            }
        return None
    
    async def list_warehouses(
        self,
        factory_id: str,
        warehouse_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取仓库列表 - 从数据库查询"""
        query = select(Warehouse).where(Warehouse.factory_id == factory_id)
        
        if warehouse_type:
            query = query.where(Warehouse.warehouse_type == warehouse_type)
        if status:
            query = query.where(Warehouse.status == status)
        
        result = await self.db.execute(query)
        warehouses = result.scalars().all()
        
        return [
            {
                "id": w.id,
                "warehouse_code": w.warehouse_code,
                "warehouse_name": w.warehouse_name,
                "factory_id": w.factory_id,
                "warehouse_type": w.warehouse_type,
                "address": w.address,
                "status": w.status,
                "manager_id": w.manager_id,
                "created_by": w.created_by,
                "created_at": w.created_at,
                "updated_at": w.updated_at,
            }
            for w in warehouses
        ]
    
    async def update_warehouse(self, warehouse_id: str, updates: Dict[str, Any]) -> bool:
        """更新仓库信息"""
        update_data = {k: v for k, v in updates.items() if k != 'id'}
        update_data['updated_at'] = datetime.utcnow()
        update_stmt = update(Warehouse).where(Warehouse.id == warehouse_id).values(update_data)
        result = await self.db.execute(update_stmt)
        await self.db.commit()
        return result.rowcount > 0
    
    async def delete_warehouse(self, warehouse_id: str) -> bool:
        """逻辑删除仓库（标记为inactive）"""
        update_stmt = update(Warehouse).where(Warehouse.id == warehouse_id).values(
            status=WarehouseStatus.INACTIVE.value,
            updated_at=datetime.utcnow()
        )
        result = await self.db.execute(update_stmt)
        await self.db.commit()
        return result.rowcount > 0
        
    async def get_location(self, location_id: str) -> Optional[Dict[str, Any]]:
        """获取库位详情 - 从数据库查询"""
        query = select(Location).where(Location.id == location_id)
        result = await self.db.execute(query)
        loc = result.scalar_one_or_none()
        
        if loc:
            return {
                "id": loc.id,
                "location_code": loc.location_code,
                "location_name": loc.location_name,
                "warehouse_id": loc.warehouse_id,
                "location_type": loc.location_type,
                "zone": loc.zone,
                "row": loc.row,
                "column": loc.column,
                "level": loc.level,
                "capacity": loc.capacity,
                "status": loc.status,
                "created_at": loc.created_at,
                "updated_at": loc.updated_at,
            }
        return None
    
    async def list_locations(
        self,
        warehouse_id: str,
        zone: Optional[str] = None,
        location_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取库位列表 - 从数据库查询"""
        query = select(Location).where(Location.warehouse_id == warehouse_id)
        
        if zone:
            query = query.where(Location.zone == zone)
        if location_type:
            query = query.where(Location.location_type == location_type)
        
        result = await self.db.execute(query)
        locations = result.scalars().all()
        
        return [
            {
                "id": loc.id,
                "location_code": loc.location_code,
                "location_name": loc.location_name,
                "warehouse_id": loc.warehouse_id,
                "location_type": loc.location_type,
                "zone": loc.zone,
                "row": loc.row,
                "column": loc.column,
                "level": loc.level,
                "capacity": loc.capacity,
                "status": loc.status,
                "created_at": loc.created_at,
            }
            for loc in locations
        ]
    
    async def get_warehouse_capacity_summary(
        self,
        warehouse_id: str,
    ) -> Dict[str, Any]:
        """获取仓库容量汇总 - 计算真实数据"""
        from database.models import Inventory
        
        # 查询仓库的总库位数
        location_query = select(func.count()).where(Location.warehouse_id == warehouse_id)
        total_locs = await self.db.execute(location_query)
        total_locations = int(total_locs.scalar() or 0)
        
        # 查询活跃库位数
        active_loc_query = select(func.count()).where(
            and_(Location.warehouse_id == warehouse_id, Location.status == 'active')
        )
        active_locs = await self.db.execute(active_loc_query)
        active_locations = int(active_locs.scalar() or 0)
        
        # 查询已使用的库位（有库存记录的）
        used_loc_query = select(func.count()).distinct().where(
            and_(
                Inventory.warehouse_id == warehouse_id,
                Inventory.status == "available"  #直接用字符串常量，避免依赖InventoryStatus枚举
            )
        )
        used_result = await self.db.execute(used_loc_query)
        used_locations = int(used_result.scalar() or 0)
        
        # 查询总容量（各库位容量之和）
        capacity_query = select(func.sum(func.cast(Location.capacity, Integer))).where(
            Location.warehouse_id == warehouse_id
        )
        total_capacity_val = int((await self.db.execute(capacity_query)).scalar() or 0)
        
        # 查询已用容量（当前库存总量）
        inv_query = select(func.sum(func.cast(Inventory.total_qty, Integer))).where(
            Inventory.warehouse_id == warehouse_id
        )
        used_capacity = int((await self.db.execute(inv_query)).scalar() or 0)
        
        summary = {
            "warehouse_id": warehouse_id,
            "total_locations": total_locations,
            "active_locations": active_locations,
            "available_locations": max(0, active_locations - used_locations),
            "used_locations": used_locations,
            "total_capacity": total_capacity_val,
            "used_capacity": used_capacity,
            "available_capacity": max(0, total_capacity_val - used_capacity),
            "utilization_rate": round(float(used_capacity / max(total_capacity_val, 1)) * 100, 2) if total_capacity_val > 0 else 0.0,
        }
        
        return summary