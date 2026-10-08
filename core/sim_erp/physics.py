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
    VERSION = "3.1.2"

    def simulate_step(self, physical_input: PhysicalInput, *,
                      heat_threshold_c: Optional[float] = None,
                      thermal: Optional[Dict[str, Any]] = None) -> PhysicalSnapshot:
        threshold = (DEFAULT_HEAT_THRESHOLD_C if heat_threshold_c is None
                     else float(heat_threshold_c))
        fatigue_score = self._calculate_fatigue(physical_input, heat_threshold_c=threshold,
                                                thermal=thermal)
        energy_kcal, energy_mech, energy_basis = self._calculate_energy(physical_input,
                                                                        thermal=thermal)
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
            energy_mechanical_kcal=round(energy_mech, 2),
            energy_basis=energy_basis,
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
            comfort_center_c=th.get("comfort_center_c"),
            comfort_band_c=th.get("comfort_band_c"),
            work_efficiency=th.get("work_efficiency"),
            energy_cost_multiplier=th.get("energy_cost_multiplier"),
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
            # 舒适带两侧都进疲劳：只罚热不罚冷是半条曲线
            fatigue *= 1.0 + float(thermal.get("comfort_fatigue_gain")
                                   or thermal.get("cold_fatigue_gain") or 0.0)
        elif temp > heat_threshold_c:
            # 兜底：拿不到规则包时退回"温度 >35℃ 一次乘 1.3"的老阶跃，并注明没按标准折算
            fatigue *= HEAT_FATIGUE_MULTIPLIER

        posture_penalty = max(0.0, (physical_input.posture_angle_deg - POSTURE_PENALTY_START_DEG)
                              / POSTURE_PENALTY_SCALE_DEG)
        continuous_penalty = physical_input.continuous_work_minutes / CONTINUOUS_PENALTY_FULL_MINUTES

        return fatigue + posture_penalty + continuous_penalty

    @staticmethod
    def _mechanical_energy(physical_input: PhysicalInput) -> float:
        """旧口径：每步外功代理。留着只为和历史读数对得上，不再当能耗真相。"""
        terrain_multiplier = TERRAIN_MULTIPLIERS[physical_input.environment.terrain.value]
        step_energy = physical_input.step_count * STEP_ENERGY_KCAL
        load_energy = physical_input.load_weight_kg * LOAD_ENERGY_KCAL_PER_KG
        incline_energy = (physical_input.environment.floor_incline_percent
                          * INCLINE_ENERGY_KCAL_PER_PERCENT)
        return (step_energy + load_energy + incline_energy) * terrain_multiplier

    def _calculate_energy(self, physical_input: PhysicalInput, *,
                          thermal: Optional[Dict[str, Any]] = None):
        """能耗 = 代谢率 x 实际作业时长 + 休息段代谢率 x 休息时长。

        高温不是把 kcal 按温度放大（标准没有这个系数），而是通过 WBGT 超限逼出工休：
        作业小时被折掉的那部分换成休息档代谢率，所以 40℃ 与 30℃ 的能耗必然不同。
        拿不到强度档（没有热应力规则包）时退回外功代理，并说明用的是哪套口径。
        """
        mech = self._mechanical_energy(physical_input)
        th = thermal or {}
        rate = th.get("metabolic_kcal_per_hour")
        hours = physical_input.continuous_work_minutes / 60.0
        if not th.get("available") or not rate or hours <= 0:
            return mech, mech, {"method": "mechanical_proxy",
                                "why": ("没有热应力规则包（拿不到强度档代谢率）→ 能耗退回外功代理值，"
                                        "这个值与温度、湿度、时长都无关")}
        rest_rate = th.get("rest_metabolic_kcal_per_hour") or rate
        rest_fraction = min(1.0, max(0.0, float(th.get("required_rest_fraction") or 0.0)))
        cost = float(th.get("energy_cost_multiplier") or 1.0)
        worked = rate * (1.0 - rest_fraction) * hours * cost
        rested = rest_rate * rest_fraction * hours * cost
        return (worked + rested), mech, {
            "energy_cost_multiplier": round(cost, 4),
            "comfort_center_c": th.get("comfort_center_c"),
            "comfort_band_c": th.get("comfort_band_c"),
            "hot_deg_outside_band": th.get("hot_deg_outside_band"),
            "hot_deg_from_dry_bulb": th.get("hot_deg_from_dry_bulb"),
            "hot_deg_from_wbgt": th.get("hot_deg_from_wbgt"),
            "cold_floor_c": th.get("cold_floor_c"),
            "cold_deg_outside_band": th.get("cold_deg_outside_band"),
            "work_efficiency": th.get("work_efficiency"),
            "comfort_basis": th.get("comfort_basis"),
            "method": "metabolic_rate_x_time",
            "metabolic_kcal_per_hour": rate,
            "metabolic_level": th.get("metabolic_level"),
            "rest_metabolic_kcal_per_hour": rest_rate,
            "exposure_hours": round(hours, 4),
            "rest_fraction": round(rest_fraction, 4),
            "worked_kcal": round(worked, 2),
            "rested_kcal": round(rested, 2),
            "basis": th.get("energy_basis"),
            "mechanical_proxy_kcal": round(mech, 2),
        }

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
                "formula": ("代谢率(强度档 kcal/h，来自 JSOH 同表) × 实际作业小时"
                            " + 休息段代谢率 × 休息小时"),
                "driven_by": ["work_context.task_type（强度档→代谢率）", "continuous_work_minutes",
                              "WBGT 超限→required_rest_fraction"],
                "thermal_route": ("温度与湿度通过 WBGT 超限逼出工休、折减实际作业小时来改变能耗；"
                                  "标准没有「同样外功的 kcal 按温度放大」的系数，所以不直接乘"),
                "fallback": "没有热应力规则包时退回外功代理值（与温度/湿度/时长都无关）",
                "scope": ("算的是这段暴露窗口内的消耗：超限被逼出工休后作业小时减少，读数就下降；"
                          "同一件工作在高温下要花更长时间完成，做完它的总消耗是升的 —— "
                          "引擎没有任务工作量输入（只有步数这类过程量），所以不下那句结论"),
                "mechanical_proxy": {
                    "field": "energy_mechanical_kcal",
                    "formula": (f"(步数×{STEP_ENERGY_KCAL} + 负重×{LOAD_ENERGY_KCAL_PER_KG} + "
                                f"坡度%×{INCLINE_ENERGY_KCAL_PER_PERCENT}) × 地形系数"
                                f"（{', '.join(f'{k}={v}' for k, v in TERRAIN_MULTIPLIERS.items())}）"),
                    "kept_because": "历史读数与回归核对要能对齐，不代表这是能耗的真相",
                },
            },
            "comfort_curve": {
                "shape": ("热湿主导的不对称曲线：冷侧 10℃ 才起算（越南 10℃ 以上偏冷不降效率），"
                          "热侧从舒适带上沿起算；中间是平台不是斜坡"),
                "cold_side_enters": ["fatigue_score", "energy_kcal", "work_efficiency"],
                "cold_floor_note": ("偏冷只在低于 cold_floor_c（默认 10℃）之后才计入，"
                                    "不再按温带舒适带下沿惩罚"),
                "hot_side_note": ("热侧两条轴分开算：舒适带偏差进疲劳/能耗/效率，"
                                  "WBGT 超职业接触限值那条另算（合规判定与所需工休）"),
                "hot_side_enters": ["fatigue_score", "energy_kcal", "work_efficiency",
                                    "required_rest_fraction"],
                "note": ("舒适中心随作业强度下移（重活怕热不怕冷）；带外斜率是包里的本厂曲线，"
                         "标准只给热应激限值，不给这条双侧曲线"),
            },
            "thermal_outputs": ["wbgt_c", "wet_bulb_c", "tlv_wbgt_c", "thermal_exceedance_c",
                                 "required_rest_fraction", "max_allowable_work_minutes_per_hour",
                                 "comfort_center_c", "comfort_band_c", "work_efficiency",
                                 "energy_cost_multiplier"],
            "inert_inputs": list(INERT_INPUTS),
            "inert_note": ("这些字段接口收、快照存、审计里查得到，但不进疲劳、不进能耗、也不触发规则；"
                           "改了它们读数不变不是「参数没生效」，是模型里就没有这一段"),
            "rule_thresholds": {
                "heat_allowance_triggers_above_c": threshold,
                "continuous_work_limit_minutes": continuous_limit_minutes,
                "operator_used_by_rules": "严格大于（>），所以 240 分钟恰好等于上限不算违规",
            },
        }
