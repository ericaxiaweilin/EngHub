"""Replenish Executor for WMS.

Handles replenishment suggestions and automatic replenishment.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from api.services.wms_architecture.policy import (
    CONSUMPTION_TYPES,
    policy_provenance,
    resolve_target,
)


class ReplenishExecutor(BaseWmsExecutor):
    """Execute replenishment operations."""
    
    def get_operation_name(self) -> str:
        return "replenish"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute replenishment operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "operation": str,  # suggestions, auto_replenish
                "material_code": Optional[str],
            }
            
        Returns:
            Replenishment operation result
        """
        operation = context.get("operation", "suggestions")
        
        if operation == "suggestions":
            return await self._get_suggestions(db, factory_id, context)
        elif operation == "auto_replenish":
            return await self._auto_replenish(db, factory_id, context)
        else:
            return {"error": True, "message": f"Unknown operation: {operation}"}
    
    async def _get_suggestions(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """补货建议：物料级配置优先，缺失时回落库存行级水位字段。

        原实现只读 safety_stock_config —— 该厂 0 行时建议恒为 0，与同一份数据算出的
        低库存告警（实测 371 项）互相矛盾；且消耗用 quantity < 0 过滤，而真实流水
        quantity 全为正数，日耗恒 0；又用 reorder_point * 2 编一个上限。
        这里改成一次集合查询 + 单一口径函数，没有消耗时明确返回 null 而不是 999 天。
        """
        limit = int(context.get("limit") or 50)
        window_days = max(1, int(context.get("consumption_window_days") or 30))

        cfg_rows = (await db.execute(text("""
            SELECT material_code, max_stock, safety_stock, reorder_point
            FROM safety_stock_config
            WHERE factory_id = :fid AND is_active = TRUE
        """), {"fid": factory_id})).mappings().all()
        configs = {r["material_code"]: dict(r) for r in cfg_rows}

        rows = (await db.execute(text("""
            WITH policy AS (
                SELECT i.material_code,
                       MAX(i.material_name) AS material_name,
                       SUM(COALESCE(i.available_qty, 0)) AS avail,
                       MAX(COALESCE(NULLIF(i.reorder_point, 0), i.safety_stock, 0)) AS reorder_point,
                       MAX(COALESCE(i.safety_stock, 0)) AS safety_stock,
                       MAX(COALESCE(i.reorder_qty, 0)) AS reorder_qty
                FROM inventory i
                WHERE i.factory_id = :fid
                GROUP BY i.material_code
            ),
            cons AS (
                SELECT m.material_code, SUM(ABS(t.quantity)) AS consumed
                FROM inventory_transactions t
                JOIN (
                    SELECT DISTINCT material_id, material_code
                    FROM inventory WHERE factory_id = :fid
                ) m ON m.material_id = t.material_id
                WHERE t.factory_id = :fid
                  AND t.transaction_type = ANY(:types)
                  AND t.created_at >= NOW() - make_interval(days => :days)
                GROUP BY m.material_code
            )
            SELECT p.material_code, p.material_name, p.avail, p.reorder_point,
                   p.safety_stock, p.reorder_qty, COALESCE(c.consumed, 0) AS consumed_window,
                   COUNT(*) OVER () AS total_below_point
            FROM policy p
            LEFT JOIN cons c ON c.material_code = p.material_code
            WHERE p.avail <= p.reorder_point
            ORDER BY (p.avail - p.reorder_point) ASC
            LIMIT :cap
        """), {
            "fid": factory_id,
            "types": list(CONSUMPTION_TYPES),
            "days": window_days,
            "cap": max(1, min(limit, 200)),
        })).mappings().all()

        suggestions = []
        total_below = 0
        for r in rows:
            cfg = configs.get(r["material_code"]) or {}
            reorder_point = float(cfg.get("reorder_point") or r["reorder_point"] or 0)
            safety_stock = float(cfg.get("safety_stock") or r["safety_stock"] or 0)
            avail = float(r["avail"] or 0)
            target, basis = resolve_target(
                reorder_point=reorder_point,
                safety_stock=safety_stock,
                reorder_qty=r["reorder_qty"],
                max_level=cfg.get("max_stock"),
            )
            if target <= 0 or avail > reorder_point:
                continue
            total_below = int(r["total_below_point"] or 0)
            consumed = float(r["consumed_window"] or 0)
            daily = consumed / window_days
            suggestions.append({
                "material_code": r["material_code"],
                "material_name": r["material_name"] or "",
                "current_stock": int(avail),
                "reorder_point": int(reorder_point),
                "safety_stock": int(safety_stock),
                "target_stock": int(target),
                "policy_basis": basis,
                "consumption_window_days": window_days,
                "consumed_in_window": int(consumed),
                "daily_consumption": round(daily, 2),
                "days_of_stock": round(avail / daily, 1) if daily > 0 else None,
                "suggested_qty": max(int(target - avail), 1),
                "urgency": "high" if safety_stock and avail <= safety_stock else "medium",
            })

        provenance = policy_provenance(len(configs), len(rows))
        urgent = sum(1 for s in suggestions if s["urgency"] == "high")
        return {
            "success": True,
            "suggestions": suggestions,
            "total_items": total_below,
            "urgent_count": urgent,
            "urgent_count_is_sample_only": urgent < total_below,
            "returned_items": len(suggestions),
            "scanned_materials": len(rows),
            **provenance,
            "message": (
                f"低于再订货点的物料 {total_below} 项（本次返回 {len(suggestions)} 项，"
                f"其中紧急 {urgent} 项）；策略来源：{provenance['policy_source']}"
            ),
            "data_note": (
                "days_of_stock 为 null 表示该窗口内没有真实消耗流水，"
                "不编造周转天数；suggested_qty 只按目标水位与现库存差额给出。"
            ),
        }

    async def _auto_replenish(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Auto replenish by creating purchase requests."""
        # Get suggestions first
        suggestions_result = await self._get_suggestions(db, factory_id, context)
        suggestions = suggestions_result.get("suggestions", [])
        
        if not suggestions:
            return {"success": True, "message": "无需要补货的物料"}
        
        # Create purchase requests
        replenishments = []
        for item in suggestions:
            urgency = item["urgency"]
            
            await db.execute(text("""
                INSERT INTO purchase_requests (id, factory_id, material_code, material_name,
                    requested_qty, unit, urgency, status, source, created_at)
                VALUES (gen_random_uuid(), :fid, :mc, :mn, :qty, 'pcs', :urg, 'pending', 'wms_replenish', NOW())
                ON CONFLICT DO NOTHING
            """), {
                "fid": factory_id,
                "mc": item["material_code"],
                "mn": item["material_name"],
                "qty": item["suggested_qty"],
                "urg": urgency,
            })
            
            replenishments.append({
                "material_code": item["material_code"],
                "suggested_qty": item["suggested_qty"],
                "urgency": urgency,
            })
        
        await db.commit()
        
        return {
            "success": True,
            "action": "auto_replenish",
            "total_items": len(replenishments),
            "replenishments": replenishments,
            "note": f"已自动创建{len(replenishments)}条采购申请",
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation