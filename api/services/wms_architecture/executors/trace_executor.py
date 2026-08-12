"""Trace Executor for WMS.

Handles batch trace operations for complete lifecycle tracking.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from database.models import Inventory, InventoryTransaction


class TraceExecutor(BaseWmsExecutor):
    """Execute trace operations."""
    
    def get_operation_name(self) -> str:
        return "trace"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute trace operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "batch_code": str,
                "material_code": Optional[str],
            }
            
        Returns:
            Trace operation result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        batch_code = context.get("batch_code")
        material_code = context.get("material_code")
        
        if not batch_code:
            return {"error": True, "message": "批次号不能为空"}
        
        # 1. Get inventory records
        inv_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.batch_code == batch_code,
            )
        )
        if material_code:
            inv_stmt = inv_stmt.where(Inventory.material_code == material_code)
        
        inv_result = await db.execute(inv_stmt)
        inv_records = [dict(r.__dict__) for r in inv_result.scalars().all()]
        
        # 2. Get transaction records
        txn_stmt = text("""
            SELECT * FROM inventory_transactions
            WHERE factory_id = :fid AND batch_code = :batch
            ORDER BY created_at ASC
        """)
        txn_result = await db.execute(txn_stmt, {"fid": factory_id, "batch": batch_code})
        transactions = [dict(r) for r in txn_result.mappings().all()]
        
        # 3. Get linked work orders
        wo_links = []
        for txn in transactions:
            if txn.get("reference_type") == "work_order" and txn.get("reference_id"):
                wo_links.append({
                    "work_order_id": txn["reference_id"],
                    "qty": abs(txn.get("quantity", 0)),
                    "date": txn["created_at"].isoformat() if txn.get("created_at") else None,
                })
        
        # 4. Calculate summary
        total_in = sum(t.get("quantity", 0) for t in transactions if t.get("quantity", 0) > 0)
        total_out = abs(sum(t.get("quantity", 0) for t in transactions if t.get("quantity", 0) < 0))
        current_stock = sum(r.get("available_qty", 0) for r in inv_records)
        
        return {
            "success": True,
            "batch_code": batch_code,
            "factory_id": factory_id,
            "material_code": material_code,
            "inventory_records": inv_records,
            "transactions": transactions,
            "work_order_links": wo_links,
            "summary": {
                "total_inbound": total_in,
                "total_outbound": total_out,
                "current_stock": current_stock,
                "transaction_count": len(transactions),
                "linked_work_orders": len(wo_links),
            },
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation