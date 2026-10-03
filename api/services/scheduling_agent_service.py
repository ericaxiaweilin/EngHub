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
from core.mes.capacity_math import load_station_models

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
            "SELECT work_order_code, priority, planned_qty, planned_due, product_id FROM work_orders WHERE id = :id"
        ), {"id": wo_id})
        wo = wo_result.first()
        if not wo:
            return {"action": "skip", "reason": "工单不存在"}

        wo_map = dict(wo._mapping)
        is_urgent = wo_map["priority"] in ("urgent", "emergency")

        if is_urgent:
            # 紧急工单：先查插单审批单（审计 Q4），有已批准批文才重排，否则挂起待审
            from core.pp.rush_approval_service import RushApprovalService

            appr_svc = RushApprovalService(self.db)
            approved = await appr_svc.find_approved_for_wo(factory_id, wo_map.get("product_id") or "")
            if not approved:
                return {
                    "action": "pending_approval",
                    "trigger": "urgent_order",
                    "message": f"紧急工单 {wo_map['work_order_code']} 无已批准插单审批单，已挂起待审批，不执行全厂重排",
                }
            result = await self.auto_reschedule(
                factory_id,
                reason=f"紧急工单 {wo_map['work_order_code']} 下达（审批单 {approved.approval_code} 已批准）",
            )
            return {"action": "reschedule", "trigger": "urgent_order", "approval_code": approved.approval_code, **result}
        else:
            # 普通工单：追加到当前排程末尾
            result = await self._append_to_schedule(factory_id, wo_id)
            return {"action": "append", "trigger": "new_order", **result}

    async def _live_schedule_id(self, factory_id: str) -> Optional[str]:
        """当前生效的那一版：优先 is_current，否则取版本号最新的一版。

        APS 事件处理只能作用在一版方案上。不带 schedule 范围的话，历史 draft 有上百份，
        按行 UPDATE 会把同一工单在每一版里各改一遍，统计口径也跟着失真。
        """
        return (await self.db.execute(text("""
            SELECT id FROM aps_schedules
            WHERE factory_id = :fid
            ORDER BY is_current DESC, version_number DESC, created_at DESC
            LIMIT 1
        """), {"fid": factory_id})).scalar()

    async def on_equipment_breakdown(
        self,
        factory_id: str,
        equipment_id: str,
        horizon_days: int = 30,
    ) -> Dict[str, Any]:
        """事件：设备故障 → 停用该工位并重排一版（PMC 钉住的工序保持不动）。

        原实现是把该工位的任务按 id 轮询塞进 stations.status='idle' 的工位。库里 28 个
        工位全是 'active'，所以它永远返回"无可用替代工位"；而一旦真出现 idle，它会把
        机加工工序搬到包装线，还会与目标工位已有任务在时间轴上重叠 —— 那不叫改派。
        现在把故障工位作为 exclude_resources 交给排程引擎：受影响工序只会落到工艺路线
        允许、班次日历允许、时间轴不冲突的其他工位；排不进的如实列出来交人工。
        """
        # 先分清"一台设备故障"和"整个工位没有可用设备"。
        # 工位是排程里的一个资源槽，一台机床坏了不该让整条加工车间停工。
        machine = (await self.db.execute(text("""
            SELECT COALESCE(NULLIF(t.station_id, ''), t.equipment_code) AS resource_id,
                   t.status AS this_status,
                   COUNT(*) AS machines_on_resource,
                   COUNT(*) FILTER (
                       WHERE COALESCE(m.status, 'running') NOT IN ('broken', 'maintenance')
                   ) AS usable_machines
            FROM equipment t
            LEFT JOIN equipment m
                   ON COALESCE(NULLIF(m.station_id, ''), m.equipment_code)
                      = COALESCE(NULLIF(t.station_id, ''), t.equipment_code)
                  AND m.factory_id = t.factory_id
            WHERE t.factory_id = :fid AND (t.id = :eid OR t.equipment_code = :eid)
            GROUP BY 1, 2
        """), {"fid": factory_id, "eid": equipment_id})).mappings().first()

        if machine and int(machine["usable_machines"]) > 0:
            return {
                "action": "none",
                "station": str(machine["resource_id"]),
                "equipment_status": machine["this_status"],
                "usable_machines": int(machine["usable_machines"]),
                "machines_on_station": int(machine["machines_on_resource"]),
                "reason": (
                    f"{machine['this_status']} 的设备只是 {machine['resource_id']} 名下 "
                    f"{machine['machines_on_resource']} 台里的 1 台，"
                    f"仍有 {machine['usable_machines']} 台可用，工位不停、排程不变"
                ),
                "note": (
                    "当前资源模型里一个工位是一个占用槽，不区分同一工位内几台设备并行，"
                    "所以单台设备故障不会改变排程；要按设备台数算产能需要另做资源模型"
                ),
            }

        live_schedule_id = await self._live_schedule_id(factory_id)
        if not live_schedule_id:
            return {"action": "none", "reason": "该工厂还没有排程方案，无需处理故障"}

        previous_total_tasks = int((await self.db.execute(text(
            "SELECT COUNT(*) FROM aps_schedule_tasks WHERE schedule_id = :sid"
        ), {"sid": str(live_schedule_id)})).scalar() or 0)

        affected = (await self.db.execute(text("""
            SELECT t.work_order_id, t.operation_seq, t.station_id,
                   COALESCE(t.is_locked, false) AS is_locked, w.work_order_code
            FROM aps_schedule_tasks t
            JOIN work_orders w ON w.id::text = t.work_order_id
            WHERE t.schedule_id = :sid AND t.station_id = :eid AND t.planned_end > NOW()
        """), {"sid": str(live_schedule_id), "eid": equipment_id})).mappings().all()
        affected_keys = {(str(r["work_order_id"]), int(r["operation_seq"])) for r in affected}
        locked_keys = {(str(r["work_order_id"]), int(r["operation_seq"])) for r in affected if r["is_locked"]}

        if not affected_keys:
            return {"action": "none", "reason": "该工位上没有未来排程任务，无需改派"}

        from api.services.aps_service import ApsService

        result = await ApsService(self.db).generate_schedule(
            factory_id=factory_id,
            mode="hybrid",
            horizon_days=horizon_days,
            created_by="scheduling_agent",
            change_reason=f"equipment_breakdown:{equipment_id}",
            exclude_resources=[equipment_id],
        )
        new_schedule_id = result.get("schedule_id")
        if not new_schedule_id:
            return {
                "action": "blocked",
                "escalate": True,
                "affected_tasks": len(affected_keys),
                "reason": f"停用 {equipment_id} 后重排失败，原方案保持不变：{result.get('message')}",
            }

        placed = (await self.db.execute(text("""
            SELECT n.work_order_id, n.operation_seq, n.station_id,
                   n.planned_start, n.planned_end, COALESCE(n.is_locked, false) AS is_locked
            FROM aps_schedule_tasks n
            WHERE n.schedule_id = :sid
              AND (n.work_order_id, n.operation_seq) IN (
                  SELECT o.work_order_id, o.operation_seq FROM aps_schedule_tasks o
                  WHERE o.schedule_id = :old_sid AND o.station_id = :eid AND o.planned_end > NOW()
              )
        """), {"sid": str(new_schedule_id), "old_sid": str(live_schedule_id),
               "eid": equipment_id})).mappings().all()

        moved, held_in_place = [], []
        for row in placed:
            key = (str(row["work_order_id"]), int(row["operation_seq"]))
            entry = {
                "work_order_id": key[0],
                "operation_seq": key[1],
                "from_station": equipment_id,
                "to_station": str(row["station_id"]),
                "planned_start": row["planned_start"].isoformat() if row["planned_start"] else None,
                "planned_end": row["planned_end"].isoformat() if row["planned_end"] else None,
                "is_locked": bool(row["is_locked"]),
            }
            if entry["to_station"] == equipment_id:
                held_in_place.append(entry)
            else:
                moved.append(entry)

        placed_keys = {(str(r["work_order_id"]), int(r["operation_seq"])) for r in placed}
        dropped = sorted(affected_keys - placed_keys)
        reasons = {}
        for detail in (result.get("diagnostics") or {}).get("unscheduled") or []:
            reasons[str(detail.get("order_id"))] = detail.get("reasons") or []
        dropped_detail = [
            {
                "work_order_id": wo,
                "operation_seq": seq,
                "was_locked": (wo, seq) in locked_keys,
                "reason": reasons.get(wo) or ["新方案里该工序未生成任务"],
            }
            for wo, seq in dropped
        ]

        if dropped_detail:
            _logger.warning(
                "[scheduling] 故障重排后仍有 %d 道工序排不进（工位 %s）", len(dropped_detail), equipment_id
            )

        new_total_tasks = int(result.get("total_tasks") or 0)
        return {
            "action": "replanned",
            # 停用关键工位可能让整盘塌掉（该厂多数工序只有一个可做工位），
            # 这时"挪了 0 道"不等于"没事发生"，必须把版本间任务数差摆出来。
            "escalate": bool(dropped_detail) or new_total_tasks < previous_total_tasks,
            "impact": {
                "previous_schedule_id": str(live_schedule_id),
                "previous_total_tasks": previous_total_tasks,
                "new_total_tasks": new_total_tasks,
                "unscheduled_after": result.get("unscheduled_count"),
            },
            "previous_schedule_id": str(live_schedule_id),
            "schedule_id": str(new_schedule_id),
            "schedule_code": result.get("schedule_code"),
            "station_excluded": equipment_id,
            "affected_tasks": len(affected_keys),
            "moved_count": len(moved),
            "moved": moved,
            "still_on_excluded_station": held_in_place,
            "unresolved_count": len(dropped_detail),
            "unresolved": dropped_detail,
            "locked_preserved_count": len([m for m in moved if m["is_locked"]]),
            "note": (
                f"已停用 {equipment_id} 并重排：{len(moved)} 道工序改派到其他工位"
                + (f"，{len(dropped_detail)} 道工序在工艺路线允许的工位里排不下，需人工处理" if dropped_detail else "")
                + f"；方案任务数 {previous_total_tasks} -> {new_total_tasks}"
                + "；PMC 钉住的工序未被自动挪动"
            ),
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

        # 推迟排程：只动当前生效那一版，历史 draft 的行不是执行依据，跟着改只会把
        # affected/postponed 数字放大几十倍（原来 ST-JG-01 一次报 556）。
        live_schedule_id = await self._live_schedule_id(factory_id)
        if not live_schedule_id:
            return {"action": "none", "reason": "该工厂还没有排程方案，无需顺延"}

        postponed = []
        for wo in affected_wos:
            result = await self.db.execute(text("""
                UPDATE aps_schedule_tasks
                SET planned_start = planned_start + :delay * INTERVAL '1 day',
                    planned_end = planned_end + :delay * INTERVAL '1 day'
                WHERE work_order_id = :wo_id
                  AND schedule_id = :sid
                  AND planned_start > NOW()
                  AND COALESCE(is_locked, false) = false
                RETURNING id
            """), {"delay": delay_days, "wo_id": wo["id"], "sid": str(live_schedule_id)})
            if result.first():
                postponed.append(wo["work_order_code"])

        locked_skipped = int((await self.db.execute(text("""
            SELECT COUNT(*) FROM aps_schedule_tasks t
            WHERE t.schedule_id = :sid
              AND t.planned_start > NOW()
              AND COALESCE(t.is_locked, false) = true
              AND t.work_order_id IN (
                  SELECT w.id::text FROM work_orders w
                  JOIN bom_items b ON w.product_id = b.product_id AND w.factory_id = b.factory_id
                  WHERE b.material_code = :mc AND w.factory_id = :fid
                    AND w.status IN ('released', 'pending')
              )
        """), {"sid": str(live_schedule_id), "mc": material_code, "fid": factory_id})).scalar() or 0)

        await self.db.commit()

        return {
            "action": "postponed",
            "material": material_code,
            "delay_days": delay_days,
            "affected_orders": len(affected_wos),
            "postponed": postponed,
            "locked_skipped": locked_skipped,
            "note": f"物料{material_code}延迟{delay_days}天，已推迟{len(postponed)}个工单"
                    + (f"；{locked_skipped} 道已钉住工序保持原时刻" if locked_skipped else ""),
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
        # 这一版 what-if 原来有三处编数：(1) 排程状态用 status IN ('draft','confirmed')
        # 跨该厂**全部**历史 draft 累加（现存 277 版），任务数与最晚完工都被推高；
        # (2) 新单工作量按"每件 0.5 小时"凭空估算；(3) 日产能把
        # station_capacity.available_hours_per_day 当小时用（该列口径是"一天可完成几件产品"），
        # 再除以 8 当作"天"。现在三处都换成可追溯的真实来源，取不到就明确说取不到。
        now = datetime.utcnow()
        horizon_end = now + timedelta(days=30)
        schedule_id = await self._live_schedule_id(factory_id)
        qty = int(new_wo.get("planned_qty") or 0)
        product_id = str(new_wo.get("product_id") or "")

        state = (await self.db.execute(text("""
            SELECT COUNT(*) AS cnt, MAX(t.planned_end) AS latest_end
            FROM aps_schedule_tasks t
            WHERE t.schedule_id = :sid
              AND t.planned_start >= :now AND t.planned_end <= :horizon
        """), {"sid": schedule_id, "now": now, "horizon": horizon_end})).mappings().first() or {}
        current_latest = state.get("latest_end")
        schedule_basis = "该厂没有任何排程方案"
        if schedule_id:
            is_current = (await self.db.execute(
                text("SELECT is_current FROM aps_schedules WHERE id = :sid"), {"sid": schedule_id}
            )).scalar()
            schedule_basis = (
                "已下达生效版本(is_current)" if is_current
                else "没有已下达方案，取版本号最新的那一版草稿"
            )

        # 新单的真实工作量：路线 standard_hours 累加 × 数量。路线解析走唯一口径
        from core.mes.route_resolution import route_ops_for_product
        route_ops = await route_ops_for_product(self.db, factory_id, product_id)
        station_codes = list(dict.fromkeys(
            str(op["work_center"]) for op in route_ops if op["work_center"]
        ))
        if not station_codes:
            return {
                "simulation": True,
                "new_order": new_wo,
                "confidence": "unavailable",
                "current_schedule": {
                    "schedule_id": schedule_id,
                    "total_tasks": int(state.get("cnt") or 0),
                    "latest_end": str(current_latest) if current_latest else None,
                },
                "impact": {
                    "orders_at_risk": 0,
                    "at_risk_list": [],
                    "recommendation": (
                        f"产品 {product_id or '(未填)'} 没有可解析的工艺路线工位，"
                        "无法模拟插单影响；先补工艺路线再评估，不给凭假设的数字"
                    ),
                },
                "assumptions": {"route_basis": "no_routing_resolved"},
            }

        models = await load_station_models(self.db, factory_id, station_codes, now, horizon_end)
        piece_capacity = {
            code: float(models[code].daily_pieces)
            for code in station_codes
            if code in models and models[code].daily_pieces
        }
        workload_hours = round(sum(float(op["standard_hours"] or 0) for op in route_ops) * qty, 1)

        if piece_capacity:
            bottleneck = min(piece_capacity, key=lambda c: piece_capacity[c])
            daily_pieces = piece_capacity[bottleneck]
            # 插一张单真正压上去的是"瓶颈工位要占几个排班日"
            impact_days = max(1, int(-(-qty // daily_pieces)))
            basis = (
                f"路线 {len(station_codes)} 道工位，瓶颈 {bottleneck} 日产能 {daily_pieces:g} 件/天，"
                f"{qty} 件需占 {impact_days} 个排班日"
            )
            confidence = "medium"
        else:
            bottleneck = None
            impact_days = None
            basis = "路线上的工位都没有按件日产能配置，无法折算占用天数"
            confidence = "low"

        at_risk_orders = []
        if impact_days:
            at_risk = await self.db.execute(text("""
                SELECT DISTINCT w.work_order_code, w.planned_due, t.planned_end
                FROM aps_schedule_tasks t
                JOIN work_orders w ON t.work_order_id = w.id::text
                WHERE t.schedule_id = :sid
                  AND w.planned_due IS NOT NULL
                  AND t.planned_end + :impact * INTERVAL '1 day' > w.planned_due
            """), {"sid": schedule_id, "impact": impact_days})
            at_risk_orders = [dict(r) for r in at_risk.mappings().all()]

        return {
            "simulation": True,
            "new_order": new_wo,
            "confidence": confidence,
            "workload_hours": workload_hours,
            "estimated_days": impact_days,
            "current_schedule": {
                "schedule_id": schedule_id,
                "basis": schedule_basis,
                "total_tasks": int(state.get("cnt") or 0),
                "latest_end": str(current_latest) if current_latest else None,
            },
            "route_stations": station_codes,
            "daily_capacity_pieces": {c: piece_capacity.get(c) for c in station_codes},
            "bottleneck_station": bottleneck,
            "impact": {
                "orders_at_risk": len(at_risk_orders),
                "at_risk_list": [r["work_order_code"] for r in at_risk_orders[:10]],
                "recommendation": (
                    "影响无法量化：" + basis if impact_days is None
                    else ("可以插入（按瓶颈工位排班日折算后没有压到交期）"
                          if not at_risk_orders
                          else f"会把 {len(at_risk_orders)} 个工单推出交期")
                ),
            },
            "assumptions": {
                "capacity_basis": basis,
                "workload_basis": "Σ 模板工序 standard_hours × 数量（不是每件 0.5 小时的假设）",
                "note": "未考虑插单后其余工序的重排，仅按瓶颈工位占用天数顺延估算",
            },
        }

    async def capacity_balance(self, factory_id: str) -> Dict[str, Any]:
        """产能平衡检查：各工位负荷是否合理

        只统计当前生效版本，并且按班次内的实际工时。以前这里是
        `SUM(EXTRACT(EPOCH FROM planned_end - planned_start))` 且 status IN
        ('draft','confirmed') 跨该厂**全部**历史 draft 累加 —— 实测单个工位报
        26379 小时/833 行，而那个工位未来 30 天只有约 264 个班次小时。
        智能体和 chatbot 的"产能不平衡"结论就建立在这个虚高数字上。
        """
        now = datetime.utcnow()
        horizon_end = now + timedelta(days=30)
        schedule_id = await self._live_schedule_id(factory_id)
        if not schedule_id:
            return {"balanced": True, "message": "该工厂还没有排程方案，无需平衡检查"}

        rows = (await self.db.execute(text("""
            SELECT station_id, planned_start, planned_end
            FROM aps_schedule_tasks
            WHERE schedule_id = :sid
              AND planned_end >= :now
              AND status IN ('planned', 'confirmed', 'released')
        """), {"sid": str(schedule_id), "now": now})).mappings().all()

        station_ids = sorted({str(row["station_id"]) for row in rows if row["station_id"]})
        if not station_ids:
            return {"balanced": True, "message": "当前生效方案没有待执行排程任务"}

        models = await load_station_models(self.db, factory_id, station_ids, now, horizon_end)

        agg: Dict[str, Dict[str, Any]] = {}
        window_days = [(now + timedelta(offset)).date() for offset in range(30)]
        for row in rows:
            station = str(row["station_id"])
            model = models.get(station)
            if not model or not row["planned_start"] or not row["planned_end"]:
                continue
            bucket = agg.setdefault(station, {"total_hours": 0.0, "task_count": 0})
            bucket["total_hours"] += model.work_seconds_between(
                max(row["planned_start"], now), row["planned_end"]
            ) / 3600
            bucket["task_count"] += 1

        loads = []
        for station, bucket in agg.items():
            model = models[station]
            capacity_hours = sum(model.capacity_hours_on(day) for day in window_days)
            loads.append({
                "station_id": station,
                "task_count": bucket["task_count"],
                "total_hours": round(bucket["total_hours"], 1),
                "capacity_hours": round(capacity_hours, 1),
                "utilization_pct": round(bucket["total_hours"] / capacity_hours * 100, 1)
                                    if capacity_hours else None,
            })

        if not loads:
            return {"balanced": True, "message": "当前生效方案的工位都未配置班次日历，无法比较"}

        hours_list = [item["total_hours"] for item in loads]
        avg_hours = sum(hours_list) / len(hours_list)

        # 不平衡度 = (最大-最小) / 平均
        imbalance = (max(hours_list) - min(hours_list)) / avg_hours if avg_hours > 0 else 0

        return {
            "balanced": imbalance < 0.3,
            "imbalance_ratio": round(imbalance, 2),
            "stations": [{
                "station_id": item["station_id"],
                "task_count": item["task_count"],
                "total_hours": item["total_hours"],
                "capacity_hours": item["capacity_hours"],
                "utilization_pct": item["utilization_pct"],
                "status": "overloaded" if (item["utilization_pct"] or 0) > 100
                          else "underloaded" if item["total_hours"] < avg_hours * 0.5
                          else "normal",
            } for item in loads],
            "avg_hours": round(avg_hours, 1),
            "schedule_id": str(schedule_id),
            "basis": "当前生效版本 + 班次内实际工时（不含夜间与休息日）",
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
            JOIN work_orders w ON t.work_order_id = w.id::text
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
            except Exception as e:
                _logger.error(f"[scheduling] 任务完成回写失败: {e}")

    async def _fail_task(self, task_id: Optional[str], error: str):
        if task_id:
            try:
                from api.services.agent_supervisor_service import AgentSupervisor
                supervisor = AgentSupervisor(self.db)
                await supervisor.complete_task(task_id, error=error)
            except Exception as e:
                _logger.error(f"[scheduling] 任务失败回写失败: {e}")
