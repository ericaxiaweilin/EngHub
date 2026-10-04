"""Outbound Executor for WMS.

Handles outbound operations including quick outbound, production outbound,
sales outbound, and scrap outbound.
"""

from typing import Any, Dict, Optional
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from api.services.wms_architecture.movements import (
    apply_movement,
    document_movement_type,
)
from database.models import Inventory, OutboundOrder


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
                "work_order_id": Optional[str],  # production 领料必填，否则拒绝记账
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
        
        quantity = int(context.get("quantity", 0))
        work_order_id = context.get("work_order_id")
        before_qty = int(inv.total_qty or 0)

        # 先立单据，再记账：流水挂的就是这张出库单
        outbound_order = OutboundOrder(
            id=str(uuid.uuid4()),
            outbound_code=f"OUT-{factory_id[:3].upper()}{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            factory_id=factory_id,
            warehouse_id=inv.warehouse_id,
            material_id=material_id,
            material_code=inv.material_code,
            quantity=quantity,
            batch_code=inv.batch_code,
            outbound_type=outbound_type,
            work_order_id=work_order_id,
            status="completed",
            created_by=operator,
            created_at=now,
            completed_at=now,
        )
        db.add(outbound_order)
        await db.flush()

        txn = await apply_movement(
            db,
            inventory=inv,
            transaction_type=document_movement_type("out", outbound_type),
            quantity=quantity,
            reference_type="outbound_order",
            reference_id=outbound_order.id,
            reference_doc_no=outbound_order.outbound_code,
            work_order_id=work_order_id,
            operator=operator,
            remark=remark or f"出库过账 ({outbound_type})",
        )
        inv.updated_at = now

        await db.commit()
        await db.refresh(inv)
        
        return {
            "success": True,
            "type": "outbound",
            "material_id": material_id,
            "material_code": inv.material_code,
            "quantity": quantity,
            "before_qty": before_qty,
            "after_qty": txn.after_qty,
            "warehouse_id": inv.warehouse_id,
            "batch_code": inv.batch_code,
            "operator": operator,
            "time": now.isoformat(),
            "outbound_order_id": outbound_order.id,
            "transaction_id": txn.id,
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation