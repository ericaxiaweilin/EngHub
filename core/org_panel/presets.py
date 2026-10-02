"""
预设组织模板 (Preset Organization Templates)
=============================================

电子厂 SMT 产线组织：6 个核心节点 + 7 条确定性逻辑链

拓扑：
[线长] ──速度→良率──→ [质量主管] ──返工量──→ [生产经理]
   │                       │
   ├──速度→应力──→ [设备主管] ──可用率──→ [生产经理]
   │
   ├──速度→疲劳──→ [HR主管] ──出勤──→ [生产经理]
   │
   └──产出→消耗──→ [仓储主管] ──缺料──→ [生产经理]
   
所有 transfer_fn 均为纯函数（确定性，无随机）。
"""

from __future__ import annotations

import math
from typing import Dict

from .signals import SignalType
from .node import OrgNode, ParameterDef, CapabilityDef, Constraint
from .chains import (
    LogicChain, ChainLink,
    linear, quadratic_degrade, power_stress,
    threshold_linear, exponential_decay,
)
from .engine import OrgSimEngine


# ==================== 传导函数（各节点的 transfer_fn） ====================

def line_leader_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """线长传导函数
    
    核心：速度是应力变量，不是线性乘数。
    - 产出 = 基础产能 × 速度 × 健康因子（受设备/人员反馈影响）
    - 良率退化、设备应力、人员疲劳由速度非线性驱动
    - 物料消耗是唯一线性维度
    """
    speed = params.get("speed", 1.0)
    shifts = params.get("shifts", 2.0)
    overtime_pct = params.get("overtime_pct", 0.0)

    # 基础产能（设计节拍：30件/天/班 at 1.0x）
    base_capacity_per_shift = 30.0
    # 反馈因子：设备可用率和出勤率从下游反馈来
    availability = inputs.get(SignalType.AVAILABILITY, 1.0)
    attendance = inputs.get(SignalType.ATTENDANCE, 1.0)
    health_factor = availability * attendance

    # 有效产能 = 基础 × 班次 × 速度 × 健康 × (1 + 加班)
    effective_speed = speed * (1.0 + overtime_pct * 0.5)  # 加班只给50%效率
    throughput = base_capacity_per_shift * shifts * effective_speed * health_factor

    # WIP：非瓶颈堆积（速度>1时WIP增长）
    wip = max(0, (speed - 1.0) * 50 * shifts)

    # 节拍：速度越快节拍越短（但有下限）
    cycle_time = max(0.1, 0.8 / speed)

    # 设备应力：speed^1.5 归一化
    if speed <= 1.0:
        stress = speed * 0.6
    else:
        stress = min(1.0, 0.6 + 0.4 * ((speed - 1.0) / 2.0) ** 1.5)

    # 故障概率：指数增长
    lam = 0.02
    failure_prob = 1.0 - math.exp(-lam * (speed ** 2.5) * 24)

    # 人员疲劳：阈值1.2后线性到2.0崩溃
    if speed <= 1.2:
        fatigue = 0.0
    else:
        fatigue = min(1.0, (speed - 1.2) / 0.8)

    # 加班时数
    overtime_hours = overtime_pct * 8 * shifts

    # 物料消耗（唯一线性）
    material_burn = throughput * 1.0  # 每件消耗1单位

    # 计划达成率（目标100件/天）
    target = params.get("target_output", 100.0)
    schedule_adh = min(1.5, throughput / target) if target > 0 else 1.0

    return {
        SignalType.THROUGHPUT: round(throughput, 2),
        SignalType.WIP_LEVEL: round(wip, 1),
        SignalType.CYCLE_TIME: round(cycle_time, 3),
        SignalType.SCHEDULE_ADHERENCE: round(schedule_adh, 3),
        SignalType.EQUIPMENT_STRESS: round(stress, 4),
        SignalType.FAILURE_PROB: round(failure_prob, 4),
        SignalType.FATIGUE_LEVEL: round(fatigue, 4),
        SignalType.OVERTIME_HOURS: round(overtime_hours, 1),
        SignalType.MATERIAL_BURN: round(material_burn, 1),
    }


def quality_supervisor_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """质量主管传导函数
    
    输入：设备应力（来自线长速度）→ 推导良率/缺陷/返工
    参数：抽检比例、SPC灵敏度、停线阈值
    """
    stress = inputs.get(SignalType.EQUIPMENT_STRESS, 0.6)
    throughput = inputs.get(SignalType.THROUGHPUT, 60.0)

    inspection_ratio = params.get("inspection_ratio", 0.2)
    spc_sensitivity = params.get("spc_sensitivity", 2.0)  # sigma
    stop_threshold = params.get("stop_threshold", 0.55)

    # 良率：从应力反推（应力越高良率越低）
    # stress 0.6 → yield 0.98, stress 1.0 → yield ~0.70
    if stress <= 0.6:
        yield_rate = 0.98
    else:
        yield_rate = max(0.1, 0.98 - 0.7 * (stress - 0.6) ** 1.8)

    # 缺陷率（ppm）
    defect_rate = (1.0 - yield_rate) * 1_000_000 / 1000  # 转为千分比 ppm

    # SPC状态：灵敏度越高越容易失控
    # stress > 0.8 且 sensitivity >= 2 → 失控
    if stress > 0.9 and spc_sensitivity >= 1.5:
        spc_status = 3.0  # 严重失控
    elif stress > 0.75 and spc_sensitivity >= 2.0:
        spc_status = 2.0  # 失控
    elif stress > 0.65:
        spc_status = 1.0  # 警告
    else:
        spc_status = 0.0  # 受控

    # 返工量 = 产出 × (1-良率) × 可返工比例(70%)
    rework_volume = throughput * (1.0 - yield_rate) * 0.7

    # 检验负荷 = 产出 × 抽检比例
    inspection_load = throughput * inspection_ratio

    # 升级：良率低于停线阈值 → 升级
    escalation = 0.0
    if yield_rate < stop_threshold:
        escalation = 3.0  # 危机
    elif yield_rate < 0.75:
        escalation = 2.0  # 紧急
    elif yield_rate < 0.90:
        escalation = 1.0  # 注意

    return {
        SignalType.YIELD_RATE: round(yield_rate, 4),
        SignalType.DEFECT_RATE: round(defect_rate, 1),
        SignalType.SPC_STATUS: spc_status,
        SignalType.REWORK_VOLUME: round(rework_volume, 2),
        SignalType.ESCALATION_LEVEL: escalation,
    }


def equipment_supervisor_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """设备主管传导函数
    
    输入：设备应力、故障概率（来自线长速度）
    参数：PM频率、维修响应时间、备件水平
    """
    stress = inputs.get(SignalType.EQUIPMENT_STRESS, 0.6)
    failure_prob = inputs.get(SignalType.FAILURE_PROB, 0.1)

    pm_frequency = params.get("pm_frequency", 30.0)   # 天
    repair_response = params.get("repair_response", 2.0)  # 小时
    spare_level = params.get("spare_level", 0.8)      # 0-1 备件充足度

    # MTBF：基础720h，应力越高越短，PM越频繁越长
    base_mtbf = 720.0
    pm_factor = min(1.5, pm_frequency / 30.0)  # PM越频繁（数值小）→因子小→MTBF短? 不对
    # PM频率=30天是标准，<30天更频繁→MTBF更长
    pm_factor = 30.0 / max(7.0, pm_frequency)  # 7天PM → factor=4.3(好), 90天PM → factor=0.33(差)
    stress_penalty = max(0.1, 1.0 - stress)
    mtbf = base_mtbf * stress_penalty * pm_factor

    # 可用率 = MTBF / (MTBF + MTTR)
    # MTTR = 维修响应时间 × (2 - 备件水平)（备件越全修越快）
    mttr = repair_response * (2.0 - spare_level)
    availability = mtbf / (mtbf + mttr) if (mtbf + mttr) > 0 else 0.0

    # 维修负荷（工时/天）：故障概率越高、响应越慢 → 负荷越大
    maintenance_load = failure_prob * 24 * (repair_response / 4.0) * (1.0 + stress)

    # 升级
    escalation = 0.0
    if availability < 0.7:
        escalation = 3.0
    elif availability < 0.85:
        escalation = 2.0
    elif stress > 0.9:
        escalation = 1.0

    return {
        SignalType.MTBF: round(mtbf, 1),
        SignalType.AVAILABILITY: round(availability, 4),
        SignalType.MAINTENANCE_LOAD: round(maintenance_load, 2),
        SignalType.ESCALATION_LEVEL: escalation,
    }


def hr_supervisor_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """HR主管传导函数
    
    输入：疲劳度（来自线长速度）
    参数：培训投入、轮班制度、加班限制
    """
    fatigue = inputs.get(SignalType.FATIGUE_LEVEL, 0.0)
    overtime_hours = inputs.get(SignalType.OVERTIME_HOURS, 0.0)

    training_budget = params.get("training_budget", 5000.0)  # 元/月
    rotation_policy = params.get("rotation_policy", 1.0)     # 1=无轮班 2=两班轮 3=三班轮
    overtime_limit = params.get("overtime_limit", 36.0)      # 月加班上限(h)

    # 出勤率：疲劳越高出勤越低，轮班缓解
    rotation_relief = 1.0 / rotation_policy  # 轮班越多疲劳缓解越大
    effective_fatigue = fatigue * rotation_relief
    attendance = max(0.5, 0.98 - effective_fatigue * 0.3)

    # 人力利用率：加班越多利用率越高（但有上限）
    overtime_ratio = min(1.0, overtime_hours / max(1, overtime_limit / 30))
    labor_util = min(1.5, 0.85 + overtime_ratio * 0.4)

    # 技能提升（培训投入的长期效果）：每5000元 → +0.1级
    skill_gain = training_budget / 50000.0  # 归一化

    # 升级：出勤太低或加班超限
    escalation = 0.0
    if attendance < 0.7:
        escalation = 3.0
    elif overtime_hours * 30 > overtime_limit:
        escalation = 2.0
    elif effective_fatigue > 0.5:
        escalation = 1.0

    return {
        SignalType.ATTENDANCE: round(attendance, 4),
        SignalType.LABOR_UTILIZATION: round(labor_util, 4),
        SignalType.ESCALATION_LEVEL: escalation,
    }


def warehouse_supervisor_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """仓储主管传导函数
    
    输入：物料消耗速率（来自线长产出）
    参数：安全库存、再订购点、供应商提前期
    """
    material_burn = inputs.get(SignalType.MATERIAL_BURN, 60.0)

    safety_stock = params.get("safety_stock", 500.0)     # 安全库存(单位)
    reorder_point = params.get("reorder_point", 200.0)   # 再订购点
    supplier_lead_days = params.get("supplier_lead_days", 3.0)  # 供应商提前期(天)
    current_stock = params.get("current_stock", 1000.0)  # 当前库存

    # 库存水位（假设持续消耗）
    daily_net = material_burn  # 简化：消耗=burn，补货在提前期后到
    stock_level = current_stock

    # 缺料风险（小时）
    if daily_net > 0:
        hours_to_stockout = current_stock / (daily_net / 24.0)
    else:
        hours_to_stockout = 9999.0

    # 是否需要紧急采购
    days_of_stock = current_stock / max(1, daily_net)
    if days_of_stock < supplier_lead_days:
        # 库存撑不到补货到达
        stockout_risk = max(0, hours_to_stockout - supplier_lead_days * 24)
    else:
        stockout_risk = hours_to_stockout

    # 升级
    escalation = 0.0
    if hours_to_stockout < 12:
        escalation = 3.0  # 12h内缺料
    elif hours_to_stockout < 48:
        escalation = 2.0  # 2天内缺料
    elif current_stock < reorder_point:
        escalation = 1.0  # 低于再订购点

    return {
        SignalType.STOCK_LEVEL: round(stock_level, 0),
        SignalType.STOCKOUT_RISK_HOURS: round(min(9999, stockout_risk), 1),
        SignalType.MATERIAL_BURN: round(material_burn, 1),
        SignalType.ESCALATION_LEVEL: escalation,
    }


def production_manager_transfer(inputs: Dict[SignalType, float], params: Dict[str, float]) -> Dict[SignalType, float]:
    """生产经理传导函数（聚合层）
    
    汇总所有下属的信号，计算综合KPI。
    """
    throughput = inputs.get(SignalType.THROUGHPUT, 60.0)
    yield_rate = inputs.get(SignalType.YIELD_RATE, 0.98)
    availability = inputs.get(SignalType.AVAILABILITY, 0.95)
    attendance = inputs.get(SignalType.ATTENDANCE, 0.95)
    rework_volume = inputs.get(SignalType.REWORK_VOLUME, 0.0)
    escalation_quality = inputs.get(SignalType.ESCALATION_LEVEL, 0.0)

    target_output = params.get("target_output", 100.0)
    base_cost = params.get("base_cost", 50.0)  # 元/件基础成本

    # OEE = 可用率 × 性能 × 良率
    performance = min(1.0, throughput / target_output) if target_output > 0 else 1.0
    oee = availability * performance * yield_rate

    # 单位成本 = 基础成本 / 良率 + 返工成本
    rework_cost_per_unit = rework_volume * 10.0 / max(1, throughput)  # 每件返工10元
    unit_cost = base_cost / max(0.1, yield_rate) + rework_cost_per_unit

    # 计划达成率
    schedule_adh = min(1.5, throughput / target_output) if target_output > 0 else 1.0

    # 综合升级（取所有下属最大）
    escalation = escalation_quality  # 从输入中已聚合

    return {
        SignalType.OEE: round(oee, 4),
        SignalType.UNIT_COST: round(unit_cost, 2),
        SignalType.SCHEDULE_ADHERENCE: round(schedule_adh, 4),
        SignalType.THROUGHPUT: round(throughput, 2),
        SignalType.ESCALATION_LEVEL: escalation,
    }


# ==================== 预设构建 ====================

def build_electronics_factory() -> OrgSimEngine:
    """构建电子厂 SMT 产线组织仿真
    
    6 节点 + 7 逻辑链
    """
    engine = OrgSimEngine()

    # ── 节点 1: 线长 (Level 1 - 现场) ──
    line_leader = OrgNode(
        node_id="line_leader",
        name="SMT线长",
        level=1,
        scope="SMT产线日常调度：速度/班次/加班/物料协调",
        transfer_fn=line_leader_transfer,
        parameters=[
            ParameterDef("speed", "产线速度", 1.0, 0.3, 3.0, 0.1, "x", "设计速度的倍率"),
            ParameterDef("shifts", "班次数", 2.0, 1.0, 3.0, 1.0, "班", "每日运行班次"),
            ParameterDef("overtime_pct", "加班比例", 0.0, 0.0, 0.5, 0.05, "%", "加班时长占正常工时比例"),
            ParameterDef("target_output", "目标产出", 100.0, 30.0, 300.0, 10.0, "件/天", "日产出目标"),
        ],
        capabilities=[
            CapabilityDef("调速", SignalType.THROUGHPUT, 1.0, 0, "直接调整产线运行速度"),
            CapabilityDef("排班", SignalType.THROUGHPUT, 0.8, 24, "调整班次（需提前1天通知）"),
            CapabilityDef("加班调度", SignalType.OVERTIME_HOURS, 1.0, 0, "安排加班"),
        ],
        constraints=[
            Constraint("人体极限", SignalType.FATIGUE_LEVEL, ">=", 1.0,
                       "shutdown", SignalType.THROUGHPUT, 0.0, "速度超2.0x→人员崩溃→停线"),
            Constraint("设备保护", SignalType.EQUIPMENT_STRESS, ">=", 0.95,
                       "shutdown", SignalType.THROUGHPUT, 0.0, "应力超95%→强制停机"),
        ],
    )

    # ── 节点 2: 质量主管 (Level 2 - 主管) ──
    quality_sup = OrgNode(
        node_id="quality_sup",
        name="质量主管",
        level=2,
        scope="产线质量管控：SPC监控/抽检/停线决策/返工调度",
        transfer_fn=quality_supervisor_transfer,
        parameters=[
            ParameterDef("inspection_ratio", "抽检比例", 0.2, 0.05, 1.0, 0.05, "%", "产出中抽检的比例"),
            ParameterDef("spc_sensitivity", "SPC灵敏度", 2.0, 1.0, 3.0, 0.5, "sigma", "控制限宽度"),
            ParameterDef("stop_threshold", "停线阈值", 0.55, 0.50, 0.80, 0.05, "%", "良率低于此值强制停线"),
        ],
        capabilities=[
            CapabilityDef("停线权", SignalType.THROUGHPUT, 0.0, 0, "良率低于阈值时强制停线"),
            CapabilityDef("SPC监控", SignalType.SPC_STATUS, 1.0, 0, "实时监控过程能力"),
            CapabilityDef("返工调度", SignalType.REWORK_VOLUME, 1.0, 2, "安排返工（2h延迟）"),
        ],
        constraints=[
            Constraint("质量地板", SignalType.YIELD_RATE, "<", 0.55,
                       "escalate", description="良率<55%→自动升级到经理"),
        ],
    )

    # ── 节点 3: 设备主管 (Level 2 - 主管) ──
    equipment_sup = OrgNode(
        node_id="equipment_sup",
        name="设备主管",
        level=2,
        scope="设备维保：PM计划/故障响应/备件管理/可用率保障",
        transfer_fn=equipment_supervisor_transfer,
        parameters=[
            ParameterDef("pm_frequency", "PM频率", 30.0, 7.0, 90.0, 7.0, "天", "预防性维护周期"),
            ParameterDef("repair_response", "维修响应", 2.0, 0.5, 8.0, 0.5, "小时", "故障到开始维修的时间"),
            ParameterDef("spare_level", "备件水平", 0.8, 0.3, 1.0, 0.1, "ratio", "关键备件充足度"),
        ],
        capabilities=[
            CapabilityDef("PM计划", SignalType.MTBF, 1.2, 168, "预防维护（效果延迟1周）"),
            CapabilityDef("紧急维修", SignalType.AVAILABILITY, 1.0, 4, "故障后抢修（4h）"),
            CapabilityDef("备件采购", SignalType.MAINTENANCE_LOAD, 0.8, 72, "备件到位（3天）"),
        ],
        constraints=[
            Constraint("停机保护", SignalType.AVAILABILITY, "<", 0.5,
                       "escalate", description="可用率<50%→升级到经理"),
        ],
    )

    # ── 节点 4: HR主管 (Level 2 - 主管) ──
    hr_sup = OrgNode(
        node_id="hr_sup",
        name="HR主管",
        level=2,
        scope="人力管理：排班/培训/加班管控/出勤保障",
        transfer_fn=hr_supervisor_transfer,
        parameters=[
            ParameterDef("training_budget", "培训投入", 5000.0, 0.0, 50000.0, 1000.0, "元/月", "月度培训预算"),
            ParameterDef("rotation_policy", "轮班制度", 1.0, 1.0, 3.0, 1.0, "班", "1=固定 2=两班轮 3=三班轮"),
            ParameterDef("overtime_limit", "加班上限", 36.0, 0.0, 60.0, 4.0, "h/月", "月度加班上限"),
        ],
        capabilities=[
            CapabilityDef("培训", SignalType.ATTENDANCE, 0.1, 720, "培训提升技能（30天见效）"),
            CapabilityDef("轮班调整", SignalType.FATIGUE_LEVEL, -0.3, 24, "轮班缓解疲劳（1天生效）"),
            CapabilityDef("招聘", SignalType.LABOR_UTILIZATION, 0.5, 2160, "新人到岗（90天）"),
        ],
        constraints=[
            Constraint("劳动法", SignalType.OVERTIME_HOURS, ">", 3.0,
                       "clamp_output", SignalType.OVERTIME_HOURS, 3.0, "日加班不超3h（劳动法）"),
        ],
    )

    # ── 节点 5: 仓储主管 (Level 2 - 主管) ──
    warehouse_sup = OrgNode(
        node_id="warehouse_sup",
        name="仓储主管",
        level=2,
        scope="物料管理：库存控制/补货/缺料预警/供应商协调",
        transfer_fn=warehouse_supervisor_transfer,
        parameters=[
            ParameterDef("safety_stock", "安全库存", 500.0, 100.0, 2000.0, 100.0, "单位", "最低库存水位"),
            ParameterDef("reorder_point", "再订购点", 200.0, 50.0, 1000.0, 50.0, "单位", "触发补货的库存水位"),
            ParameterDef("supplier_lead_days", "供应商提前期", 3.0, 1.0, 14.0, 1.0, "天", "下单到到货天数"),
            ParameterDef("current_stock", "当前库存", 1000.0, 0.0, 5000.0, 100.0, "单位", "现有库存量"),
        ],
        capabilities=[
            CapabilityDef("紧急采购", SignalType.STOCKOUT_RISK_HOURS, 1.0, 24, "加急补货（1天）"),
            CapabilityDef("库存调配", SignalType.STOCK_LEVEL, 1.0, 4, "从其他仓调货（4h）"),
        ],
        constraints=[
            Constraint("缺料停线", SignalType.STOCKOUT_RISK_HOURS, "<", 4.0,
                       "escalate", description="4h内缺料→升级到经理"),
        ],
    )

    # ── 节点 6: 生产经理 (Level 3 - 经理) ──
    prod_manager = OrgNode(
        node_id="prod_manager",
        name="生产经理",
        level=3,
        scope="全产线统筹：KPI监控/资源调配/异常升级决策/成本管控",
        transfer_fn=production_manager_transfer,
        parameters=[
            ParameterDef("target_output", "目标产出", 100.0, 30.0, 300.0, 10.0, "件/天", "月度目标分解到日"),
            ParameterDef("base_cost", "基础成本", 50.0, 20.0, 200.0, 5.0, "元/件", "标准制造成本"),
        ],
        capabilities=[
            CapabilityDef("资源调配", SignalType.THROUGHPUT, 1.2, 8, "跨线调配资源（8h生效）"),
            CapabilityDef("预算审批", SignalType.UNIT_COST, 0.9, 0, "审批降本方案"),
            CapabilityDef("升级决策", SignalType.ESCALATION_LEVEL, 1.0, 0, "接收并处理升级"),
        ],
        constraints=[
            Constraint("OEE底线", SignalType.OEE, "<", 0.4,
                       "escalate", description="OEE<40%→升级到厂长"),
        ],
    )

    # 注册所有节点
    for node in [line_leader, quality_sup, equipment_sup, hr_sup, warehouse_sup, prod_manager]:
        engine.add_node(node)

    # ── 逻辑链 ──

    # 链1: 速度-质量链（线长→质量主管）
    chain_speed_quality = LogicChain("chain_speed_quality", "速度-质量链")
    chain_speed_quality.add_link(ChainLink(
        "line_leader", SignalType.EQUIPMENT_STRESS,
        "quality_sup", SignalType.EQUIPMENT_STRESS,
        linear(1.0), label="应力→良率推导"
    ))
    chain_speed_quality.add_link(ChainLink(
        "line_leader", SignalType.THROUGHPUT,
        "quality_sup", SignalType.THROUGHPUT,
        linear(1.0), label="产出→返工基数"
    ))

    # 链2: 速度-设备链（线长→设备主管）
    chain_speed_equipment = LogicChain("chain_speed_equipment", "速度-设备链")
    chain_speed_equipment.add_link(ChainLink(
        "line_leader", SignalType.EQUIPMENT_STRESS,
        "equipment_sup", SignalType.EQUIPMENT_STRESS,
        linear(1.0), label="应力传导"
    ))
    chain_speed_equipment.add_link(ChainLink(
        "line_leader", SignalType.FAILURE_PROB,
        "equipment_sup", SignalType.FAILURE_PROB,
        linear(1.0), label="故障概率传导"
    ))

    # 链3: 速度-人员链（线长→HR主管）
    chain_speed_workforce = LogicChain("chain_speed_workforce", "速度-人员链")
    chain_speed_workforce.add_link(ChainLink(
        "line_leader", SignalType.FATIGUE_LEVEL,
        "hr_sup", SignalType.FATIGUE_LEVEL,
        linear(1.0), label="疲劳传导"
    ))
    chain_speed_workforce.add_link(ChainLink(
        "line_leader", SignalType.OVERTIME_HOURS,
        "hr_sup", SignalType.OVERTIME_HOURS,
        linear(1.0), label="加班传导"
    ))

    # 链4: 产出-物料链（线长→仓储主管）
    chain_output_material = LogicChain("chain_output_material", "产出-物料链")
    chain_output_material.add_link(ChainLink(
        "line_leader", SignalType.MATERIAL_BURN,
        "warehouse_sup", SignalType.MATERIAL_BURN,
        linear(1.0), label="消耗速率传导"
    ))

    # 链5: 设备-产能反馈（设备主管→线长）
    chain_equip_feedback = LogicChain("chain_equip_feedback", "设备-产能反馈")
    chain_equip_feedback.add_link(ChainLink(
        "equipment_sup", SignalType.AVAILABILITY,
        "line_leader", SignalType.AVAILABILITY,
        linear(1.0), label="可用率反馈→有效产能"
    ))

    # 链6: 人员-产能反馈（HR主管→线长）
    chain_hr_feedback = LogicChain("chain_hr_feedback", "人员-产能反馈")
    chain_hr_feedback.add_link(ChainLink(
        "hr_sup", SignalType.ATTENDANCE,
        "line_leader", SignalType.ATTENDANCE,
        linear(1.0), label="出勤率反馈→有效产能"
    ))

    # 链7: 聚合链（所有主管→生产经理）
    chain_aggregate = LogicChain("chain_aggregate", "KPI聚合链")
    chain_aggregate.add_link(ChainLink(
        "line_leader", SignalType.THROUGHPUT,
        "prod_manager", SignalType.THROUGHPUT,
        linear(1.0), label="产出汇总"
    ))
    chain_aggregate.add_link(ChainLink(
        "quality_sup", SignalType.YIELD_RATE,
        "prod_manager", SignalType.YIELD_RATE,
        linear(1.0), label="良率汇总"
    ))
    chain_aggregate.add_link(ChainLink(
        "quality_sup", SignalType.REWORK_VOLUME,
        "prod_manager", SignalType.REWORK_VOLUME,
        linear(1.0), label="返工汇总"
    ))
    chain_aggregate.add_link(ChainLink(
        "equipment_sup", SignalType.AVAILABILITY,
        "prod_manager", SignalType.AVAILABILITY,
        linear(1.0), label="可用率汇总"
    ))
    chain_aggregate.add_link(ChainLink(
        "hr_sup", SignalType.ATTENDANCE,
        "prod_manager", SignalType.ATTENDANCE,
        linear(1.0), label="出勤汇总"
    ))
    chain_aggregate.add_link(ChainLink(
        "quality_sup", SignalType.ESCALATION_LEVEL,
        "prod_manager", SignalType.ESCALATION_LEVEL,
        linear(1.0), label="升级汇总"
    ))

    # 注册所有链
    for chain in [
        chain_speed_quality, chain_speed_equipment, chain_speed_workforce,
        chain_output_material, chain_equip_feedback, chain_hr_feedback,
        chain_aggregate,
    ]:
        engine.connect(chain)

    return engine
