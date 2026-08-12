"""Inventory Alert Executor for WMS.

Handles inventory alert management including:
- Low stock alert (already partially implemented)
- Overstock alert
- Stagnant stock alert
- Imminent expiry alert
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class InventoryAlertExecutor(BaseWmsExecutor):
    """Execute inventory alert operations."""
    
    def get_operation_name(self) -> str:
        return "inventory_alert"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute inventory alert operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # get_alerts, get_low_stock, get_overstock, get_stagnant, get_expiry
                "days_threshold": int,  # default 30 for stagnant
            }
            
        Returns:
            Inventory alert operation result
        """
        operation = context.get("operation", "get_alerts")
        days_threshold = context.get("days_threshold", 30)
        
        if operation == "get_alerts":
            return await self._get_all_alerts(db, factory_id)
        elif operation == "get_low_stock":
            return await self._get_low_stock(db, factory_id)
        elif operation == "get_overstock":
            return await self._get_overstock(db, factory_id)
        elif operation == "get_stagnant":
            return await self._get_stagnant(db, factory_id, days_threshold)
        elif operation == "get_expiry":
            return await self._get_expiry(db, factory_id)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _get_all_alerts(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get all inventory alerts."""
        low_stock = await self._get_low_stock(db, factory_id)
        overstock = await self._get_overstock(db, factory_id)
        stagnant = await self._get_stagnant(db, factory_id)
        expiry = await self._get_expiry(db, factory_id)
        
        all_alerts = []
        
        # Low stock alerts
        for item in low_stock.get("items", []):
            all_alerts.append({
                "type": "low_stock",
                "severity": "high" if item["urgency"] == "urgent" else "medium",
                "material_code": item["material_code"],
                "material_name": item.get("material_name", ""),
                "current_qty": item["current_qty"],
                "reorder_point": item["reorder_point"],
                "safety_stock": item["safety_stock"],
                "suggested_qty": item.get("suggested_qty", 0),
                "message": item.get("message", ""),
            })
        
        # Overstock alerts
        for item in overstock.get("items", []):
            all_alerts.append({
                "type": "overstock",
                "severity": "medium",
                "material_code": item["material_code"],
                "material_name": item.get("material_name", ""),
                "current_qty": item["current_qty"],
                "max_stock": item["max_stock"],
                "excess_qty": item["excess_qty"],
                "message": item.get("message", ""),
            })
        
        # Stagnant alerts
        for item in stagnant.get("items", []):
            all_alerts.append({
                "type": "stagnant",
                "severity": "high" if item["idle_days"] > 180 else "medium",
                "material_code": item["material_code"],
                "material_name": item.get("material_name", ""),
                "current_qty": item["current_qty"],
                "idle_days": item["idle_days"],
                "message": item.get("message", ""),
            })
        
        # Expiry alerts
        for item in expiry.get("items", []):
            all_alerts.append({
                "type": "expiry",
                "severity": "critical" if item["status"] == "expired" else "high",
                "material_code": item["material_code"],
                "batch_code": item["batch_code"],
                "current_qty": item["current_qty"],
                "expire_date": item["expire_date"],
                "days_until_expiry": item.get("days_until_expiry"),
                "message": item.get("message", ""),
            })
        
        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        all_alerts.sort(key=lambda x: severity_order.get(x["severity"], 99))
        
        return {
            "success": True,
            "alerts": all_alerts,
            "total_alerts": len(all_alerts),
            "critical_count": len([a for a in all_alerts if a["severity"] == "critical"]),
            "high_count": len([a for a in all_alerts if a["severity"] == "high"]),
            "medium_count": len([a for a in all_alerts if a["severity"] == "medium"]),
            "low_count": len([a for a in all_alerts if a["severity"] == "low"]),
        }
    
    async def _get_low_stock(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get low stock alerts."""
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                i.safety_stock,
                i.reorder_point,
                i.reorder_qty,
                i.unit,
                i.abc_class,
                CASE 
                    WHEN i.available_qty <= COALESCE(i.safety_stock, 0) THEN 'urgent'
                    WHEN i.available_qty <= COALESCE(i.reorder_point, i.safety_stock, 10) THEN 'normal'
                    ELSE 'ok'
                END as urgency
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.available_qty <= COALESCE(i.reorder_point, i.safety_stock, 10)
              AND i.available_qty >= 0
        """), {"fid": factory_id})
        
        items = []
        for r in result.mappings().all():
            r = dict(r)
            suggested_qty = r.get("reorder_qty") or max(
                (r.get("safety_stock") or 10) * 2 - (r.get("available_qty") or 0), 10
            )
            
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "current_qty": r["available_qty"],
                "safety_stock": r.get("safety_stock"),
                "reorder_point": r.get("reorder_point"),
                "suggested_qty": suggested_qty,
                "urgency": r["urgency"],
                "abc_class": r.get("abc_class", "C"),
                "unit": r.get("unit", "pcs"),
                "message": f"库存不足，当前{r['available_qty']}{r.get('unit', 'pcs')}，建议补货{suggested_qty}{r.get('unit', 'pcs')}" if r["urgency"] == "urgent" else f"库存低于安全线，建议补货",
            })
        
        return {
            "success": True,
            "items": items,
            "total": len(items),
            "urgent_count": len([i for i in items if i["urgency"] == "urgent"]),
        }
    
    async def _get_overstock(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get overstock alerts."""
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                i.max_stock,
                i.unit
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.max_stock IS NOT NULL
              AND i.available_qty > i.max_stock
        """), {"fid": factory_id})
        
        items = []
        for r in result.mappings().all():
            r = dict(r)
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "current_qty": r["available_qty"],
                "max_stock": r["max_stock"],
                "excess_qty": r["available_qty"] - r["max_stock"],
                "unit": r.get("unit", "pcs"),
                "message": f"库存超量，当前{r['available_qty']}{r.get('unit', 'pcs')}，最大库存{r['max_stock']}{r.get('unit', 'pcs')}，超量{r['available_qty'] - r['max_stock']}{r.get('unit', 'pcs')}",
            })
        
        return {
            "success": True,
            "items": items,
            "total": len(items),
        }
    
    async def _get_stagnant(
        self,
        db: AsyncSession,
        factory_id: str,
        days_threshold: int = 90
    ) -> Dict[str, Any]:
        """Get stagnant stock alerts."""
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.available_qty,
                i.unit,
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
            WHERE i.factory_id = :fid 
              AND i.available_qty > 0
              AND COALESCE(last_txn.last_activity, i.created_at) < NOW() - :days * INTERVAL '1 day'
            ORDER BY idle_days DESC
        """), {"fid": factory_id, "days": days_threshold})
        
        items = []
        for r in result.mappings().all():
            r = dict(r)
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "current_qty": r["available_qty"],
                "idle_days": int(r["idle_days"]),
                "abc_class": r.get("abc_class", "C"),
                "unit": r.get("unit", "pcs"),
                "message": f"呆滞库存，已{int(r['idle_days'])}天无出入库记录",
            })
        
        return {
            "success": True,
            "items": items,
            "total": len(items),
            "days_threshold": days_threshold,
        }
    
    async def _get_expiry(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get expiry alerts."""
        now = datetime.utcnow()
        
        # Expiring soon (within 30 days)
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.batch_code,
                i.available_qty,
                i.expire_date,
                EXTRACT(DAY FROM i.expire_date - NOW()) as days_until_expiry
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.expire_date IS NOT NULL
              AND i.expire_date > NOW()
              AND i.expire_date <= NOW() + INTERVAL '30 days'
              AND i.available_qty > 0
            ORDER BY i.expire_date ASC
        """), {"fid": factory_id})
        
        items = []
        for r in result.mappings().all():
            r = dict(r)
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "batch_code": r["batch_code"],
                "current_qty": r["available_qty"],
                "expire_date": r["expire_date"],
                "days_until_expiry": int(r["days_until_expiry"]),
                "status": "expiring_soon",
                "message": f"即将过期，{int(r['days_until_expiry'])}天后到期",
            })
        
        # Already expired
        result = await db.execute(text("""
            SELECT 
                i.material_code,
                i.material_name,
                i.batch_code,
                i.available_qty,
                i.expire_date,
                EXTRACT(DAY FROM NOW() - i.expire_date) as days_expired
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.expire_date IS NOT NULL
              AND i.expire_date < NOW()
              AND i.available_qty > 0
            ORDER BY i.expire_date ASC
        """), {"fid": factory_id})
        
        for r in result.mappings().all():
            r = dict(r)
            items.append({
                "material_code": r["material_code"],
                "material_name": r.get("material_name", ""),
                "batch_code": r["batch_code"],
                "current_qty": r["available_qty"],
                "expire_date": r["expire_date"],
                "days_expired": int(r["days_expired"]),
                "status": "expired",
                "message": f"已过期{int(r['days_expired'])}天，建议立即报废",
            })
        
        return {
            "success": True,
            "items": items,
            "total": len(items),
            "expiring_soon_count": len([i for i in items if i["status"] == "expiring_soon"]),
            "expired_count": len([i for i in items if i["status"] == "expired"]),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation