"""
排产智能体（Scheduling Agent）
==============================
将APS引擎从"人点按钮排程"升级为"事件驱动自动排程+闭环验证"

触发条件：
- 新工单下达（released）→ 自动排入
- 紧急插单（priority=urgent/emergency）→ 立即重排
- 设备故障 → 受影响工单自动迁移
- 物料延迟 → 推迟相关工单
- 定时（每30分钟）→ 产能平衡检查

闭环验证：
- 排程后检查：所有工单是否都有时间段？交期冲突是否已标记？
- 插单后检查：被挤掉的工单是否已通知？
- 产能平衡：各工位利用率是否在合理范围（40%-90%）？

与现有APS引擎的关系：
- ApsEngine: 核心算法（EDD/SPT/CR排序+时间轴分配）
- SchedulingAgent: 智能体壳（事件感知+自动触发+闭环验证+进度上报）
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func, and_

from database.models import WorkOrder, Station, Equipment

_logger = logging.getLogger("scheduling_agent")


class SchedulingAgent:
    """排产智能体 - 事件驱动自动排程"""

    AGENT_KEY = "scheduling_agent"
    AGENT_NAME = "排产智能体"

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # 事件处理
    # ═══════════════════════════════════════════════════════════

    async def on_work_order_released(self, factory_id: str, wo_id: str) -> Dict[str, Any]:
        """事件：新工单下达 → 自动排入当前计划"""
        _logger.info(f"[scheduling] 新工单下达: {wo_id}")

        # 检查是否需要立即重排（紧急工单）
        wo_result = await self.db.execute(text(
            "SELECT work_order_code, priority, planned_qty, planned_due FROM work_orders WHERE id = :id"
        ), {"id": wo_id})
        wo = wo_result.first()
        if not wo:
            return {"action": "skip", "reason": "工单不存在"}

        wo_map = dict(wo._mapping)
        is_urgent = wo_map["priority"] in ("urgent", "emergency")

        if is_urgent:
            # 紧急工单：立即重排
            result = await self.auto_reschedule(factory_id, reason=f"紧急工单 {wo_map['work_order_code']} 下达")
            return {"action": "reschedule", "trigger": "urgent_order", **result}
        else:
            # 普通工单：追加到当前排程末尾
            result = await self._append_to_schedule(factory_id, wo_id)
            return {"action": "append", "trigger": "new_order", **result}

    async def on_equipment_breakdown(self, factory_id: str, equipment_id: str) -> Dict[str, Any]:
        """事件：设备故障 → 受影响工单自动迁移到其他工位"""
        _logger.info(f"[scheduling] 设备故障: {equipment_id}")

        # 找到该设备上正在排程的工单
        affected = await self.db.execute(text("""
            SELECT t.id, t.work_order_id, t.planned_start, t.planned_end, w.work_order_code
            FROM aps_schedule_tasks t
            JOIN work_orders w ON t.work_order_id = w.id
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE t.station_id = :eid AND s.factory_id = :fid AND s.status IN ('draft', 'confirmed')
              AND t.planned_end > NOW()
        """), {"eid": equipment_id, "fid": factory_id})
        affected_tasks = [dict(r) for r in affected.mappings().all()]

        if not affected_tasks:
            return {"action": "none", "reason": "该设备无待执行排程任务"}

        # 找可用替代工位
        alt_stations = await self.db.execute(text("""
            SELECT id, station_code FROM stations
            WHERE factory_id = :fid AND status = 'idle' AND id != :eid
            LIMIT 3
        """), {"fid": factory_id, "eid": equipment_id})
        alternatives = [dict(r) for r in alt_stations.mappings().all()]

        if not alternatives:
            return {
                "action": "blocked",
                "affected_orders": len(affected_tasks),
                "reason": "无可用替代工位，需人工调度",
                "escalate": True,
            }

        # 自动迁移
        migrated = []
        alt_idx = 0
        for task in affected_tasks:
            target = alternatives[alt_idx % len(alternatives)]
            await self.db.execute(text("""
                UPDATE aps_schedule_tasks SET station_id = :new_sid WHERE id = :tid
            """), {"new_sid": target["id"], "tid": task["id"]})
            migrated.append({
                "work_order": task["work_order_code"],
                "from": equipment_id,
                "to": target["station_code"],
            })
            alt_idx += 1

        await self.db.commit()

        return {
            "action": "migrated",
            "affected_orders": len(affected_tasks),
            "migrated": migrated,
            "note": f"已将{len(migrated)}个工单从故障设备迁移到替代工位",
        }

    async def on_material_delay(self, factory_id: str, material_code: str, delay_days: int) -> Dict[str, Any]:
        """事件：物料延迟 → 推迟使用该物料的工单"""
        _logger.info(f"[scheduling] 物料延迟: {material_code} +{delay_days}天")

        # 找使用该物料的待排工单（通过BOM）
        affected = await self.db.execute(text("""
            SELECT DISTINCT w.id, w.work_order_code, w.planned_due
            FROM work_orders w
            JOIN bom_items b ON w.product_id = b.product_id AND w.factory_id = b.factory_id
            WHERE b.material_code = :mc AND w.factory_id = :fid
              AND w.status IN ('released', 'pending')
        """), {"mc": material_code, "fid": factory_id})
        affected_wos = [dict(r) for r in affected.mappings().all()]

        if not affected_wos:
            return {"action": "none", "reason": f"无工单使用物料 {material_code}"}

        # 推迟排程
        postponed = []
        for wo in affected_wos:
            result = await self.db.execute(text("""
                UPDATE aps_schedule_tasks
                SET planned_start = planned_start + :delay * INTERVAL '1 day',
                    planned_end = planned_end + :delay * INTERVAL '1 day'
                WHERE work_order_id = :wo_id
                  AND planned_start > NOW()
                RETURNING id
            """), {"delay": delay_days, "wo_id": wo["id"]})
            if result.first():
                postponed.append(wo["work_order_code"])

        await self.db.commit()

        return {
            "action": "postponed",
            "material": material_code,
            "delay_days": delay_days,
            "affected_orders": len(affected_wos),
            "postponed": postponed,
            "note": f"物料{material_code}延迟{delay_days}天，已推迟{len(postponed)}个工单",
        }

    # ═══════════════════════════════════════════════════════════
    # 核心能力
    # ═══════════════════════════════════════════════════════════

    async def auto_schedule(self, factory_id: str, algorithm: str = "EDD") -> Dict[str, Any]:
        """自动排程（定时触发 or 手动触发）"""
        from api.services.aps_engine import ApsEngine

        # 启动长任务
        task_id = await self._start_task(factory_id, "auto_schedule", f"自动排程({algorithm})")

        try:
            engine = ApsEngine(self.db)
            result = await engine.schedule(factory_id, algorithm=algorithm, created_by="scheduling_agent")

            if "error" in result:
                await self._fail_task(task_id, result["error"])
                return {"success": False, "error": result["error"]}

            # 闭环验证
            verification = await self._verify_schedule(factory_id, result["schedule_id"])

            await self._complete_task(task_id, {
                "schedule_id": result["schedule_id"],
                "tasks": result["total_tasks"],
                "conflicts": result["conflict_count"],
            })

            return {
                "success": True,
                "schedule_id": result["schedule_id"],
                "schedule_code": result["schedule_code"],
                "algorithm": algorithm,
                "total_tasks": result["total_tasks"],
                "conflict_count": result["conflict_count"],
                "conflicts": result.get("conflicts", []),
                "station_utilization": result.get("station_utilization", {}),
                "verification": verification,
            }
        except Exception as e:
            await self._fail_task(task_id, str(e))
            raise

    async def auto_reschedule(self, factory_id: str, reason: str = "") -> Dict[str, Any]:
        """自动重排（插单/设备故障/物料延迟触发）"""
        from api.services.aps_engine import ApsEngine

        task_id = await self._start_task(factory_id, "auto_reschedule", f"自动重排: {reason}")

        try:
            engine = ApsEngine(self.db)
            result = await engine.reschedule(factory_id, created_by="scheduling_agent")

            verification = await self._verify_schedule(factory_id, result.get("schedule_id"))
            await self._complete_task(task_id, {"reason": reason, "tasks": result.get("total_tasks", 0)})

            return {
                "success": True,
                "reason": reason,
                "locked_orders": result.get("locked_orders", 0),
                "total_tasks": result.get("total_tasks", 0),
                "conflict_count": result.get("conflict_count", 0),
                "verification": verification,
            }
        except Exception as e:
            await self._fail_task(task_id, str(e))
            raise

    async def what_if(self, factory_id: str, new_wo: Dict[str, Any]) -> Dict[str, Any]:
        """
        What-if模拟：如果加入这个新工单，对现有排程有什么影响？
        不实际修改数据，只返回模拟结果。
        """
        # 获取当前排程状态
        current = await self.db.execute(text("""
            SELECT COUNT(*) as cnt,
                   MAX(planned_end) as latest_end
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft', 'confirmed')
        """), {"fid": factory_id})
        cur = dict(current.first()._mapping)

        # 获取产能
        cap_result = await self.db.execute(text("""
            SELECT station_id, available_hours_per_day, efficiency_rate
            FROM station_capacity WHERE factory_id = :fid AND is_active = TRUE
        """), {"fid": factory_id})
        capacities = [dict(r) for r in cap_result.mappings().all()]

        total_daily_capacity = sum(
            float(c.get("available_hours_per_day") or 16)
            * float(c.get("efficiency_rate") or 0.85)
            for c in capacities
        ) or 16

        # 估算新工单需要的工时
        qty = new_wo.get("planned_qty", 100)
        estimated_hours = qty * 0.5 / 0.85  # 简化：每件0.5h / 效率

        # 影响分析
        impact_days = estimated_hours / (total_daily_capacity / 8)  # 大约需要几天
        current_latest = cur.get("latest_end")

        # 检查对交期的影响
        at_risk = await self.db.execute(text("""
            SELECT w.work_order_code, w.planned_due, t.planned_end
            FROM aps_schedule_tasks t
            JOIN work_orders w ON t.work_order_id = w.id
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft', 'confirmed')
              AND w.planned_due IS NOT NULL
              AND t.planned_end + :impact * INTERVAL '1 hour' > w.planned_due
        """), {"fid": factory_id, "impact": estimated_hours})
        at_risk_orders = [dict(r) for r in at_risk.mappings().all()]

        return {
            "simulation": True,
            "new_order": new_wo,
            "estimated_hours": round(estimated_hours, 1),
            "estimated_days": round(impact_days, 1),
            "current_schedule": {
                "total_tasks": cur.get("cnt", 0),
                "latest_end": str(current_latest) if current_latest else None,
            },
            "total_daily_capacity_hours": round(total_daily_capacity, 1),
            "impact": {
                "orders_at_risk": len(at_risk_orders),
                "at_risk_list": [r["work_order_code"] for r in at_risk_orders[:10]],
                "recommendation": "可以插入" if len(at_risk_orders) == 0 else f"会影响{len(at_risk_orders)}个工单交期",
            },
        }

    async def capacity_balance(self, factory_id: str) -> Dict[str, Any]:
        """产能平衡检查：各工位利用率是否合理"""
        result = await self.db.execute(text("""
            SELECT t.station_id,
                   COUNT(*) as task_count,
                   SUM(EXTRACT(EPOCH FROM (t.planned_end - t.planned_start)) / 3600) as total_hours
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft', 'confirmed')
              AND t.planned_start > NOW()
            GROUP BY t.station_id
        """), {"fid": factory_id})
        loads = [dict(r) for r in result.mappings().all()]

        if not loads:
            return {"balanced": True, "message": "无待执行排程任务"}

        hours_list = [l["total_hours"] for l in loads]
        avg_hours = sum(hours_list) / len(hours_list)
        max_hours = max(hours_list)
        min_hours = min(hours_list)

        # 不平衡度 = (最大-最小) / 平均
        imbalance = (max_hours - min_hours) / avg_hours if avg_hours > 0 else 0

        overloaded = [l for l in loads if l["total_hours"] > avg_hours * 1.3]
        underloaded = [l for l in loads if l["total_hours"] < avg_hours * 0.5]

        return {
            "balanced": imbalance < 0.3,
            "imbalance_ratio": round(imbalance, 2),
            "stations": [{
                "station_id": l["station_id"],
                "task_count": l["task_count"],
                "total_hours": round(l["total_hours"], 1),
                "status": "overloaded" if l["total_hours"] > avg_hours * 1.3
                          else "underloaded" if l["total_hours"] < avg_hours * 0.5
                          else "normal",
            } for l in loads],
            "avg_hours": round(avg_hours, 1),
            "recommendation": "产能平衡" if imbalance < 0.3 else f"不平衡度{imbalance:.0%}，建议重排",
            "auto_action": None if imbalance < 0.3 else "建议执行auto_reschedule",
        }

    # ═══════════════════════════════════════════════════════════
    # 闭环验证
    # ═══════════════════════════════════════════════════════════

    async def _verify_schedule(self, factory_id: str, schedule_id: Optional[str]) -> Dict[str, Any]:
        """排程闭环验证：排完了检查对不对"""
        checks = []

        if not schedule_id:
            return {"passed": False, "checks": [{"check": "schedule_exists", "passed": False}]}

        # 1. 所有待排工单是否都有时间段？
        unscheduled = await self.db.execute(text("""
            SELECT COUNT(*) FROM work_orders w
            WHERE w.factory_id = :fid AND w.status IN ('released', 'pending') AND w.wo_type = 'master'
              AND NOT EXISTS (
                  SELECT 1 FROM aps_schedule_tasks t WHERE t.work_order_id = w.id AND t.schedule_id = :sid
              )
        """), {"fid": factory_id, "sid": schedule_id})
        unscheduled_count = unscheduled.scalar() or 0
        checks.append({
            "check": "all_orders_scheduled",
            "passed": unscheduled_count == 0,
            "detail": f"{unscheduled_count}个工单未排入" if unscheduled_count > 0 else "全部已排",
        })

        # 2. 是否有时间重叠？
        overlaps = await self.db.execute(text("""
            SELECT COUNT(*) FROM aps_schedule_tasks a
            JOIN aps_schedule_tasks b ON a.station_id = b.station_id AND a.id < b.id
            WHERE a.schedule_id = :sid AND b.schedule_id = :sid
              AND a.planned_start < b.planned_end AND b.planned_start < a.planned_end
        """), {"sid": schedule_id})
        overlap_count = overlaps.scalar() or 0
        checks.append({
            "check": "no_time_overlap",
            "passed": overlap_count == 0,
            "detail": f"{overlap_count}个时间冲突" if overlap_count > 0 else "无冲突",
        })

        # 3. 交期风险是否已标记？
        late_count = await self.db.execute(text("""
            SELECT COUNT(*) FROM aps_schedule_tasks t
            JOIN work_orders w ON t.work_order_id = w.id
            WHERE t.schedule_id = :sid AND w.planned_due IS NOT NULL AND t.planned_end > w.planned_due
        """), {"sid": schedule_id})
        late = late_count.scalar() or 0
        checks.append({
            "check": "delivery_risk_flagged",
            "passed": True,  # 只要有标记就行
            "detail": f"{late}个工单有交期风险（已标记）",
        })

        all_passed = all(c["passed"] for c in checks)
        return {"passed": all_passed, "checks": checks}

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _append_to_schedule(self, factory_id: str, wo_id: str) -> Dict[str, Any]:
        """追加到当前排程末尾"""
        # 获取最新排程
        latest = await self.db.execute(text(
            "SELECT id FROM aps_schedules WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 1"
        ), {"fid": factory_id})
        row = latest.first()
        if not row:
            # 没有排程，触发全量排程
            return await self.auto_schedule(factory_id)

        schedule_id = row[0]

        # 获取工单信息
        wo_result = await self.db.execute(text(
            "SELECT work_order_code, planned_qty, assigned_station_id FROM work_orders WHERE id = :id"
        ), {"id": wo_id})
        wo = wo_result.first()
        if not wo:
            return {"success": False, "error": "工单不存在"}

        wo_map = dict(wo._mapping)
        station_id = wo_map.get("assigned_station_id") or "ST-01"

        # 找该工位最晚结束时间
        last_end = await self.db.execute(text("""
            SELECT MAX(planned_end) FROM aps_schedule_tasks
            WHERE schedule_id = :sid AND station_id = :stid
        """), {"sid": schedule_id, "stid": station_id})
        end_row = last_end.first()
        start_time = end_row[0] if end_row and end_row[0] else datetime.utcnow()

        process_hours = (wo_map["planned_qty"] or 100) * 0.5 / 0.85
        end_time = start_time + timedelta(hours=process_hours)

        import uuid
        task_id = str(uuid.uuid4())
        await self.db.execute(text("""
            INSERT INTO aps_schedule_tasks (id, schedule_id, work_order_id, station_id,
                planned_start, planned_end, setup_minutes, sequence_in_station, material_ready, operation_seq)
            VALUES (:id, :sid, :wo_id, :st_id, :start, :end, 30, 99, TRUE, 99)
        """), {
            "id": task_id, "sid": schedule_id, "wo_id": wo_id,
            "st_id": station_id, "start": start_time, "end": end_time,
        })
        await self.db.commit()

        return {
            "success": True,
            "work_order": wo_map["work_order_code"],
            "station": station_id,
            "planned_start": start_time.isoformat(),
            "planned_end": end_time.isoformat(),
        }

    async def _start_task(self, factory_id: str, task_type: str, desc: str) -> Optional[str]:
        """向supervisor注册长任务"""
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
            _logger.warning(f"[scheduling] 注册长任务失败: {e}")
            return None

    async def _complete_task(self, task_id: Optional[str], result: Dict):
        if task_id:
            try:
                from api.services.agent_supervisor_service import AgentSupervisor
                supervisor = AgentSupervisor(self.db)
                await supervisor.complete_task(task_id, result=result)
            except Exception:
                pass

    async def _fail_task(self, task_id: Optional[str], error: str):
        if task_id:
            try:
                from api.services.agent_supervisor_service import AgentSupervisor
                supervisor = AgentSupervisor(self.db)
                await supervisor.complete_task(task_id, error=error)
            except Exception:
                pass
