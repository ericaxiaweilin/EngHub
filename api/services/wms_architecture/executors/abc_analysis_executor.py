"""ABC Analysis Executor for WMS.

Handles ABC analysis including:
- ABC classification
- Inventory turnover analysis
- Inventory cost analysis
- Location utilization analysis
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class AbcAnalysisExecutor(BaseWmsExecutor):
    """Execute ABC analysis operations."""
    
    def get_operation_name(self) -> str:
        return "abc_analysis"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute ABC analysis operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # analyze, get_turnover, get_cost, get_utilization
                "period_days": int,  # default 30
            }
            
        Returns:
            ABC analysis operation result
        """
        operation = context.get("operation", "analyze")
        period_days = context.get("period_days", 30)
        
        if operation == "analyze":
            return await self._analyze(db, factory_id)
        elif operation == "get_turnover":
            return await self._get_turnover(db, factory_id, period_days)
        elif operation == "get_cost":
            return await self._get_cost(db, factory_id)
        elif operation == "get_utilization":
            return await self._get_utilization(db, factory_id)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _analyze(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Perform full ABC analysis."""
        # Get ABC distribution
        abc_result = await db.execute(text("""
            SELECT 
                COALESCE(abc_class, 'C') as cls,
                COUNT(*) as sku_count,
                SUM(available_qty) as total_qty,
                SUM(COALESCE(available_qty * unit_cost, 0)) as total_value
            FROM inventory
            WHERE factory_id = :fid AND available_qty > 0
            GROUP BY abc_class
            ORDER BY cls
        """), {"fid": factory_id})
        
        abc_dist = {}
        for r in abc_result.mappings().all():
            r = dict(r)
            abc_dist[r["cls"]] = {
                "sku_count": r["sku_count"],
                "total_qty": r["total_qty"],
                "total_value": float(r["total_value"]) if r["total_value"] else 0,
            }
        
        # Get top materials by value
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                COALESCE(i.unit_cost, 0) as unit_cost,
                i.abc_class,
                (i.available_qty * COALESCE(i.unit_cost, 0)) as total_value,
                COUNT(*) OVER (PARTITION BY i.abc_class) as class_count
            FROM inventory i
            WHERE i.factory_id = :fid AND i.available_qty > 0
            ORDER BY i.abc_class, total_value DESC
            LIMIT 100
        """), {"fid": factory_id})
        
        top_items = []
        for r in result.mappings().all():
            r = dict(r)
            top_items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "available_qty": r["available_qty"],
                "unit_cost": float(r["unit_cost"]) if r["unit_cost"] else 0,
                "total_value": float(r["total_value"]) if r["total_value"] else 0,
                "abc_class": r.get("abc_class", "C"),
            })
        
        # Calculate percentages
        total_value = sum(item["total_value"] for item in top_items)
        cumulative_value = 0
        for item in top_items:
            cumulative_value += item["total_value"]
            item["cumulative_pct"] = (cumulative_value / total_value * 100) if total_value > 0 else 0
        
        return {
            "success": True,
            "abc_distribution": abc_dist,
            "top_items": top_items[:50],
            "total_skus": sum(v["sku_count"] for v in abc_dist.values()),
            "total_value": total_value,
        }
    
    async def _get_turnover(
        self,
        db: AsyncSession,
        factory_id: str,
        period_days: int = 30
    ) -> Dict[str, Any]:
        """Get inventory turnover analysis."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)
        
        # Get consumption by material
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                COALESCE(SUM(ABS(it.quantity)), 0) as consumption,
                CASE 
                    WHEN i.available_qty > 0 THEN ROUND(i.available_qty * 1.0 / NULLIF(SUM(ABS(it.quantity)), 0) * :days, 2)
                    ELSE 999
                END as days_of_stock
            FROM inventory i
            LEFT JOIN inventory_transactions it ON it.material_id = i.material_id 
                AND it.factory_id = i.factory_id
                AND it.transaction_type = 'outbound'
                AND it.created_at >= :start_date
                AND it.created_at < :end_date
            WHERE i.factory_id = :fid AND i.available_qty > 0
            GROUP BY i.material_id, i.material_code, i.material_name, i.available_qty
            ORDER BY days_of_stock ASC
        """), {
            "fid": factory_id,
            "start_date": start_date,
            "end_date": end_date,
            "days": period_days,
        })
        
        items = []
        for r in result.mappings().all():
            r = dict(r)
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "current_qty": r["available_qty"],
                "consumption": float(r["consumption"]) if r["consumption"] else 0,
                "days_of_stock": float(r["days_of_stock"]) if r["days_of_stock"] else 999,
                "turnover_rate": round(365.0 / max(float(r["days_of_stock"]) if r["days_of_stock"] else 999, 1), 2),
            })
        
        return {
            "success": True,
            "period_days": period_days,
            "items": items[:100],
            "total": len(items),
            "fast_moving": len([i for i in items if i["days_of_stock"] < 30]),
            "slow_moving": len([i for i in items if i["days_of_stock"] >= 90]),
        }
    
    async def _get_cost(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get inventory cost analysis."""
        result = await db.execute(text("""
            SELECT 
                COALESCE(abc_class, 'C') as cls,
                COUNT(*) as sku_count,
                SUM(available_qty) as total_qty,
                SUM(COALESCE(available_qty * unit_cost, 0)) as total_value,
                AVG(COALESCE(unit_cost, 0)) as avg_cost
            FROM inventory
            WHERE factory_id = :fid AND available_qty > 0
            GROUP BY abc_class
            ORDER BY cls
        """), {"fid": factory_id})
        
        cost_by_class = []
        total_value = 0
        for r in result.mappings().all():
            r = dict(r)
            value = float(r["total_value"]) if r["total_value"] else 0
            total_value += value
            cost_by_class.append({
                "abc_class": r["cls"],
                "sku_count": r["sku_count"],
                "total_qty": r["total_qty"],
                "total_value": value,
                "avg_cost": float(r["avg_cost"]) if r["avg_cost"] else 0,
                "pct_of_total": round(value * 100.0 / max(total_value, 1), 2),
            })
        
        # Get top cost items
        result = await db.execute(text("""
            SELECT 
                material_code,
                material_name,
                available_qty,
                COALESCE(unit_cost, 0) as unit_cost,
                (available_qty * COALESCE(unit_cost, 0)) as total_value,
                COALESCE(abc_class, 'C') as abc_class
            FROM inventory
            WHERE factory_id = :fid AND available_qty > 0
            ORDER BY total_value DESC
            LIMIT 50
        """), {"fid": factory_id})
        
        top_cost_items = []
        for r in result.mappings().all():
            r = dict(r)
            top_cost_items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "available_qty": r["available_qty"],
                "unit_cost": float(r["unit_cost"]) if r["unit_cost"] else 0,
                "total_value": float(r["total_value"]) if r["total_value"] else 0,
                "abc_class": r.get("abc_class", "C"),
            })
        
        return {
            "success": True,
            "cost_by_class": cost_by_class,
            "top_cost_items": top_cost_items,
            "total_inventory_value": total_value,
        }
    
    async def _get_utilization(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get location utilization analysis."""
        result = await db.execute(text("""
            SELECT 
                l.zone,
                COUNT(*) as location_count,
                COALESCE(SUM(l.capacity), 0) as total_capacity,
                COALESCE(SUM(i.available_qty), 0) as used_capacity,
                ROUND(COALESCE(SUM(i.available_qty) * 100.0 / NULLIF(SUM(l.capacity), 0), 0), 2) as utilization_rate
            FROM locations l
            LEFT JOIN inventory i ON i.location_id = l.id AND i.status = 'available'
            WHERE l.factory_id = :fid AND l.status = 'active'
            GROUP BY l.zone
            ORDER BY l.zone
        """), {"fid": factory_id})
        
        zones = []
        for r in result.mappings().all():
            r = dict(r)
            zones.append({
                "zone": r["zone"],
                "location_count": r["location_count"],
                "total_capacity": int(r["total_capacity"]) if r["total_capacity"] else 0,
                "used_capacity": int(r["used_capacity"]) if r["used_capacity"] else 0,
                "utilization_rate": float(r["utilization_rate"]) if r["utilization_rate"] else 0,
            })
        
        return {
            "success": True,
            "zones": zones,
            "total_zones": len(zones),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation