"""Replenish Executor for WMS.

Handles replenishment suggestions and automatic replenishment.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class ReplenishExecutor(BaseWmsExecutor):
    """Execute replenishment operations."""
    
    def get_operation_name(self) -> str:
        return "replenish"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute replenishment operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # suggestions, auto_replenish
                "material_code": Optional[str],
            }
            
        Returns:
            Replenishment operation result
        """
        operation = context.get("operation", "suggestions")
        
        if operation == "suggestions":
            return await self._get_suggestions(db, factory_id, context)
        elif operation == "auto_replenish":
            return await self._auto_replenish(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _get_suggestions(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get replenishment suggestions based on safety stock + daily consumption."""
        # Get safety stock config
        config_result = await db.execute(text("""
            SELECT material_code, material_name, safety_stock, reorder_point, max_stock
            FROM safety_stock_config 
            WHERE factory_id = :fid AND is_active = TRUE
        """), {"fid": factory_id})
        configs = [dict(r) for r in config_result.mappings().all()]
        
        suggestions = []
        for cfg in configs:
            code = cfg["material_code"]
            
            # Current inventory
            inv_result = await db.execute(text("""
                SELECT COALESCE(SUM(available_qty), 0) as avail 
                FROM inventory
                WHERE factory_id = :fid AND material_code = :code
            """), {"fid": factory_id, "code": code})
            avail = inv_result.scalar() or 0
            
            reorder_point = cfg.get("reorder_point") or cfg.get("safety_stock") or 0
            if avail <= reorder_point:
                # Calculate daily consumption (last 30 days)
                consumption_result = await db.execute(text("""
                    SELECT COALESCE(SUM(ABS(quantity)), 0) as consumed
                    FROM inventory_transactions
                    WHERE factory_id = :fid AND material_code = :code
                        AND quantity < 0 AND created_at >= NOW() - INTERVAL '30 days'
                """), {"fid": factory_id, "code": code})
                consumed_30d = consumption_result.scalar() or 0
                daily_avg = consumed_30d / 30
                
                # Replenishment quantity
                max_stock = cfg.get("max_stock") or int(reorder_point * 2)
                suggested_qty = max(int(max_stock - avail), 1)
                
                suggestions.append({
                    "material_code": code,
                    "material_name": cfg.get("material_name", ""),
                    "current_stock": int(avail),
                    "reorder_point": reorder_point,
                    "safety_stock": cfg.get("safety_stock", 0),
                    "daily_consumption": round(daily_avg, 1),
                    "days_of_stock": round(avail / daily_avg, 1) if daily_avg > 0 else 999,
                    "suggested_qty": suggested_qty,
                    "urgency": "high" if avail <= (cfg.get("safety_stock") or 0) else "medium",
                })
        
        suggestions.sort(key=lambda x: x["days_of_stock"])
        
        return {
            "success": True,
            "suggestions": suggestions,
            "total_items": len(suggestions),
            "urgent_count": sum(1 for s in suggestions if s["urgency"] == "high"),
        }
    
    async def _auto_replenish(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Auto replenish by creating purchase requests."""
        # Get suggestions first
        suggestions_result = await self._get_suggestions(db, factory_id, context)
        suggestions = suggestions_result.get("suggestions", [])
        
        if not suggestions:
            return {"success": True, "message": "无需要补货的物料"}
        
        # Create purchase requests
        replenishments = []
        for item in suggestions:
            urgency = item["urgency"]
            
            await db.execute(text("""
                INSERT INTO purchase_requests (id, factory_id, material_code, material_name,
                    requested_qty, unit, urgency, status, source, created_at)
                VALUES (gen_random_uuid(), :fid, :mc, :mn, :qty, 'pcs', :urg, 'pending', 'wms_replenish', NOW())
                ON CONFLICT DO NOTHING
            """), {
                "fid": factory_id,
                "mc": item["material_code"],
                "mn": item["material_name"],
                "qty": item["suggested_qty"],
                "urg": urgency,
            })
            
            replenishments.append({
                "material_code": item["material_code"],
                "suggested_qty": item["suggested_qty"],
                "urgency": urgency,
            })
        
        await db.commit()
        
        return {
            "success": True,
            "action": "auto_replenish",
            "total_items": len(replenishments),
            "replenishments": replenishments,
            "note": f"已自动创建{len(replenishments)}条采购申请",
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation