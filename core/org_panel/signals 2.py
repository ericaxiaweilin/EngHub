"""
信号类型系统 (Signal Type System)
=================================

定义所有可在组织节点间传导的信号类型。
类型安全：只有 SignalType 兼容的信号才能通过 LogicChain 连接。

信号分域：
- 生产域：产出/WIP/节拍/达成率
- 质量域：良率/缺陷/SPC/返工
- 设备域：应力/故障率/MTBF/维修负荷
- 人员域：疲劳/出勤/利用率/加班
- 物料域：消耗/库存/缺料风险
- 成本域：单位成本/OEE
- 管理域：升级/决策延迟
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalDomain(str, Enum):
    """信号所属域"""
    PRODUCTION = "production"
    QUALITY = "quality"
    EQUIPMENT = "equipment"
    WORKFORCE = "workforce"
    MATERIAL = "material"
    COST = "cost"
    MANAGEMENT = "management"


class SignalType(Enum):
    """所有可传导信号类型"""

    # ── 生产域 ──
    THROUGHPUT = ("throughput", SignalDomain.PRODUCTION, "件/天")
    WIP_LEVEL = ("wip_level", SignalDomain.PRODUCTION, "件")
    CYCLE_TIME = ("cycle_time", SignalDomain.PRODUCTION, "小时/件")
    SCHEDULE_ADHERENCE = ("schedule_adh", SignalDomain.PRODUCTION, "%")

    # ── 质量域 ──
    YIELD_RATE = ("yield_rate", SignalDomain.QUALITY, "ratio")
    DEFECT_RATE = ("defect_rate", SignalDomain.QUALITY, "ppm")
    SPC_STATUS = ("spc_status", SignalDomain.QUALITY, "level")
    REWORK_VOLUME = ("rework_volume", SignalDomain.QUALITY, "件/天")

    # ── 设备域 ──
    EQUIPMENT_STRESS = ("equip_stress", SignalDomain.EQUIPMENT, "ratio")
    FAILURE_PROB = ("failure_prob", SignalDomain.EQUIPMENT, "ratio")
    MTBF = ("mtbf", SignalDomain.EQUIPMENT, "小时")
    MAINTENANCE_LOAD = ("maint_load", SignalDomain.EQUIPMENT, "工时/天")
    AVAILABILITY = ("availability", SignalDomain.EQUIPMENT, "ratio")

    # ── 人员域 ──
    FATIGUE_LEVEL = ("fatigue", SignalDomain.WORKFORCE, "ratio")
    ATTENDANCE = ("attendance", SignalDomain.WORKFORCE, "ratio")
    LABOR_UTILIZATION = ("labor_util", SignalDomain.WORKFORCE, "ratio")
    OVERTIME_HOURS = ("overtime", SignalDomain.WORKFORCE, "小时/天")

    # ── 物料域 ──
    MATERIAL_BURN = ("material_burn", SignalDomain.MATERIAL, "单位/天")
    STOCK_LEVEL = ("stock_level", SignalDomain.MATERIAL, "单位")
    STOCKOUT_RISK_HOURS = ("stockout_h", SignalDomain.MATERIAL, "小时")

    # ── 成本域 ──
    UNIT_COST = ("unit_cost", SignalDomain.COST, "元/件")
    OEE = ("oee", SignalDomain.COST, "ratio")

    # ── 管理域 ──
    ESCALATION_LEVEL = ("escalation", SignalDomain.MANAGEMENT, "level")
    DECISION_LATENCY = ("decision_lat", SignalDomain.MANAGEMENT, "小时")

    def __init__(self, code: str, domain: SignalDomain, unit: str):
        self.code = code
        self.domain = domain
        self.unit = unit

    @property
    def label(self) -> str:
        """中文显示名"""
        return _SIGNAL_LABELS.get(self, self.code)


# 中文标签映射
_SIGNAL_LABELS = {
    SignalType.THROUGHPUT: "日产出",
    SignalType.WIP_LEVEL: "在制品量",
    SignalType.CYCLE_TIME: "节拍",
    SignalType.SCHEDULE_ADHERENCE: "计划达成率",
    SignalType.YIELD_RATE: "良率",
    SignalType.DEFECT_RATE: "缺陷率",
    SignalType.SPC_STATUS: "SPC状态",
    SignalType.REWORK_VOLUME: "返工量",
    SignalType.EQUIPMENT_STRESS: "设备应力",
    SignalType.FAILURE_PROB: "故障概率",
    SignalType.MTBF: "平均故障间隔",
    SignalType.MAINTENANCE_LOAD: "维修负荷",
    SignalType.AVAILABILITY: "设备可用率",
    SignalType.FATIGUE_LEVEL: "疲劳度",
    SignalType.ATTENDANCE: "出勤率",
    SignalType.LABOR_UTILIZATION: "人力利用率",
    SignalType.OVERTIME_HOURS: "加班时数",
    SignalType.MATERIAL_BURN: "物料消耗",
    SignalType.STOCK_LEVEL: "库存水位",
    SignalType.STOCKOUT_RISK_HOURS: "缺料风险",
    SignalType.UNIT_COST: "单位成本",
    SignalType.OEE: "OEE",
    SignalType.ESCALATION_LEVEL: "升级等级",
    SignalType.DECISION_LATENCY: "决策延迟",
}


# ── 类型兼容性表 ──
# 定义哪些信号类型可以互相传导（同域内默认兼容，跨域需要显式声明）
_CROSS_DOMAIN_COMPATIBLE = {
    # 生产→质量：产出速度影响良率
    (SignalType.THROUGHPUT, SignalType.YIELD_RATE): True,
    (SignalType.THROUGHPUT, SignalType.DEFECT_RATE): True,
    # 生产→设备：产出速度影响设备应力
    (SignalType.THROUGHPUT, SignalType.EQUIPMENT_STRESS): True,
    (SignalType.THROUGHPUT, SignalType.FAILURE_PROB): True,
    # 生产→人员：产出速度影响疲劳
    (SignalType.THROUGHPUT, SignalType.FATIGUE_LEVEL): True,
    # 生产→物料：产出消耗物料
    (SignalType.THROUGHPUT, SignalType.MATERIAL_BURN): True,
    # 质量→成本：良率影响成本
    (SignalType.YIELD_RATE, SignalType.UNIT_COST): True,
    (SignalType.REWORK_VOLUME, SignalType.UNIT_COST): True,
    # 设备→生产：可用率影响产出
    (SignalType.AVAILABILITY, SignalType.THROUGHPUT): True,
    (SignalType.MTBF, SignalType.AVAILABILITY): True,
    # 人员→生产：出勤影响产出
    (SignalType.ATTENDANCE, SignalType.THROUGHPUT): True,
    (SignalType.FATIGUE_LEVEL, SignalType.ATTENDANCE): True,
    # 物料→生产：缺料影响产出
    (SignalType.STOCKOUT_RISK_HOURS, SignalType.THROUGHPUT): True,
    # 任何→管理：异常触发升级
    (SignalType.YIELD_RATE, SignalType.ESCALATION_LEVEL): True,
    (SignalType.FAILURE_PROB, SignalType.ESCALATION_LEVEL): True,
    (SignalType.FATIGUE_LEVEL, SignalType.ESCALATION_LEVEL): True,
    (SignalType.STOCKOUT_RISK_HOURS, SignalType.ESCALATION_LEVEL): True,
}


def signals_compatible(source: SignalType, target: SignalType) -> bool:
    """检查两个信号类型是否可以建立传导关系
    
    规则：
    1. 同域内信号默认兼容
    2. 跨域需要在 _CROSS_DOMAIN_COMPATIBLE 中显式声明
    3. 未声明的跨域连接 = 不能串 → 拒绝
    """
    if source.domain == target.domain:
        return True
    return _CROSS_DOMAIN_COMPATIBLE.get((source, target), False)


@dataclass
class Signal:
    """一个具体的信号实例"""
    signal_type: SignalType
    value: float
    source_node_id: str = ""
    timestamp: float = 0.0  # 仿真时间戳（小时）
    metadata: dict = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return self.signal_type.unit

    @property
    def label(self) -> str:
        return self.signal_type.label

    def __repr__(self) -> str:
        return f"Signal({self.label}={self.value:.3f} {self.unit}, from={self.source_node_id})"
