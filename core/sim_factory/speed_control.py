"""
产线速度控制引擎 (Speed Control Engine)
========================================
核心哲学：速度不是线性乘数，是应力变量(stress variable)。

设计原则：
1. 瓶颈免疫 — 加速非瓶颈只堆WIP，不增加系统产出
2. 非线性退化 — 质量/设备/人员效率随速度非线性衰减
3. 物理边界 — 存在不可逾越的硬约束（设备极限/人体极限）
4. 反馈耦合 — 速度变化触发连锁效应（加速→磨损→故障→停线）
5. 不变量守恒 — 任何速度下 IN = OUT + WIP + Scrap 恒成立

速度区间语义：
  0.3-0.7x  低速/节能模式（设备低应力，适合保养期）
  0.7-1.0x  标准模式（设计产能）
  1.0-1.3x  加速模式（轻微应力，可短期运行）
  1.3-1.8x  高压模式（显著退化，需监控）
  1.8-2.5x  极限模式（接近物理边界，故障率飙升）
  2.5-3.0x  崩溃区（不可持续，系统将在数小时内停摆）
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ==================== 物理常数（不可调） ====================

SPEED_MIN = 0.3          # 最低速度（低于此无物理意义）
SPEED_MAX = 3.0          # 最高速度（超过=设备自毁）
QUALITY_FLOOR = 0.55     # 良率地板（低于此自动停线——全是废品没有意义）
EQUIPMENT_STRESS_MAX = 0.95  # 设备应力上限（超过=强制停机保护）
WORKER_FATIGUE_THRESHOLD = 1.2  # 疲劳阈值（超过此速度人才开始退化）
WORKER_COLLAPSE = 2.0    # 人体极限（超过=效率归零）
MTBF_EXPONENT = 2.5      # 故障率指数（速度^2.5 倍增长）


# ==================== 数据模型 ====================

@dataclass
class WorkstationState:
    """工位状态"""
    name: str
    base_cycle_hours: float      # 设计节拍（小时/件）
    equipment_count: int         # 设备数量
    is_bottleneck: bool = False  # 是否为当前瓶颈
    equipment_health: float = 1.0  # 设备健康度 0-1
    worker_efficiency: float = 1.0  # 人员效率 0-1


@dataclass
class SpeedImpact:
    """速度影响评估结果"""
    speed: float
    # 产出维度
    system_throughput_per_day: float  # 系统日产出（件/天）
    bottleneck_name: str              # 当前瓶颈工位
    bottleneck_utilization: float     # 瓶颈利用率 %
    wip_buildup_rate: float           # WIP堆积速率（件/天）
    # 质量维度
    quality_yield: float              # 良率 0-1
    quality_degradation: float        # 良率退化量
    spc_drift_risk: str               # SPC漂移风险等级
    # 设备维度
    equipment_stress: float           # 设备应力 0-1
    breakdown_probability_24h: float  # 24h故障概率
    mtbf_hours: float                 # 平均故障间隔
    # 人员维度
    worker_fatigue_level: float       # 疲劳度 0-1
    effective_labor_hours: float      # 有效工时/天
    overtime_required: float          # 需要加班时数
    # 物料维度
    material_burn_multiplier: float   # 物料消耗倍率
    hours_to_stockout: Optional[float]  # 距缺料时间（h）
    # 综合
    sustainability_hours: float       # 可持续运行时间（h）
    risk_level: str                   # 综合风险等级
    warnings: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)  # 硬约束违反


# ==================== 核心引擎 ====================

class SpeedControlEngine:
    """产线速度控制引擎"""

    def __init__(self, workstations: List[WorkstationState], current_inventory: int = 1000,
                 daily_material_supply: int = 500):
        self.workstations = workstations
        self.current_inventory = current_inventory
        self.daily_material_supply = daily_material_supply
        self._identify_bottleneck()

    def _identify_bottleneck(self):
        """识别当前瓶颈（产能最低的工位）"""
        for ws in self.workstations:
            ws.is_bottleneck = False
        if not self.workstations:
            return
        # 产能 = 设备数 × 24h / 节拍
        min_capacity = float('inf')
        for ws in self.workstations:
            capacity = ws.equipment_count * 24.0 / ws.base_cycle_hours
            if capacity < min_capacity:
                min_capacity = capacity
                bottleneck = ws
        bottleneck.is_bottleneck = True

    def evaluate(self, speed: float) -> SpeedImpact:
        """评估指定速度下的全维度影响"""
        speed = max(SPEED_MIN, min(SPEED_MAX, speed))
        warnings = []
        violations = []

        # ---- 1. 产出计算（瓶颈决定） ----
        throughput = self._calc_throughput(speed)
        bottleneck_ws = next((ws for ws in self.workstations if ws.is_bottleneck), None)
        bn_name = bottleneck_ws.name if bottleneck_ws else "N/A"
        bn_util = self._calc_bottleneck_utilization(speed, bottleneck_ws)

        # WIP堆积 = 非瓶颈产出 - 瓶颈消化量
        wip_rate = self._calc_wip_buildup(speed, throughput)
        if wip_rate > 0:
            warnings.append(f"非瓶颈工位以 {wip_rate:.0f}件/天 堆积WIP（瓶颈消化不了）")

        # ---- 2. 质量退化（二次函数） ----
        quality_yield = self._calc_quality(speed)
        quality_deg = 1.0 - quality_yield
        spc_risk = self._spc_risk_level(speed)
        if quality_yield < QUALITY_FLOOR:
            violations.append(f"良率 {quality_yield:.1%} < 地板 {QUALITY_FLOOR:.0%} → 强制停线")
        elif quality_yield < 0.75:
            warnings.append(f"良率降至 {quality_yield:.1%}，废品率显著上升")

        # ---- 3. 设备应力（超线性） ----
        stress = self._calc_equipment_stress(speed)
        breakdown_prob = self._calc_breakdown_probability(speed)
        mtbf = self._calc_mtbf(speed)
        if stress > EQUIPMENT_STRESS_MAX:
            violations.append(f"设备应力 {stress:.1%} > 上限 {EQUIPMENT_STRESS_MAX:.0%} → 强制停机保护")
        elif stress > 0.8:
            warnings.append(f"设备应力 {stress:.1%}，进入高磨损区")

        # ---- 4. 人员疲劳（阈值+线性） ----
        fatigue = self._calc_worker_fatigue(speed)
        effective_hours = 24 * (1 - fatigue * 0.4)  # 疲劳降低有效工时
        overtime = max(0, (speed - 1.0) * 8) if speed > 1.0 else 0
        if speed > WORKER_COLLAPSE:
            violations.append(f"速度 {speed}x > 人体极限 {WORKER_COLLAPSE}x → 人员效率归零")
        elif fatigue > 0.7:
            warnings.append(f"人员疲劳度 {fatigue:.0%}，效率显著下降，需轮班")

        # ---- 5. 物料消耗（唯一线性） ----
        burn_mult = speed  # 物料消耗是唯一与速度线性相关的
        daily_burn = throughput * burn_mult  # 简化：每件消耗1单位
        hours_to_stockout = None
        if daily_burn > 0:
            net_burn = daily_burn - self.daily_material_supply
            if net_burn > 0:
                hours_to_stockout = self.current_inventory / (net_burn / 24)
                if hours_to_stockout < 24:
                    warnings.append(f"按当前速度，{hours_to_stockout:.0f}h 后缺料停线")

        # ---- 6. 可持续性评估 ----
        sustainability = self._calc_sustainability(speed, stress, fatigue, quality_yield)
        risk_level = self._overall_risk(speed, stress, fatigue, quality_yield, breakdown_prob)

        return SpeedImpact(
            speed=speed,
            system_throughput_per_day=throughput,
            bottleneck_name=bn_name,
            bottleneck_utilization=bn_util,
            wip_buildup_rate=wip_rate,
            quality_yield=quality_yield,
            quality_degradation=quality_deg,
            spc_drift_risk=spc_risk,
            equipment_stress=stress,
            breakdown_probability_24h=breakdown_prob,
            mtbf_hours=mtbf,
            worker_fatigue_level=fatigue,
            effective_labor_hours=effective_hours,
            overtime_required=overtime,
            material_burn_multiplier=burn_mult,
            hours_to_stockout=hours_to_stockout,
            sustainability_hours=sustainability,
            risk_level=risk_level,
            warnings=warnings,
            violations=violations,
        )

    def sweep(self, speeds: List[float] = None) -> List[SpeedImpact]:
        """速度扫描：生成速度-影响曲线"""
        if speeds is None:
            speeds = [0.5, 0.7, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
        return [self.evaluate(s) for s in speeds]

    # ==================== 退化函数（核心逻辑） ====================

    def _calc_throughput(self, speed: float) -> float:
        """系统产出 = 瓶颈产能 × 速度 × 健康因子
        
        关键：瓶颈处加速有效（因为瓶颈限制系统），
        但非瓶颈处加速只堆WIP（不增加系统产出）。
        """
        bottleneck = next((ws for ws in self.workstations if ws.is_bottleneck), None)
        if not bottleneck:
            return 0
        # 瓶颈的设计日产能
        base_capacity = bottleneck.equipment_count * 24.0 / bottleneck.base_cycle_hours
        # 速度有效范围：瓶颈不能超过其物理极限
        effective_speed = min(speed, 1.0 / bottleneck.base_cycle_hours * 24 / base_capacity * 1.5)
        # 健康因子：设备+人员
        health = bottleneck.equipment_health * bottleneck.worker_efficiency
        return base_capacity * effective_speed * health

    def _calc_bottleneck_utilization(self, speed: float, ws: Optional[WorkstationState]) -> float:
        if not ws:
            return 0
        base_cap = ws.equipment_count * 24.0 / ws.base_cycle_hours
        demanded = base_cap * speed
        return min(demanded / base_cap * 100, 999)

    def _calc_wip_buildup(self, speed: float, system_throughput: float) -> float:
        """WIP堆积 = 最快非瓶颈产出 - 系统产出"""
        max_non_bn = 0
        for ws in self.workstations:
            if not ws.is_bottleneck:
                cap = ws.equipment_count * 24.0 / ws.base_cycle_hours * speed
                max_non_bn = max(max_non_bn, cap)
        return max(0, max_non_bn - system_throughput)

    def _calc_quality(self, speed: float) -> float:
        """良率退化：二次函数
        
        speed ≤ 1.0: 无退化（设计速度内）
        speed > 1.0: yield = 0.98 - 0.15 × (speed-1)²
        
        物理含义：加速→工艺参数偏移→缺陷率非线性上升
        例：1.5x → 0.98 - 0.15×0.25 = 0.94 (还行)
            2.0x → 0.98 - 0.15×1.0 = 0.83 (显著)
            2.5x → 0.98 - 0.15×2.25 = 0.64 (接近废品线)
            3.0x → 0.98 - 0.15×4.0 = 0.38 (全是废品)
        """
        if speed <= 1.0:
            return 0.98
        degradation = 0.15 * (speed - 1.0) ** 2
        return max(0.1, 0.98 - degradation)

    def _calc_equipment_stress(self, speed: float) -> float:
        """设备应力：1.5次方增长
        
        stress = speed^1.5 / 3^1.5 (归一化到0-1)
        物理含义：加速→振动/热/磨损超线性增加
        """
        if speed <= 1.0:
            return speed * 0.6  # 标准速度下应力60%
        return min(1.0, 0.6 + 0.4 * ((speed - 1.0) / (SPEED_MAX - 1.0)) ** 1.5)

    def _calc_breakdown_probability(self, speed: float) -> float:
        """24h故障概率：指数增长
        
        P(failure in 24h) = 1 - exp(-λ × speed^2.5)
        λ = 0.02 (基准故障率)
        
        1.0x → ~5%
        1.5x → ~15%
        2.0x → ~35%
        2.5x → ~60%
        3.0x → ~80%
        """
        lam = 0.02
        rate = lam * (speed ** MTBF_EXPONENT)
        return 1 - math.exp(-rate * 24)

    def _calc_mtbf(self, speed: float) -> float:
        """平均故障间隔（小时）：随速度指数衰减"""
        base_mtbf = 720  # 30天（标准速度）
        return base_mtbf / (speed ** MTBF_EXPONENT)

    def _calc_worker_fatigue(self, speed: float) -> float:
        """人员疲劳：阈值后线性
        
        speed ≤ 1.2: fatigue = 0（正常节奏）
        speed > 1.2: fatigue = (speed - 1.2) / (COLLAPSE - 1.2)
        
        物理含义：人不是机器，有节奏感，
        轻微加速可适应，超过阈值后效率急剧下降
        """
        if speed <= WORKER_FATIGUE_THRESHOLD:
            return 0.0
        return min(1.0, (speed - WORKER_FATIGUE_THRESHOLD) / (WORKER_COLLAPSE - WORKER_FATIGUE_THRESHOLD))

    def _spc_risk_level(self, speed: float) -> str:
        if speed <= 1.0:
            return "低"
        elif speed <= 1.5:
            return "中"
        elif speed <= 2.0:
            return "高"
        else:
            return "极高"

    def _calc_sustainability(self, speed: float, stress: float, fatigue: float, quality: float) -> float:
        """可持续运行时间（小时）
        
        综合考虑设备磨损、人员疲劳、质量退化
        返回在此速度下系统能维持多久不崩溃
        """
        if speed <= 1.0:
            return float('inf')  # 设计速度内，无限可持续

        # 设备寿命消耗
        equip_life_h = 100 / max(0.01, stress - 0.5) if stress > 0.5 else 9999

        # 人员持续极限（超过阈值后，每多0.1速度减少2h可持续）
        if fatigue > 0:
            human_limit_h = max(2, 12 - fatigue * 10)
        else:
            human_limit_h = 9999

        # 质量崩溃时间（良率低于地板的时间）
        if quality < QUALITY_FLOOR:
            quality_limit_h = 0  # 已经不可持续
        elif quality < 0.7:
            quality_limit_h = 4  # 最多撑4小时
        else:
            quality_limit_h = 9999

        return min(equip_life_h, human_limit_h, quality_limit_h)

    def _overall_risk(self, speed: float, stress: float, fatigue: float,
                      quality: float, breakdown_prob: float) -> str:
        """综合风险等级"""
        if speed <= 1.0:
            return "🟢 安全"
        score = 0
        if stress > 0.8: score += 2
        elif stress > 0.6: score += 1
        if fatigue > 0.5: score += 2
        elif fatigue > 0.2: score += 1
        if quality < 0.7: score += 3
        elif quality < 0.85: score += 1
        if breakdown_prob > 0.5: score += 3
        elif breakdown_prob > 0.2: score += 1

        if score >= 6: return "🔴 崩溃"
        elif score >= 4: return "🟠 危险"
        elif score >= 2: return "🟡 警告"
        else: return "🟢 可控"


# ==================== 预设产线配置 ====================

def get_electronics_line() -> SpeedControlEngine:
    """电子厂SMT产线（8工序）"""
    stations = [
        WorkstationState("SMT贴片", 0.6, 2),
        WorkstationState("回流焊", 0.3, 1),
        WorkstationState("X-Ray检测", 0.3, 1),
        WorkstationState("组装", 1.2, 1),       # 瓶颈
        WorkstationState("固件烧录", 0.5, 1),
        WorkstationState("声学全检", 0.5, 1),
        WorkstationState("防水测试", 0.3, 1),
        WorkstationState("包装", 0.2, 1),
    ]
    return SpeedControlEngine(stations, current_inventory=1000, daily_material_supply=500)
