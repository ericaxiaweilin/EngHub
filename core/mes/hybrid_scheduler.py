"""
混合排产引擎 - 数据驱动的高级计划与排程

功能:
1. 基于实时资源状态的有限产能排程
2. 基于订单约束 (交期、优先级、工艺路线) 的智能排产
3. 融合正向排程和逆向排程的混合模式
4. 支持插单、急单处理的动态重排程
5. 考虑设备 OEE、工位效率、工艺能力的约束优化
6. 安灯事件触发的实时响应式排程调整

作者：APS Development Team
日期：2026-05-24
"""

import datetime
import logging
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SchedulingMode(Enum):
    """排程模式"""
    FORWARD = "forward"  # 正向排程 (从最早时间开始)
    BACKWARD = "backward"  # 逆向排程 (从交期倒推)
    HYBRID = "hybrid"  # 混合排程 (结合正反向)
    CONSTRAINT_BASED = "constraint_based"  # 约束驱动排程


class SchedulingPriority(Enum):
    """排程优先级"""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20  # 急单
    EMERGENCY = 50  # 插单/军品


@dataclass
class ResourceConstraint:
    """资源约束"""
    resource_id: str
    available_from: datetime.datetime  # 可用开始时间
    available_to: datetime.datetime  # 可用结束时间
    capacity: int = 1  # 并行能力
    efficiency: float = 1.0  # 效率系数 (来自 OEE)
    skills_required: List[str] = field(default_factory=list)
    calendar: List[Tuple[datetime.time, datetime.time]] = field(default_factory=list)
    is_broken: bool = False  # 是否故障
    maintenance_schedule: List[Tuple[datetime.datetime, datetime.datetime]] = field(default_factory=list)


@dataclass
class OrderConstraint:
    """订单约束"""
    order_id: str
    product_code: str
    quantity: int
    release_date: datetime.datetime  # 最早开始时间
    due_date: datetime.datetime  # 最晚完成时间
    priority: SchedulingPriority = SchedulingPriority.NORMAL
    customer_id: Optional[str] = None
    is_fixed: bool = False  # 是否已锁定 (不可调整)
    preferred_resources: List[str] = field(default_factory=list)
    alternative_routings: List[List[Dict]] = field(default_factory=list)  # 替代工艺路线


@dataclass
class ProcessConstraint:
    """工艺约束"""
    product_code: str
    operation_sequence: int
    operation_name: str
    standard_time: float  # 标准工时 (秒)
    setup_time: float = 0.0  # 换型时间
    allowed_stations: List[str] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)
    predecessor_op: Optional[int] = None  # 前驱工序序号
    successor_op: Optional[int] = None  # 后继工序序号
    min_wait_time: float = 0.0  # 最小等待时间 (秒) - 如冷却、固化
    max_wait_time: float = float('inf')  # 最大等待时间 (秒)


@dataclass
class ScheduleTask:
    """排产任务"""
    task_id: str
    order_id: str
    product_code: str
    operation_sequence: int
    station_id: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    setup_time: float = 0.0
    run_time: float = 0.0
    quantity: int = 0
    status: str = "PLANNED"  # PLANNED, CONFIRMED, RUNNING, COMPLETED, CANCELLED
    actual_start: Optional[datetime.datetime] = None
    actual_end: Optional[datetime.datetime] = None
    actual_good_qty: int = 0
    actual_defect_qty: int = 0
    constraint_violations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "order_id": self.order_id,
            "product_code": self.product_code,
            "operation_sequence": self.operation_sequence,
            "station_id": self.station_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "setup_time": self.setup_time,
            "run_time": self.run_time,
            "quantity": self.quantity,
            "status": self.status,
            "actual_start": self.actual_start.isoformat() if self.actual_start else None,
            "actual_end": self.actual_end.isoformat() if self.actual_end else None,
            "actual_good_qty": self.actual_good_qty,
            "actual_defect_qty": self.actual_defect_qty,
            "constraint_violations": self.constraint_violations,
        }


@dataclass
class SchedulingResult:
    """排程结果"""
    success: bool
    schedule: List[ScheduleTask]
    unscheduled_orders: List[str]  # 未能排产的订单
    constraint_violations: List[Dict]  # 约束违反记录
    performance_metrics: Dict[str, Any]
    message: str = ""


class HybridScheduler:
    """混合排产引擎 - 核心类"""
    
    def __init__(self):
        self.resources: Dict[str, ResourceConstraint] = {}
        self.orders: Dict[str, OrderConstraint] = {}
        self.processes: Dict[str, Dict[int, ProcessConstraint]] = {}  # key: product_code
        self.schedule: List[ScheduleTask] = []
        self.resource_timeline: Dict[str, List[ScheduleTask]] = {}
        self.process_capability_cache: Dict[str, Dict] = {}  # 工艺能力缓存
        
    def load_resource_constraints(
        self,
        resource_id: str,
        available_from: datetime.datetime,
        available_to: datetime.datetime,
        capacity: int = 1,
        oee: float = 1.0,
        calendar: List[Tuple[datetime.time, datetime.time]] = None,
        is_broken: bool = False,
        maintenance_schedule: List[Tuple[datetime.datetime, datetime.datetime]] = None,
    ):
        """加载资源约束"""
        self.resources[resource_id] = ResourceConstraint(
            resource_id=resource_id,
            available_from=available_from,
            available_to=available_to,
            capacity=capacity,
            efficiency=oee / 100.0 if oee > 1 else oee,
            calendar=calendar or [(datetime.time(8, 0), datetime.time(20, 0))],
            is_broken=is_broken,
            maintenance_schedule=maintenance_schedule or [],
        )
        self.resource_timeline[resource_id] = []
        
    def load_order_constraints(
        self,
        order_id: str,
        product_code: str,
        quantity: int,
        release_date: datetime.datetime,
        due_date: datetime.datetime,
        priority: SchedulingPriority = SchedulingPriority.NORMAL,
        is_fixed: bool = False,
        preferred_resources: List[str] = None,
    ):
        """加载订单约束"""
        self.orders[order_id] = OrderConstraint(
            order_id=order_id,
            product_code=product_code,
            quantity=quantity,
            release_date=release_date,
            due_date=due_date,
            priority=priority,
            is_fixed=is_fixed,
            preferred_resources=preferred_resources or [],
        )
        
    def load_process_constraints(
        self,
        product_code: str,
        operations: List[Dict],
    ):
        """加载工艺约束"""
        if product_code not in self.processes:
            self.processes[product_code] = {}
            
        for op in operations:
            seq = op["sequence"]
            self.processes[product_code][seq] = ProcessConstraint(
                product_code=product_code,
                operation_sequence=seq,
                operation_name=op["name"],
                standard_time=op.get("standard_time", 60.0),
                setup_time=op.get("setup_time", 0.0),
                allowed_stations=op.get("allowed_stations", []),
                required_skills=op.get("required_skills", []),
                predecessor_op=op.get("predecessor"),
                successor_op=op.get("successor"),
                min_wait_time=op.get("min_wait_time", 0.0),
                max_wait_time=op.get("max_wait_time", float('inf')),
            )
    
    def update_process_capability(self, capability_data: Dict):
        """更新工艺能力数据 (来自数据采集模块)"""
        key = f"{capability_data['product_code']}_{capability_data['operation_sequence']}_{capability_data['station_id']}"
        self.process_capability_cache[key] = capability_data
    
    def _get_effective_process_time(
        self,
        product_code: str,
        operation_sequence: int,
        station_id: str,
    ) -> float:
        """获取有效工艺时间 (考虑实际工时和能力)"""
        cap_key = f"{product_code}_{operation_sequence}_{station_id}"
        
        if cap_key in self.process_capability_cache:
            cap = self.process_capability_cache[cap_key]
            # 使用实际平均工时，而不是标准工时
            avg = cap.get("avg_actual_time", 0.0)
            if avg > 0:
                return avg
        
        # 回退到标准工时
        if product_code in self.processes and operation_sequence in self.processes[product_code]:
            return self.processes[product_code][operation_sequence].standard_time
        
        return 60.0  # 默认值
    
    def _check_resource_availability(
        self,
        resource_id: str,
        start_time: datetime.datetime,
        duration: float,
    ) -> Tuple[bool, datetime.datetime]:
        """检查资源可用性，返回 (是否可用，建议开始时间)"""
        if resource_id not in self.resources:
            return False, start_time
            
        res = self.resources[resource_id]
        
        # 1. 检查资源是否故障
        if res.is_broken:
            return False, datetime.datetime.max
        
        # 2. 检查是否在维护期间
        for maint_start, maint_end in res.maintenance_schedule:
            if start_time < maint_end and (start_time + datetime.timedelta(seconds=duration)) > maint_start:
                # 与维护时间冲突，跳到维护结束后
                return False, maint_end
        
        # 3. 检查资源时间轴冲突
        conflict = self._check_timeline_conflict(resource_id, start_time, duration)
        if conflict:
            return False, conflict.end_time
        
        # 4. 检查工作日历
        if not self._is_within_calendar(res, start_time, duration):
            next_slot = self._find_next_work_slot(res, start_time)
            return False, next_slot
        
        return True, start_time
    
    def _check_timeline_conflict(
        self,
        resource_id: str,
        start: datetime.datetime,
        duration: float,
    ) -> Optional[ScheduleTask]:
        """检查时间轴冲突"""
        end = start + datetime.timedelta(seconds=duration)
        for task in self.resource_timeline.get(resource_id, []):
            # 检查重叠
            if not (end <= task.start_time or start >= task.end_time):
                return task
        return None
    
    def _is_within_calendar(
        self,
        resource: ResourceConstraint,
        start: datetime.datetime,
        duration: float,
    ) -> bool:
        """检查是否在工作日历内（只要求开始时间在工作时段内，任务可跨天）"""
        for work_start, work_end in resource.calendar:
            slot_start = datetime.datetime.combine(start.date(), work_start)
            slot_end = datetime.datetime.combine(start.date(), work_end)
            
            if slot_start <= start < slot_end:
                return True
        
        return False
    
    def _find_next_work_slot(
        self,
        resource: ResourceConstraint,
        from_time: datetime.datetime,
    ) -> datetime.datetime:
        """查找下一个工作时间段"""
        # 简化实现：跳到第二天第一个工作时段
        next_day = from_time.date() + datetime.timedelta(days=1)
        if resource.calendar:
            first_start = resource.calendar[0][0]
            return datetime.datetime.combine(next_day, first_start)
        return from_time + datetime.timedelta(hours=1)
    
    def _calculate_setup_time(
        self,
        station_id: str,
        prev_task: Optional[ScheduleTask],
        curr_product: str,
        operation: ProcessConstraint,
    ) -> float:
        """计算换型时间"""
        base_setup = operation.setup_time
        
        if prev_task is None:
            return base_setup
        
        # 不同产品需要换型
        if prev_task.product_code != curr_product:
            return base_setup * 1.5  # 不同产品换型时间增加 50%
        
        # 相同产品但不同工序
        if prev_task.operation_sequence != operation.operation_sequence:
            return base_setup * 0.5  # 同产品不同工序，换型时间减半
        
        return 0.0  # 连续相同工序无需换型
    
    def schedule_hybrid(
        self,
        mode: SchedulingMode = SchedulingMode.HYBRID,
        optimize_for: str = "delivery",  # delivery, efficiency, cost
    ) -> SchedulingResult:
        """执行混合排程"""
        logger.info("启动混合排程引擎 (模式：%s, 优化目标：%s)", mode.value, optimize_for)
        
        self.schedule = []
        for rid in self.resource_timeline:
            self.resource_timeline[rid] = []
        
        unscheduled = []
        violations = []
        
        # 按优先级和交期排序订单
        sorted_orders = sorted(
            self.orders.values(),
            key=lambda x: (x.priority.value, x.due_date),
            reverse=True if mode == SchedulingMode.BACKWARD else False
        )
        
        for order in sorted_orders:
            try:
                scheduled_tasks = self._schedule_order(order, mode)
                if scheduled_tasks:
                    self.schedule.extend(scheduled_tasks)
                    for task in scheduled_tasks:
                        self.resource_timeline[task.station_id].append(task)
                else:
                    unscheduled.append(order.order_id)
                    violations.append({
                        "order_id": order.order_id,
                        "reason": "无法找到满足约束的排程方案",
                    })
            except Exception as e:
                unscheduled.append(order.order_id)
                violations.append({
                    "order_id": order.order_id,
                    "reason": str(e),
                })
        
        # 计算性能指标
        metrics = self._calculate_performance_metrics(optimize_for)
        
        success = len(unscheduled) == 0
        result = SchedulingResult(
            success=success,
            schedule=self.schedule,
            unscheduled_orders=unscheduled,
            constraint_violations=violations,
            performance_metrics=metrics,
            message="排程成功" if success else f"部分订单未排产：{len(unscheduled)}个",
        )
        
        logger.info(
            "排程完成: 总任务数=%d, 未排产订单=%d, 准时交付率=%.1f%%, 资源利用率=%.1f%%",
            len(self.schedule), len(unscheduled),
            metrics.get('on_time_delivery_rate', 0),
            metrics.get('avg_resource_utilization', 0),
        )
        
        return result
    
    def _schedule_order(
        self,
        order: OrderConstraint,
        mode: SchedulingMode,
    ) -> List[ScheduleTask]:
        """排产单个订单"""
        tasks = []
        
        if order.product_code not in self.processes:
            raise ValueError(f"产品 {order.product_code} 没有定义工艺路线")
        
        operations = self.processes[order.product_code]
        sorted_ops = sorted(operations.values(), key=lambda x: x.operation_sequence)
        
        current_time = order.release_date if mode != SchedulingMode.BACKWARD else order.due_date
        last_task = None
        
        for op in sorted_ops:
            # 寻找最佳工位
            best_station = None
            best_start = None
            best_duration = float('inf')
            
            candidate_stations = op.allowed_stations if op.allowed_stations else list(self.resources.keys())
            
            for station_id in candidate_stations:
                if station_id not in self.resources:
                    continue
                
                # 获取有效工时
                effective_time = self._get_effective_process_time(
                    order.product_code,
                    op.operation_sequence,
                    station_id,
                )
                
                # 计算换型时间
                setup_time = self._calculate_setup_time(
                    station_id,
                    last_task,
                    order.product_code,
                    op,
                )
                
                total_duration = setup_time + effective_time * order.quantity
                
                # 考虑资源效率
                res = self.resources[station_id]
                if res.efficiency > 0 and res.efficiency < 1.0:
                    total_duration = total_duration / res.efficiency
                
                # 检查可用性（重试循环，建议时间可能仍不满足日历/时间轴约束）
                if mode == SchedulingMode.BACKWARD:
                    check_time = current_time - datetime.timedelta(seconds=total_duration)
                else:
                    check_time = current_time
                
                available = False
                suggested_time = check_time
                for _retry in range(10):
                    available, suggested_time = self._check_resource_availability(
                        station_id,
                        suggested_time if _retry > 0 else check_time,
                        total_duration,
                    )
                    if available:
                        break
                
                if available and suggested_time < (best_start or datetime.datetime.max):
                    best_station = station_id
                    best_start = suggested_time
                    best_duration = total_duration
            
            if best_station:
                setup_time = self._calculate_setup_time(
                    best_station,
                    last_task,
                    order.product_code,
                    op,
                )
                run_time = best_duration - setup_time
                
                start_time = best_start
                end_time = best_start + datetime.timedelta(seconds=best_duration)
                
                task = ScheduleTask(
                    task_id=f"TSK-{order.order_id}-{op.operation_sequence:03d}",
                    order_id=order.order_id,
                    product_code=order.product_code,
                    operation_sequence=op.operation_sequence,
                    station_id=best_station,
                    start_time=start_time,
                    end_time=end_time,
                    setup_time=setup_time,
                    run_time=run_time,
                    quantity=order.quantity,
                )
                
                tasks.append(task)
                last_task = task
                
                # 更新当前时间 (考虑等待时间)
                if mode == SchedulingMode.BACKWARD:
                    current_time = start_time - datetime.timedelta(seconds=op.min_wait_time)
                else:
                    current_time = end_time + datetime.timedelta(seconds=op.min_wait_time)
            else:
                raise ValueError(f"工序 {op.operation_sequence} 无法找到可用工位")
        
        return tasks
    
    def _calculate_performance_metrics(self, optimize_for: str) -> Dict[str, Any]:
        """计算性能指标"""
        if not self.schedule:
            return {}
        
        # 1. 准时交付率
        on_time_count = 0
        total_orders = len(set(t.order_id for t in self.schedule))
        
        for order_id in set(t.order_id for t in self.schedule):
            order = self.orders.get(order_id)
            if not order:
                continue
            
            order_tasks = [t for t in self.schedule if t.order_id == order_id]
            if order_tasks:
                last_end = max(t.end_time for t in order_tasks)
                if last_end <= order.due_date:
                    on_time_count += 1
        
        on_time_rate = (on_time_count / total_orders * 100) if total_orders > 0 else 0
        
        # 2. 资源利用率
        resource_load = {}
        for task in self.schedule:
            rid = task.station_id
            if rid not in resource_load:
                resource_load[rid] = 0
            resource_load[rid] += (task.end_time - task.start_time).total_seconds()
        
        if self.schedule:
            min_start = min(t.start_time for t in self.schedule)
            max_end = max(t.end_time for t in self.schedule)
            total_span = (max_end - min_start).total_seconds()
            
            utilizations = [
                load / total_span * 100
                for load in resource_load.values()
            ] if total_span > 0 else [0]
            avg_utilization = sum(utilizations) / len(utilizations)
        else:
            avg_utilization = 0
        
        # 3. 总换型时间
        total_setup = sum(t.setup_time for t in self.schedule)
        
        # 4. 平均制造周期
        order_cycles = []
        for order_id in set(t.order_id for t in self.schedule):
            order_tasks = [t for t in self.schedule if t.order_id == order_id]
            if order_tasks:
                first_start = min(t.start_time for t in order_tasks)
                last_end = max(t.end_time for t in order_tasks)
                cycle = (last_end - first_start).total_seconds() / 3600  # 小时
                order_cycles.append(cycle)
        
        avg_cycle = sum(order_cycles) / len(order_cycles) if order_cycles else 0
        
        return {
            "on_time_delivery_rate": on_time_rate,
            "avg_resource_utilization": avg_utilization,
            "total_setup_time": total_setup / 60,  # 分钟
            "avg_manufacturing_cycle": avg_cycle,  # 小时
            "total_tasks": len(self.schedule),
            "total_orders": total_orders,
        }
    
    def reschedule_with_insertion(
        self,
        new_order_id: str,
        preserve_running: bool = True,
    ) -> SchedulingResult:
        """插单重排程"""
        logger.info("触发插单重排程：%s", new_order_id)
        
        if new_order_id not in self.orders:
            raise ValueError(f"订单 {new_order_id} 不存在")
        
        new_order = self.orders[new_order_id]
        
        # 如果是急单/插单，提升优先级
        if new_order.priority in [SchedulingPriority.URGENT, SchedulingPriority.EMERGENCY]:
            logger.info("高优先级订单：%s", new_order.priority.name)
        
        # 保留已开工的任务
        if preserve_running:
            running_tasks = [t for t in self.schedule if t.status in ["RUNNING", "COMPLETED"]]
            logger.info("保留已开工任务：%d 个", len(running_tasks))
        
        # 重新执行混合排程
        return self.schedule_hybrid(SchedulingMode.HYBRID)
    
    def handle_andon_impact(
        self,
        andon_event_id: str,
        affected_station: str,
        estimated_downtime: float,
    ) -> SchedulingResult:
        """处理安灯事件对排程的影响"""
        logger.info(
            "处理安灯事件影响：%s, 受影响工位=%s, 预计停机=%.1f分钟",
            andon_event_id, affected_station, estimated_downtime / 60,
        )
        
        # 1. 标记资源不可用
        if affected_station in self.resources:
            self.resources[affected_station].is_broken = True
        
        # 2. 找出受影响的任务
        now = datetime.datetime.now()
        affected_tasks = [
            t for t in self.schedule
            if t.station_id == affected_station
            and t.start_time > now
            and t.status == "PLANNED"
        ]
        
        logger.info("受影响任务数：%d", len(affected_tasks))
        
        # 3. 重新排程
        return self.schedule_hybrid(SchedulingMode.HYBRID)
    
    def export_gantt_data(self) -> Dict[str, List[Dict]]:
        """导出甘特图数据"""
        gantt = {}
        for task in self.schedule:
            if task.station_id not in gantt:
                gantt[task.station_id] = []
            gantt[task.station_id].append(task.to_dict())
        
        # 按开始时间排序
        for station_id in gantt:
            gantt[station_id].sort(key=lambda x: x["start_time"])
        
        return gantt

