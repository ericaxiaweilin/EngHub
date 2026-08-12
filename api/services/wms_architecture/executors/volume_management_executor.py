"""Volume Management Executor for WMS.

Handles volume-based inventory management including:
- Volume tracking (cubic meters)
- Volume-based capacity management
- Volume-weight calculations
- Space utilization analysis
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class VolumeManagementExecutor(BaseWmsExecutor):
    """Execute volume-based inventory management operations."""
    
    def get_operation_name(self) -> str:
        return "volume_management"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute volume management operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # track_volume, get_volume_summary, calculate_shipping_volume, get_space_utilization
                "material_id": Optional[str],
                "batch_code": Optional[str],
                "warehouse_id": Optional[str],
                "quantity": Optional[float],
                "length": Optional[float],
                "width": Optional[float],
                "height": Optional[float],
                "weight": Optional[float],
            }
            
        Returns:
            Volume management operation result
        """
        operation = context.get("operation", "get_volume_summary")
        
        if operation == "track_volume":
            return await self._track_volume(db, factory_id, context)
        elif operation == "get_volume_summary":
            return await self._get_volume_summary(db, factory_id, context)
        elif operation == "calculate_shipping_volume":
            return await self._calculate_shipping_volume(db, factory_id, context)
        elif operation == "get_space_utilization":
            return await self._get_space_utilization(db, factory_id, context)
        elif operation == "update_volume":
            return await self._update_volume(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _track_volume(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Track volume for inventory items."""
        material_id = context.get("material_id")
        batch_code = context.get("batch_code")
        quantity = context.get("quantity", 0)
        length = context.get("length")
        width = context.get("width")
        height = context.get("height")
        weight = context.get("weight")
        
        if not material_id:
            return {"error": True, "message": "物料 ID 不能为空"}
        
        if quantity <= 0:
            return {"error": True, "message": "数量必须大于 0"}
        
        # Get material info
        result = await db.execute(text("""
            SELECT id, material_code, material_name, unit, volume_per_unit, weight_per_unit
            FROM materials WHERE factory_id = :fid AND id = :mid
        """), {"fid": factory_id, "mid": material_id})
        
        material = result.first()
        if not material:
            return {"error": True, "message": "物料不存在"}
        
        mat_dict = dict(material._mapping)
        
        # Calculate volume
        if length and width and height:
            # Use provided dimensions
            unit_volume = length * width * height
            total_volume = unit_volume * quantity
        elif mat_dict.get("volume_per_unit"):
            # Use material's default volume
            unit_volume = mat_dict["volume_per_unit"]
            total_volume = unit_volume * quantity
        else:
            # Estimate based on weight (assuming density ~500 kg/m³ for general goods)
            unit_weight = mat_dict.get("weight_per_unit") or 1.0
            estimated_volume = (unit_weight * quantity) / 500.0
            total_volume = estimated_volume
            unit_volume = estimated_volume / quantity if quantity > 0 else 0
        
        # Calculate weight
        if weight:
            total_weight = weight * quantity
        elif mat_dict.get("weight_per_unit"):
            total_weight = mat_dict["weight_per_unit"] * quantity
        else:
            total_weight = total_volume * 500.0  # Estimate
        
        return {
            "success": True,
            "material_id": material_id,
            "material_code": mat_dict.get("material_code"),
            "material_name": mat_dict.get("material_name"),
            "quantity": quantity,
            "unit": mat_dict.get("unit", "pcs"),
            "volume_per_unit": round(unit_volume, 6),
            "total_volume": round(total_volume, 6),
            "weight_per_unit": round(total_weight / quantity, 6) if quantity > 0 else 0,
            "total_weight": round(total_weight, 6),
            "calculation_method": "dimensions" if (length and width and height) else ("material_default" if mat_dict.get("volume_per_unit") else "estimated"),
        }
    
    async def _get_volume_summary(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get volume summary for factory."""
        warehouse_id = context.get("warehouse_id")
        
        # Base query
        where_clause = "factory_id = :fid AND available_qty > 0"
        params = {"fid": factory_id}
        
        if warehouse_id:
            where_clause += " AND warehouse_id = :wh"
            params["wh"] = warehouse_id
        
        # Get volume summary
        result = await db.execute(text(f"""
            SELECT 
                COUNT(*) as sku_count,
                COALESCE(SUM(i.available_qty * COALESCE(i.volume_per_unit, 0.001)), 0) as total_volume,
                COALESCE(SUM(i.available_qty * COALESCE(i.weight_per_unit, 0.5)), 0) as total_weight,
                COALESCE(AVG(COALESCE(i.volume_per_unit, 0.001)), 0) as avg_volume_per_unit,
                COALESCE(AVG(COALESCE(i.weight_per_unit, 0.5)), 0) as avg_weight_per_unit
            FROM inventory i
            WHERE {where_clause}
        """), params)
        
        summary = dict(result.first()._mapping)
        
        # Get volume by warehouse
        result = await db.execute(text(f"""
            SELECT 
                warehouse_id,
                COUNT(*) as sku_count,
                COALESCE(SUM(i.available_qty * COALESCE(i.volume_per_unit, 0.001)), 0) as total_volume,
                COALESCE(SUM(i.available_qty * COALESCE(i.weight_per_unit, 0.5)), 0) as total_weight
            FROM inventory i
            WHERE {where_clause}
            GROUP BY warehouse_id
            ORDER BY total_volume DESC
        """), params)
        
        by_warehouse = [dict(r) for r in result.mappings().all()]
        
        # Get top volume items
        result = await db.execute(text(f"""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                COALESCE(i.volume_per_unit, 0.001) as volume_per_unit,
                (i.available_qty * COALESCE(i.volume_per_unit, 0.001)) as total_volume,
                COALESCE(i.weight_per_unit, 0.5) as weight_per_unit,
                (i.available_qty * COALESCE(i.weight_per_unit, 0.5)) as total_weight
            FROM inventory i
            WHERE {where_clause}
            ORDER BY total_volume DESC
            LIMIT 20
        """), params)
        
        top_items = [dict(r) for r in result.mappings().all()]
        
        return {
            "success": True,
            "summary": {
                "sku_count": summary["sku_count"] or 0,
                "total_volume": round(float(summary["total_volume"]), 6),
                "total_weight": round(float(summary["total_weight"]), 6),
                "avg_volume_per_unit": round(float(summary["avg_volume_per_unit"]), 6),
                "avg_weight_per_unit": round(float(summary["avg_weight_per_unit"]), 6),
            },
            "by_warehouse": by_warehouse,
            "top_volume_items": top_items,
        }
    
    async def _calculate_shipping_volume(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate shipping volume for outbound orders."""
        work_order_id = context.get("work_order_id")
        material_ids = context.get("material_ids", [])
        quantities = context.get("quantities", [])
        
        if not work_order_id and not material_ids:
            return {"error": True, "message": "需要提供工单 ID 或物料列表"}
        
        # Get materials and volumes
        if work_order_id:
            result = await db.execute(text("""
                SELECT 
                    bi.material_code,
                    bi.material_name,
                    bi.qty_per_unit,
                    i.available_qty,
                    COALESCE(i.volume_per_unit, 0.001) as volume_per_unit,
                    COALESCE(i.weight_per_unit, 0.5) as weight_per_unit
                FROM bom_items bi
                JOIN work_orders wo ON wo.product_id = bi.product_id
                LEFT JOIN inventory i ON i.material_id = bi.material_id AND i.factory_id = wo.factory_id
                WHERE wo.id = :wo_id AND wo.factory_id = :fid
            """), {"wo_id": work_order_id, "fid": factory_id})
            
            items = [dict(r) for r in result.mappings().all()]
            planned_qty = context.get("planned_qty", 1)
        else:
            # Use provided material IDs and quantities
            items = []
            for i, mid in enumerate(material_ids):
                result = await db.execute(text("""
                    SELECT 
                        material_code,
                        material_name,
                        available_qty,
                        COALESCE(volume_per_unit, 0.001) as volume_per_unit,
                        COALESCE(weight_per_unit, 0.5) as weight_per_unit
                    FROM inventory
                    WHERE factory_id = :fid AND material_id = :mid AND available_qty > 0
                    LIMIT 1
                """), {"fid": factory_id, "mid": mid})
                
                item = result.first()
                if item:
                    item_dict = dict(item._mapping)
                    item_dict["required_qty"] = quantities[i] if i < len(quantities) else 10
                    items.append(item_dict)
            
            planned_qty = 1
        
        # Calculate shipping volume
        total_volume = 0
        total_weight = 0
        shipping_items = []
        
        for item in items:
            qty = item.get("required_qty", 1)
            vol_per_unit = float(item.get("volume_per_unit", 0.001))
            weight_per_unit = float(item.get("weight_per_unit", 0.5))
            
            item_volume = qty * vol_per_unit
            item_weight = qty * weight_per_unit
            total_volume += item_volume
            total_weight += item_weight
            
            shipping_items.append({
                "material_code": item.get("material_code"),
                "material_name": item.get("material_name"),
                "quantity": qty,
                "volume_per_unit": vol_per_unit,
                "total_volume": round(item_volume, 6),
                "weight_per_unit": weight_per_unit,
                "total_weight": round(item_weight, 6),
            })
        
        # Calculate container requirements (standard 20ft container: 33 m³, 28 ton)
        container_volume = 33.0
        container_weight = 28000.0
        
        containers_by_volume = int(total_volume / container_volume) + (1 if total_volume % container_volume > 0 else 0)
        containers_by_weight = int(total_weight / container_weight) + (1 if total_weight % container_weight > 0 else 0)
        containers_needed = max(containers_by_volume, containers_by_weight)
        
        return {
            "success": True,
            "total_volume": round(total_volume, 6),
            "total_weight": round(total_weight, 6),
            "shipping_items": shipping_items,
            "container_requirements": {
                "volume_containers": containers_by_volume,
                "weight_containers": containers_by_weight,
                "total_containers": containers_needed,
                "container_type": "20ft",
                "container_volume_m3": container_volume,
                "container_weight_ton": container_weight,
            },
            "recommendation": self._get_shipping_recommendation(total_volume, total_weight, containers_needed),
        }
    
    async def _get_space_utilization(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get space utilization analysis."""
        warehouse_id = context.get("warehouse_id")
        
        # Get warehouse capacity
        result = await db.execute(text("""
            SELECT 
                w.id as warehouse_id,
                w.warehouse_code,
                w.warehouse_name,
                COALESCE(SUM(l.capacity), 0) as total_capacity,
                COALESCE(SUM(CASE WHEN l.status = 'active' THEN l.capacity ELSE 0 END), 0) as active_capacity,
                COALESCE(SUM(i.available_qty * COALESCE(i.volume_per_unit, 0.001)), 0) as used_volume
            FROM warehouses w
            LEFT JOIN locations l ON l.warehouse_id = w.id
            LEFT JOIN inventory i ON i.location_id = l.id AND i.status = 'available'
            WHERE w.factory_id = :fid
        """), {"fid": factory_id})
        
        if warehouse_id:
            result = await db.execute(text("""
                SELECT 
                    w.id as warehouse_id,
                    w.warehouse_code,
                    w.warehouse_name,
                    COALESCE(SUM(l.capacity), 0) as total_capacity,
                    COALESCE(SUM(CASE WHEN l.status = 'active' THEN l.capacity ELSE 0 END), 0) as active_capacity,
                    COALESCE(SUM(i.available_qty * COALESCE(i.volume_per_unit, 0.001)), 0) as used_volume
                FROM warehouses w
                LEFT JOIN locations l ON l.warehouse_id = w.id
                LEFT JOIN inventory i ON i.location_id = l.id AND i.status = 'available'
                WHERE w.factory_id = :fid AND w.id = :whid
            """), {"fid": factory_id, "whid": warehouse_id})
        
        warehouses = []
        for r in result.mappings().all():
            r = dict(r)
            total_cap = float(r.get("total_capacity") or 0)
            used_vol = float(r.get("used_volume") or 0)
            utilization = (used_vol / total_cap * 100) if total_cap > 0 else 0
            
            warehouses.append({
                "warehouse_id": r.get("warehouse_id"),
                "warehouse_code": r.get("warehouse_code"),
                "warehouse_name": r.get("warehouse_name"),
                "total_capacity": total_cap,
                "used_volume": used_vol,
                "utilization_rate": round(utilization, 2),
                "status": "full" if utilization >= 90 else ("warning" if utilization >= 70 else "normal"),
            })
        
        # Get zone utilization
        result = await db.execute(text("""
            SELECT 
                l.zone,
                COUNT(*) as location_count,
                COALESCE(SUM(l.capacity), 0) as zone_capacity,
                COALESCE(SUM(i.available_qty * COALESCE(i.volume_per_unit, 0.001)), 0) as zone_used_volume,
                ROUND(COALESCE(AVG(i.available_qty * COALESCE(i.volume_per_unit, 0.001)) / NULLIF(l.capacity, 0) * 100, 0), 2) as zone_utilization
            FROM locations l
            LEFT JOIN inventory i ON i.location_id = l.id AND i.status = 'available'
            WHERE l.factory_id = :fid
            GROUP BY l.zone
            ORDER BY zone_utilization DESC
        """), {"fid": factory_id})
        
        zones = [dict(r) for r in result.mappings().all()]
        
        return {
            "success": True,
            "warehouses": warehouses,
            "zones": zones,
            "total_warehouses": len(warehouses),
            "full_warehouses": len([w for w in warehouses if w["status"] == "full"]),
            "warning_warehouses": len([w for w in warehouses if w["status"] == "warning"]),
        }
    
    async def _update_volume(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update volume and weight for inventory items."""
        material_id = context.get("material_id")
        batch_code = context.get("batch_code")
        volume_per_unit = context.get("volume_per_unit")
        weight_per_unit = context.get("weight_per_unit")
        length = context.get("length")
        width = context.get("width")
        height = context.get("height")
        operator = context.get("operator", "system")
        
        if not material_id:
            return {"error": True, "message": "物料 ID 不能为空"}
        
        if volume_per_unit is None and weight_per_unit is None:
            return {"error": True, "message": "请提供体积或重量数据"}
        
        # Calculate volume from dimensions if provided
        if length and width and height and volume_per_unit is None:
            volume_per_unit = length * width * height
        
        # Update inventory
        update_fields = []
        params = {"fid": factory_id, "mid": material_id}
        
        if volume_per_unit is not None:
            update_fields.append("volume_per_unit = :volume_per_unit")
            params["volume_per_unit"] = volume_per_unit
        
        if weight_per_unit is not None:
            update_fields.append("weight_per_unit = :weight_per_unit")
            params["weight_per_unit"] = weight_per_unit
        
        update_fields.append("updated_at = NOW()")
        update_fields.append("updated_by = :operator")
        params["operator"] = operator
        
        if batch_code:
            update_fields.append("batch_code = :batch_code")
            params["batch_code"] = batch_code
        
        await db.execute(text(f"""
            UPDATE inventory
            SET {', '.join(update_fields)}
            WHERE factory_id = :fid AND material_id = :mid
        """), params)
        
        await db.commit()
        
        return {
            "success": True,
            "action": "update_volume",
            "material_id": material_id,
            "batch_code": batch_code,
            "volume_per_unit": volume_per_unit,
            "weight_per_unit": weight_per_unit,
            "operator": operator,
            "message": "体积/重量数据已更新",
        }
    
    def _get_shipping_recommendation(self, total_volume: float, total_weight: float, containers: int) -> str:
        """Get shipping recommendation."""
        if containers == 0:
            return "无需发货"
        elif containers == 1:
            return f"需要 1 个 20ft 集装箱"
        else:
            return f"需要 {containers} 个 20ft 集装箱"
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == "volume_management"