"""Count Executor for WMS.

Handles inventory count operations including cycle count and periodic count.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from database.models import Inventory, InventoryTransaction


class CountExecutor(BaseWmsExecutor):
    """Execute count operations."""
    
    def get_operation_name(self) -> str:
        return "count"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute count operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # create_task, submit_count, list_tasks
                "task_id": Optional[str],
                "item_id": Optional[str],
                "counted_qty": Optional[int],
                "counted_by": Optional[str],
                "warehouse_id": Optional[str],
                "count_type": str,  # cycle, periodic
            }
            
        Returns:
            Count operation result
        """
        operation = context.get("operation", "create_task")
        
        if operation == "create_task":
            return await self._create_task(db, factory_id, context)
        elif operation == "submit_count":
            return await self._submit_count(db, factory_id, context)
        elif operation == "list_tasks":
            return await self._list_tasks(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _create_task(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a count task."""
        now = datetime.utcnow()
        task_id = str(__import__('uuid').uuid4())
        task_code = f"CC-{factory_id[:3].upper()}-{now.strftime('%m%d%H%M')}-{__import__('uuid').uuid4().hex[:4].upper()}"
        
        warehouse_id = context.get("warehouse_id")
        count_type = context.get("count_type", "cycle")
        assigned_to = context.get("assigned_to")
        created_by = context.get("created_by", "system")
        
        # Get inventory to count
        conditions = [Inventory.factory_id == factory_id, Inventory.total_qty > 0]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)
        
        stmt = select(Inventory).where(and_(*conditions))
        result = await db.execute(stmt)
        inv_items = result.scalars().all()
        
        if not inv_items:
            return {"error": True, "message": "无可盘点的库存"}
        
        # Create task
        await db.execute(text("""
            INSERT INTO cycle_count_tasks (id, factory_id, task_code, warehouse_id, count_type,
                status, total_items, assigned_to, created_by, created_at)
            VALUES (:id, :fid, :code, :wh, :type, 'pending', :total, :assigned, :by, :now)
        """), {
            "id": task_id,
            "fid": factory_id,
            "code": task_code,
            "wh": warehouse_id,
            "type": count_type,
            "total": len(inv_items),
            "assigned": assigned_to,
            "by": created_by,
            "now": now,
        })
        
        # Create count items
        for inv in inv_items:
            await db.execute(text("""
                INSERT INTO cycle_count_items (id, task_id, material_id, material_code, 
                    location_id, system_qty, status, created_at)
                VALUES (:id, :tid, :mid, :mcode, :lid, :qty, 'pending', :now)
            """), {
                "id": str(__import__('uuid').uuid4()),
                "tid": task_id,
                "mid": inv.material_id,
                "mcode": inv.material_code,
                "lid": inv.location_id,
                "qty": inv.total_qty,
                "now": now,
            })
        
        await db.commit()
        
        return {
            "success": True,
            "task_id": task_id,
            "task_code": task_code,
            "total_items": len(inv_items),
            "count_type": count_type,
        }
    
    async def _submit_count(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit count result."""
        now = datetime.utcnow()
        task_id = context.get("task_id")
        item_id = context.get("item_id")
        counted_qty = context.get("counted_qty", 0)
        counted_by = context.get("counted_by", "system")
        
        # Get item
        result = await db.execute(text(
            "SELECT * FROM cycle_count_items WHERE id = :id AND task_id = :tid"
        ), {"id": item_id, "tid": task_id})
        item = result.mappings().first()
        
        if not item:
            return {"error": True, "message": "盘点项不存在"}
        
        diff = counted_qty - item["system_qty"]
        
        # Update item
        await db.execute(text("""
            UPDATE cycle_count_items SET counted_qty = :qty, diff_qty = :diff,
                status = 'counted', counted_by = :by, counted_at = :now
            WHERE id = :id
        """), {"qty": counted_qty, "diff": diff, "by": counted_by, "now": now, "id": item_id})
        
        # Update task progress
        await db.execute(text("""
            UPDATE cycle_count_tasks SET
                counted_items = (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND status != 'pending'),
                diff_items = (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND diff_qty != 0 AND diff_qty IS NOT NULL),
                status = CASE WHEN (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND status = 'pending') = 0
                    THEN 'completed' ELSE 'in_progress' END
            WHERE id = :tid
        """), {"tid": task_id})
        
        await db.commit()
        
        return {
            "success": True,
            "diff": diff,
            "item_id": item_id,
            "counted_qty": counted_qty,
            "system_qty": item["system_qty"],
        }
    
    async def _list_tasks(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """List count tasks."""
        status = context.get("status")
        
        query = "SELECT * FROM cycle_count_tasks WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT 50"
        
        result = await db.execute(text(query), params)
        tasks = [dict(r) for r in result.mappings().all()]
        
        return {
            "tasks": tasks,
            "total": len(tasks),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation