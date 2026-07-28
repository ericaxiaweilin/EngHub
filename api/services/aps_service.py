"""
APS 排程服务 - 桥接 DB 数据与 HybridScheduler 核心算法
"""
import uuid
import logging
from datetime import datetime, timedelta, time as dtime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    WorkOrder, Equipment, RoutingTemplate, RoutingTemplateStep,
    ApsSchedule, ApsScheduleTask, ApsWorkCalendar,
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

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_schedule(
        self,
        factory_id: str,
        mode: str = "hybrid",
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        created_by: str = "system",
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

        for wo in work_orders:
            if wo.routing_template_id:
                if wo.product_id not in product_routings:
                    steps_stmt = select(RoutingTemplateStep).where(
                        RoutingTemplateStep.template_id == wo.routing_template_id
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

            # 如果产品有工艺路线，加载到排程器
            if wo.product_id in product_routings:
                scheduler.load_process_constraints(wo.product_id, product_routings[wo.product_id])

        # 3. 加载资源约束（设备/工位）
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

        # 加载设备作为资源
        loaded_resources = set()
        for eq in equipments:
            resource_id = eq.station_id or eq.equipment_code
            if resource_id and resource_id not in loaded_resources:
                is_broken = eq.status in ("broken", "maintenance")
                scheduler.load_resource_constraints(
                    resource_id=resource_id,
                    available_from=horizon_start,
                    available_to=horizon_end,
                    capacity=1,
                    oee=85.0,
                    calendar=[(dtime(8, 0), dtime(20, 0))],
                    is_broken=is_broken,
                )
                loaded_resources.add(resource_id)

        # 如果没有设备数据，用工艺路线中的工位创建虚拟资源
        for station in needed_stations:
            if station and station not in loaded_resources:
                scheduler.load_resource_constraints(
                    resource_id=station,
                    available_from=horizon_start,
                    available_to=horizon_end,
                    capacity=1,
                    oee=90.0,
                    calendar=[(dtime(8, 0), dtime(20, 0))],
                )
                loaded_resources.add(station)

        if not loaded_resources:
            return {"success": False, "message": "无可用资源（设备/工位）", "schedule_id": None}

        # 4. 加载订单约束
        for wo in work_orders:
            if wo.product_id not in product_routings:
                continue  # 无工艺路线的跳过
            priority = PRIORITY_MAP.get(wo.priority, SchedulingPriority.NORMAL)
            release = wo.planned_start or horizon_start
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

        # 6. 持久化排程方案
        schedule_id = str(uuid.uuid4())
        schedule_code = f"APS-{factory_id[:6]}-{now.strftime('%Y%m%d%H%M')}"

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
                work_order_id=task.order_id,
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
            )
            self.db.add(aps_task)

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
            "metrics": result.performance_metrics,
            "message": result.message,
        }

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
                wo.planned_start = times["start"]
                wo.planned_due = times["end"]
                wo.assigned_station_id = times["station"]
                wo.updated_at = datetime.utcnow()
                updated_count += 1

        # 更新任务状态
        for t in tasks:
            t.status = "confirmed"

        schedule.status = "confirmed"
        schedule.confirmed_by = confirmed_by
        schedule.updated_at = datetime.utcnow()
        await self.db.commit()

        return {"success": True, "message": f"已确认，回写 {updated_count} 个工单", "updated_orders": updated_count}

    async def release_schedule(self, schedule_id: str) -> Dict[str, Any]:
        """下达排程 → 工单状态 released"""
        schedule = await self.db.get(ApsSchedule, schedule_id)
        if not schedule:
            return {"success": False, "message": "排程方案不存在"}
        if schedule.status != "confirmed":
            return {"success": False, "message": "需先确认再下达"}

        tasks_stmt = select(ApsScheduleTask).where(ApsScheduleTask.schedule_id == schedule_id)
        tasks_result = await self.db.execute(tasks_stmt)
        tasks = list(tasks_result.scalars().all())

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
        schedule.updated_at = datetime.utcnow()
        await self.db.commit()

        return {"success": True, "message": f"已下达 {released} 个工单"}

    async def reschedule(self, factory_id: str, insert_wo_id: Optional[str] = None, created_by: str = "system") -> Dict[str, Any]:
        """插单/重排：将最新工单纳入重新排程"""
        return await self.generate_schedule(factory_id, mode="hybrid", created_by=created_by)

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
                "setup_seconds": t.setup_seconds,
                "run_seconds": t.run_seconds,
                "quantity": t.quantity,
                "status": t.status,
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
        tasks_stmt = select(ApsScheduleTask).where(
            ApsScheduleTask.planned_start >= now,
            ApsScheduleTask.planned_start <= horizon_end,
            ApsScheduleTask.status.in_(["planned", "confirmed", "released"]),
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

        # 标准产能：12小时/天（08:00-20:00）
        daily_capacity = 12.0
        resources = []
        for station_id, date_loads in load_map.items():
            dates = []
            for date_key, hours in sorted(date_loads.items()):
                utilization = hours / daily_capacity * 100
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
            })

        resources.sort(key=lambda x: x["avg_utilization"], reverse=True)

        return {
            "factory_id": factory_id,
            "horizon_days": days,
            "daily_capacity_hours": daily_capacity,
            "resources": resources,
            "bottleneck_count": sum(1 for r in resources if r["is_bottleneck"]),
        }
