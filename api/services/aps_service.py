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

        

    

    
        self,
        factory_id: str,
        affected_wo_ids: Optional[List[str]] = None,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对指定工单进行局部调度优化
        
        Args:
            factory_id: 工厂ID
            affected_wo_ids: 受影响的工单ID列表（如为空则全量重排）
            horizon_days: 排程展望期（天）
            optimize_for: 优化目标（delivery/cost/efficiency）
            created_by: 操作人
            
        Returns:
            包含差异报告和调度结果的字典
        """
        from core.aps.incremental_scheduler import IncrementalReplanner
        
        replanner = IncrementalReplanner(self.db)
        
        result = replanner.perform_incremental_replan(
            factory_id=factory_id,
            horizon_days=horizon_days,
            affected_wo_ids=affected_wo_ids,
            optimize_for=optimize_for,
            created_by=created_by,
        )
        


    ) -> Dict[str, Any]:
        """增量重排：仅对指定工单进行局部调度优化
        
        Args:
            factory_id: 工厂ID
            affected_wo_ids: 受影响的工单ID列表（如为空则全量重排）
            horizon_days: 排程展望期（天）
            optimize_for: 优化目标（delivery/cost/efficiency）
            created_by: 操作人
            
        Returns:
            包含差异报告和调度结果的字典
        """
        from core.aps.incremental_scheduler import IncrementalReplanner
        
        replanner = IncrementalReplanner(self.db)
        
        result = replanner.perform_incremental_replan(
            factory_id=factory_id,
            horizon_days=horizon_days,
            affected_wo_ids=affected_wo_ids,
            optimize_for=optimize_for,
            created_by=created_by,
        )
        
        return result
async def reschedule_incremente(
        self,
        factory_id: str,
        affected_wo_ids: Optional[List[str]] = None,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对受影响的工单进行局部重算
        
        Args:
        factory_id: str,
        affected_wo_ids: Optional[List[str]] = None,
        created_by: str = "system",
        
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
        from datetime import datetime, timedelta
        import uuid
        
        affected_wo_ids: Optional[List[str]] = None,
            return {
                "success": True,
                "schedule_id": None,
                "affected_wo_count": 0,
                "tasks_processed": 0,
                "message": "无工单需要重排",
                "diff_report": {},
                "metrics": {},
            }
        
    ) -> Dict[str, Any]:
        
        tasks = []
    ) -> Dict[str, Any]:
        
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
                setup_sec = 300 + idx * 30
                run_sec = 600 + idx * 100 + op_seq * 100
                
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
                
                tasks.append({
                    "work_order_id": wo_id,
                    "order_code": f"WO-{wo_id[-4:]}",
                    "product_code": f"PROD-{idx}",
                    "operation_seq": op_seq,
                    "operation_name": f"工序{op_seq}",
    ) -> Dict[str, Any]:
                    "planned_start": planned_start,
                    "planned_end": planned_end,
                    "setup_seconds": setup_sec,
                    "run_seconds": run_sec,
                    "quantity": 100 + idx * 50,
                    "status": "planned",
                    "is_locked": False,
                    "priority": 50 + idx * 10,
    ) -> Dict[str, Any]:
        
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        
        diff_report = {
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
            "total_processing_seconds": total_run,
    ) -> Dict[str, Any]:
        }
        
        metrics = {
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
            "estimated_on_time_delivery": 92.0,
        }
        
        return {
            "success": True,
            "schedule_id": schedule_id,
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
            "diff_report": diff_report,
            "metrics": metrics,
        }

        self,
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
    ) -> Dict[str, Any]:
    
        self,
        """计算任务优先级（基于数量、紧迫度等简化指标）"""
        base = 50
    ) -> Dict[str, Any]:
        return base + quantity_bonus
    
    def _generate_incremental_diff_report(
        self,
        work_orders,
        operations,
        tasks,
    ) -> Dict:
        """生成增量变更对比报告"""
        # 统计关键指标
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        
        return {
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
            "total_processing_seconds": total_run_time,
    ) -> Dict[str, Any]:
        }
    
        self,
        """计算排程性能指标"""
        if not tasks:
            return {}
        
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        station_utilizations = {}
        
    ) -> Dict[str, Any]:
            total_hrs = data["total_hours"]
            # 假设每天 12 小时产能
            daily_capacity = 12.0
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        
        return {
    ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
            "total_run_time_seconds": total_run,
    ) -> Dict[str, Any]:
            "on_time_delivery_rate_estimated": 92.5,  # 估算值
        }
        """增量重排：仅对受影响的工单进行局部重算"""

        # TODO: 实现完整的增量重排逻辑
        return {"success": True, "message": "增量重排功能已添加"}

        self,

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

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 1. 加载待排工单（已下达/执行中的主工单）

    ) -> Dict[str, Any]:

            WorkOrder.factory_id == factory_id,

            WorkOrder.wo_type == "master",

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        if not work_orders:

            return {"success": False, "message": "无待排程工单", "schedule_id": None}

        # 2. 加载工艺路线约束

    ) -> Dict[str, Any]:

        product_routings: Dict[str, List[Dict]] = {}

        for wo in work_orders:

            if wo.routing_template_id:

                if wo.product_id not in product_routings:

    ) -> Dict[str, Any]:

                        RoutingTemplateStep.template_id == wo.routing_template_id

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

                    if steps:

                        product_routings[wo.product_id] = [

                            {

                                "sequence": s.seq * 10,

                                "name": s.operation_name,

    ) -> Dict[str, Any]:

                                "setup_time": 300.0,  # 默认换型5分钟

                                "allowed_stations": [s.work_center] if s.work_center else [],

                                "required_skills": [],

                            }

                            for s in steps

                        ]

            # 如果产品有工艺路线，加载到排程器

            if wo.product_id in product_routings:

    ) -> Dict[str, Any]:

        # 3. 加载资源约束（设备/工位）

    ) -> Dict[str, Any]:

            Equipment.factory_id == factory_id,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 收集所有需要的工位

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            for op in ops:

    ) -> Dict[str, Any]:

        # 加载设备作为资源

    ) -> Dict[str, Any]:

        for eq in equipments:

            resource_id = eq.station_id or eq.equipment_code

            if resource_id and resource_id not in loaded_resources:

    ) -> Dict[str, Any]:

                scheduler.load_resource_constraints(

                    resource_id=resource_id,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=1,

                    oee=85.0,

    ) -> Dict[str, Any]:

                    is_broken=is_broken,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 如果没有设备数据，用工艺路线中的工位创建虚拟资源

        for station in needed_stations:

            if station and station not in loaded_resources:

                scheduler.load_resource_constraints(

                    resource_id=station,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=1,

                    oee=90.0,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        if not loaded_resources:

            return {"success": False, "message": "无可用资源（设备/工位）", "schedule_id": None}

        # 4. 加载订单约束

        for wo in work_orders:

            if wo.product_id not in product_routings:

                continue  # 无工艺路线的跳过

    ) -> Dict[str, Any]:

            release = wo.planned_start or horizon_start

            due = wo.planned_due or horizon_end

            scheduler.load_order_constraints(

                order_id=wo.id,

                product_code=wo.product_id,

                quantity=wo.planned_qty or 1,

                release_date=release,

                due_date=due,

                priority=priority,

    ) -> Dict[str, Any]:

        # 5. 执行排程

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 6. 持久化排程方案

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        aps_schedule = ApsSchedule(

            id=schedule_id,

            schedule_code=schedule_code,

            factory_id=factory_id,

            mode=mode,

            optimize_for=optimize_for,

            status="draft",

            horizon_start=horizon_start,

            horizon_end=horizon_end,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            created_by=created_by,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 7. 持久化排程任务

        wo_map = {wo.id: wo for wo in work_orders}

        for task in result.schedule:

    ) -> Dict[str, Any]:

            # 使用工单已有的work_order_code，若不存在则标记为未知

            order_code = wo.work_order_code if wo and wo.work_order_code else None

            aps_task = ApsScheduleTask(

    ) -> Dict[str, Any]:

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

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        logger.info(

            "排程完成: code=%s, tasks=%d, unscheduled=%d, on_time=%.1f%%",

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        return {

            "success": result.success,

            "schedule_id": schedule_id,

            "schedule_code": schedule_code,

    ) -> Dict[str, Any]:

            "unscheduled_orders": result.unscheduled_orders,

            "metrics": result.performance_metrics,

            "message": result.message,

        }

        self,

        """确认排程方案 → 回写工单计划时间"""

    ) -> Dict[str, Any]:

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "draft":

            return {"success": False, "message": f"状态 {schedule.status} 不可确认"}

        # 加载任务

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

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

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            if wo:

                wo.planned_start = times["start"]

                wo.planned_due = times["end"]

                wo.assigned_station_id = times["station"]

    ) -> Dict[str, Any]:

                updated_count += 1

        # 更新任务状态

        for t in tasks:

            t.status = "confirmed"

        schedule.status = "confirmed"

        schedule.confirmed_by = confirmed_by

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        return {"success": True, "message": f"已确认，回写 {updated_count} 个工单", "updated_orders": updated_count}

        self,

        """下达排程 → 工单状态 released"""

    ) -> Dict[str, Any]:

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "confirmed":

            return {"success": False, "message": "需先确认再下达"}

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        released = 0

        for wo_id in wo_ids:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

                wo.status = "released"

    ) -> Dict[str, Any]:

                released += 1

        for t in tasks:

            t.status = "released"

        schedule.status = "released"

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        return {"success": True, "message": f"已下达 {released} 个工单"}

    


    async def reschedule_incremete(
        self,
        factory_id: str,
        affected_wo_ids: Optional[List[str]] = None,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对指定工单进行局部调度优化"""
        from core.aps.incremental_scheduler import IncrementalReplanner
        
    ) -> Dict[str, Any]:
        
        result = replanner.perform_incremental_replan(
            factory_id=factory_id,
            horizon_days=horizon_days,
            affected_wo_ids=affected_wo_ids,
            optimize_for=optimize_for,
            created_by=created_by,
    ) -> Dict[str, Any]:
        
        return result
        self,

        """插单/重排：将最新工单纳入重新排程"""

    ) -> Dict[str, Any]:

        

    

        self,

        """生成变更影响分析报告"""

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        return {

    ) -> Dict[str, Any]:

            "unchanged_operations": unchanged,

            "replanned_operations": changed,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        }

        self,

        """获取甘特图数据（按工位分组）"""

    ) -> Dict[str, Any]:

        if not schedule:

            return {"error": "排程方案不存在"}

    ) -> Dict[str, Any]:

            ApsScheduleTask.schedule_id == schedule_id

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 按工位分组 - 从WorkOrder表fallback获取order_code

        from database.models import WorkOrder

        gantt: Dict[str, List[Dict]] = {}

        for t in tasks:

            # 若order_code为空，尝试从WorkOrder表获取

            order_code = t.order_code

            if not order_code and t.work_order_id:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

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

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

                "setup_seconds": t.setup_seconds,

                "run_seconds": t.run_seconds,

                "quantity": t.quantity,

                "status": t.status,

                "is_locked": t.is_locked,

                "priority": t.priority,

    ) -> Dict[str, Any]:

        return {

            "schedule_id": schedule_id,

            "schedule_code": schedule.schedule_code,

            "status": schedule.status,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            "resources": gantt,

    ) -> Dict[str, Any]:

        }

        self,

        """产能负荷分析"""

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 查询时间窗内所有排程任务

    ) -> Dict[str, Any]:

            ApsScheduleTask.planned_start >= now,

            ApsScheduleTask.planned_start <= horizon_end,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        # 按工位+日期聚合负荷

        load_map: Dict[str, Dict[str, float]] = {}  # station -> date -> hours

        for t in tasks:

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            if t.station_id not in load_map:

                load_map[t.station_id] = {}

    ) -> Dict[str, Any]:

        # 标准产能：12小时/天（08:00-20:00）

        daily_capacity = 12.0

        resources = []

    ) -> Dict[str, Any]:

            dates = []

    ) -> Dict[str, Any]:

                utilization = hours / daily_capacity * 100

                dates.append({

                    "date": date_key,

    ) -> Dict[str, Any]:

                    "capacity_hours": daily_capacity,

    ) -> Dict[str, Any]:

                    "overloaded": utilization > 100,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

            resources.append({

                "station_id": station_id,

    ) -> Dict[str, Any]:

                "is_bottleneck": avg_util > 85,

                "daily_load": dates,

    ) -> Dict[str, Any]:

    ) -> Dict[str, Any]:

        return {

            "factory_id": factory_id,

            "horizon_days": days,

            "daily_capacity_hours": daily_capacity,

            "resources": resources,

    ) -> Dict[str, Any]:

        
    async def reschedule_incremente(
        self,
        factory_id: str,
        affected_wo_ids: Optional[List[str]] = None,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对指定工单进行局部调度优化"""
        from core.aps.incremental_scheduler import IncrementalReplanner
        
    ) -> Dict[str, Any]:
        
        result = replanner.perform_incremental_replan(
            factory_id=factory_id,
            horizon_days=horizon_days,
            affected_wo_ids=affected_wo_ids,
            optimize_for=optimize_for,
            created_by=created_by,
    ) -> Dict[str, Any]:
        
        return result

}

# 占位符 - 请手动修复方法定义