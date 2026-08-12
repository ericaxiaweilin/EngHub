"""FIFO Executor for WMS.

Handles FIFO (First-In-First-Out) picking recommendations.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from database.models import Inventory


class FifoExecutor(BaseWmsExecutor):
    """Execute FIFO picking operations."""
    
    def get_operation_name(self) -> str:
        return "fifo"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute FIFO picking operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "material_code": str,
                "qty_needed": int,
                "warehouse_id": Optional[str],
            }
            
        Returns:
            FIFO picking result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        # Extract parameters
        material_code = context.get("material_code")
        qty_needed = context.get("qty_needed", 0)
        warehouse_id = context.get("warehouse_id")
        
        if not material_code:
            return {"error": True, "message": "物料编码不能为空"}
        
        if qty_needed <= 0:
            return {"error": True, "message": "需求数量必须大于 0"}
        
        # Query inventory by creation time (FIFO)
        conditions = [
            Inventory.factory_id == factory_id,
            Inventory.material_code == material_code,
            Inventory.available_qty > 0,
        ]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)
        
        stmt = select(Inventory).where(and_(*conditions)).order_by(Inventory.created_at.asc())
        result = await db.execute(stmt)
        batches = result.scalars().all()
        
        picks = []
        remaining = qty_needed
        
        for batch in batches:
            if remaining <= 0:
                break
            
            pick_qty = min(batch.available_qty, remaining)
            picks.append({
                "inventory_id": batch.id,
                "batch_code": batch.batch_code,
                "warehouse_id": batch.warehouse_id,
                "location_id": batch.location_id,
                "pick_qty": pick_qty,
                "available_qty": batch.available_qty,
                "inbound_date": batch.created_at.isoformat() if batch.created_at else None,
            })
            remaining -= pick_qty
        
        return {
            "success": True,
            "material_code": material_code,
            "qty_needed": qty_needed,
            "picks": picks,
            "total_picked": qty_needed - max(remaining, 0),
            "shortage": max(remaining, 0),
            "fifo_compliant": remaining <= 0,
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation