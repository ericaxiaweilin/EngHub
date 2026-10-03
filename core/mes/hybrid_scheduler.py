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
    calendar_by_weekday: Dict[int, List[Tuple[datetime.time, datetime.time]]] = field(default_factory=dict)
    blocked_dates: Set[datetime.date] = field(default_factory=set)
    working_dates: Set[datetime.date] = field(default_factory=set)
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
    operation_name: str = ""
    is_locked: bool = False  # PMC 手动钉住的工序，重排时不得移动
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
            "operation_name": self.operation_name,
            "station_id": self.station_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "setup_time": self.setup_time,
            "run_time": self.run_time,
            "quantity": self.quantity,
            "is_locked": self.is_locked,
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
        self.pinned_tasks: Dict[tuple, ScheduleTask] = {}  # (order_id, op_seq) -> PMC 钉住的任务
        # 被人工/故障停用的工位不进 resources，但排不进时要说清是"被停用"而不是"没注册"
        self.unavailable_notes: Dict[str, str] = {}
        self.process_capability_cache: Dict[str, Dict] = {}  # 工艺能力缓存
        
    def load_resource_constraints(
        self,
        resource_id: str,
        available_from: datetime.datetime,
        available_to: datetime.datetime,
        capacity: int = 1,
        oee: float = 1.0,
        calendar: List[Tuple[datetime.time, datetime.time]] = None,
        calendar_by_weekday: Dict[int, List[Tuple[datetime.time, datetime.time]]] = None,
        blocked_dates: Set[datetime.date] = None,
        working_dates: Set[datetime.date] = None,
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
            calendar_by_weekday=calendar_by_weekday or {},
            blocked_dates=blocked_dates or set(),
            working_dates=working_dates or set(),
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
        
    def load_pinned_tasks(self, pinned_tasks: List[Dict]) -> int:
        """把 PMC 钉住（锁定）的工序原样放回时间轴，重排时保持不动。

        锁定是计划员的否决权：它们不参与排序、不移动，其余工序绕开它们排。
        """
        self.pinned_tasks = {}
        loaded = 0
        for row in pinned_tasks or []:
            station_id = row.get("station_id")
            start_time = row.get("start_time")
            end_time = row.get("end_time")
            if not station_id or not start_time or not end_time:
                continue
            if station_id not in self.resources:
                continue  # 钉住的工位本轮不是可用资源，只能放弃钉住
            key = (str(row.get("order_id")), int(row.get("operation_sequence") or 0))
            task = ScheduleTask(
                task_id=row.get("task_id") or f"PIN-{key[0]}-{key[1]:03d}",
                order_id=key[0],
                product_code=row.get("product_code") or "",
                operation_sequence=key[1],
                operation_name=row.get("operation_name") or "",
                station_id=station_id,
                start_time=start_time,
                end_time=end_time,
                setup_time=float(row.get("setup_time") or 0.0),
                run_time=float(row.get("run_time") or 0.0),
                quantity=int(row.get("quantity") or 0),
                is_locked=True,
                status=row.get("status") or "planned",
            )
            self.pinned_tasks[key] = task
            self.resource_timeline.setdefault(station_id, []).append(task)
            loaded += 1
        if loaded:
            logger.info("载入 %d 道锁定工序，重排时保持不动", loaded)
        return loaded

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
    
    def _maintenance_block_end(
        self,
        resource: ResourceConstraint,
        start: datetime.datetime,
        duration: float,
    ) -> Optional[datetime.datetime]:
        """若占用区间撞上保养窗口，返回需要跳到的时间点。"""
        if not resource.maintenance_schedule:
            return None
        span_end = self._work_span_end(resource, start, duration)
        for maint_start, maint_end in resource.maintenance_schedule:
            if start < maint_end and span_end > maint_start:
                return maint_end
        return None
    
    def _find_earliest_start(
        self,
        resource_id: str,
        not_before: datetime.datetime,
        duration: float,
        ignore_horizon: bool = False,
    ) -> Tuple[Optional[datetime.datetime], Optional[str]]:
        """沿时间轴单向前推进，直到找到可用开工时刻；排不进时返回具体阻塞原因。

        只要求开工时刻落在计划期内，完工允许延伸到计划期之外：
        排队靠后的工单因此得到"最早可开工日/超期天数"，而不是笼统的"找不到工位"。
        """
        res = self.resources.get(resource_id)
        if res is None:
            return None, self.unavailable_notes.get(resource_id, "该工位未注册为排程资源")
        if res.is_broken:
            return None, "该工位设备全部处于故障或保养状态"

        cursor = not_before
        blocked_by = "该工位时间轴已被其他工单占满"
        for _ in range(2000):
            if not ignore_horizon and res.available_to and cursor > res.available_to:
                earliest, _ = self._find_earliest_start(
                    resource_id, not_before, duration, ignore_horizon=True
                )
                horizon_end = res.available_to.strftime('%Y-%m-%d')
                if earliest:
                    late_days = (earliest.date() - res.available_to.date()).days
                    if late_days > 0:
                        return None, (
                            f"计划期止 {horizon_end}，"
                            f"最早可开工 {earliest.strftime('%Y-%m-%d')}（超期 {late_days} 天）"
                        )
                return None, f"该工位产能已排满至计划期止 {horizon_end}，期内无空档"

            if not self._can_start_in_calendar(res, cursor):
                nxt = self._find_next_work_slot(res, cursor)
                if nxt <= cursor:
                    return None, "资源日历内没有可用开工时段"
                cursor = nxt
                blocked_by = "班次日历与休息日限制"
                continue

            conflict = self._check_timeline_conflict(resource_id, cursor, duration)
            if conflict is not None:
                cursor = max(
                    conflict.end_time, cursor + datetime.timedelta(minutes=1)
                )
                blocked_by = "该工位时间轴已被其他工单占满"
                continue

            maint_end = self._maintenance_block_end(res, cursor, duration)
            if maint_end is not None:
                cursor = max(
                    maint_end, cursor + datetime.timedelta(minutes=1)
                )
                blocked_by = "设备保养窗口占用"
                continue

            return cursor, None

        return None, blocked_by
    
    def _check_timeline_conflict(
        self,
        resource_id: str,
        start: datetime.datetime,
        duration: float,
    ) -> Optional[ScheduleTask]:
        """检查时间轴冲突"""
        resource = self.resources.get(resource_id)
        if resource is None:
            return None
        end = self._work_span_end(resource, start, duration)
        overlapping = [
            task for task in self.resource_timeline.get(resource_id, [])
            if not (end <= task.start_time or start >= task.end_time)
        ]
        if len(overlapping) >= max(1, resource.capacity):
            return max(overlapping, key=lambda task: task.end_time)
        return None
    
    def _working_slots(
        self,
        resource: ResourceConstraint,
        day: datetime.date,
    ) -> List[Tuple[datetime.time, datetime.time]]:
        """某日的有效班次。工厂维护了按周日历时，缺失的星期即为休息日，不回落到默认班次。"""
        if resource.calendar_by_weekday:
            slots = resource.calendar_by_weekday.get(day.weekday(), [])
        else:
            slots = resource.calendar
        if day in resource.blocked_dates and day not in resource.working_dates:
            return []
        return sorted(slots)
    
    def _can_start_in_calendar(
        self,
        resource: ResourceConstraint,
        start: datetime.datetime,
    ) -> bool:
        """开工时点是否落在有效班次内 (完工可跨班次，不要求整段塞进同一班次)。"""
        return any(
            slot_start <= start.time() < slot_end
            for slot_start, slot_end in self._working_slots(resource, start.date())
        )
    
    def _work_span_end(
        self,
        resource: ResourceConstraint,
        start: datetime.datetime,
        duration: float,
    ) -> datetime.datetime:
        """从 start 起沿班次累积消耗 duration 秒，返回完工时刻。"""
        if duration <= 0:
            return start
        remaining = float(duration)
        cursor = start
        day = start.date()
        # 上限两年：超出说明批量大到无法在计划期内完成，交由调用方按未排处理。
        for _ in range(732):
            for slot_start, slot_end in self._working_slots(resource, day):
                begin = datetime.datetime.combine(day, slot_start)
                finish = datetime.datetime.combine(day, slot_end)
                segment_start = max(cursor, begin)
                if segment_start >= finish:
                    continue
                segment_seconds = (finish - segment_start).total_seconds()
                if remaining <= segment_seconds:
                    return segment_start + datetime.timedelta(seconds=remaining)
                remaining -= segment_seconds
            day += datetime.timedelta(days=1)
            cursor = datetime.datetime.combine(day, datetime.time.min)
        return cursor
    
    def _find_next_work_slot(
        self,
        resource: ResourceConstraint,
        from_time: datetime.datetime,
    ) -> datetime.datetime:
        """查找下一个可开工时刻。只要求落在班次内，不要求整道工序塞进同一班次。"""
        day = from_time.date()
        for _ in range(732):
            for slot_start, slot_end in self._working_slots(resource, day):
                begin = datetime.datetime.combine(day, slot_start)
                finish = datetime.datetime.combine(day, slot_end)
                candidate = max(from_time, begin)
                if candidate < finish:
                    return candidate
            day += datetime.timedelta(days=1)
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
            # 锁定工序是计划员的否决权，重排只清自动分配，不动钉住的行。
            self.resource_timeline[rid] = [
                t for t in self.resource_timeline[rid] if t.is_locked
            ]
        
        unscheduled = []
        violations = []
        
        # 按优先级和交期排序订单
        # 优先级数值越大越紧急，交期越早越优先。原实现 forward/hybrid
        # 按升序排列，导致 LOW 订单先占用资源，破坏 APS 的优先级语义。
        def estimated_work_seconds(order: OrderConstraint) -> float:
            operations = self.processes.get(order.product_code, {})
            return sum(
                max(0.0, op.standard_time) * max(1, order.quantity) + max(0.0, op.setup_time)
                for op in operations.values()
            )

        def critical_ratio(order: OrderConstraint) -> float:
            remaining = max(0.0, (order.due_date - order.release_date).total_seconds())
            return remaining / max(estimated_work_seconds(order), 1.0)

        if mode == SchedulingMode.BACKWARD:
            sorted_orders = sorted(
                self.orders.values(),
                key=lambda x: (-x.priority.value, -x.due_date.timestamp()),
            )
        elif optimize_for == "efficiency":
            sorted_orders = sorted(
                self.orders.values(),
                key=lambda x: (estimated_work_seconds(x), -x.priority.value, x.due_date),
            )
        elif optimize_for == "critical_ratio":
            sorted_orders = sorted(
                self.orders.values(),
                key=lambda x: (critical_ratio(x), -x.priority.value, x.due_date),
            )
        elif optimize_for == "priority":
            sorted_orders = sorted(
                self.orders.values(),
                key=lambda x: (-x.priority.value, x.due_date, estimated_work_seconds(x)),
            )
        else:
            sorted_orders = sorted(
                self.orders.values(),
                key=lambda x: (-x.priority.value, x.due_date),
            )
        
        for order in sorted_orders:
            try:
                scheduled_tasks = self._schedule_order(order, mode)
                if scheduled_tasks:
                    self.schedule.extend(scheduled_tasks)
                    for task in scheduled_tasks:
                        # 锁定任务在 load_pinned_tasks 里已占好时间轴，重复塞会自我冲突
                        if not task.is_locked:
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
                # 钉住的是计划员的决定：即使这单后面的工序排不进产能，已钉住的工序也必须
                # 留在方案里。否则PMC一改派，整单从甘特图上蒸发，锁反而变成丢单。
                for pinned_order, _seq in self.pinned_tasks:
                    if str(pinned_order) != str(order.order_id):
                        continue
                    pinned = self.pinned_tasks[(pinned_order, _seq)]
                    if pinned not in self.schedule:
                        self.schedule.append(pinned)
        
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
            pinned = self.pinned_tasks.get((order.order_id, op.operation_sequence))
            if pinned is not None:
                # PMC 钉住的工序不参与计算：原样保留，只把衔接时间让给它
                if mode != SchedulingMode.BACKWARD and pinned.start_time < current_time:
                    pinned.constraint_violations.append(
                        f"锁定开工 {pinned.start_time:%m-%d %H:%M} 早于前道工序完工 "
                        f"{current_time:%m-%d %H:%M}，系统未改动锁定行，请人工复核衔接"
                    )
                tasks.append(pinned)
                last_task = pinned
                if mode != SchedulingMode.BACKWARD:
                    current_time = max(current_time, pinned.end_time)
                else:
                    current_time = min(current_time, pinned.start_time)
                current_time += datetime.timedelta(seconds=op.min_wait_time)
                continue

            # 寻找最佳工位
            best_station = None
            best_start = None
            best_duration = float('inf')
            station_blockers: Dict[str, str] = {}
            
            candidate_stations = op.allowed_stations if op.allowed_stations else list(self.resources.keys())
            
            for station_id in candidate_stations:
                if station_id not in self.resources:
                    station_blockers[station_id] = self.unavailable_notes.get(
                        station_id, "该工位未注册为排程资源")
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
                
                candidate_start, blocker = self._find_earliest_start(
                    station_id, check_time, total_duration
                )
                if candidate_start is None:
                    station_blockers[station_id] = blocker or "未知约束"
                    continue
                
                if best_start is None or candidate_start < best_start:
                    best_station = station_id
                    best_start = candidate_start
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
                end_time = self._work_span_end(
                    self.resources[best_station], best_start, best_duration
                )
                
                task = ScheduleTask(
                    task_id=f"TSK-{order.order_id}-{op.operation_sequence:03d}",
                    order_id=order.order_id,
                    product_code=order.product_code,
                    operation_sequence=op.operation_sequence,
                    operation_name=op.operation_name,
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
                if station_blockers:
                    detail = "；".join(
                        f"{sid} {reason}"
                        for sid, reason in list(station_blockers.items())[:3]
                    )
                elif not candidate_stations:
                    detail = "工艺路线该工序未指定工位，且工厂没有可用资源"
                else:
                    detail = "该工序没有可选工位"
                raise ValueError(
                    f"工序 {op.operation_sequence}({op.operation_name}) 排不进: {detail}"
                )
        
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
