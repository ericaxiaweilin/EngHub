"""Outbound Executor for WMS.

Handles outbound operations including quick outbound, production outbound,
sales outbound, and scrap outbound.
"""

from typing import Any, Dict, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from database.models import Inventory, InventoryTransaction, OutboundOrder


class OutboundExecutor(BaseWmsExecutor):
    """Execute outbound operations."""
    
    def get_operation_name(self) -> str:
        return "outbound"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute outbound operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "material_id": str,
                "quantity": int,
                "warehouse_id": Optional[str],
                "batch_code": Optional[str],
                "reference_type": Optional[str],
                "reference_id": Optional[str],
                "operator": str,
                "remark": Optional[str],
                "outbound_type": str,  # production/sales/scrap
            }
            
        Returns:
            Outbound operation result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        # Extract parameters
        material_id = context.get("material_id")
        quantity = context.get("quantity", 0)
        warehouse_id = context.get("warehouse_id")
        batch_code = context.get("batch_code")
        reference_type = context.get("reference_type")
        reference_id = context.get("reference_id")
        operator = context.get("operator", "system")
        remark = context.get("remark")
        outbound_type = context.get("outbound_type", "production")
        
        now = datetime.utcnow()
        
        # Find inventory
        conditions = [
            Inventory.factory_id == factory_id,
            Inventory.material_id == material_id,
        ]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)
        if batch_code:
            conditions.append(Inventory.batch_code == batch_code)
        
        inv_stmt = select(Inventory).where(and_(*conditions)).order_by(Inventory.created_at.asc())
        inv_result = await db.execute(inv_stmt)
        inv = inv_result.scalar_one_or_none()
        
        if not inv:
            return {"error": True, "message": f"物料 {material_id} 无库存"}
        
        if inv.available_qty < quantity:
            return {
                "error": True,
                "message": f"可用库存不足：需要 {quantity}，可用 {inv.available_qty}",
                "available_qty": inv.available_qty,
                "required_qty": quantity,
            }
        
        before_qty = inv.total_qty
        inv.total_qty -= quantity
        inv.available_qty -= quantity
        inv.last_movement_at = now
        inv.updated_at = now
        
        # Record transaction
        txn = InventoryTransaction(
            id=str(__import__('uuid').uuid4()),
            factory_id=factory_id,
            inventory_id=inv.id,
            material_id=material_id,
            batch_code=inv.batch_code,
            transaction_type="outbound",
            quantity=-quantity,
            before_qty=before_qty,
            after_qty=before_qty - quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark or f"快速出库 ({outbound_type})",
            created_at=now,
        )
        db.add(txn)
        
        # Create outbound order
        outbound_order = OutboundOrder(
            id=str(__import__('uuid').uuid4()),
            outbound_code=f"OUT-{factory_id[:3].upper()}{datetime.now().strftime('%Y%m%d')}-{str(__import__('uuid').uuid4())[:6].upper()}",
            factory_id=factory_id,
            warehouse_id=inv.warehouse_id,
            material_id=material_id,
            material_code=inv.material_code,
            quantity=quantity,
            batch_code=inv.batch_code,
            outbound_type=outbound_type,
            status="completed",
            created_by=operator,
            created_at=now,
            completed_at=now,
        )
        db.add(outbound_order)
        
        await db.commit()
        await db.refresh(inv)
        
        return {
            "success": True,
            "type": "outbound",
            "material_id": material_id,
            "material_code": inv.material_code,
            "quantity": quantity,
            "before_qty": before_qty,
            "after_qty": before_qty - quantity,
            "warehouse_id": inv.warehouse_id,
            "batch_code": inv.batch_code,
            "operator": operator,
            "time": now.isoformat(),
            "outbound_order_id": outbound_order.id,
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation