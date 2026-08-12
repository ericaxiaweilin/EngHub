"""Transfer Executor for WMS.

Handles transfer operations between warehouses.
"""

from typing import Any, Dict, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from database.models import Inventory, InventoryTransaction


class TransferExecutor(BaseWmsExecutor):
    """Execute transfer operations."""
    
    def get_operation_name(self) -> str:
        return "transfer"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute transfer operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "material_id": str,
                "quantity": int,
                "from_warehouse_id": str,
                "to_warehouse_id": str,
                "to_location_id": Optional[str],
                "operator": str,
                "remark": Optional[str],
            }
            
        Returns:
            Transfer operation result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        # Extract parameters
        material_id = context.get("material_id")
        quantity = context.get("quantity", 0)
        from_warehouse_id = context.get("from_warehouse_id")
        to_warehouse_id = context.get("to_warehouse_id")
        to_location_id = context.get("to_location_id")
        operator = context.get("operator", "system")
        remark = context.get("remark")
        
        if from_warehouse_id == to_warehouse_id:
            return {"error": True, "message": "源仓库和目标仓库不能相同"}
        
        now = datetime.utcnow()
        
        # Find source inventory
        src_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == from_warehouse_id,
            )
        )
        src_result = await db.execute(src_stmt)
        src_inv = src_result.scalar_one_or_none()
        
        if not src_inv:
            return {"error": True, "message": f"源仓库无物料 {material_id} 库存"}
        
        if src_inv.available_qty < quantity:
            return {
                "error": True,
                "message": f"源库存不足：需要 {quantity}，可用 {src_inv.available_qty}",
                "available_qty": src_inv.available_qty,
                "required_qty": quantity,
            }
        
        # Deduct source
        before_src = src_inv.total_qty
        src_inv.total_qty -= quantity
        src_inv.available_qty -= quantity
        src_inv.last_movement_at = now
        src_inv.updated_at = now
        
        # Find or create destination inventory
        dst_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == to_warehouse_id,
            )
        )
        dst_result = await db.execute(dst_stmt)
        dst_inv = dst_result.scalar_one_or_none()
        
        before_dst = 0
        if dst_inv:
            before_dst = dst_inv.total_qty
            dst_inv.total_qty += quantity
            dst_inv.available_qty += quantity
            dst_inv.last_movement_at = now
            dst_inv.updated_at = now
        else:
            dst_inv = Inventory(
                id=str(__import__('uuid').uuid4()),
                material_id=material_id,
                material_code=src_inv.material_code,
                material_name=src_inv.material_name,
                factory_id=factory_id,
                warehouse_id=to_warehouse_id,
                location_id=to_location_id,
                batch_code=src_inv.batch_code,
                total_qty=quantity,
                available_qty=quantity,
                reserved_qty=0,
                unit=src_inv.unit or "pcs",
                status="available",
                last_movement_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(dst_inv)
        
        # Record transactions (out + in)
        db.add(InventoryTransaction(
            id=str(__import__('uuid').uuid4()),
            factory_id=factory_id,
            inventory_id=src_inv.id,
            material_id=material_id,
            batch_code=src_inv.batch_code,
            transaction_type="transfer",
            quantity=-quantity,
            before_qty=before_src,
            after_qty=before_src - quantity,
            reference_type="transfer",
            reference_id=to_warehouse_id,
            operator=operator,
            remark=remark or f"移库→{to_warehouse_id}",
            created_at=now,
        ))
        db.add(InventoryTransaction(
            id=str(__import__('uuid').uuid4()),
            factory_id=factory_id,
            inventory_id=dst_inv.id,
            material_id=material_id,
            batch_code=src_inv.batch_code,
            transaction_type="transfer",
            quantity=quantity,
            before_qty=before_dst,
            after_qty=before_dst + quantity,
            reference_type="transfer",
            reference_id=from_warehouse_id,
            operator=operator,
            remark=remark or f"移库←{from_warehouse_id}",
            created_at=now,
        ))
        
        await db.commit()
        await db.refresh(src_inv)
        await db.refresh(dst_inv)
        
        return {
            "success": True,
            "type": "transfer",
            "material_id": material_id,
            "material_code": src_inv.material_code,
            "quantity": quantity,
            "from_warehouse_id": from_warehouse_id,
            "to_warehouse_id": to_warehouse_id,
            "before_src": before_src,
            "after_src": before_src - quantity,
            "before_dst": before_dst,
            "after_dst": before_dst + quantity,
            "operator": operator,
            "time": now.isoformat(),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation