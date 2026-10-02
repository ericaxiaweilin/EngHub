"""
交期智能体（delivery_agent）—— T+3 交期管控定时循环

职责：每 60 分钟扫描在制工单交期风险
- 高风险（距交期 <3 天且按当前速度无法完成）→ 真实提升工单优先级（幂等）
- 中风险 → 仅记录建议，不自动干预
- 全程落 agent_tasks 生命周期 + 心跳 + 事件，监督看板可见

注意：所有写入幂等（仅更新 priority != 'high' 的工单），重复运行不产生脏数据。
"""
import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger("delivery_agent")

AGENT_KEY = "delivery_agent"
AGENT_NAME = "交期智能体"


class DeliveryAgent:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_delivery_risks(self, factory_id: str) -> Dict[str, Any]:
        """扫描交期风险：高风险真实提优先级，返回汇总（幂等）。"""
        from api.services.agent_supervisor_service import AgentSupervisor
        svc = AgentSupervisor(self.db)

        task = await svc.start_task(
            factory_id, AGENT_KEY, "delivery_risk_scan",
            "T+3 交期风险扫描与自动提级", total_steps=2, timeout_minutes=10,
        )
        task_id = task["task_id"]

        risks: List[Dict[str, Any]] = []
        escalated: List[str] = []
        try:
            # 与 supervisor predict 同一口径：按当前速度估算剩余天数
            result = await self.db.execute(text("""
                SELECT wo.id, wo.work_order_code, wo.planned_qty, wo.completed_qty,
                       wo.planned_due, wo.priority, wo.actual_start,
                       CASE WHEN wo.completed_qty > 0 AND wo.actual_start IS NOT NULL
                            THEN (wo.planned_qty - wo.completed_qty) *
                                 EXTRACT(EPOCH FROM (NOW() - wo.actual_start)) / wo.completed_qty / 86400.0
                            ELSE NULL END as estimated_remaining_days
                FROM work_orders wo
                WHERE wo.factory_id = :fid AND wo.status = 'in_progress'
                  AND wo.planned_due IS NOT NULL
            """), {"fid": factory_id})

            for row in result.fetchall():
                r = dict(row._mapping)
                remaining_days = r.get("estimated_remaining_days")
                due_date = r.get("planned_due")
                if not (remaining_days and due_date):
                    continue
                days_to_due = (due_date - datetime.utcnow()).total_seconds() / 86400
                if remaining_days > days_to_due and days_to_due > 0:
                    severity = "high" if days_to_due < 3 else "medium"
                    risks.append({
                        "work_order_code": r["work_order_code"],
                        "severity": severity,
                        "days_to_due": round(days_to_due, 1),
                        "estimated_remaining_days": round(remaining_days, 1),
                    })

            await svc.update_progress(task_id, 1, f"扫描完成，{len(risks)} 个风险工单")

            # 高风险：真实提升优先级（幂等——仅更新非 high 的）
            high_codes = [x["work_order_code"] for x in risks if x["severity"] == "high"]
            if high_codes:
                upd = await self.db.execute(text("""
                    UPDATE work_orders SET priority = 'high'
                    WHERE factory_id = :fid AND work_order_code = ANY(:codes)
                      AND COALESCE(priority, '') != 'high'
                    RETURNING work_order_code
                """), {"fid": factory_id, "codes": high_codes})
                escalated = [r[0] for r in upd.fetchall()]

            await svc.complete_task(task_id, {
                "scanned_risks": len(risks), "escalated": escalated,
            })

            # 事件落总线（供 SSE/审计实时可见）
            try:
                from core.agent import AgentEventBus, EventType
                await AgentEventBus.get_instance().emit(
                    EventType.ACTION_END, AGENT_KEY, factory_id,
                    task_id=task_id,
                    data={
                        "event_type": "delivery_risk_scan",
                        "risks": len(risks),
                        "escalated": escalated,
                    },
                )
            except Exception as _ee:
                _logger.warning("[delivery] 事件写入失败: %s", _ee)

            summary = f"风险{len(risks)}单，提级{len(escalated)}单"
            await svc.record_heartbeat(
                factory_id, AGENT_KEY, "T+3 交期扫描", "schedule", summary,
            )
            _logger.info("[delivery] %s: %s", factory_id, summary)

            return {
                "factory_id": factory_id,
                "scanned_risks": len(risks),
                "escalated": escalated,
                "risks": risks,
            }
        except Exception as e:
            try:
                await svc.complete_task(task_id, error=str(e))
                await self.db.rollback()
            except Exception:
                pass
            _logger.warning("[delivery] %s 扫描失败: %s", factory_id, e)
            return {"factory_id": factory_id, "scanned_risks": 0, "escalated": [], "error": str(e)}
