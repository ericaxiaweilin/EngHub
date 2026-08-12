"""Location Executor for WMS.

Handles location optimization suggestions.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class LocationExecutor(BaseWmsExecutor):
    """Execute location optimization operations."""
    
    def get_operation_name(self) -> str:
        return "location"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute location optimization operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # optimize, get_suggestions
            }
            
        Returns:
            Location optimization result
        """
        operation = context.get("operation", "optimize")
        
        if operation == "optimize":
            return await self._optimize(db, factory_id)
        elif operation == "get_suggestions":
            return await self._get_suggestions(db, factory_id)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _optimize(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get location optimization suggestions."""
        # Get outbound frequency
        result = await db.execute(text("""
            SELECT it.material_id, COUNT(*) as outbound_count,
                   i.location_code, i.abc_class, i.material_code
            FROM inventory_transactions it
            JOIN inventory i ON it.material_id = i.material_id AND i.factory_id = :fid
            WHERE it.factory_id = :fid AND it.transaction_type = 'outbound'
              AND it.created_at > NOW() - INTERVAL '30 days'
            GROUP BY it.material_id, i.location_code, i.abc_class, i.material_code
            ORDER BY outbound_count DESC
        """), {"fid": factory_id})
        freq_data = [dict(r) for r in result.mappings().all()]
        
        if not freq_data:
            return {
                "success": True,
                "action": "none",
                "message": "无近 30 天出库记录",
                "suggestions": [],
            }
        
        # High-frequency items (outbound > 10) in far zones (C/D zones)
        suggestions = []
        for item in freq_data:
            loc = item.get("location_code") or ""
            is_far = any(loc.startswith(z) for z in ["C", "D", "Z"])
            if item["outbound_count"] > 10 and is_far:
                suggestions.append({
                    "material_code": item["material_code"],
                    "current_location": loc,
                    "outbound_count_30d": item["outbound_count"],
                    "abc_class": item.get("abc_class", "C"),
                    "suggestion": "移至 A 区（靠近出货口）",
                    "priority": "high" if item["outbound_count"] > 50 else "medium",
                })
        
        return {
            "success": True,
            "action": "location_optimization",
            "total_analyzed": len(freq_data),
            "suggestions": suggestions[:20],
            "suggestion_count": len(suggestions),
            "note": f"{len(suggestions)}种高频物料建议调整库位" if suggestions else "库位合理",
        }
    
    async def _get_suggestions(
        self,
        db: AsyncSession,
        factory_id: str
    ) -> Dict[str, Any]:
        """Get location suggestions."""
        result = await self._optimize(db, factory_id)
        return result
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation