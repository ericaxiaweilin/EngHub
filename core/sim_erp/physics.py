"""
Physics core for step-based fatigue and energy estimation.

读数口径（不要靠猜）：这两个数是下面这些项算出来的，没列进去的输入**不影响结果**。
`describe_model()` 把这套口径原样端出去，界面与助手答复要引用它，别各自解释。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import PhysicalInput, PhysicalSnapshot

# 疲劳：每步累加，超过阈值的负重按倍率放大，高温按应变系数放大，姿势与连续工时按线性项相加
STEP_FATIGUE_PER_STEP = 0.001
LOAD_FATIGUE_THRESHOLD_KG = 15.0
LOAD_FATIGUE_DIVISOR_KG = 10.0
HEAT_FATIGUE_MULTIPLIER = 1.3
POSTURE_PENALTY_START_DEG = 45.0
POSTURE_PENALTY_SCALE_DEG = 90.0
CONTINUOUS_PENALTY_FULL_MINUTES = 480.0
# 兜底用的老阶跃阈值：只有拿不到热应力规则包时才走这条路（见 _calculate_fatigue）
DEFAULT_HEAT_THRESHOLD_C = 35.0

# 能耗：只由步数、负重、坡度与地形系数决定（热应激的代价不在这里，见 thermal 说明）
STEP_ENERGY_KCAL = 0.04
LOAD_ENERGY_KCAL_PER_KG = 0.08
INCLINE_ENERGY_KCAL_PER_PERCENT = 0.02
TERRAIN_MULTIPLIERS = {"flat": 1.0, "slope": 1.15, "stairs": 1.3, "uneven": 1.1}

# 这些输入被接口接受、也照原样存进快照与审计，但不进上面任何一项计算。
# 明写出来是因为"传了参数却没反应"必须看得见，不能让人以为参数已经生效。
INERT_INPUTS = (
    "environment.noise_db", "environment.dust_mg_m3",
    "distance_meters", "time_step_minutes", "x_position_m", "y_position_m",
    "work_context.action_type", "work_context.skill_level",
    "work_context.ppe_status", "work_context.machine_risk_level",
)


class PhysicsCore:
    VERSION = "2.2.0"

    def simulate_step(self, physical_input: PhysicalInput, *,
                      heat_threshold_c: Optional[float] = None,
                      thermal: Optional[Dict[str, Any]] = None) -> PhysicalSnapshot:
        threshold = (DEFAULT_HEAT_THRESHOLD_C if heat_threshold_c is None
                     else float(heat_threshold_c))
        fatigue_score = self._calculate_fatigue(physical_input, heat_threshold_c=threshold,
                                                thermal=thermal)
        energy_kcal = self._calculate_energy(physical_input)
        context = physical_input.work_context
        th = thermal or {}

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
            wbgt_c=th.get("wbgt_c"),
            wet_bulb_c=th.get("wet_bulb_c"),
            tlv_wbgt_c=th.get("tlv_wbgt_c"),
            thermal_exceedance_c=th.get("exceedance_c"),
            metabolic_level=th.get("metabolic_level"),
            required_rest_fraction=th.get("required_rest_fraction"),
            max_allowable_work_minutes_per_hour=th.get("max_allowable_work_minutes_per_hour"),
            thermal_basis=dict(th.get("basis") or {}),
        )

    def _calculate_fatigue(self, physical_input: PhysicalInput, *,
                           heat_threshold_c: float = DEFAULT_HEAT_THRESHOLD_C,
                           thermal: Optional[Dict[str, Any]] = None) -> float:
        steps = physical_input.step_count
        load = physical_input.load_weight_kg
        temp = physical_input.environment.temperature_c

        fatigue = steps * STEP_FATIGUE_PER_STEP
        if load > LOAD_FATIGUE_THRESHOLD_KG:
            fatigue *= 1.0 + ((load - LOAD_FATIGUE_THRESHOLD_KG) / LOAD_FATIGUE_DIVISOR_KG)
        if thermal and thermal.get("available"):
            # 有热应力折算时按 WBGT 超限幅度放大（应变系数来自规则包，可改可追）
            fatigue *= float(thermal.get("strain_multiplier") or 1.0)
        elif temp > heat_threshold_c:
            # 兜底：拿不到规则包时退回"温度 >35℃ 一次乘 1.3"的老阶跃，并注明没按标准折算
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
                       continuous_limit_minutes: Optional[int] = None,
                       thermal_available: bool = True,
                       strain_gain_per_exceedance_c: Optional[float] = None,
                       tlv_by_level: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """把"哪个数由什么决定、哪些参数其实没反应"端出去（供接口/界面/答复引用）。"""
        threshold = (DEFAULT_HEAT_THRESHOLD_C if heat_threshold_c is None
                     else float(heat_threshold_c))
        thermal_part = (
            f"×(1 + {strain_gain_per_exceedance_c:g}×max(0, WBGT−限值))"
            if (thermal_available and strain_gain_per_exceedance_c is not None)
            else (f"（温度>{threshold:g}℃ 时乘 {HEAT_FATIGUE_MULTIPLIER}，**兜底阶跃**，"
                  "没有按标准折算热应力）" if not thermal_available else "×热应变系数"))
        return {
            "physics_version": PhysicsCore.VERSION,
            "fatigue_score": {
                "formula": (f"步数×{STEP_FATIGUE_PER_STEP} →（负重>{LOAD_FATIGUE_THRESHOLD_KG}kg 时乘 "
                            f"1+(负重-{LOAD_FATIGUE_THRESHOLD_KG})/{LOAD_FATIGUE_DIVISOR_KG:g}）"
                            f"{thermal_part} + max(0,(姿势-{POSTURE_PENALTY_START_DEG:g})/"
                            f"{POSTURE_PENALTY_SCALE_DEG:g}) + 连续分钟/{CONTINUOUS_PENALTY_FULL_MINUTES:g}"),
                "driven_by": ["step_count", "load_weight_kg", "environment.temperature_c",
                              "environment.humidity_percent", "posture_angle_deg",
                              "continuous_work_minutes", "work_context.task_type"],
                "thermal_route": ("WBGT = 0.7×自然湿球 + 0.3×干球（室内无太阳辐射，无黑球实测时 Tg≈Td）"
                                  " → 与该作业强度档的职业接触限值比较，超限幅度进应变系数"
                                  if thermal_available else
                                  f"没有热应力规则包 → 只有 >{threshold:g}℃ 的一次阶跃"),
                "heat_is_a_step_not_a_curve": not thermal_available,
                "heat_threshold_c": threshold,
                "tlv_by_metabolic_level": tlv_by_level or {},
            },
            "energy_kcal": {
                "formula": (f"(步数×{STEP_ENERGY_KCAL} + 负重×{LOAD_ENERGY_KCAL_PER_KG} + "
                            f"坡度%×{INCLINE_ENERGY_KCAL_PER_PERCENT}) × 地形系数"
                            f"（{', '.join(f'{k}={v}' for k, v in TERRAIN_MULTIPLIERS.items())}）"),
                "driven_by": ["step_count", "load_weight_kg", "environment.floor_incline_percent",
                              "environment.terrain"],
                "temperature_changes_it": False,
                "humidity_changes_it": False,
                "why": ("高温的代价在标准里体现为热应变与所需工休（ISO 7933/8996 一系的口径），"
                        "不是「同样外功的 kcal 按温度放大」——没有这个系数，所以不编"),
            },
            "thermal_outputs": ["wbgt_c", "wet_bulb_c", "tlv_wbgt_c", "thermal_exceedance_c",
                                 "required_rest_fraction", "max_allowable_work_minutes_per_hour"],
            "inert_inputs": list(INERT_INPUTS),
            "inert_note": ("这些字段接口收、快照存、审计里查得到，但不进疲劳、不进能耗、也不触发规则；"
                           "改了它们读数不变不是「参数没生效」，是模型里就没有这一段"),
            "rule_thresholds": {
                "heat_allowance_triggers_above_c": threshold,
                "continuous_work_limit_minutes": continuous_limit_minutes,
                "operator_used_by_rules": "严格大于（>），所以 240 分钟恰好等于上限不算违规",
            },
        }
