"""Inbound Executor for WMS.

Handles inbound operations including quick inbound, purchase inbound,
production inbound, and return inbound.
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
from database.models import Inventory, InboundOrder


class InboundExecutor(BaseWmsExecutor):
    """Execute inbound operations."""
    
    def get_operation_name(self) -> str:
        return "inbound"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute inbound operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "material_id": str,
                "material_code": str,
                "quantity": int,
                "warehouse_id": str,
                "location_id": Optional[str],
                "batch_code": Optional[str],
                "material_name": Optional[str],
                "unit": str,
                "reference_type": Optional[str],
                "reference_id": Optional[str],
                "purchase_order_id": Optional[str],
                "supplier_id": Optional[str],
                "operator": str,
                "remark": Optional[str],
                "inbound_type": str,  # purchase/production/return
            }
            
        Returns:
            Inbound operation result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        # Extract parameters
        material_id = context.get("material_id")
        material_code = context.get("material_code")
        quantity = context.get("quantity", 0)
        warehouse_id = context.get("warehouse_id")
        location_id = context.get("location_id")
        batch_code = context.get("batch_code") or f"BATCH-{material_code}-{datetime.now().strftime('%Y%m%d')}"
        material_name = context.get("material_name", material_code)
        unit = context.get("unit", "pcs")
        reference_type = context.get("reference_type")
        reference_id = context.get("reference_id")
        purchase_order_id = context.get("purchase_order_id") or (
            reference_id if reference_type in {"purchase_order", "po"} else None
        )
        supplier_id = context.get("supplier_id")
        operator = context.get("operator", "system")
        remark = context.get("remark")
        inbound_type = context.get("inbound_type", "purchase")
        
        now = datetime.utcnow()
        inbound_type = context.get("inbound_type", "purchase")
        quantity = int(context.get("quantity", 0))

        # 先立单据：流水要挂得住这张单，数量与流水才不会分家
        inbound_order = InboundOrder(
            id=str(uuid.uuid4()),
            inbound_code=f"IN-{factory_id[:3].upper()}{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            material_id=material_id,
            material_code=material_code,
            quantity=quantity,
            batch_code=batch_code,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            inbound_type=inbound_type,
            status="completed",
            created_by=operator,
            created_at=now,
            completed_at=now,
        )
        db.add(inbound_order)
        await db.flush()

        # Find or create inventory record（数量只由记账原语改，这里建行给 0）
        inv_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == warehouse_id,
                Inventory.batch_code == batch_code,
            )
        )
        inv_result = await db.execute(inv_stmt)
        inv = inv_result.scalar_one_or_none()

        if not inv:
            inv = Inventory(
                id=str(uuid.uuid4()),
                material_id=material_id,
                material_code=material_code,
                material_name=material_name,
                factory_id=factory_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_code=batch_code,
                total_qty=0,
                available_qty=0,
                reserved_qty=0,
                unit=unit,
                status="available",
                last_movement_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(inv)
            await db.flush()

        before_qty = int(inv.total_qty or 0)
        txn = await apply_movement(
            db,
            inventory=inv,
            transaction_type=document_movement_type("in", inbound_type),
            quantity=quantity,
            reference_type="inbound_order",
            reference_id=inbound_order.id,
            reference_doc_no=inbound_order.inbound_code,
            work_order_id=context.get("work_order_id"),
            operator=operator,
            remark=remark or f"入库过账 ({inbound_type})",
        )
        inv.updated_at = now

        await db.commit()
        await db.refresh(inv)

        return {
            "success": True,
            "type": "inbound",
            "material_id": material_id,
            "material_code": material_code,
            "quantity": quantity,
            "before_qty": before_qty,
            "after_qty": txn.after_qty,
            "warehouse_id": warehouse_id,
            "batch_code": batch_code,
            "purchase_order_id": purchase_order_id,
            "supplier_id": supplier_id,
            "operator": operator,
            "time": now.isoformat(),
            "inbound_order_id": inbound_order.id,
            "transaction_id": txn.id,
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation
