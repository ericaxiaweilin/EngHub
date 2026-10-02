"""

APS 排程服务 - 桥接 DB 数据与 HybridScheduler 核心算法

"""

import uuid

import logging

from datetime import datetime, timedelta, time as dtime, date as ddate

from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_, text

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (

    WorkOrder, Equipment, Routing, RoutingTemplate, RoutingTemplateStep,

    ApsSchedule, ApsScheduleTask, ApsWorkCalendar, ApsHoliday,
    ApsPlanEvent, Station,

)

from core.mes.hybrid_scheduler import (

    HybridScheduler, SchedulingMode, SchedulingPriority,

)

logger = logging.getLogger(__name__)

# 优先级映射

PRIORITY_MAP = {

    "low": SchedulingPriority.LOW,

    "medium": SchedulingPriority.NORMAL,

    "high": SchedulingPriority.HIGH,

    "urgent": SchedulingPriority.URGENT,

    "emergency": SchedulingPriority.EMERGENCY,

}

class ApsService:

    """APS 排程服务"""

        

    

    async def reschedule_incremente(
        self,
        factory_id: str,
        affected_wo_ids: List[str],
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对受影响的工单进行局部重算
        
        Args:
            factory_id: 工厂ID
            affected_wo_ids: 需要重新排程的工单ID列表（受影响的部分）
            created_by: 操作用户
        
        Returns:
            {
                "success": bool,
                "schedule_id": Optional[str],
                "affected_wo_count": int,
                "tasks_processed": int,
                "message": str,
                "diff_report": Dict,
                "metrics": Dict,
            }
        """
        if not affected_wo_ids:
            return {
                "success": True,
                "schedule_id": None,
                "affected_wo_count": 0,
                "tasks_processed": 0,
                "message": "无工单需要重排",
                "diff_report": {},
                "metrics": {},
            }

        # 现阶段使用同一主引擎做全量重算，并明确标记受影响工单；
        # 不再返回内存拼造的“增量任务”，避免前端看到不存在于数据库的计划。
        result = await self.reschedule(
            factory_id=factory_id,
            created_by=created_by,
            change_reason=f"incremental:{','.join(affected_wo_ids)}",
        )
        result["affected_wo_count"] = len(affected_wo_ids)
        result["tasks_processed"] = result.get("total_tasks", 0)
        return result

        from datetime import datetime, timedelta
        import uuid
        
        if not affected_wo_ids:
            return {
                "success": True,
                "schedule_id": None,
                "affected_wo_count": 0,
                "tasks_processed": 0,
                "message": "无工单需要重排",
                "diff_report": {},
                "metrics": {},
            }
        
        schedule_id = f"INCR-{factory_id[:6]}-{int(uuid.uuid4().hex[:8], 16)}"
        
        tasks = []
        current_time = datetime.now()
        
        for idx, wo_id in enumerate(affected_wo_ids):
            for op_seq in range(1, 4):
                setup_sec = 300 + idx * 30
                run_sec = 600 + idx * 100 + op_seq * 100
                
                planned_start = current_time + timedelta(hours=idx * 2 + op_seq * 0.5)
                planned_end = planned_start + timedelta(seconds=setup_sec + run_sec)
                
                tasks.append({
                    "work_order_id": wo_id,
                    "order_code": f"WO-{wo_id[-4:]}",
                    "product_code": f"PROD-{idx}",
                    "operation_seq": op_seq,
                    "operation_name": f"工序{op_seq}",
                    "station_id": f"STA-{(idx+op_seq)%3+1}",
                    "planned_start": planned_start,
                    "planned_end": planned_end,
                    "setup_seconds": setup_sec,
                    "run_seconds": run_sec,
                    "quantity": 100 + idx * 50,
                    "status": "planned",
                    "is_locked": False,
                    "priority": 50 + idx * 10,
                })
        
        total_run = sum(t["run_seconds"] for t in tasks)
        stations = set(t["station_id"] for t in tasks)
        
        diff_report = {
            "affected_wo_count": len(affected_wo_ids),
            "operations_replanned": len(tasks),
            "stations_affected": list(stations),
            "total_processing_seconds": total_run,
            "change_summary": f"对 {len(affected_wo_ids)} 个工单执行局部重算，生成 {len(tasks)} 条操作计划",
        }
        
        metrics = {
            "total_tasks": len(tasks),
            "avg_setup_time_seconds": round(sum(t["setup_seconds"] for t in tasks) / len(tasks)) if tasks else 0,
            "max_station_utilization": min(95.0, 70.0 + len(affected_wo_ids) * 5),
            "estimated_on_time_delivery": 92.0,
        }
        
        return {
            "success": True,
            "schedule_id": schedule_id,
            "affected_wo_count": len(affected_wo_ids),
            "tasks_processed": len(tasks),
            "message": f"成功处理 {len(affected_wo_ids)} 个工单的增量重排",
            "diff_report": diff_report,
            "metrics": metrics,
        }

    def _get_mock_routing_for_product(self, product_code: str) -> List[Dict]:
        """获取产品的模拟工艺路线"""
        # 实际应从 RoutingTable 查询
        routings = {
            "PRODUCT-A": [
                {"seq": 10, "name": "原材料检验", "station": "STA-QC-01", "setup_time": 180, "run_rate": 2.0},
                {"seq": 20, "name": "机械加工", "station": "STA-MFG-01", "setup_time": 300, "run_rate": 1.5},
                {"seq": 30, "name": "装配测试", "station": "STA-ASSY-01", "setup_time": 240, "run_rate": 0.8},
                {"seq": 40, "name": "包装入库", "station": "STA-PACK-01", "setup_time": 120, "run_rate": 3.0},
            ],
            "PRODUCT-B": [
                {"seq": 10, "name": "组装", "station": "STA-ASSY-01", "setup_time": 200, "run_rate": 1.0},
                {"seq": 20, "name": "检测", "station": "STA-QC-01", "setup_time": 150, "run_rate": 2.5},
                {"seq": 30, "name": "包装", "station": "STA-PACK-01", "setup_time": 100, "run_rate": 4.0},
            ],
        }
        return routings.get(product_code, [{"seq": 10, "name": "通用工序", "station": "STA-GEN-01", "setup_time": 300, "run_rate": 1.0}])
    
    def _calculate_priority_for_op(self, operation: Dict) -> int:
        """计算任务优先级（基于数量、紧迫度等简化指标）"""
        base = 50
        quantity_bonus = min(50, max(0, (operation["quantity"] - 100) // 10))
        return base + quantity_bonus
    
    def _generate_incremental_diff_report(
        self,
        work_orders,
        operations,
        tasks,
    ) -> Dict:
        """生成增量变更对比报告"""
        # 统计关键指标
        stations_involved = set(op["station_id"] for op in operations)
        total_run_time = sum(t["run_seconds"] for t in tasks) if tasks else 0
        avg_cycle = total_run_time / len(tasks) if tasks else 0
        
        return {
            "schedule_code": f"INC-DIFF-{int(datetime.utcnow().timestamp())}",
            "timestamp": datetime.utcnow().isoformat(),
            "affected_work_orders": len(work_orders),
            "affected_operations": len(operations),
            "stations_modified": list(stations_involved),
            "tasks_updated": len(tasks),
            "average_cycle_time_minutes": round(avg_cycle / 60, 2),
            "total_processing_seconds": total_run_time,
            "change_summary": f"对 {len(work_orders)} 个工单执行局部重排，涉及 {len(stations_involved)} 个工位，共更新 {len(tasks)} 条操作计划",
        }
    
    def _calculate_metrics(self, tasks, station_loads) -> Dict:
        """计算排程性能指标"""
        if not tasks:
            return {}
        
        total_setup = sum(t["setup_seconds"] for t in tasks)
        total_run = sum(t["run_seconds"] for t in tasks)
        station_utilizations = {}
        
        for station, data in station_loads.items():
            total_hrs = data["total_hours"]
            # 假设每天 12 小时产能
            daily_capacity = 12.0
            utilization = (total_hrs / daily_capacity) * 100 if daily_capacity > 0 else 0
            station_utilizations[station] = round(utilization, 1)
        
        return {
            "total_tasks": len(tasks),
            "avg_setup_time_seconds": round(total_setup / len(tasks)),
            "total_run_time_seconds": total_run,
            "max_station_utilization": max(station_utilizations.values()) if station_utilizations else 0,
            "on_time_delivery_rate_estimated": 92.5,  # 估算值
        }
        """增量重排：仅对受影响的工单进行局部重算"""

        # TODO: 实现完整的增量重排逻辑
        return {"success": True, "message": "增量重排功能已添加"}

    def __init__(self, db: AsyncSession):

        self.db = db

    @staticmethod
    def _routing_step_seconds(step: Dict[str, Any]) -> float:
        """统一旧 Routing JSON 与模板路线的工时单位。"""
        if step.get("standard_hours") is not None:
            return float(step.get("standard_hours") or 0) * 3600
        if step.get("time_min") is not None:
            return float(step.get("time_min") or 0) * 60
        # routings.steps 的 standard_time 历史口径为秒。
        return float(step.get("standard_time") or 0)

    async def _load_calendar_constraints(
        self,
        factory_id: str,
        resource_id: str,
        horizon_start: datetime,
        horizon_end: datetime,
    ) -> Dict[str, Any]:
        """读取工厂/资源日历和日期级假期，不在算法内写死班次。"""
        calendar_result = await self.db.execute(
            select(ApsWorkCalendar).where(
                ApsWorkCalendar.factory_id == factory_id,
                ApsWorkCalendar.resource_id.in_([resource_id, "*"]),
                ApsWorkCalendar.is_active.is_(True),
                or_(
                    ApsWorkCalendar.effective_from.is_(None),
                    ApsWorkCalendar.effective_from <= horizon_end.date(),
                ),
                or_(
                    ApsWorkCalendar.effective_to.is_(None),
                    ApsWorkCalendar.effective_to >= horizon_start.date(),
                ),
            ).order_by(ApsWorkCalendar.resource_id, ApsWorkCalendar.day_of_week)
        )
        calendars = list(calendar_result.scalars().all())
        by_weekday: Dict[int, List] = {}
        for item in calendars:
            by_weekday.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))

        # 只有在工厂没有配置日历时才使用明确标注的兼容默认值；该值不会覆盖已维护的工厂配置。
        if not by_weekday:
            by_weekday = {dow: [(dtime(8, 0), dtime(20, 0))] for dow in range(6)}

        holiday_result = await self.db.execute(
            select(ApsHoliday).where(
                ApsHoliday.factory_id == factory_id,
                ApsHoliday.is_active.is_(True),
                ApsHoliday.holiday_date >= horizon_start.date(),
                ApsHoliday.holiday_date <= horizon_end.date(),
            )
        )
        holidays = list(holiday_result.scalars().all())
        blocked_dates = {item.holiday_date for item in holidays if not item.is_working_day}
        working_dates = {item.holiday_date for item in holidays if item.is_working_day}
        return {
            "calendar_by_weekday": by_weekday,
            "blocked_dates": blocked_dates,
            "working_dates": working_dates,
        }

    async def generate_schedule(

        self,

        factory_id: str,

        mode: str = "hybrid",

        horizon_days: int = 7,

        optimize_for: str = "delivery",

        created_by: str = "system",

        change_reason: str = "manual_generation",

    ) -> Dict[str, Any]:

        """生成排程方案"""

        now = datetime.utcnow()

        horizon_start = now.replace(hour=8, minute=0, second=0, microsecond=0)

        horizon_end = horizon_start + timedelta(days=horizon_days)

        # 1. 加载待排工单（已下达/执行中的主工单）

        wo_stmt = select(WorkOrder).where(

            WorkOrder.factory_id == factory_id,

            WorkOrder.wo_type == "master",

            WorkOrder.status.in_(["released", "in_progress", "pending"]),

        ).order_by(WorkOrder.priority.desc(), WorkOrder.planned_due.asc().nullslast())

        wo_result = await self.db.execute(wo_stmt)

        work_orders = list(wo_result.scalars().all())

        if not work_orders:

            return {"success": False, "message": "无待排程工单", "schedule_id": None}

        # 2. 加载工艺路线约束

        scheduler = HybridScheduler()

        product_routings: Dict[str, List[Dict]] = {}
        unrouted_orders: List[str] = []

        for wo in work_orders:

            if wo.routing_template_id:

                if wo.product_id not in product_routings:
                    routing_template_id = str(wo.routing_template_id)

                    steps_stmt = select(RoutingTemplateStep).where(

                        RoutingTemplateStep.template_id == routing_template_id

                    ).order_by(RoutingTemplateStep.seq)

                    steps_result = await self.db.execute(steps_stmt)

                    steps = list(steps_result.scalars().all())

                    if steps:

                        product_routings[wo.product_id] = [

                            {

                                "sequence": s.seq * 10,

                                "name": s.operation_name,

                                "standard_time": float(s.standard_hours or 0) * 3600,  # 转秒

                                "setup_time": 300.0,  # 默认换型5分钟

                                "allowed_stations": [s.work_center] if s.work_center else [],

                                "required_skills": [],

                            }

                            for s in steps

                        ]

            elif wo.routing_id:
                # 兼容旧版 routings.steps JSON；新工单优先使用模板路线，
                # 但历史工单没有模板绑定时也必须进入同一套 APS 引擎。
                routing = await self.db.get(Routing, str(wo.routing_id))
                if routing and isinstance(routing.steps, list) and routing.steps:
                    product_routings[wo.product_id] = [
                        {
                            "sequence": int(step.get("sequence", step.get("seq", (idx + 1) * 10))),
                            "name": step.get("name", step.get("operation_name", f"工序{idx + 1}")),
                            "standard_time": self._routing_step_seconds(step),
                            "setup_time": float(step.get("setup_time", 300) or 300),
                            "allowed_stations": [step.get("station") or step.get("work_center")] if (step.get("station") or step.get("work_center")) else [],
                            "required_skills": step.get("required_skills", []),
                        }
                        for idx, step in enumerate(routing.steps)
                    ]

            # 如果产品有工艺路线，加载到排程器

            if wo.product_id in product_routings:

                scheduler.load_process_constraints(wo.product_id, product_routings[wo.product_id])
            else:
                unrouted_orders.append(str(wo.id))

        # 3. 加载资源约束（设备/工位、真实产能、班次和假期）

        capacity_result = await self.db.execute(text("""
            SELECT station_id, available_hours_per_day, efficiency_rate,
                   setup_time_minutes, max_concurrent_orders
            FROM station_capacity
            WHERE factory_id = :factory_id AND is_active = TRUE
        """), {"factory_id": factory_id})
        capacity_map = {row["station_id"]: dict(row) for row in capacity_result.mappings().all()}

        eq_stmt = select(Equipment).where(

            Equipment.factory_id == factory_id,

        )

        eq_result = await self.db.execute(eq_stmt)

        equipments = list(eq_result.scalars().all())

        # 收集所有需要的工位

        needed_stations = set()

        for ops in product_routings.values():

            for op in ops:

                needed_stations.update(op.get("allowed_stations", []))

        # 加载设备作为资源：按工位聚合其下所有设备，只要还有可用设备该工位就可排，
        # 避免扫到哪台设备就决定整个工位健康度。
        station_equipment: Dict[str, List] = {}
        for eq in equipments:
            resource_id = eq.station_id or eq.equipment_code
            if resource_id:
                station_equipment.setdefault(resource_id, []).append(eq)

        loaded_resources = set()

        for resource_id, eq_rows in station_equipment.items():

            if resource_id not in loaded_resources:

                is_broken = all(
                    eq.status in ("broken", "maintenance") for eq in eq_rows
                )
                capacity = capacity_map.get(resource_id, {})
                calendar = await self._load_calendar_constraints(
                    factory_id, resource_id, horizon_start, horizon_end
                )

                scheduler.load_resource_constraints(

                    resource_id=resource_id,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=int(capacity.get("max_concurrent_orders") or 1),

                    oee=float(capacity.get("efficiency_rate") or 0.85),

                    calendar_by_weekday=calendar["calendar_by_weekday"],

                    blocked_dates=calendar["blocked_dates"],

                    working_dates=calendar["working_dates"],

                    is_broken=is_broken,

                )

                loaded_resources.add(resource_id)

        # 如果没有设备数据，用工艺路线中的工位创建虚拟资源

        for station in needed_stations:

            if station and station not in loaded_resources:
                capacity = capacity_map.get(station, {})
                calendar = await self._load_calendar_constraints(
                    factory_id, station, horizon_start, horizon_end
                )

                scheduler.load_resource_constraints(

                    resource_id=station,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=int(capacity.get("max_concurrent_orders") or 1),

                    oee=float(capacity.get("efficiency_rate") or 0.9),

                    calendar_by_weekday=calendar["calendar_by_weekday"],

                    blocked_dates=calendar["blocked_dates"],

                    working_dates=calendar["working_dates"],

                )

                loaded_resources.add(station)

        # 如果设备和工艺路线工位都没有，回退使用工厂工位表

        if not loaded_resources:

            st_stmt = select(Station).where(

                Station.factory_id == factory_id,

                Station.status == "active",

            )

            st_result = await self.db.execute(st_stmt)

            for st in st_result.scalars().all():

                rid = st.station_code or str(st.id)

                if rid not in loaded_resources:
                    capacity = capacity_map.get(rid, {})
                    calendar = await self._load_calendar_constraints(
                        factory_id, rid, horizon_start, horizon_end
                    )

                    scheduler.load_resource_constraints(

                        resource_id=rid,

                        available_from=horizon_start,

                        available_to=horizon_end,

                        capacity=int(capacity.get("max_concurrent_orders") or 1),

                        oee=float(capacity.get("efficiency_rate") or 0.9),

                        calendar_by_weekday=calendar["calendar_by_weekday"],

                        blocked_dates=calendar["blocked_dates"],

                        working_dates=calendar["working_dates"],

                    )

                    loaded_resources.add(rid)

        if not loaded_resources:

            return {"success": False, "message": "无可用资源（设备/工位）", "schedule_id": None}

        # 4. 加载订单约束

        for wo in work_orders:

            if wo.product_id not in product_routings:

                continue  # 无工艺路线的跳过

            priority = PRIORITY_MAP.get(wo.priority, SchedulingPriority.NORMAL)

            release = max(wo.planned_start or horizon_start, horizon_start)

            due = wo.planned_due or horizon_end

            scheduler.load_order_constraints(

                order_id=wo.id,

                product_code=wo.product_id,

                quantity=wo.planned_qty or 1,

                release_date=release,

                due_date=due,

                priority=priority,

            )

        # 5. 执行排程

        sched_mode = SchedulingMode(mode) if mode in ("forward", "backward", "hybrid") else SchedulingMode.HYBRID

        result = scheduler.schedule_hybrid(sched_mode, optimize_for)

        if unrouted_orders:
            result.unscheduled_orders = list(dict.fromkeys(result.unscheduled_orders + unrouted_orders))
            result.constraint_violations.extend(
                {"order_id": wo_id, "reason": "工单没有可用工艺路线"}
                for wo_id in unrouted_orders
            )
            result.success = False
            result.message = f"有 {len(unrouted_orders)} 个工单缺少可用工艺路线"

        # 生成可解释结果：把“算法跑完”拆成输入、排入、未排和约束原因，供前端审阅。
        work_order_map = {str(wo.id): wo for wo in work_orders}
        scheduled_order_ids = {str(task.order_id) for task in result.schedule}
        violation_by_order: Dict[str, List[str]] = {}
        for violation in result.constraint_violations:
            order_id = str(violation.get("order_id") or "")
            reason = str(violation.get("reason") or "未满足排程约束")
            violation_by_order.setdefault(order_id, []).append(reason)

        unscheduled_details = []
        for order_id in result.unscheduled_orders:
            key = str(order_id)
            wo = work_order_map.get(key)
            due_date = getattr(wo, "planned_due", None) if wo else None
            unscheduled_details.append({
                "order_id": key,
                "work_order_code": getattr(wo, "work_order_code", None) if wo else None,
                "product_id": getattr(wo, "product_id", None) if wo else None,
                "priority": getattr(wo, "priority", None) if wo else None,
                "due_date": due_date.isoformat() if due_date else None,
                "reasons": violation_by_order.get(key, ["未生成排程任务"]),
            })

        violation_details = []
        for violation in result.constraint_violations:
            key = str(violation.get("order_id") or "")
            wo = work_order_map.get(key)
            violation_details.append({
                "order_id": key,
                "work_order_code": getattr(wo, "work_order_code", None) if wo else None,
                "reason": str(violation.get("reason") or "未满足排程约束"),
            })

        station_load_map: Dict[str, Dict[str, Any]] = {}
        for task in result.schedule:
            station_id = str(task.station_id)
            load = station_load_map.setdefault(station_id, {
                "station_id": station_id,
                "task_count": 0,
                "order_ids": set(),
                "load_minutes": 0.0,
                "first_start": task.start_time,
                "last_end": task.end_time,
            })
            load["task_count"] += 1
            load["order_ids"].add(str(task.order_id))
            load["load_minutes"] += max(0.0, (task.end_time - task.start_time).total_seconds() / 60)
            load["first_start"] = min(load["first_start"], task.start_time)
            load["last_end"] = max(load["last_end"], task.end_time)

        station_loads = []
        for load in station_load_map.values():
            load["order_count"] = len(load.pop("order_ids"))
            load["load_minutes"] = round(load["load_minutes"], 1)
            load["load_hours"] = round(load["load_minutes"] / 60, 2)
            load["first_start"] = load["first_start"].isoformat()
            load["last_end"] = load["last_end"].isoformat()
            station_loads.append(load)
        station_loads.sort(key=lambda item: item["load_minutes"], reverse=True)

        rule_explanations = {
            "delivery": "先按工单优先级，再按交期排序；同时遵守工艺路线、资源日历、设备可用性和工位不重叠约束。",
            "efficiency": "先按预计加工工时从短到长，再按优先级和交期排序；同时遵守工艺路线、资源日历、设备可用性和工位不重叠约束。",
            "critical_ratio": "先按关键比率（剩余交期时间 ÷ 预计加工工时）从低到高，再按优先级和交期排序。",
            "priority": "先按工单优先级，再按交期和预计加工工时排序。",
            "cost": "当前以优先级和交期为主排序，换型时间计入任务负荷；成本优化将在后续版本继续细化。",
        }
        input_summary = {
            "total_orders": len(work_orders),
            "routable_orders": len(work_orders) - len(unrouted_orders),
            "skipped_orders": len(unrouted_orders),
            "scheduled_orders": len(scheduled_order_ids),
            "unscheduled_orders": len(result.unscheduled_orders),
            "scheduled_tasks": len(result.schedule),
        }

        # 6. 持久化排程方案

        schedule_id = str(uuid.uuid4())

        schedule_code = f"APS-{factory_id[:6]}-{now.strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"

        current_result = await self.db.execute(
            select(ApsSchedule)
            .where(
                ApsSchedule.factory_id == factory_id,
                ApsSchedule.is_current.is_(True),
            )
            .order_by(ApsSchedule.created_at.desc())
            .limit(1)
        )
        current_schedule = current_result.scalar_one_or_none()
        version_result = await self.db.execute(
            select(func.max(ApsSchedule.version_number)).where(ApsSchedule.factory_id == factory_id)
        )
        next_version = int(version_result.scalar() or 0) + 1

        material_ready_map: Dict[str, bool] = {}
        if work_orders:
            material_result = await self.db.execute(
                text("""
                    SELECT work_order_id,
                           SUM(CASE WHEN COALESCE(shortage_qty, 0) > 0 THEN 1 ELSE 0 END) AS shortage_count
                    FROM work_order_materials
                    WHERE work_order_id IN (
                        SELECT id FROM work_orders
                        WHERE factory_id = :factory_id
                          AND wo_type = 'master'
                          AND status IN ('released', 'in_progress', 'pending')
                    )
                    GROUP BY work_order_id
                """),
                {"factory_id": factory_id},
            )
            material_ready_map = {
                str(row["work_order_id"]): int(row["shortage_count"] or 0) == 0
                for row in material_result.mappings().all()
            }

        aps_schedule = ApsSchedule(

            id=schedule_id,

            schedule_code=schedule_code,

            factory_id=factory_id,

            mode=mode,

            optimize_for=optimize_for,

            status="draft",

            horizon_start=horizon_start,

            horizon_end=horizon_end,

            on_time_rate=result.performance_metrics.get("on_time_delivery_rate"),

            avg_utilization=result.performance_metrics.get("avg_resource_utilization"),

            total_setup_minutes=result.performance_metrics.get("total_setup_time"),

            avg_cycle_hours=result.performance_metrics.get("avg_manufacturing_cycle"),

            total_tasks=len(result.schedule),

            unscheduled_count=len(result.unscheduled_orders),

            created_by=created_by,
            version_number=next_version,
            is_current=False,
            supersedes_schedule_id=current_schedule.id if current_schedule else None,
            change_reason=change_reason,

        )

        self.db.add(aps_schedule)

        # 7. 持久化排程任务

        wo_map = {wo.id: wo for wo in work_orders}

        for task in result.schedule:

            wo = wo_map.get(task.order_id)

            # 使用工单已有的work_order_code，若不存在则标记为未知

            order_code = wo.work_order_code if wo and wo.work_order_code else None

            aps_task = ApsScheduleTask(

                id=str(uuid.uuid4()),

                schedule_id=schedule_id,

                work_order_id=str(task.order_id),

                order_code=order_code,

                product_code=task.product_code,

                operation_seq=task.operation_sequence,

                operation_name=None,

                station_id=task.station_id,

                planned_start=task.start_time,

                planned_end=task.end_time,

                setup_seconds=task.setup_time,

                run_seconds=task.run_time,

                quantity=task.quantity,

                status="planned",

                is_locked=False,

                priority=PRIORITY_MAP.get(wo.priority if wo else "medium", SchedulingPriority.NORMAL).value,
                material_ready=material_ready_map.get(str(task.order_id), True),

            )

            self.db.add(aps_task)

        await self._record_event(
            factory_id=factory_id,
            event_type="schedule_generated",
            actor=created_by,
            schedule_id=schedule_id,
            reason=change_reason,
            payload={
                "version_number": next_version,
                "total_tasks": len(result.schedule),
                "unscheduled_orders": result.unscheduled_orders,
            },
        )
        await self.db.commit()

        logger.info(

            "排程完成: code=%s, tasks=%d, unscheduled=%d, on_time=%.1f%%",

            schedule_code, len(result.schedule), len(result.unscheduled_orders),

            result.performance_metrics.get("on_time_delivery_rate", 0),

        )

        return {

            "success": result.success,

            "schedule_id": schedule_id,

            "schedule_code": schedule_code,

            "total_tasks": len(result.schedule),

            "unscheduled_orders": result.unscheduled_orders,

            "unscheduled_count": len(result.unscheduled_orders),

            "constraint_violation_count": len(result.constraint_violations),

            "horizon_days": horizon_days,

            "horizon": f"{horizon_days}天",

            "horizon_start": horizon_start.isoformat(),

            "horizon_end": horizon_end.isoformat(),

            "input_summary": input_summary,

            "diagnostics": {
                "unscheduled": unscheduled_details,
                "constraint_violations": violation_details,
            },

            "station_loads": station_loads,

            "rule_explanation": rule_explanations.get(optimize_for, rule_explanations["delivery"]),

            "metrics": result.performance_metrics,

            "message": result.message,

        }

    async def _record_event(
        self,
        *,
        factory_id: str,
        event_type: str,
        actor: str,
        schedule_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db.add(ApsPlanEvent(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            event_type=event_type,
            actor=actor,
            schedule_id=schedule_id,
            plan_id=plan_id,
            work_order_id=work_order_id,
            reason=reason,
            payload=payload or {},
        ))

    async def confirm_schedule(self, schedule_id: str, confirmed_by: str) -> Dict[str, Any]:

        """确认排程方案 → 回写工单计划时间"""

        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "draft":

            return {"success": False, "message": f"状态 {schedule.status} 不可确认"}

        # 加载任务

        tasks_stmt = select(ApsScheduleTask).where(ApsScheduleTask.schedule_id == schedule_id)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        # 按工单聚合：取最早开始和最晚结束

        wo_times: Dict[str, Dict] = {}

        for t in tasks:

            if not t.work_order_id:

                continue

            if t.work_order_id not in wo_times:

                wo_times[t.work_order_id] = {"start": t.planned_start, "end": t.planned_end, "station": t.station_id}

            else:

                if t.planned_start < wo_times[t.work_order_id]["start"]:

                    wo_times[t.work_order_id]["start"] = t.planned_start

                if t.planned_end > wo_times[t.work_order_id]["end"]:

                    wo_times[t.work_order_id]["end"] = t.planned_end

        # 回写工单

        updated_count = 0

        for wo_id, times in wo_times.items():

            wo = await self.db.get(WorkOrder, wo_id)

            if wo:

                # planned_due 是 MPS/销售承诺交期，不能被 APS 预计完工覆盖。
                # APS 任务的 planned_end 保留实际排程结果，工单只补齐计划开始时间。
                if wo.planned_start is None:
                    wo.planned_start = times["start"]

                wo.assigned_station_id = times["station"]

                wo.updated_at = datetime.utcnow()

                updated_count += 1

        # 更新任务状态

        for t in tasks:

            t.status = "confirmed"

        schedule.status = "confirmed"

        schedule.confirmed_by = confirmed_by
        schedule.approved_by = confirmed_by
        schedule.is_current = False

        schedule.updated_at = datetime.utcnow()
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="schedule_confirmed",
            actor=confirmed_by,
            schedule_id=schedule.id,
            reason="APS 方案确认",
            payload={"updated_orders": updated_count},
        )

        await self.db.commit()

        return {"success": True, "message": f"已确认，回写 {updated_count} 个工单", "updated_orders": updated_count}

    async def release_schedule(self, schedule_id: str, released_by: str = "system") -> Dict[str, Any]:

        """下达排程 → 工单状态 released"""

        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "confirmed":

            return {"success": False, "message": "需先确认再下达"}

        tasks_stmt = select(ApsScheduleTask).where(ApsScheduleTask.schedule_id == schedule_id)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        not_ready = [t for t in tasks if t.material_ready is False]
        if not_ready:
            return {
                "success": False,
                "message": f"有 {len(not_ready)} 条排程任务物料未齐套，不能下达",
                "material_shortage_tasks": len(not_ready),
            }
        if schedule.unscheduled_count:
            return {
                "success": False,
                "message": f"方案仍有 {schedule.unscheduled_count} 个工单未排产，不能下达",
                "unscheduled_count": schedule.unscheduled_count,
            }

        previous_result = await self.db.execute(
            select(ApsSchedule).where(
                ApsSchedule.factory_id == schedule.factory_id,
                ApsSchedule.is_current.is_(True),
                ApsSchedule.id != schedule.id,
            )
        )
        for previous in previous_result.scalars().all():
            previous.is_current = False
            if previous.status == "released":
                previous.status = "archived"
            previous.updated_at = datetime.utcnow()

        wo_ids = set(t.work_order_id for t in tasks if t.work_order_id)

        released = 0

        for wo_id in wo_ids:

            wo = await self.db.get(WorkOrder, wo_id)

            if wo and wo.status in ("pending", "released"):

                wo.status = "released"

                wo.updated_at = datetime.utcnow()

                released += 1

        for t in tasks:

            t.status = "released"

        schedule.status = "released"
        schedule.is_current = True
        schedule.released_by = released_by
        schedule.released_at = datetime.utcnow()
        schedule.updated_at = datetime.utcnow()
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="schedule_released",
            actor=released_by,
            schedule_id=schedule.id,
            reason="APS 方案下达",
            payload={"released_orders": released},
        )

        await self.db.commit()

        return {
            "success": True,
            "message": f"已下达 {released} 个工单",
            "schedule_id": schedule.id,
            "version_number": schedule.version_number,
        }

    

    async def reschedule(
        self,
        factory_id: str,
        insert_wo_id: Optional[str] = None,
        created_by: str = "system",
        change_reason: Optional[str] = None,
    ) -> Dict[str, Any]:

        """插单/重排：校验插单归属后生成新版本，并保留审计原因。"""
        if insert_wo_id:
            insert_wo = await self.db.get(WorkOrder, insert_wo_id)
            if not insert_wo or insert_wo.factory_id != factory_id:
                return {"success": False, "message": "插入工单不存在或不属于当前工厂", "schedule_id": None}
            if insert_wo.status not in ("pending", "released", "in_progress"):
                return {"success": False, "message": f"工单状态 {insert_wo.status} 不允许进入 APS 重排", "schedule_id": None}

        result = await self.generate_schedule(
            factory_id,
            mode="hybrid",
            created_by=created_by,
            change_reason=change_reason or (f"insert:{insert_wo_id}" if insert_wo_id else "manual_reschedule"),
        )
        if result.get("schedule_id"):
            await self._record_event(
                factory_id=factory_id,
                event_type="schedule_rescheduled",
                actor=created_by,
                schedule_id=result["schedule_id"],
                work_order_id=insert_wo_id,
                reason=change_reason or "APS 重排",
                payload={"insert_wo_id": insert_wo_id},
            )
            await self.db.commit()
        return result

        

    

    def _generate_diff_report(self, work_orders, operations) -> Dict:

        """生成变更影响分析报告"""

        unchanged = len(work_orders) * 2  # 假设部分操作不变

        changed = len(operations) - unchanged

        return {

            "total_operations": len(operations),

            "unchanged_operations": unchanged,

            "replanned_operations": changed,

            "stations_affected": len(set(op["station_id"] for op in operations)),

            "time_impact_hours": round(changed * 0.5, 2),  # 估算影响时长

        }

    async def get_gantt_data(self, schedule_id: str) -> Dict[str, Any]:

        """获取甘特图数据（按工位分组）"""

        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"error": "排程方案不存在"}

        tasks_stmt = select(ApsScheduleTask).where(

            ApsScheduleTask.schedule_id == schedule_id

        ).order_by(ApsScheduleTask.planned_start)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        # 按工位分组 - 从WorkOrder表fallback获取order_code

        from database.models import WorkOrder

        gantt: Dict[str, List[Dict]] = {}

        for t in tasks:

            # 若order_code为空，尝试从WorkOrder表获取

            order_code = t.order_code

            if not order_code and t.work_order_id:

                wo_stmt = select(WorkOrder).where(WorkOrder.id == t.work_order_id)

                wo_result = await self.db.execute(wo_stmt)

                wo = wo_result.scalar_one_or_none()

                if wo and wo.work_order_code:

                    order_code = wo.work_order_code

            if not order_code:

                order_code = f"UNKNOWN-{t.work_order_id[:8]}" if t.work_order_id else "UNKNOWN"

            if t.station_id not in gantt:

                gantt[t.station_id] = []

            gantt[t.station_id].append({

                "id": t.id,

                "work_order_id": t.work_order_id,

                "order_code": order_code,

                "product_code": t.product_code,

                "operation_seq": t.operation_seq,

                "operation_name": t.operation_name,

                "start": t.planned_start.isoformat(),

                "end": t.planned_end.isoformat(),

                "planned_start": t.planned_start.isoformat(),

                "planned_end": t.planned_end.isoformat(),

                "setup_seconds": t.setup_seconds,

                "run_seconds": t.run_seconds,

                "quantity": t.quantity,

                "status": t.status,

                "material_ready": t.material_ready,

                "is_locked": t.is_locked,

                "priority": t.priority,

            })

        return {

            "schedule_id": schedule_id,

            "schedule_code": schedule.schedule_code,

            "status": schedule.status,

            "horizon_start": schedule.horizon_start.isoformat(),

            "horizon_end": schedule.horizon_end.isoformat(),

            "resources": gantt,

            "total_tasks": len(tasks),

        }

    async def get_capacity_load(self, factory_id: str, days: int = 7) -> Dict[str, Any]:

        """产能负荷分析"""

        now = datetime.utcnow()

        horizon_end = now + timedelta(days=days)

        # 查询时间窗内所有排程任务

        tasks_stmt = (
            select(ApsScheduleTask)
            .join(ApsSchedule, ApsSchedule.id == ApsScheduleTask.schedule_id)
            .where(
                ApsSchedule.factory_id == factory_id,
                ApsSchedule.is_current.is_(True),
                ApsScheduleTask.planned_start >= now,
                ApsScheduleTask.planned_start <= horizon_end,
                ApsScheduleTask.status.in_(["planned", "confirmed", "released"]),
            )
        )

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        # 按工位+日期聚合负荷

        load_map: Dict[str, Dict[str, float]] = {}  # station -> date -> hours

        for t in tasks:

            date_key = t.planned_start.strftime("%Y-%m-%d")

            hours = (t.planned_end - t.planned_start).total_seconds() / 3600

            if t.station_id not in load_map:

                load_map[t.station_id] = {}

            load_map[t.station_id][date_key] = load_map[t.station_id].get(date_key, 0) + hours

        # Load configured capacity first, then include active stations even
        # when there are no APS tasks. Returning an empty resource list for a
        # configured but idle factory made the PMC dashboard look incomplete.
        capacity_result = await self.db.execute(text("""
            SELECT station_id, available_hours_per_day
            FROM station_capacity
            WHERE factory_id = :factory_id AND is_active = TRUE
        """), {"factory_id": factory_id})
        capacity_rows = [dict(row) for row in capacity_result.mappings().all()]
        capacity_map = {
            str(row["station_id"]): float(row["available_hours_per_day"] or 12.0)
            for row in capacity_rows
        }
        station_result = await self.db.execute(
            select(Station).where(
                Station.factory_id == factory_id,
                Station.status == "active",
            )
        )
        active_stations = list(station_result.scalars().all())
        station_aliases: Dict[str, str] = {}
        for station in active_stations:
            canonical = str(station.station_code or station.id)
            station_aliases[str(station.id)] = canonical
            station_aliases[canonical] = canonical
            if canonical not in capacity_map and station.capacity_per_hour:
                capacity_map[canonical] = float(station.capacity_per_hour) * 8.0

        normalized_load_map: Dict[str, Dict[str, float]] = {}
        for resource_id, date_loads in load_map.items():
            canonical = station_aliases.get(str(resource_id), str(resource_id))
            target = normalized_load_map.setdefault(canonical, {})
            for date_key, hours in date_loads.items():
                target[date_key] = target.get(date_key, 0.0) + hours
        load_map = normalized_load_map
        resource_ids = set(load_map)
        resource_ids.update(station_aliases.values())
        resource_ids.update(str(row["station_id"]) for row in capacity_rows if row.get("station_id"))
        horizon_dates = [
            (now + timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(max(1, days))
        ]

        resources = []

        for station_id in resource_ids:
            date_loads = load_map.get(station_id, {})

            dates = []

            for date_key in horizon_dates:
                hours = date_loads.get(date_key, 0.0)

                daily_capacity = capacity_map.get(station_id, 12.0)
                utilization = hours / daily_capacity * 100 if daily_capacity else 0

                dates.append({

                    "date": date_key,

                    "load_hours": round(hours, 1),

                    "capacity_hours": daily_capacity,

                    "utilization": round(utilization, 1),

                    "overloaded": utilization > 100,

                })

            avg_util = sum(d["utilization"] for d in dates) / len(dates) if dates else 0

            resources.append({

                "station_id": station_id,

                "avg_utilization": round(avg_util, 1),

                "is_bottleneck": avg_util > 85,

                "daily_load": dates,
                "capacity_hours_per_day": capacity_map.get(station_id, 12.0),

            })

        resources.sort(key=lambda x: (-x["avg_utilization"], x["station_id"]))

        return {

            "factory_id": factory_id,

            "horizon_days": days,

            "daily_capacity_hours": None,

            "resources": resources,

            "bottleneck_count": sum(1 for r in resources if r["is_bottleneck"]),

        }
