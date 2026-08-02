"""
车间级 / 工段级负荷仿真 —— 领域契约

建模真实工厂的负荷传导：
- 工厂 → 车间(Workshop) → 工段(Section)
- 订单(Order) → 产品工艺路线(Routing) → 工序(Operation) 落到具体工段
- 工段生产策略：
    * MTS (make-to-stock / 备料平准)：负荷在整个计划期内平准铺开 —— 如备料、零件加工
    * MTO (make-to-order / 订单驱动)：负荷由订单交期拉动，呈脉冲式 —— 如组立（订单进、订单出）
- 所有工段/车间参数均可被仿真控制：人员、设备、班次、工时、效率、加班、排班日历
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ProductionStrategy(str, Enum):
    """工段生产策略"""

    MTS = "mts"  # 备料/库存生产：负荷平准
    MTO = "mto"  # 订单生产：订单进、订单出


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


PRIORITY_RANK = {Priority.LOW: 3, Priority.MEDIUM: 2, Priority.HIGH: 1, Priority.URGENT: 0}


# ==================== 输入侧 ====================

class RealWorkerSeed(BaseModel):
    """真实员工种子（来自 HR 花名册 hr_employees + hr_employee_skills）。

    用于把真实人力数据喂入仿真：工段配置一旦携带 real_workers，
    引擎将用真实花名册替代合成工人，并按平均技能等级修正产能。
    """

    name: str
    skill_level: int = Field(default=3, ge=1, le=5)        # 技能等级 1~5（L1~L5 映射）
    shift: int = Field(default=1, ge=1, le=3)              # 所属班次
    gender: Optional[str] = None                            # 性别
    height_cm: Optional[float] = Field(default=None, ge=0)  # 身高(cm)
    weight_kg: Optional[float] = Field(default=None, ge=0)  # 体重(kg)
    role: Optional[str] = None                              # 工种/岗位
    attendance_rate: Optional[float] = Field(default=None, ge=0.5, le=1.0)  # 出勤率


class SectionConfig(BaseModel):
    """工段（可完全控制的核心参数）"""

    section_id: str
    name: str
    workshop_id: str
    strategy: ProductionStrategy = ProductionStrategy.MTO
    workers: int = Field(default=10, ge=1, le=500)            # 单班人数
    machines: int = Field(default=0, ge=0, le=200)           # 设备台数（0 = 纯人工作业）
    shifts_per_day: int = Field(default=1, ge=1, le=3)       # 每日班次
    hours_per_shift: float = Field(default=8.0, ge=4.0, le=12.0)  # 每班工时
    efficiency: float = Field(default=0.85, ge=0.3, le=1.0)  # 综合效率 OEE
    max_overtime_pct: float = Field(default=0.2, ge=0.0, le=1.0)  # 最大加班比例
    yield_rate: float = Field(default=0.98, ge=0.5, le=1.0)       # 良品率（产出合格比例）
    role_name: str = ""                                            # 工种名（如"焊工"），空则按工段派生
    description: str = ""
    # 真实员工花名册（空 = 合成生成，向后兼容既有场景）；非空时技能影响产能
    real_workers: List[RealWorkerSeed] = Field(default_factory=list)


class WorkshopConfig(BaseModel):
    """车间：工段的组织单元，拥有自己的排班日历"""

    workshop_id: str
    name: str
    working_days_per_week: int = Field(default=6, ge=5, le=7)  # 5=双休 6=单休 7=全周
    description: str = ""


class RoutingOperation(BaseModel):
    """工序：挂在工艺路线上、落到具体工段"""

    op_no: int = Field(..., ge=1)
    name: str
    section_id: str
    setup_minutes: float = Field(default=30.0, ge=0.0)       # 每批次换型/准备时间(分钟)
    cycle_seconds: float = Field(default=60.0, ge=0.0)       # 单件节拍(秒)
    batch_size: int = Field(default=50, ge=1)                # 转移批量
    move_hours: float = Field(default=4.0, ge=0.0, le=72.0)  # 工序间转移/等待(小时)


class RoutingDef(BaseModel):
    """产品工艺路线：工序顺序"""

    routing_id: str
    product_id: str
    product_name: str
    operations: List[RoutingOperation] = Field(..., min_length=1)


class OrderInput(BaseModel):
    """仿真订单输入"""

    order_id: str
    product_id: str
    quantity: int = Field(default=100, ge=1, le=100_000)
    release_day: int = Field(default=0, ge=0)    # 投放日（第几天进入工厂）
    due_day: int = Field(default=10, ge=1)       # 交期日
    priority: Priority = Priority.MEDIUM


class FactorySimConfig(BaseModel):
    """仿真总配置 —— 所有参数前端可控"""

    horizon_days: int = Field(default=14, ge=5, le=60)              # 计划期长度(天)
    demand_variability_pct: float = Field(default=0.0, ge=0.0, le=0.5)  # 日负荷波动幅度(±)
    overtime_allowed: bool = True                                    # 全局是否允许加班
    seed: int = Field(default=42, ge=0)                              # 随机种子（可复现）
    workshops: List[WorkshopConfig] = Field(..., min_length=1)
    sections: List[SectionConfig] = Field(..., min_length=1)
    routings: List[RoutingDef] = Field(..., min_length=1)
    orders: List[OrderInput] = Field(..., min_length=1)
    # 实时数据仿真来源标识（可选，配合 is_simulation 分离原则）
    factory_id: Optional[str] = None
    factory_name: Optional[str] = None
    data_source: Optional[str] = None  # scenario / live_db


# ==================== 输出侧 ====================

class SectionDayLoad(BaseModel):
    """工段 × 日 负荷单元"""

    day: int
    load_hours: float
    capacity_hours: float
    load_rate: float          # load / capacity，>1 表示过载
    is_workday: bool = True   # 休息日为 False（负荷为 0）
    wip_qty: int = 0          # 该工段当日在制积压件数（物料堆在此处的数量）


class SectionSummary(BaseModel):
    """工段级汇总"""

    section_id: str
    name: str
    workshop_id: str
    workshop_name: str
    strategy: ProductionStrategy
    workers: int
    machines: int
    shifts_per_day: int
    hours_per_shift: float
    efficiency: float
    total_load_hours: float
    total_capacity_hours: float
    avg_load_rate: float
    peak_load_rate: float
    peak_day: int
    is_bottleneck: bool       # 峰值 > 1.0（含加班仍过载）
    overtime_used_hours: float
    series: List[SectionDayLoad]


class OrderOpSchedule(BaseModel):
    """订单工序排程结果（甘特图数据）"""

    op_no: int
    name: str
    section_id: str
    section_name: str
    strategy: ProductionStrategy
    start_day: int
    end_day: int
    work_hours: float


class OrderResult(BaseModel):
    """订单级结果"""

    order_id: str
    product_id: str
    product_name: str
    quantity: int
    priority: Priority
    release_day: int
    due_day: int
    completion_day: int
    delay_days: int           # max(0, completion - due)
    on_time: bool
    total_work_hours: float
    ops: List[OrderOpSchedule]


class OrderSectionLoad(BaseModel):
    """订单 × 工段 负荷贡献（回答"不同订单对不同部门负荷不同"）"""

    order_id: str
    section_id: str
    section_name: str
    work_hours: float
    share_pct: float          # 占该工段总负荷的百分比


class WorkerDef(BaseModel):
    """单个工人（仿真花名册）"""

    worker_id: str
    name: str
    section_id: str
    section_name: str
    role: str                       # 工种（如焊工 / 冲压工 / 贴片操作工）
    skill_level: int = Field(default=3, ge=1, le=5)   # 技能等级 1~5
    shift: int = Field(default=1, ge=1, le=3)         # 所属班次
    attendance_rate: float = Field(default=0.95, ge=0.5, le=1.0)  # 出勤率
    # 真实员工档案（来自 HR 花名册；合成工人为 None）
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None


class SectionWorkforce(BaseModel):
    """工段级人力汇总 + 花名册"""

    section_id: str
    name: str
    headcount: int                  # 在岗总人数 = 单班人数 × 班次
    per_shift: int                  # 单班人数
    shift_headcount: Dict[int, int] = Field(default_factory=dict)  # 班次 → 人数
    avg_skill: float                # 平均技能等级
    avg_attendance: float           # 平均出勤率
    labor_utilization: float        # 人力利用率 = 总负荷工时 / 总可用人力工时
    workers: List[WorkerDef] = Field(default_factory=list)


class OutputPoint(BaseModel):
    """工厂 × 日 成品产出"""

    day: int
    output_qty: int                 # 当日成品产出（末道工序完工）
    good_qty: int                   # 当日良品
    scrap_qty: int                  # 当日报废
    cumulative: int                 # 累计成品产出


class SectionOutput(BaseModel):
    """工段级产出（计划期累计）"""

    section_id: str
    name: str
    planned_qty: int                # 计划期流过的总量
    good_qty: int
    scrap_qty: int
    yield_rate: float


class PoOpResult(BaseModel):
    """PO 工单工序结果"""

    op_no: int
    name: str
    section_id: str
    section_name: str
    start_day: int
    end_day: int
    qty: int
    good_qty: int
    scrap_qty: int
    status: str                     # completed / delayed
    wait_days: int = 0              # 本工序开工前等待天数（与上工序完工的间隙）


class ProductionOrderResult(BaseModel):
    """生产工单（PO）全生命周期结果"""

    po_id: str
    order_id: str
    product_name: str
    quantity: int
    release_day: int                # 下达日
    start_day: int                  # 首工序开工日
    completion_day: int             # 末道工序完工日
    due_day: int
    status: str                     # released / in_progress / completed / delayed
    on_time: bool
    good_qty: int
    scrap_qty: int
    current_section: str            # 当前/末道工段名
    ops: List[PoOpResult] = Field(default_factory=list)


class TransferRecord(BaseModel):
    """工序间流转（移转）记录"""

    transfer_id: str
    order_id: str
    product_name: str
    from_section_id: str
    from_section_name: str
    to_section_id: str
    to_section_name: str
    qty: int
    depart_day: int                 # 离开上工序日
    arrive_day: int                 # 到达下工序日


class BlockingPoint(BaseModel):
    """卡点（物流停滞处）分析结果"""

    rank: int
    section_id: str
    section_name: str
    workshop_name: str
    blocking_type: str              # overload / wip_buildup / process_wait
    severity: float                 # 综合严重度 0~100
    peak_day: int                   # 峰值出现日
    peak_load_rate: float           # 峰值负荷率
    overload_days: int              # 过载天数
    wip_peak: int                   # 在制积压峰值（件）
    avg_wait_days: float            # 平均工序等待天数
    delayed_orders: int             # 经此工段且延期的订单数
    detail: str                     # 卡点说明


class OutboundOrder(BaseModel):
    """货物出库单（末道工序完工 → 成品出库）"""

    outbound_id: str                # OB-xxx
    order_id: str
    po_id: str
    product_name: str
    quantity: int
    good_qty: int
    outbound_day: int               # 出库日（计划期内）
    on_time: bool
    warehouse: str                  # 成品仓
    status: str                     # shipped / pending


class WipPoint(BaseModel):
    """在制品曲线"""

    day: int
    wip_qty: int              # 当天在制总量（已投放未完工的订单数量之和）
    active_orders: int


class FactoryAlert(BaseModel):
    """仿真告警"""

    level: str                # critical / warning / info
    category: str             # overload / delay / bottleneck / idle / imbalance
    title: str
    detail: str
    section_id: Optional[str] = None
    order_id: Optional[str] = None
    day: Optional[int] = None


class FactoryKPIs(BaseModel):
    """工厂级 KPI"""

    total_work_hours: float
    total_capacity_hours: float
    avg_load_rate: float
    peak_load_rate: float
    on_time_rate: float       # 0~1
    delayed_orders: int
    bottleneck_sections: int
    wip_peak: int
    imbalance_index: float    # 各工段平均负荷率的极差，越大说明订单结构对部门负荷分化越明显
    overtime_hours: float
    # ---- 产出 / 人力 / PO 扩展 ----
    total_output: int = 0          # 计划期成品产出总量
    good_output: int = 0           # 良品产出
    scrap_output: int = 0          # 报废量
    avg_yield_rate: float = 1.0    # 综合良品率
    headcount: int = 0             # 全厂在岗总人数（人数×班次）
    po_completed: int = 0          # 准时完工 PO 数
    po_delayed: int = 0            # 延期 PO 数
    # ---- 全过程 / 卡点扩展 ----
    blocking_point_count: int = 0  # 卡点数（过载工段数）
    max_section_wip: int = 0       # 单工段峰值在制积压（件）
    total_outbound: int = 0        # 计划期出库总量
    pending_outbound: int = 0      # 计划期未出库数
    avg_process_wait: float = 0.0  # 平均工序等待天数


class FactorySimResult(BaseModel):
    """仿真总结果"""

    simulation_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine_version: str
    horizon_days: int
    workshop_count: int
    section_count: int
    order_count: int
    kpis: FactoryKPIs
    sections: List[SectionSummary]
    orders: List[OrderResult]
    order_section_loads: List[OrderSectionLoad]
    wip_curve: List[WipPoint]
    alerts: List[FactoryAlert]
    # ---- 完整仿真扩展 ----
    workforce: List[SectionWorkforce] = Field(default_factory=list)
    daily_output: List[OutputPoint] = Field(default_factory=list)
    section_outputs: List[SectionOutput] = Field(default_factory=list)
    production_orders: List[ProductionOrderResult] = Field(default_factory=list)
    transfers: List[TransferRecord] = Field(default_factory=list)
    # ---- 全过程 / 卡点扩展 ----
    blocking_points: List[BlockingPoint] = Field(default_factory=list)
    outbound_orders: List[OutboundOrder] = Field(default_factory=list)
