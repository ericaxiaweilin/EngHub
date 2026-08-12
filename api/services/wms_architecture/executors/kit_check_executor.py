"""Kit Check Executor for WMS.

Handles kit check operations to verify if materials are sufficient for work orders.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class KitCheckExecutor(BaseWmsExecutor):
    """Execute kit check operations."""
    
    def get_operation_name(self) -> str:
        return "kit_check"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute kit check operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "work_order_id": str,
            }
            
        Returns:
            Kit check result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        work_order_id = context.get("work_order_id")
        
        if not work_order_id:
            return {"error": True, "message": "工单 ID 不能为空"}
        
        # Get work order info
        wo_result = await db.execute(text(
            "SELECT work_order_code, product_id, planned_qty FROM work_orders WHERE id = :id"
        ), {"id": work_order_id})
        wo = wo_result.first()
        
        if not wo:
            return {"error": True, "message": "工单不存在"}
        
        wo_map = dict(wo._mapping)
        planned_qty = wo_map["planned_qty"] or 1
        
        # Get BOM
        bom_result = await db.execute(text("""
            SELECT b.material_code, b.material_name, b.qty_per_unit, b.unit,
                   COALESCE(i.available_qty, 0) as available_qty
            FROM bom_items b
            LEFT JOIN inventory i ON b.material_code = i.material_code AND i.factory_id = :fid
            WHERE b.product_id = :pid AND b.factory_id = :fid
        """), {"fid": factory_id, "pid": wo_map["product_id"]})
        bom_items = [dict(r) for r in bom_result.mappings().all()]
        
        if not bom_items:
            return {
                "success": True,
                "action": "no_bom",
                "work_order": wo_map["work_order_code"],
                "message": "该产品无 BOM，无法进行齐套检查",
            }
        
        # Kit check analysis
        material_status = []
        shortage_count = 0
        for item in bom_items:
            required = (item["qty_per_unit"] or 1) * planned_qty
            available = item["available_qty"]
            is_short = available < required
            if is_short:
                shortage_count += 1
            
            material_status.append({
                "material_code": item["material_code"],
                "material_name": item.get("material_name", ""),
                "required": required,
                "available": available,
                "shortage": max(0, required - available),
                "status": "short" if is_short else "ok",
            })
        
        is_complete = shortage_count == 0
        
        # If short on materials, mark work order
        if not is_complete:
            await db.execute(text("""
                UPDATE work_orders SET material_status = 'shortage' WHERE id = :id
            """), {"id": work_order_id})
            await db.commit()
        
        return {
            "success": True,
            "action": "kit_check",
            "work_order": wo_map["work_order_code"],
            "planned_qty": planned_qty,
            "is_complete": is_complete,
            "total_materials": len(bom_items),
            "shortage_count": shortage_count,
            "materials": material_status,
            "recommendation": "可以开工" if is_complete else f"缺{shortage_count}种物料，建议先补货",
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation