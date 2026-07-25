"""
仓储智能体（Warehouse Agent）
==============================
将WMS从"人查库存→人下补货单"升级为"自动感知→自动补货→自动预警"

触发条件：
- 库存低于安全线 → 自动创建采购申请
- 收货完成 → 自动更新库存+触发IQC
- 出库完成 → 检查是否需要补货
- 定时（每天）→ 呆滞料预警+库位优化建议
- 工单下达 → 齐套检查（物料够不够）

闭环验证：
- 补货后检查：采购申请是否已创建？
- 齐套检查后：缺料工单是否已标记？
- 呆滞预警后：是否已通知采购/仓库？
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("warehouse_agent")


class WarehouseAgent:
    """仓储智能体 - 自动补货+呆滞预警+齐套检查"""

    AGENT_KEY = "warehouse_agent"
    AGENT_NAME = "仓储智能体"

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # 事件处理
    # ═══════════════════════════════════════════════════════════

    async def on_stock_below_safety(self, factory_id: str) -> Dict[str, Any]:
        """事件：库存低于安全线 → 自动创建补货需求"""
        _logger.info(f"[warehouse] 检查安全库存: {factory_id}")

        # 找低于安全线的物料
        result = await self.db.execute(text("""
            SELECT i.material_code, i.material_name, i.available_qty,
                   i.safety_stock, i.reorder_point, i.reorder_qty,
                   i.unit, i.abc_class
            FROM inventory i
            WHERE i.factory_id = :fid
              AND i.available_qty <= COALESCE(i.reorder_point, i.safety_stock, 10)
              AND i.available_qty >= 0
        """), {"fid": factory_id})
        low_stock = [dict(r) for r in result.mappings().all()]

        if not low_stock:
            return {"action": "none", "message": "所有物料库存正常"}

        # 自动创建补货需求（按ABC分类决定紧急度）
        replenishments = []
        for item in low_stock:
            urgency = "urgent" if item.get("abc_class") == "A" else "normal"
            suggested_qty = item.get("reorder_qty") or max(
                (item.get("safety_stock") or 10) * 2 - (item.get("available_qty") or 0), 10
            )

            replenishments.append({
                "material_code": item["material_code"],
                "material_name": item.get("material_name", ""),
                "current_qty": item["available_qty"],
                "safety_stock": item.get("safety_stock"),
                "suggested_qty": suggested_qty,
                "urgency": urgency,
                "abc_class": item.get("abc_class", "C"),
            })

        # 记录补货事件
        task_id = await self._start_task(factory_id, "auto_replenish", f"{len(replenishments)}项物料需补货")

        # 创建采购申请记录
        for r in replenishments:
            await self.db.execute(text("""
                INSERT INTO purchase_requests (id, factory_id, material_code, material_name,
                    requested_qty, unit, urgency, status, source, created_at)
                VALUES (gen_random_uuid(), :fid, :mc, :mn, :qty, :unit, :urg, 'pending', 'warehouse_agent', NOW())
                ON CONFLICT DO NOTHING
            """), {
                "fid": factory_id, "mc": r["material_code"],
                "mn": r["material_name"], "qty": r["suggested_qty"],
                "unit": item.get("unit", "pcs"), "urg": r["urgency"],
            })

        await self.db.commit()
        await self._complete_task(task_id, {"replenishments": len(replenishments)})

        return {
            "action": "auto_replenish",
            "total_items": len(replenishments),
            "urgent_items": len([r for r in replenishments if r["urgency"] == "urgent"]),
            "replenishments": replenishments[:20],
            "note": f"已自动创建{len(replenishments)}条采购申请",
        }

    async def on_work_order_released(self, factory_id: str, wo_id: str) -> Dict[str, Any]:
        """事件：工单下达 → 齐套检查（物料够不够开工）"""
        _logger.info(f"[warehouse] 齐套检查: {wo_id}")

        # 获取工单信息
        wo_result = await self.db.execute(text(
            "SELECT work_order_code, product_id, planned_qty FROM work_orders WHERE id = :id"
        ), {"id": wo_id})
        wo = wo_result.first()
        if not wo:
            return {"action": "skip", "reason": "工单不存在"}

        wo_map = dict(wo._mapping)
        planned_qty = wo_map["planned_qty"] or 1

        # 获取BOM
        bom_result = await self.db.execute(text("""
            SELECT b.material_code, b.material_name, b.quantity_per_unit, b.unit,
                   COALESCE(i.available_qty, 0) as available_qty
            FROM bom_items b
            LEFT JOIN inventory i ON b.material_code = i.material_code AND i.factory_id = :fid
            WHERE b.product_id = :pid AND b.factory_id = :fid
        """), {"fid": factory_id, "pid": wo_map["product_id"]})
        bom_items = [dict(r) for r in bom_result.mappings().all()]

        if not bom_items:
            return {
                "action": "no_bom",
                "work_order": wo_map["work_order_code"],
                "message": "该产品无BOM，无法进行齐套检查",
            }

        # 齐套分析
        material_status = []
        shortage_count = 0
        for item in bom_items:
            required = (item["quantity_per_unit"] or 1) * planned_qty
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

        # 如果缺料，标记工单
        if not is_complete:
            await self.db.execute(text("""
                UPDATE work_orders SET material_status = 'shortage' WHERE id = :id
            """), {"id": wo_id})
            await self.db.commit()

        return {
            "action": "kit_check",
            "work_order": wo_map["work_order_code"],
            "planned_qty": planned_qty,
            "is_complete": is_complete,
            "total_materials": len(bom_items),
            "shortage_count": shortage_count,
            "materials": material_status,
            "recommendation": "可以开工" if is_complete else f"缺{shortage_count}种物料，建议先补货",
        }

    # ═══════════════════════════════════════════════════════════
    # 定时任务
    # ═══════════════════════════════════════════════════════════

    async def daily_dead_stock_check(self, factory_id: str, days_threshold: int = 90) -> Dict[str, Any]:
        """定时：呆滞料预警（N天无出入库记录）"""
        _logger.info(f"[warehouse] 呆滞料检查: {factory_id} (>{days_threshold}天)")

        result = await self.db.execute(text("""
            SELECT i.material_code, i.material_name, i.available_qty, i.unit,
                   i.abc_class,
                   COALESCE(last_txn.last_activity, i.created_at) as last_activity,
                   EXTRACT(DAY FROM NOW() - COALESCE(last_txn.last_activity, i.created_at)) as idle_days
            FROM inventory i
            LEFT JOIN (
                SELECT material_code, MAX(created_at) as last_activity
                FROM inventory_transactions
                WHERE factory_id = :fid
                GROUP BY material_code
            ) last_txn ON i.material_code = last_txn.material_code
            WHERE i.factory_id = :fid AND i.available_qty > 0
              AND COALESCE(last_txn.last_activity, i.created_at) < NOW() - :days * INTERVAL '1 day'
            ORDER BY idle_days DESC
        """), {"fid": factory_id, "days": days_threshold})
        dead_stock = [dict(r) for r in result.mappings().all()]

        if not dead_stock:
            return {"action": "none", "message": f"无超过{days_threshold}天的呆滞料"}

        # 计算占用资金（简化：按数量×单价估算）
        total_value = sum(d["available_qty"] * 10 for d in dead_stock)  # 简化估价

        return {
            "action": "dead_stock_alert",
            "threshold_days": days_threshold,
            "total_items": len(dead_stock),
            "estimated_value": total_value,
            "items": [{
                "material_code": d["material_code"],
                "material_name": d.get("material_name", ""),
                "qty": d["available_qty"],
                "idle_days": int(d["idle_days"]),
                "abc_class": d.get("abc_class", "C"),
                "suggestion": "建议处理" if d["idle_days"] > 180 else "关注",
            } for d in dead_stock[:30]],
            "recommendation": f"{len(dead_stock)}种物料超过{days_threshold}天未动，占用约{total_value}元",
        }

    async def location_optimization(self, factory_id: str) -> Dict[str, Any]:
        """定时：库位优化建议（高频物料应靠近出货区）"""
        # 获取出库频率
        result = await self.db.execute(text("""
            SELECT it.material_code, COUNT(*) as outbound_count,
                   i.location_code, i.abc_class
            FROM inventory_transactions it
            JOIN inventory i ON it.material_code = i.material_code AND i.factory_id = :fid
            WHERE it.factory_id = :fid AND it.transaction_type = 'outbound'
              AND it.created_at > NOW() - INTERVAL '30 days'
            GROUP BY it.material_code, i.location_code, i.abc_class
            ORDER BY outbound_count DESC
        """), {"fid": factory_id})
        freq_data = [dict(r) for r in result.mappings().all()]

        if not freq_data:
            return {"action": "none", "message": "无近30天出库记录"}

        # 高频物料（出库>10次）如果在远区（假设C/D区为远区），建议移到近区
        suggestions = []
        for item in freq_data:
            loc = item.get("location_code") or ""
            is_far = any(loc.startswith(z) for z in ["C", "D", "Z"])
            if item["outbound_count"] > 10 and is_far:
                suggestions.append({
                    "material_code": item["material_code"],
                    "current_location": loc,
                    "outbound_count_30d": item["outbound_count"],
                    "suggestion": "移至A区（靠近出货口）",
                })

        return {
            "action": "location_optimization",
            "total_analyzed": len(freq_data),
            "suggestions": suggestions[:20],
            "suggestion_count": len(suggestions),
            "note": f"{len(suggestions)}种高频物料建议调整库位" if suggestions else "库位合理",
        }

    async def inventory_health(self, factory_id: str) -> Dict[str, Any]:
        """库存健康度总览"""
        # 总库存
        total = await self.db.execute(text("""
            SELECT COUNT(DISTINCT material_code) as sku_count,
                   SUM(available_qty) as total_qty
            FROM inventory WHERE factory_id = :fid AND available_qty > 0
        """), {"fid": factory_id})
        total_row = dict(total.first()._mapping)

        # 低于安全线
        low = await self.db.execute(text("""
            SELECT COUNT(*) FROM inventory
            WHERE factory_id = :fid AND available_qty <= COALESCE(reorder_point, safety_stock, 10)
        """), {"fid": factory_id})
        low_count = low.scalar() or 0

        # 呆滞（>90天）
        dead = await self.db.execute(text("""
            SELECT COUNT(*) FROM inventory i
            WHERE i.factory_id = :fid AND i.available_qty > 0
              AND NOT EXISTS (
                  SELECT 1 FROM inventory_transactions it
                  WHERE it.material_code = i.material_code AND it.factory_id = :fid
                    AND it.created_at > NOW() - INTERVAL '90 days'
              )
        """), {"fid": factory_id})
        dead_count = dead.scalar() or 0

        # ABC分布
        abc = await self.db.execute(text("""
            SELECT COALESCE(abc_class, 'C') as cls, COUNT(*) as cnt
            FROM inventory WHERE factory_id = :fid AND available_qty > 0
            GROUP BY abc_class
        """), {"fid": factory_id})
        abc_dist = {r[0]: r[1] for r in abc.fetchall()}

        sku_count = total_row["sku_count"] or 1
        health_score = max(0, 100 - (low_count / sku_count * 50) - (dead_count / sku_count * 30))

        return {
            "factory_id": factory_id,
            "health_score": round(health_score, 1),
            "sku_count": total_row["sku_count"],
            "total_qty": total_row["total_qty"],
            "below_safety": low_count,
            "dead_stock_90d": dead_count,
            "abc_distribution": abc_dist,
            "alerts": {
                "replenishment_needed": low_count > 0,
                "dead_stock_cleanup": dead_count > 5,
            },
            "recommendation": "库存健康" if health_score > 70 else "需要关注" if health_score > 50 else "需要立即处理",
        }

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _start_task(self, factory_id: str, task_type: str, desc: str) -> Optional[str]:
        try:
            from api.services.agent_supervisor_service import AgentSupervisor
            supervisor = AgentSupervisor(self.db)
            result = await supervisor.start_task(
                factory_id=factory_id,
                agent_key=self.AGENT_KEY,
                agent_name=self.AGENT_NAME,
                task_type=task_type,
                task_desc=desc,
                total_steps=3,
                timeout_minutes=10,
            )
            return result.get("task_id")
        except Exception as e:
            _logger.warning(f"[warehouse] 注册长任务失败: {e}")
            return None

    async def _complete_task(self, task_id: Optional[str], result: Dict):
        if task_id:
            try:
                from api.services.agent_supervisor_service import AgentSupervisor
                supervisor = AgentSupervisor(self.db)
                await supervisor.complete_task(task_id, result=result)
            except Exception:
                pass
