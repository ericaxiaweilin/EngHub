"""
Physics core for step-based fatigue and energy estimation.

读数口径（不要靠猜）：这两个数是下面这些项算出来的，没列进去的输入**不影响结果**。
`describe_model()` 把这套口径原样端出去，界面与助手答复要引用它，别各自解释。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import PhysicalInput, PhysicalSnapshot

# 疲劳：每步累加，超过阈值的负重/温度各按一次倍率放大，姿势与连续工时按线性项相加
STEP_FATIGUE_PER_STEP = 0.001
LOAD_FATIGUE_THRESHOLD_KG = 15.0
LOAD_FATIGUE_DIVISOR_KG = 10.0
HEAT_FATIGUE_MULTIPLIER = 1.3
POSTURE_PENALTY_START_DEG = 45.0
POSTURE_PENALTY_SCALE_DEG = 90.0
CONTINUOUS_PENALTY_FULL_MINUTES = 480.0
# 高温阈值默认值只是兜底：引擎会把法规包里的 heat_allowance.temperature_c_gt 传进来，
# 同一个法定温度线不该在物理层和规则层各写一遍
DEFAULT_HEAT_THRESHOLD_C = 35.0

# 能耗：只由步数、负重、坡度与地形系数决定
STEP_ENERGY_KCAL = 0.04
LOAD_ENERGY_KCAL_PER_KG = 0.08
INCLINE_ENERGY_KCAL_PER_PERCENT = 0.02
TERRAIN_MULTIPLIERS = {"flat": 1.0, "slope": 1.15, "stairs": 1.3, "uneven": 1.1}

# 这些输入被接口接受、也照原样存进快照与审计，但不进上面任何一项计算。
# 明写出来是因为"传了参数却没反应"必须看得见，不能让人以为温度/湿度已经改了能耗。
INERT_INPUTS = (
    "environment.humidity_percent", "environment.noise_db", "environment.dust_mg_m3",
    "distance_meters", "time_step_minutes", "x_position_m", "y_position_m",
    "work_context.action_type", "work_context.skill_level",
    "work_context.ppe_status", "work_context.machine_risk_level",
)


class PhysicsCore:
    VERSION = "2.1.0"

    def simulate_step(self, physical_input: PhysicalInput, *,
                      heat_threshold_c: Optional[float] = None) -> PhysicalSnapshot:
        threshold = (DEFAULT_HEAT_THRESHOLD_C if heat_threshold_c is None
                     else float(heat_threshold_c))
        fatigue_score = self._calculate_fatigue(physical_input, heat_threshold_c=threshold)
        energy_kcal = self._calculate_energy(physical_input)
        context = physical_input.work_context

        return PhysicalSnapshot(
            timestamp=physical_input.timestamp,
            worker_ref=context.worker_ref,
            shift_id=context.shift_id,
            task_type=context.task_type,
            zone_id=context.zone_id,
            action_type=context.action_type,
            x_position_m=physical_input.x_position_m,
            y_position_m=physical_input.y_position_m,
            distance_meters=physical_input.distance_meters,
            step_count=physical_input.step_count,
            load_weight_kg=physical_input.load_weight_kg,
            posture_angle_deg=physical_input.posture_angle_deg,
            continuous_work_minutes=physical_input.continuous_work_minutes,
            fatigue_score=round(fatigue_score, 4),
            energy_kcal=round(energy_kcal, 2),
            environment=physical_input.environment,
            skill_level=context.skill_level,
            ppe_status=context.ppe_status,
            machine_risk_level=context.machine_risk_level,
        )

    def _calculate_fatigue(self, physical_input: PhysicalInput, *,
                           heat_threshold_c: float = DEFAULT_HEAT_THRESHOLD_C) -> float:
        steps = physical_input.step_count
        load = physical_input.load_weight_kg
        temp = physical_input.environment.temperature_c

        fatigue = steps * STEP_FATIGUE_PER_STEP
        if load > LOAD_FATIGUE_THRESHOLD_KG:
            fatigue *= 1.0 + ((load - LOAD_FATIGUE_THRESHOLD_KG) / LOAD_FATIGUE_DIVISOR_KG)
        # 阶跃项，不是连续函数：阈值下 0 反应，阈值上整个基础项一次乘 1.3
        if temp > heat_threshold_c:
            fatigue *= HEAT_FATIGUE_MULTIPLIER

        posture_penalty = max(0.0, (physical_input.posture_angle_deg - POSTURE_PENALTY_START_DEG)
                              / POSTURE_PENALTY_SCALE_DEG)
        continuous_penalty = physical_input.continuous_work_minutes / CONTINUOUS_PENALTY_FULL_MINUTES

        return fatigue + posture_penalty + continuous_penalty

    def _calculate_energy(self, physical_input: PhysicalInput) -> float:
        terrain_multiplier = TERRAIN_MULTIPLIERS[physical_input.environment.terrain.value]

        step_energy = physical_input.step_count * STEP_ENERGY_KCAL
        load_energy = physical_input.load_weight_kg * LOAD_ENERGY_KCAL_PER_KG
        incline_energy = (physical_input.environment.floor_incline_percent
                          * INCLINE_ENERGY_KCAL_PER_PERCENT)

        return (step_energy + load_energy + incline_energy) * terrain_multiplier

    @staticmethod
    def describe_model(*, heat_threshold_c: Optional[float] = None,
                       continuous_limit_minutes: Optional[int] = None) -> Dict[str, Any]:
        """把"哪个数由什么决定、哪些参数其实没反应"端出去（供接口/界面/答复引用）。"""
        threshold = (DEFAULT_HEAT_THRESHOLD_C if heat_threshold_c is None
                     else float(heat_threshold_c))
        return {
            "physics_version": PhysicsCore.VERSION,
            "fatigue_score": {
                "formula": (f"步数×{STEP_FATIGUE_PER_STEP} →（负重>{LOAD_FATIGUE_THRESHOLD_KG}kg 时乘 "
                            f"1+(负重-{LOAD_FATIGUE_THRESHOLD_KG})/10）→（温度>{threshold:g}℃ 时乘 "
                            f"{HEAT_FATIGUE_MULTIPLIER}）+ max(0,(姿势-{POSTURE_PENALTY_START_DEG:g})/"
                            f"{POSTURE_PENALTY_SCALE_DEG:g}) + 连续分钟/{CONTINUOUS_PENALTY_FULL_MINUTES:g}"),
                "driven_by": ["step_count", "load_weight_kg", "environment.temperature_c",
                              "posture_angle_deg", "continuous_work_minutes"],
                "heat_is_a_step_not_a_curve": True,
                "heat_threshold_c": threshold,
            },
            "energy_kcal": {
                "formula": (f"(步数×{STEP_ENERGY_KCAL} + 负重×{LOAD_ENERGY_KCAL_PER_KG} + "
                            f"坡度%×{INCLINE_ENERGY_KCAL_PER_PERCENT}) × 地形系数"
                            f"（{', '.join(f'{k}={v}' for k, v in TERRAIN_MULTIPLIERS.items())}）"),
                "driven_by": ["step_count", "load_weight_kg", "environment.floor_incline_percent",
                              "environment.terrain"],
                "temperature_changes_it": False,
                "humidity_changes_it": False,
            },
            "inert_inputs": list(INERT_INPUTS),
            "inert_note": ("这些字段接口收、快照存、审计里能查到，但**不进**疲劳与能耗的任何一项；"
                           "改了它们读数不变不是 bug 复现，是模型本来就没这一段。"
                           "要让湿度/噪声影响判定，得先有法规或厂内阈值依据，再进规则包，"
                           "不由物理层自己编系数"),
            "rule_thresholds": {
                "heat_allowance_triggers_above_c": threshold,
                "continuous_work_limit_minutes": continuous_limit_minutes,
                "operator_used_by_rules": "严格大于（>），所以 240 分钟恰好等于上限不算违规",
            },
        }
