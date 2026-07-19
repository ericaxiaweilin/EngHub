"""
MES 生产数据采集模块 - 混合排产数据基础

功能:
1. 岗位工时采集单据 (工序报工、准备时间、换型时间)
2. 产品工艺路线数据沉淀 (标准工时、实际工时、良率)
3. 设备状态数据采集 (OEE、故障时间、维护记录)
4. 安灯事件数据集成 (异常停机、响应时间)
5. 物料消耗数据采集 (投料、退料、损耗)

为混合排产提供实时、准确的数据基础

作者：APS Development Team
日期：2026-05-24
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass, field
import json


class CollectionType(Enum):
    """数据采集类型"""
    OPERATION_REPORT = "operation_report"  # 工序报工
    SETUP_TIME = "setup_time"  # 换型时间
    EQUIPMENT_STATUS = "equipment_status"  # 设备状态
    QUALITY_CHECK = "quality_check"  # 质量检验
    MATERIAL_CONSUMPTION = "material_consumption"  # 物料消耗
    ANDON_EVENT = "andon_event"  # 安灯事件
    MAINTENANCE_RECORD = "maintenance_record"  # 维护记录


class DataStatus(Enum):
    """数据状态"""
    PENDING = "pending"  # 待确认
    CONFIRMED = "confirmed"  # 已确认
    ADJUSTED = "adjusted"  # 已调整
    INVALIDATED = "invalidated"  # 已作废


@dataclass
class OperationDataPoint:
    """工序数据点 - 最小数据采集单元"""
    id: str
    work_order_id: str
    routing_id: str
    operation_sequence: int  # 工序序号
    station_id: str
    operator_id: str
    product_code: str
    quantity: int  # 加工数量
    start_time: datetime
    end_time: datetime
    actual_time: float  # 实际工时 (秒)
    standard_time: float  # 标准工时 (秒)
    setup_time: float = 0.0  # 准备/换型时间 (秒)
    good_qty: int = 0  # 良品数
    defect_qty: int = 0  # 不良品数
    scrap_qty: int = 0  # 报废数
    defect_codes: List[str] = field(default_factory=list)  # 不良代码
    equipment_id: Optional[str] = None
    material_batch: Optional[str] = None
    status: DataStatus = DataStatus.PENDING
    remark: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "routing_id": self.routing_id,
            "operation_sequence": self.operation_sequence,
            "station_id": self.station_id,
            "operator_id": self.operator_id,
            "product_code": self.product_code,
            "quantity": self.quantity,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "actual_time": self.actual_time,
            "standard_time": self.standard_time,
            "setup_time": self.setup_time,
            "good_qty": self.good_qty,
            "defect_qty": self.defect_qty,
            "scrap_qty": self.scrap_qty,
            "defect_codes": self.defect_codes,
            "equipment_id": self.equipment_id,
            "material_batch": self.material_batch,
            "status": self.status.value,
            "remark": self.remark,
            "created_at": self.created_at.isoformat(),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'OperationDataPoint':
        return cls(
            id=data["id"],
            work_order_id=data["work_order_id"],
            routing_id=data["routing_id"],
            operation_sequence=data["operation_sequence"],
            station_id=data["station_id"],
            operator_id=data["operator_id"],
            product_code=data["product_code"],
            quantity=data["quantity"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            actual_time=data["actual_time"],
            standard_time=data["standard_time"],
            setup_time=data.get("setup_time", 0.0),
            good_qty=data.get("good_qty", 0),
            defect_qty=data.get("defect_qty", 0),
            scrap_qty=data.get("scrap_qty", 0),
            defect_codes=data.get("defect_codes", []),
            equipment_id=data.get("equipment_id"),
            material_batch=data.get("material_batch"),
            status=DataStatus(data.get("status", "pending")),
            remark=data.get("remark", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            confirmed_by=data.get("confirmed_by"),
            confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None,
        )


@dataclass
class EquipmentStatusRecord:
    """设备状态记录"""
    id: str
    equipment_id: str
    station_id: str
    status: str  # RUNNING, IDLE, STOPPED, MAINTENANCE, BROKEN
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    reason_code: Optional[str] = None  # 状态原因代码
    operator_id: Optional[str] = None
    andon_event_id: Optional[str] = None  # 关联的安灯事件
    production_count: int = 0  # 期间产量
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "equipment_id": self.equipment_id,
            "station_id": self.station_id,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "reason_code": self.reason_code,
            "operator_id": self.operator_id,
            "andon_event_id": self.andon_event_id,
            "production_count": self.production_count,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ProcessCapabilityData:
    """工艺能力数据 - 用于排产的约束参数"""
    product_code: str
    operation_sequence: int
    station_id: str
    avg_actual_time: float  # 平均实际工时
    min_actual_time: float  # 最小工时
    max_actual_time: float  # 最大工时
    std_deviation: float  # 标准差
    yield_rate: float  # 良率
    sample_count: int  # 样本数量
    last_updated: datetime
    is_stable: bool = True  # 工艺是否稳定
    capability_index: float = 0.0  # CPK值
    
    def to_dict(self) -> dict:
        return {
            "product_code": self.product_code,
            "operation_sequence": self.operation_sequence,
            "station_id": self.station_id,
            "avg_actual_time": self.avg_actual_time,
            "min_actual_time": self.min_actual_time,
            "max_actual_time": self.max_actual_time,
            "std_deviation": self.std_deviation,
            "yield_rate": self.yield_rate,
            "sample_count": self.sample_count,
            "last_updated": self.last_updated.isoformat(),
            "is_stable": self.is_stable,
            "capability_index": self.capability_index,
        }


class ProductionDataCollector:
    """生产数据采集器 - 核心类"""
    
    def __init__(self):
        self.operation_data: Dict[str, OperationDataPoint] = {}
        self.equipment_status: Dict[str, EquipmentStatusRecord] = {}
        self.process_capability: Dict[str, ProcessCapabilityData] = {}  # key: product_code_op_seq_station
        self.active_equipment_status: Dict[str, EquipmentStatusRecord] = {}  # 当前活跃的设备状态
        
    def collect_operation_data(
        self,
        work_order_id: str,
        routing_id: str,
        operation_sequence: int,
        station_id: str,
        operator_id: str,
        product_code: str,
        quantity: int,
        start_time: datetime,
        end_time: datetime,
        standard_time: float,
        good_qty: int,
        defect_qty: int = 0,
        scrap_qty: int = 0,
        setup_time: float = 0.0,
        defect_codes: List[str] = None,
        equipment_id: str = None,
        material_batch: str = None,
        remark: str = "",
    ) -> OperationDataPoint:
        """采集工序数据"""
        data_id = f"OPD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        
        actual_time = (end_time - start_time).total_seconds()
        
        data_point = OperationDataPoint(
            id=data_id,
            work_order_id=work_order_id,
            routing_id=routing_id,
            operation_sequence=operation_sequence,
            station_id=station_id,
            operator_id=operator_id,
            product_code=product_code,
            quantity=quantity,
            start_time=start_time,
            end_time=end_time,
            actual_time=actual_time,
            standard_time=standard_time,
            setup_time=setup_time,
            good_qty=good_qty,
            defect_qty=defect_qty,
            scrap_qty=scrap_qty,
            defect_codes=defect_codes or [],
            equipment_id=equipment_id,
            material_batch=material_batch,
            remark=remark,
        )
        
        self.operation_data[data_id] = data_point
        
        # 自动更新工艺能力数据
        self._update_process_capability(data_point)
        
        print(f"✅ 采集工序数据：{data_id}")
        print(f"   工单：{work_order_id}, 工序：{operation_sequence}, 工位：{station_id}")
        print(f"   数量：{quantity}, 良品：{good_qty}, 不良：{defect_qty}")
        print(f"   标准工时：{standard_time}s, 实际工时：{actual_time:.1f}s, 效率：{(standard_time/actual_time*100) if actual_time > 0 else 0:.1f}%")
        
        return data_point
    
    def confirm_operation_data(self, data_id: str, confirmed_by: str) -> bool:
        """确认工序数据"""
        if data_id not in self.operation_data:
            print(f"❌ 数据 {data_id} 不存在")
            return False
        
        data_point = self.operation_data[data_id]
        data_point.status = DataStatus.CONFIRMED
        data_point.confirmed_by = confirmed_by
        data_point.confirmed_at = datetime.now()
        
        print(f"✅ 确认工序数据：{data_id} by {confirmed_by}")
        return True
    
    def record_equipment_status(
        self,
        equipment_id: str,
        station_id: str,
        status: str,
        reason_code: str = None,
        operator_id: str = None,
        andon_event_id: str = None,
    ) -> EquipmentStatusRecord:
        """记录设备状态变化"""
        record_id = f"EQS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        now = datetime.now()
        
        # 结束上一个状态记录
        if equipment_id in self.active_equipment_status:
            prev_record = self.active_equipment_status[equipment_id]
            prev_record.end_time = now
            prev_record.duration_seconds = (now - prev_record.start_time).total_seconds()
        
        # 创建新状态记录
        record = EquipmentStatusRecord(
            id=record_id,
            equipment_id=equipment_id,
            station_id=station_id,
            status=status,
            start_time=now,
            reason_code=reason_code,
            operator_id=operator_id,
            andon_event_id=andon_event_id,
        )
        
        self.equipment_status[record_id] = record
        self.active_equipment_status[equipment_id] = record
        
        print(f"📊 设备状态变更：{equipment_id}")
        print(f"   新状态：{status}, 原因：{reason_code or 'N/A'}")
        
        return record
    
    def _update_process_capability(self, data_point: OperationDataPoint):
        """更新工艺能力数据"""
        key = f"{data_point.product_code}_{data_point.operation_sequence}_{data_point.station_id}"
        
        if key not in self.process_capability:
            # 初始化
            self.process_capability[key] = ProcessCapabilityData(
                product_code=data_point.product_code,
                operation_sequence=data_point.operation_sequence,
                station_id=data_point.station_id,
                avg_actual_time=data_point.actual_time,
                min_actual_time=data_point.actual_time,
                max_actual_time=data_point.actual_time,
                std_deviation=0.0,
                yield_rate=(data_point.good_qty / data_point.quantity * 100) if data_point.quantity > 0 else 0,
                sample_count=1,
                last_updated=datetime.now(),
            )
        else:
            cap = self.process_capability[key]
            n = cap.sample_count
            
            # 更新统计值 (Welford 算法)
            new_avg = cap.avg_actual_time + (data_point.actual_time - cap.avg_actual_time) / (n + 1)
            new_min = min(cap.min_actual_time, data_point.actual_time)
            new_max = max(cap.max_actual_time, data_point.actual_time)
            
            # 简化计算标准差
            variance = ((n * (cap.std_deviation ** 2 + cap.avg_actual_time ** 2)) + 
                       data_point.actual_time ** 2) / (n + 1) - new_avg ** 2
            new_std = variance ** 0.5 if variance > 0 else 0
            
            # 更新良率 (加权平均)
            current_yield = (data_point.good_qty / data_point.quantity * 100) if data_point.quantity > 0 else 0
            new_yield = (cap.yield_rate * n + current_yield) / (n + 1)
            
            cap.avg_actual_time = new_avg
            cap.min_actual_time = new_min
            cap.max_actual_time = new_max
            cap.std_deviation = new_std
            cap.yield_rate = new_yield
            cap.sample_count = n + 1
            cap.last_updated = datetime.now()
            
            # 判断工艺稳定性 (变异系数 < 10% 认为稳定)
            cv = (cap.std_deviation / cap.avg_actual_time * 100) if cap.avg_actual_time > 0 else 0
            cap.is_stable = cv < 10
    
    def get_process_capability(
        self,
        product_code: str,
        operation_sequence: int,
        station_id: str,
    ) -> Optional[ProcessCapabilityData]:
        """获取工艺能力数据"""
        key = f"{product_code}_{operation_sequence}_{station_id}"
        return self.process_capability.get(key)
    
    def get_station_efficiency(
        self,
        station_id: str,
        time_range_hours: int = 24,
    ) -> Dict[str, Any]:
        """获取工位效率分析"""
        cutoff_time = datetime.now() - timedelta(hours=time_range_hours)
        
        station_data = [
            d for d in self.operation_data.values()
            if d.station_id == station_id
            and d.created_at > cutoff_time
            and d.status == DataStatus.CONFIRMED
        ]
        
        if not station_data:
            return {
                "station_id": station_id,
                "total_operations": 0,
                "avg_efficiency": 0,
                "total_good_qty": 0,
                "total_defect_qty": 0,
                "yield_rate": 0,
            }
        
        total_standard_time = sum(d.standard_time * d.quantity for d in station_data)
        total_actual_time = sum(d.actual_time for d in station_data)
        total_good = sum(d.good_qty for d in station_data)
        total_defect = sum(d.defect_qty for d in station_data)
        
        efficiency = (total_standard_time / total_actual_time * 100) if total_actual_time > 0 else 0
        yield_rate = (total_good / (total_good + total_defect) * 100) if (total_good + total_defect) > 0 else 0
        
        return {
            "station_id": station_id,
            "time_range_hours": time_range_hours,
            "total_operations": len(station_data),
            "total_standard_time": total_standard_time,
            "total_actual_time": total_actual_time,
            "avg_efficiency": efficiency,
            "total_good_qty": total_good,
            "total_defect_qty": total_defect,
            "yield_rate": yield_rate,
        }
    
    def get_equipment_oee(
        self,
        equipment_id: str,
        time_range_hours: int = 24,
    ) -> Dict[str, Any]:
        """计算设备 OEE (整体设备效率)"""
        cutoff_time = datetime.now() - timedelta(hours=time_range_hours)
        
        equipment_records = [
            r for r in self.equipment_status.values()
            if r.equipment_id == equipment_id
            and r.start_time > cutoff_time
        ]
        
        total_time = time_range_hours * 3600  # 秒
        running_time = sum(
            r.duration_seconds for r in equipment_records
            if r.status == "RUNNING"
        )
        idle_time = sum(
            r.duration_seconds for r in equipment_records
            if r.status == "IDLE"
        )
        stopped_time = sum(
            r.duration_seconds for r in equipment_records
            if r.status in ["STOPPED", "BROKEN"]
        )
        maintenance_time = sum(
            r.duration_seconds for r in equipment_records
            if r.status == "MAINTENANCE"
        )
        
        availability = (running_time / total_time * 100) if total_time > 0 else 0
        
        # 简化计算性能稼动率 (假设标准节拍为 60 秒)
        total_production = sum(r.production_count for r in equipment_records)
        performance = (total_production * 60 / running_time * 100) if running_time > 0 else 0
        performance = min(performance, 100)  # 不超过 100%
        
        # 简化计算良率 (假设 98%)
        quality_rate = 98.0
        
        oee = availability * performance * quality_rate / 10000
        
        return {
            "equipment_id": equipment_id,
            "time_range_hours": time_range_hours,
            "availability": availability,
            "performance": performance,
            "quality_rate": quality_rate,
            "oee": oee,
            "running_time": running_time,
            "idle_time": idle_time,
            "stopped_time": stopped_time,
            "maintenance_time": maintenance_time,
            "total_production": total_production,
        }
    
    def export_for_aps(self) -> Dict[str, Any]:
        """导出 APS 排产所需的数据"""
        # 汇总工艺能力数据
        process_capabilities = {
            k: v.to_dict() for k, v in self.process_capability.items()
        }
        
        # 汇总工位效率
        station_ids = set(d.station_id for d in self.operation_data.values())
        station_efficiency = {
            sid: self.get_station_efficiency(sid) for sid in station_ids
        }
        
        # 汇总设备 OEE
        equipment_ids = set(r.equipment_id for r in self.equipment_status.values())
        equipment_oee = {
            eid: self.get_equipment_oee(eid) for eid in equipment_ids
        }
        
        return {
            "export_time": datetime.now().isoformat(),
            "process_capabilities": process_capabilities,
            "station_efficiency": station_efficiency,
            "equipment_oee": equipment_oee,
            "total_operation_records": len(self.operation_data),
            "total_equipment_records": len(self.equipment_status),
        }


def demonstrate_data_collection():
    """演示数据采集功能"""
    print("=" * 80)
    print("MES 生产数据采集系统演示 - 混合排产数据基础")
    print("=" * 80)
    
    collector = ProductionDataCollector()
    
    # 1. 模拟采集工序数据
    print("\n📝 采集工序数据...")
    base_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    
    # 工单 1: 产品 A, 工序 10
    collector.collect_operation_data(
        work_order_id="WO-20260524-001",
        routing_id="RT-TM-X100",
        operation_sequence=10,
        station_id="STATION-SMT-01",
        operator_id="OP-001",
        product_code="TM-X100",
        quantity=100,
        start_time=base_time,
        end_time=base_time + timedelta(minutes=45),
        standard_time=30.0,  # 标准 30 秒/pcs
        good_qty=98,
        defect_qty=2,
        setup_time=300,  # 换型 5 分钟
        equipment_id="EQ-SMT-001",
    )
    
    # 工单 1: 产品 A, 工序 20
    collector.collect_operation_data(
        work_order_id="WO-20260524-001",
        routing_id="RT-TM-X100",
        operation_sequence=20,
        station_id="STATION-ASSY-01",
        operator_id="OP-002",
        product_code="TM-X100",
        quantity=98,
        start_time=base_time + timedelta(hours=1),
        end_time=base_time + timedelta(hours=1, minutes=40),
        standard_time=45.0,
        good_qty=96,
        defect_qty=2,
        setup_time=180,
    )
    
    # 工单 2: 产品 B, 工序 10 (相同工位)
    collector.collect_operation_data(
        work_order_id="WO-20260524-002",
        routing_id="RT-TM-X200",
        operation_sequence=10,
        station_id="STATION-SMT-01",
        operator_id="OP-001",
        product_code="TM-X200",
        quantity=80,
        start_time=base_time + timedelta(hours=2),
        end_time=base_time + timedelta(hours=2, minutes=35),
        standard_time=32.0,
        good_qty=78,
        defect_qty=2,
        setup_time=420,  # 不同产品换型时间更长
        equipment_id="EQ-SMT-001",
    )
    
    # 2. 确认数据
    print("\n✅ 确认工序数据...")
    for data_id in list(collector.operation_data.keys())[:2]:
        collector.confirm_operation_data(data_id, "SUPERVISOR-001")
    
    # 3. 记录设备状态
    print("\n📊 记录设备状态...")
    collector.record_equipment_status(
        equipment_id="EQ-SMT-001",
        station_id="STATION-SMT-01",
        status="RUNNING",
        operator_id="OP-001",
    )
    
    # 模拟设备故障
    collector.record_equipment_status(
        equipment_id="EQ-SMT-001",
        station_id="STATION-SMT-01",
        status="BROKEN",
        reason_code="ERR-001",
        operator_id="OP-001",
        andon_event_id="ANDON-001",
    )
    
    # 恢复运行
    collector.record_equipment_status(
        equipment_id="EQ-SMT-001",
        station_id="STATION-SMT-01",
        status="RUNNING",
        operator_id="MAINT-001",
    )
    
    # 4. 查询工艺能力
    print("\n🔍 查询工艺能力数据...")
    cap = collector.get_process_capability("TM-X100", 10, "STATION-SMT-01")
    if cap:
        print(f"   产品：{cap.product_code}, 工序：{cap.operation_sequence}")
        print(f"   平均工时：{cap.avg_actual_time:.1f}s (标准：30s)")
        print(f"   工时范围：{cap.min_actual_time:.1f}s ~ {cap.max_actual_time:.1f}s")
        print(f"   标准差：{cap.std_deviation:.2f}s")
        print(f"   良率：{cap.yield_rate:.1f}%")
        print(f"   样本数：{cap.sample_count}")
        print(f"   工艺稳定：{'是' if cap.is_stable else '否'}")
    
    # 5. 工位效率分析
    print("\n📈 工位效率分析...")
    eff = collector.get_station_efficiency("STATION-SMT-01")
    print(f"   工位：{eff['station_id']}")
    print(f"   总操作数：{eff['total_operations']}")
    print(f"   平均效率：{eff['avg_efficiency']:.1f}%")
    print(f"   总良品：{eff['total_good_qty']}")
    print(f"   良率：{eff['yield_rate']:.1f}%")
    
    # 6. 设备 OEE
    print("\n⚙️  设备 OEE 分析...")
    oee = collector.get_equipment_oee("EQ-SMT-001")
    print(f"   设备：{oee['equipment_id']}")
    print(f"   时间稼动率：{oee['availability']:.1f}%")
    print(f"   性能稼动率：{oee['performance']:.1f}%")
    print(f"   良品率：{oee['quality_rate']:.1f}%")
    print(f"   OEE: {oee['oee']:.1f}%")
    
    # 7. 导出 APS 数据
    print("\n📤 导出 APS 排产数据...")
    aps_data = collector.export_for_aps()
    print(f"   导出时间：{aps_data['export_time']}")
    print(f"   工艺能力数据：{len(aps_data['process_capabilities'])} 条")
    print(f"   工位效率数据：{len(aps_data['station_efficiency'])} 个")
    print(f"   设备 OEE 数据：{len(aps_data['equipment_oee'])} 个")
    print(f"   工序记录总数：{aps_data['total_operation_records']}")
    print(f"   设备记录总数：{aps_data['total_equipment_records']}")
    
    print("\n" + "=" * 80)
    print("数据采集演示完成")
    print("=" * 80)
    
    return collector


if __name__ == "__main__":
    demonstrate_data_collection()
