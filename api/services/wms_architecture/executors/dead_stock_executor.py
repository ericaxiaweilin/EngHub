"""Dead Stock Executor for WMS.

Handles dead stock detection and alerting.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class DeadStockExecutor(BaseWmsExecutor):
    """Execute dead stock operations."""
    
    def get_operation_name(self) -> str:
        return "dead_stock"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute dead stock operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # check, get_alerts
                "days_threshold": int,  # default 90
            }
            
        Returns:
            Dead stock operation result
        """
        operation = context.get("operation", "check")
        days_threshold = context.get("days_threshold", 90)
        
        if operation == "check":
            return await self._check_dead_stock(db, factory_id, days_threshold)
        elif operation == "get_alerts":
            return await self._get_alerts(db, factory_id, days_threshold)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _check_dead_stock(
        self,
        db: AsyncSession,
        factory_id: str,
        days_threshold: int
    ) -> Dict[str, Any]:
        """Check for dead stock items."""
        result = await db.execute(text("""
            SELECT i.material_code, i.material_name, i.available_qty, i.unit,
                   i.abc_class,
                   COALESCE(last_txn.last_activity, i.created_at) as last_activity,
                   EXTRACT(DAY FROM NOW() - COALESCE(last_txn.last_activity, i.created_at)) as idle_days
            FROM inventory i
            LEFT JOIN (
                SELECT material_id, MAX(created_at) as last_activity
                FROM inventory_transactions
                WHERE factory_id = :fid
                GROUP BY material_id
            ) last_txn ON i.material_id = last_txn.material_id
            WHERE i.factory_id = :fid AND i.available_qty > 0
              AND COALESCE(last_txn.last_activity, i.created_at) < NOW() - :days * INTERVAL '1 day'
            ORDER BY idle_days DESC
        """), {"fid": factory_id, "days": days_threshold})
        dead_stock = [dict(r) for r in result.mappings().all()]
        
        if not dead_stock:
            return {
                "success": True,
                "action": "none",
                "message": f"无超过{days_threshold}天的呆滞料",
                "total_items": 0,
                "items": [],
            }
        
        # Calculate estimated value (simplified: quantity * 10)
        total_value = sum(d["available_qty"] * 10 for d in dead_stock)
        
        return {
            "success": True,
            "action": "dead_stock_alert",
            "threshold_days": days_threshold,
            "total_items": len(dead_stock),
            "estimated_value": total_value,
            "items": [{
                "material_code": d["material_code"],
                "material_name": d.get("material_name", ""),
                "qty": d["available_qty"],
                "idle_days": int(d["idle_days"]),
                "abc_class": d.get("abc_class", "C"),
                "suggestion": "建议处理" if d["idle_days"] > 180 else "关注",
            } for d in dead_stock[:30]],
            "recommendation": f"{len(dead_stock)}种物料超过{days_threshold}天未动，占用约{total_value}元",
        }
    
    async def _get_alerts(
        self,
        db: AsyncSession,
        factory_id: str,
        days_threshold: int
    ) -> Dict[str, Any]:
        """Get dead stock alerts."""
        result = await self._check_dead_stock(db, factory_id, days_threshold)
        
        if result.get("action") == "none":
            return {"success": True, "alerts": [], "message": "无呆滞料预警"}
        
        alerts = []
        for item in result.get("items", []):
            alerts.append({
                "type": "dead_stock",
                "severity": "high" if item["idle_days"] > 180 else "medium",
                "material_code": item["material_code"],
                "material_name": item["material_name"],
                "qty": item["qty"],
                "idle_days": item["idle_days"],
                "suggestion": item["suggestion"],
            })
        
        return {
            "success": True,
            "alerts": alerts,
            "total_alerts": len(alerts),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation