"""Location Capacity Executor for WMS.

Handles location capacity management including:
- 3D location management (row/column/level)
- Location capacity management
- Location status management
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class LocationCapacityExecutor(BaseWmsExecutor):
    """Execute location capacity management operations."""
    
    def get_operation_name(self) -> str:
        return "location_capacity"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute location capacity operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # get_capacity, update_capacity, get_status, list_locations
                "warehouse_id": str,
                "location_id": Optional[str],
                "capacity": Optional[int],
            }
            
        Returns:
            Location capacity operation result
        """
        operation = context.get("operation", "get_capacity")
        
        if operation == "get_capacity":
            return await self._get_capacity(db, factory_id, context)
        elif operation == "update_capacity":
            return await self._update_capacity(db, factory_id, context)
        elif operation == "get_status":
            return await self._get_status(db, factory_id, context)
        elif operation == "list_locations":
            return await self._list_locations(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _get_capacity(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get location capacity summary."""
        warehouse_id = context.get("warehouse_id")
        location_id = context.get("location_id")
        
        # Base query
        where_clause = "factory_id = :fid"
        params = {"fid": factory_id}
        
        if warehouse_id:
            where_clause += " AND warehouse_id = :wh"
            params["wh"] = warehouse_id
        
        if location_id:
            where_clause += " AND id = :lid"
            params["lid"] = location_id
        
        # Get location summary
        result = await db.execute(text(f"""
            SELECT 
                COUNT(*) as total_locations,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_locations,
                SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END) as inactive_locations,
                SUM(CASE WHEN status = 'maintenance' THEN 1 ELSE 0 END) as maintenance_locations,
                COALESCE(SUM(capacity), 0) as total_capacity,
                COALESCE(SUM(used_capacity), 0) as used_capacity,
                COALESCE(AVG(usage_rate), 0) as avg_usage_rate
            FROM locations
            WHERE {where_clause}
        """), params)
        
        summary = dict(result.first()._mapping)
        
        # Get usage by zone
        result = await db.execute(text(f"""
            SELECT 
                zone,
                COUNT(*) as location_count,
                COALESCE(SUM(capacity), 0) as zone_capacity,
                COALESCE(SUM(used_capacity), 0) as zone_used,
                ROUND(COALESCE(AVG(usage_rate), 0), 2) as avg_usage_rate
            FROM locations
            WHERE {where_clause} AND zone IS NOT NULL
            GROUP BY zone
            ORDER BY zone
        """), params)
        
        zones = [dict(r) for r in result.mappings().all()]
        
        return {
            "success": True,
            "summary": {
                "total_locations": summary["total_locations"] or 0,
                "active_locations": summary["active_locations"] or 0,
                "inactive_locations": summary["inactive_locations"] or 0,
                "maintenance_locations": summary["maintenance_locations"] or 0,
                "total_capacity": summary["total_capacity"] or 0,
                "used_capacity": summary["used_capacity"] or 0,
                "available_capacity": (summary["total_capacity"] or 0) - (summary["used_capacity"] or 0),
                "avg_usage_rate": summary["avg_usage_rate"] or 0,
            },
            "zones": zones,
        }
    
    async def _update_capacity(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update location capacity."""
        location_id = context.get("location_id")
        capacity = context.get("capacity")
        operator = context.get("operator", "system")
        
        if not location_id:
            return {"error": True, "message": "库位 ID 不能为空"}
        
        if capacity is None:
            return {"error": True, "message": "容量不能为空"}
        
        # Check if location exists
        result = await db.execute(text("""
            SELECT id, location_code, capacity FROM locations
            WHERE id = :lid AND factory_id = :fid
        """), {"lid": location_id, "fid": factory_id})
        
        location = result.first()
        if not location:
            return {"error": True, "message": "库位不存在"}
        
        # Update capacity
        await db.execute(text("""
            UPDATE locations
            SET capacity = :capacity,
                updated_at = NOW()
            WHERE id = :lid
        """), {
            "capacity": capacity,
            "lid": location_id,
        })
        
        await db.commit()
        
        return {
            "success": True,
            "action": "update_capacity",
            "location_id": location_id,
            "location_code": location["location_code"],
            "old_capacity": location["capacity"],
            "new_capacity": capacity,
            "operator": operator,
            "message": f"库位 {location['location_code']} 容量已更新",
        }
    
    async def _get_status(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get location status."""
        warehouse_id = context.get("warehouse_id")
        location_id = context.get("location_id")
        
        # Base query
        where_clause = "factory_id = :fid"
        params = {"fid": factory_id}
        
        if warehouse_id:
            where_clause += " AND warehouse_id = :wh"
            params["wh"] = warehouse_id
        
        if location_id:
            where_clause += " AND id = :lid"
            params["lid"] = location_id
        
        # Get location status
        result = await db.execute(text(f"""
            SELECT 
                l.id,
                l.location_code,
                l.location_name,
                l.zone,
                l.row,
                l.column,
                l.level,
                l.location_type,
                l.status,
                l.capacity,
                COALESCE(SUM(i.available_qty), 0) as current_qty,
                CASE 
                    WHEN l.capacity > 0 THEN ROUND(COALESCE(SUM(i.available_qty), 0) * 100.0 / l.capacity, 2)
                    ELSE 0
                END as usage_rate
            FROM locations l
            LEFT JOIN inventory i ON i.location_id = l.id AND i.status = 'available'
            WHERE {where_clause}
            GROUP BY l.id
            ORDER BY l.zone, l.row, l.column, l.level
        """), params)
        
        locations = [dict(r) for r in result.mappings().all()]
        
        # Summary
        status_summary = {
            "active": len([l for l in locations if l["status"] == "active"]),
            "inactive": len([l for l in locations if l["status"] == "inactive"]),
            "maintenance": len([l for l in locations if l["status"] == "maintenance"]),
        }
        
        return {
            "success": True,
            "locations": locations[:100],
            "total": len(locations),
            "summary": status_summary,
        }
    
    async def _list_locations(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """List all locations."""
        warehouse_id = context.get("warehouse_id")
        zone = context.get("zone")
        location_type = context.get("location_type")
        
        # Base query
        where_clause = "factory_id = :fid"
        params = {"fid": factory_id}
        
        if warehouse_id:
            where_clause += " AND warehouse_id = :wh"
            params["wh"] = warehouse_id
        
        if zone:
            where_clause += " AND zone = :zone"
            params["zone"] = zone
        
        if location_type:
            where_clause += " AND location_type = :type"
            params["type"] = location_type
        
        # Get locations
        result = await db.execute(text(f"""
            SELECT 
                id,
                location_code,
                location_name,
                warehouse_id,
                zone,
                row,
                column,
                level,
                location_type,
                capacity,
                status,
                created_at
            FROM locations
            WHERE {where_clause}
            ORDER BY zone, row, column, level
        """), params)
        
        locations = [dict(r) for r in result.mappings().all()]
        
        return {
            "success": True,
            "locations": locations[:200],
            "total": len(locations),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation