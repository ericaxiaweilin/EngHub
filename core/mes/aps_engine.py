"""
高级计划与排程系统 (APS - Advanced Planning and Scheduling)
核心引擎：基于约束理论的有限产能排程

功能:
1. 多维约束建模 (设备、人员、物料、模具)
2. 智能排程算法 (遗传算法/启发式规则)
3. 插单/急单处理与重排程
4. 瓶颈分析与产能模拟
"""

import datetime
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import heapq

class Priority(Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20  # 急单
    EMERGENCY = 50  # 插单

@dataclass
class Resource:
    """资源定义 (设备/人员/工位)"""
    id: str
    name: str
    type: str  # MACHINE, OPERATOR, STATION
    capacity: int = 1  # 并行能力
    skills: List[str] = field(default_factory=list)  # 技能列表
    calendar: List[Tuple[datetime.time, datetime.time]] = field(default_factory=list)  # 工作日历
    status: str = "AVAILABLE"  # AVAILABLE, BUSY, MAINTENANCE, BROKEN
    efficiency: float = 1.0  # 效率系数 0-1
    
    def is_available(self, timestamp: datetime.datetime) -> bool:
        if self.status != "AVAILABLE":
            return False
        # 检查日历
        time_only = timestamp.time()
        for start, end in self.calendar:
            if start <= time_only <= end:
                return True
        return False

@dataclass
class Operation:
    """工序定义"""
    id: str
    name: str
    process_code: str
    std_time: float  # 标准工时 (秒)
    setup_time: float = 0.0  # 换型时间 (秒)
    required_skills: List[str] = field(default_factory=list)
    allowed_resources: List[str] = field(default_factory=list)  # 可执行的资源ID列表
    predecessor: Optional[str] = None  # 前驱工序ID

@dataclass
class ManufacturingOrder:
    """制造订单"""
    id: str
    product_code: str
    quantity: int
    priority: Priority = Priority.NORMAL
    release_date: datetime.datetime = field(default_factory=datetime.datetime.now)
    due_date: datetime.datetime = field(default_factory=datetime.datetime.now)
    operations: List[Operation] = field(default_factory=list)
    status: str = "RELEASED"  # RELEASED, SCHEDULED, RUNNING, COMPLETED
    current_op_index: int = 0
    
    def get_current_operation(self) -> Optional[Operation]:
        if self.current_op_index < len(self.operations):
            return self.operations[self.current_op_index]
        return None

@dataclass
class ScheduleItem:
    """排程结果项"""
    mo_id: str
    op_id: str
    resource_id: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    setup_time: float = 0.0
    run_time: float = 0.0
    quantity: int = 0
    status: str = "PLANNED"  # PLANNED, CONFIRMED, RUNNING, COMPLETED

class APSEngine:
    """APS 排程引擎"""
    
    def __init__(self):
        self.resources: Dict[str, Resource] = {}
        self.orders: Dict[str, ManufacturingOrder] = {}
        self.schedule: List[ScheduleItem] = []
        self.resource_timeline: Dict[str, List[ScheduleItem]] = {}  # 资源时间轴
        
    def add_resource(self, resource: Resource):
        self.resources[resource.id] = resource
        self.resource_timeline[resource.id] = []
        
    def add_order(self, order: ManufacturingOrder):
        self.orders[order.id] = order
        
    def _get_earliest_start_time(self, resource: Resource, 
                                 earliest_possible: datetime.datetime,
                                 duration: float) -> datetime.datetime:
        """计算资源最早可用时间 (考虑日历和已有排程)"""
        current_time = earliest_possible
        max_iterations = 1000
        iterations = 0
        
        while iterations < max_iterations:
            iterations += 1
            
            # 1. 检查资源状态
            if resource.status != "AVAILABLE":
                current_time += datetime.timedelta(hours=1)
                continue
                
            # 2. 检查日历
            if not resource.is_available(current_time):
                # 跳到下一个工作时间段
                current_time = self._next_work_slot(resource, current_time)
                continue
                
            # 3. 检查时间轴冲突
            conflict = self._check_conflict(resource.id, current_time, duration)
            if conflict:
                current_time = conflict.end_time
                continue
                
            return current_time
            
        return current_time  # 超时返回当前时间
        
    def _next_work_slot(self, resource: Resource, from_time: datetime.datetime) -> datetime.datetime:
        """查找下一个工作时间段"""
        # 简化实现：跳到第二天 8:00
        next_day = from_time.date() + datetime.timedelta(days=1)
        return datetime.datetime.combine(next_day, datetime.time(8, 0))
        
    def _check_conflict(self, resource_id: str, start: datetime.datetime, 
                        duration: float) -> Optional[ScheduleItem]:
        """检查时间轴冲突"""
        end = start + datetime.timedelta(seconds=duration)
        for item in self.resource_timeline.get(resource_id, []):
            # 检查重叠
            if not (end <= item.start_time or start >= item.end_time):
                return item
        return None
        
    def _calculate_setup_time(self, resource_id: str, prev_mo: Optional[str], 
                              curr_mo: str, operation: Operation) -> float:
        """计算换型时间 (简化版：同产品族无换型，不同则增加)"""
        if prev_mo is None:
            return operation.setup_time
            
        prev_order = self.orders.get(prev_mo)
        curr_order = self.orders.get(curr_mo)
        
        if prev_order and curr_order:
            if prev_order.product_code == curr_order.product_code:
                return 0.0  # 同产品无换型
            else:
                return operation.setup_time * 1.5  # 不同产品换型时间增加
                
        return operation.setup_time

    def schedule_forward(self, start_date: Optional[datetime.datetime] = None) -> List[ScheduleItem]:
        """正向排程 (从最早时间开始)"""
        if start_date is None:
            start_date = datetime.datetime.now()
            
        self.schedule = []
        # 清空时间轴
        for rid in self.resource_timeline:
            self.resource_timeline[rid] = []
            
        # 按优先级和交期排序订单
        sorted_orders = sorted(
            self.orders.values(),
            key=lambda x: (x.priority.value, x.due_date)
        )
        
        for order in sorted_orders:
            if order.status != "RELEASED":
                continue
                
            current_time = max(start_date, order.release_date)
            last_resource = None
            last_mo = None
            
            for op in order.operations:
                # 寻找最佳资源
                best_resource = None
                best_start = None
                best_duration = float('inf')
                
                candidate_resources = op.allowed_resources if op.allowed_resources else list(self.resources.keys())
                
                for rid in candidate_resources:
                    resource = self.resources.get(rid)
                    if not resource:
                        continue
                    if op.required_skills and not any(s in resource.skills for s in op.required_skills):
                        continue
                        
                    # 计算有效工时
                    effective_time = op.std_time / resource.efficiency
                    
                    # 计算换型时间
                    setup = self._calculate_setup_time(rid, last_mo, order.id, op)
                    
                    total_duration = setup + effective_time
                    
                    start_time = self._get_earliest_start_time(resource, current_time, total_duration)
                    
                    if start_time < (best_start or datetime.datetime.max):
                        best_resource = resource
                        best_start = start_time
                        best_duration = total_duration
                
                if best_resource:
                    setup_time = self._calculate_setup_time(best_resource.id, last_mo, order.id, op)
                    run_time = best_duration - setup_time
                    
                    end_time = best_start + datetime.timedelta(seconds=best_duration)
                    
                    item = ScheduleItem(
                        mo_id=order.id,
                        op_id=op.id,
                        resource_id=best_resource.id,
                        start_time=best_start,
                        end_time=end_time,
                        setup_time=setup_time,
                        run_time=run_time,
                        quantity=order.quantity,
                        status="PLANNED"
                    )
                    
                    self.schedule.append(item)
                    self.resource_timeline[best_resource.id].append(item)
                    
                    # 更新顺序
                    current_time = end_time
                    last_resource = best_resource
                    last_mo = order.id
                else:
                    print(f"⚠️ 无法为工序 {op.id} 找到可用资源")
                    
        # 按开始时间排序
        self.schedule.sort(key=lambda x: x.start_time)
        return self.schedule

    def reschedule_with_insertion(self, new_order: ManufacturingOrder, 
                                  preserve_completed: bool = True) -> List[ScheduleItem]:
        """插单重排程"""
        print(f"\n🚨 触发插单重排程: {new_order.id} (优先级: {new_order.priority.name})")
        
        # 添加新订单
        self.add_order(new_order)
        
        # 标记已完成的排程项不可变动
        if preserve_completed:
            # 实际场景中应锁定已开工或完工的工序
            pass
            
        # 重新运行正向排程
        return self.schedule_forward()

    def get_gantt_data(self) -> Dict[str, List[Dict]]:
        """获取甘特图数据"""
        gantt = {}
        for item in self.schedule:
            if item.resource_id not in gantt:
                gantt[item.resource_id] = []
            gantt[item.resource_id].append({
                'mo_id': item.mo_id,
                'op_id': item.op_id,
                'start': item.start_time.isoformat(),
                'end': item.end_time.isoformat(),
                'setup': item.setup_time,
                'run': item.run_time,
                'status': item.status
            })
        return gantt

    def analyze_bottlenecks(self) -> List[Dict]:
        """瓶颈分析"""
        resource_load = {}
        for item in self.schedule:
            rid = item.resource_id
            if rid not in resource_load:
                resource_load[rid] = {'total_time': 0, 'setup_time': 0, 'run_time': 0}
            resource_load[rid]['total_time'] += (item.end_time - item.start_time).total_seconds()
            resource_load[rid]['setup_time'] += item.setup_time
            resource_load[rid]['run_time'] += item.run_time
            
        # 计算负载率 (假设排程跨度为总时间)
        if not self.schedule:
            return []
            
        min_start = min(i.start_time for i in self.schedule)
        max_end = max(i.end_time for i in self.schedule)
        total_span = (max_end - min_start).total_seconds()
        
        bottlenecks = []
        for rid, load in resource_load.items():
            utilization = load['total_time'] / total_span if total_span > 0 else 0
            bottlenecks.append({
                'resource_id': rid,
                'utilization': utilization,
                'total_time': load['total_time'],
                'setup_ratio': load['setup_time'] / load['total_time'] if load['total_time'] > 0 else 0
            })
            
        # 按利用率排序
        bottlenecks.sort(key=lambda x: x['utilization'], reverse=True)
        return bottlenecks

# 演示函数
def run_aps_demo():
    print("="*60)
    print("APS 高级排程系统演示")
    print("="*60)
    
    engine = APSEngine()
    
    # 1. 定义资源 (产线)
    resources = [
        Resource("SMT_LINE", "SMT 贴片线", "MACHINE", 
                 skills=["SMT"], calendar=[(datetime.time(8,0), datetime.time(20,0))]),
        Resource("ASSY_1", "组装线 1", "STATION", 
                 skills=["ASSEMBLY"], calendar=[(datetime.time(8,0), datetime.time(20,0))]),
        Resource("ASSY_2", "组装线 2", "STATION", 
                 skills=["ASSEMBLY"], calendar=[(datetime.time(8,0), datetime.time(20,0))]),
        Resource("TEST_ST", "测试站", "STATION", 
                 skills=["TEST"], calendar=[(datetime.time(8,0), datetime.time(20,0))]),
        Resource("PACK_1", "包装线", "STATION", 
                 skills=["PACKING"], calendar=[(datetime.time(8,0), datetime.time(20,0))])
    ]
    
    for r in resources:
        engine.add_resource(r)
        
    # 2. 定义正常订单
    base_time = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    
    orders = []
    for i in range(5):
        ops = [
            Operation("OP10", "SMT 贴片", "SMT", std_time=300, setup_time=600, required_skills=["SMT"], allowed_resources=["SMT_LINE"]),
            Operation("OP20", "整机组装", "ASSY", std_time=450, setup_time=300, required_skills=["ASSEMBLY"], allowed_resources=["ASSY_1", "ASSY_2"]),
            Operation("OP30", "功能测试", "TEST", std_time=120, setup_time=60, required_skills=["TEST"], allowed_resources=["TEST_ST"]),
            Operation("OP40", "成品包装", "PACK", std_time=180, setup_time=120, required_skills=["PACKING"], allowed_resources=["PACK_1"])
        ]
        
        order = ManufacturingOrder(
            id=f"MO-20260524-{i+1:03d}",
            product_code=f"TM-X{i%2+1}00",
            quantity=50,
            priority=Priority.NORMAL,
            release_date=base_time,
            due_date=base_time + datetime.timedelta(days=2),
            operations=ops
        )
        orders.append(order)
        engine.add_order(order)
        
    print(f"\n📋 初始订单池：{len(orders)} 个订单")
    
    # 3. 初次排程
    print("\n⚙️ 执行初次正向排程...")
    schedule = engine.schedule_forward(base_time)
    print(f"✅ 生成排程项：{len(schedule)} 项")
    
    # 4. 瓶颈分析
    bottlenecks = engine.analyze_bottlenecks()
    print("\n📊 瓶颈分析:")
    for bn in bottlenecks[:3]:
        res_name = next((r.name for r in resources if r.id == bn['resource_id']), bn['resource_id'])
        print(f"  - {res_name}: 负载率 {bn['utilization']*100:.1f}%, 换型占比 {bn['setup_ratio']*100:.1f}%")
        
    # 5. 模拟插单 (急单)
    urgent_ops = [
        Operation("OP10", "SMT 贴片", "SMT", std_time=300, setup_time=600, required_skills=["SMT"], allowed_resources=["SMT_LINE"]),
        Operation("OP20", "整机组装", "ASSY", std_time=450, setup_time=300, required_skills=["ASSEMBLY"], allowed_resources=["ASSY_1", "ASSY_2"]),
        Operation("OP30", "功能测试", "TEST", std_time=120, setup_time=60, required_skills=["TEST"], allowed_resources=["TEST_ST"]),
        Operation("OP40", "成品包装", "PACK", std_time=180, setup_time=120, required_skills=["PACKING"], allowed_resources=["PACK_1"])
    ]
    
    urgent_order = ManufacturingOrder(
        id="MO-URGENT-001",
        product_code="TM-X500-PRO",
        quantity=20,
        priority=Priority.EMERGENCY,  # 最高优先级
        release_date=base_time + datetime.timedelta(hours=2),
        due_date=base_time + datetime.timedelta(hours=10),  # 非常紧急
        operations=urgent_ops
    )
    
    print(f"\n🚨 收到插单：{urgent_order.id} (数量:{urgent_order.quantity}, 交期:{urgent_order.due_date.strftime('%H:%M')})")
    
    # 6. 重排程
    new_schedule = engine.reschedule_with_insertion(urgent_order)
    
    # 7. 对比分析
    urgent_items = [i for i in new_schedule if i.mo_id == "MO-URGENT-001"]
    if urgent_items:
        first_start = min(i.start_time for i in urgent_items)
        last_end = max(i.end_time for i in urgent_items)
        duration = (last_end - first_start).total_seconds() / 60
        print(f"✅ 插单排程完成:")
        print(f"   开始时间：{first_start.strftime('%H:%M')}")
        print(f"   预计完成：{last_end.strftime('%H:%M')}")
        print(f"   总耗时：{duration:.1f} 分钟")
        
    # 8. 输出甘特图数据摘要
    gantt = engine.get_gantt_data()
    print(f"\n📅 甘特图数据已生成 (覆盖 {len(gantt)} 个资源)")
    
    print("\n" + "="*60)
    print("APS 演示结束")
    print("="*60)

if __name__ == "__main__":
    run_aps_demo()
