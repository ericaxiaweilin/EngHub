"""Batch Expiry Executor for WMS.

Handles batch expiry management including:
- Batch validity period tracking
- Expiration warning
- Batch locking/unlocking
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor


class BatchExpiryExecutor(BaseWmsExecutor):
    """Execute batch expiry management operations."""
    
    def get_operation_name(self) -> str:
        return "batch_expiry"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute batch expiry operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # check_expiry, get_warnings, lock_batch, unlock_batch
                "batch_code": Optional[str],
                "days_threshold": int,  # default 30
            }
            
        Returns:
            Batch expiry operation result
        """
        operation = context.get("operation", "check_expiry")
        days_threshold = context.get("days_threshold", 30)
        
        if operation == "check_expiry":
            return await self._check_expiry(db, factory_id, days_threshold)
        elif operation == "get_warnings":
            return await self._get_warnings(db, factory_id, days_threshold)
        elif operation == "lock_batch":
            return await self._lock_batch(db, factory_id, context)
        elif operation == "unlock_batch":
            return await self._unlock_batch(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _check_expiry(
        self,
        db: AsyncSession,
        factory_id: str,
        days_threshold: int
    ) -> Dict[str, Any]:
        """Check batch expiry status."""
        now = datetime.utcnow()
        threshold_date = now + timedelta(days=days_threshold)
        
        # Get batches expiring soon
        result = await db.execute(text("""
            SELECT i.material_code, i.material_name, i.batch_code, 
                   i.available_qty, i.unit,
                   i.expiry_date,
                   EXTRACT(DAY FROM i.expiry_date - NOW()) as days_until_expiry
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.expiry_date IS NOT NULL
              AND i.expiry_date > NOW()
              AND i.expiry_date <= :threshold
              AND i.available_qty > 0
            ORDER BY i.expiry_date ASC
        """), {"fid": factory_id, "threshold": threshold_date})
        
        expiring_batches = [dict(r) for r in result.mappings().all()]
        
        # Get expired batches
        result = await db.execute(text("""
            SELECT i.material_code, i.material_name, i.batch_code,
                   i.available_qty, i.unit,
                   i.expiry_date,
                   EXTRACT(DAY FROM NOW() - i.expiry_date) as days_expired
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.expiry_date IS NOT NULL
              AND i.expiry_date < NOW()
              AND i.available_qty > 0
        """), {"fid": factory_id})
        
        expired_batches = [dict(r) for r in result.mappings().all()]
        
        return {
            "success": True,
            "days_threshold": days_threshold,
            "expiring_soon": {
                "count": len(expiring_batches),
                "batches": expiring_batches[:50],
            },
            "expired": {
                "count": len(expired_batches),
                "batches": expired_batches[:50],
            },
            "total_issues": len(expiring_batches) + len(expired_batches),
        }
    
    async def _get_warnings(
        self,
        db: AsyncSession,
        factory_id: str,
        days_threshold: int
    ) -> Dict[str, Any]:
        """Get batch expiry warnings."""
        result = await self._check_expiry(db, factory_id, days_threshold)
        
        warnings = []
        
        # Expiring soon warnings
        for batch in result.get("expiring_soon", {}).get("batches", []):
            warnings.append({
                "type": "expiring_soon",
                "severity": "medium" if batch["days_until_expiry"] > 7 else "high",
                "material_code": batch["material_code"],
                "batch_code": batch["batch_code"],
                "qty": batch["available_qty"],
                "expiry_date": batch["expiry_date"],
                "days_until_expiry": int(batch["days_until_expiry"]),
                "suggestion": "建议优先使用" if batch["days_until_expiry"] < 14 else "关注",
            })
        
        # Expired warnings
        for batch in result.get("expired", {}).get("batches", []):
            warnings.append({
                "type": "expired",
                "severity": "critical",
                "material_code": batch["material_code"],
                "batch_code": batch["batch_code"],
                "qty": batch["available_qty"],
                "expiry_date": batch["expiry_date"],
                "days_expired": int(batch["days_expired"]),
                "suggestion": "建议立即报废处理",
            })
        
        return {
            "success": True,
            "warnings": warnings,
            "total_warnings": len(warnings),
            "critical_count": len([w for w in warnings if w["severity"] == "critical"]),
            "high_count": len([w for w in warnings if w["severity"] == "high"]),
            "medium_count": len([w for w in warnings if w["severity"] == "medium"]),
        }
    
    async def _lock_batch(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Lock a batch (prevent outbound)."""
        batch_code = context.get("batch_code")
        lock_reason = context.get("lock_reason", "manual_lock")
        operator = context.get("operator", "system")
        
        if not batch_code:
            return {"error": True, "message": "批次号不能为空"}
        
        # Check if batch exists
        result = await db.execute(text("""
            SELECT id, batch_code, status FROM inventory 
            WHERE factory_id = :fid AND batch_code = :batch
        """), {"fid": factory_id, "batch": batch_code})
        
        inv = result.first()
        if not inv:
            return {"error": True, "message": "批次不存在"}
        
        # Update batch status
        await db.execute(text("""
            UPDATE inventory 
            SET status = 'frozen', 
                freeze_reason = :reason,
                frozen_by = :operator,
                frozen_at = NOW()
            WHERE factory_id = :fid AND batch_code = :batch
        """), {
            "fid": factory_id,
            "batch": batch_code,
            "reason": lock_reason,
            "operator": operator,
        })
        
        await db.commit()
        
        return {
            "success": True,
            "action": "lock_batch",
            "batch_code": batch_code,
            "lock_reason": lock_reason,
            "operator": operator,
            "message": f"批次 {batch_code} 已锁定",
        }
    
    async def _unlock_batch(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Unlock a batch (allow outbound)."""
        batch_code = context.get("batch_code")
        operator = context.get("operator", "system")
        
        if not batch_code:
            return {"error": True, "message": "批次号不能为空"}
        
        # Check if batch exists and is frozen
        result = await db.execute(text("""
            SELECT id, batch_code, status FROM inventory 
            WHERE factory_id = :fid AND batch_code = :batch AND status = 'frozen'
        """), {"fid": factory_id, "batch": batch_code})
        
        inv = result.first()
        if not inv:
            return {"error": True, "message": "批次不存在或未锁定"}
        
        # Update batch status
        await db.execute(text("""
            UPDATE inventory 
            SET status = 'available',
                freeze_reason = NULL,
                frozen_by = NULL,
                frozen_at = NULL
            WHERE factory_id = :fid AND batch_code = :batch
        """), {
            "fid": factory_id,
            "batch": batch_code,
        })
        
        await db.commit()
        
        return {
            "success": True,
            "action": "unlock_batch",
            "batch_code": batch_code,
            "operator": operator,
            "message": f"批次 {batch_code} 已解锁",
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation