"""热应力与输入口径的契约测试（ISO 7243 型 WBGT × JSOH 2025-2026 限值）。

这些断言记录的是"引擎现在真的按什么算"：
- 温度与湿度按 WBGT 折算进入疲劳与判定；30℃/60% 与 40℃/60% 必须不同；
- 能耗仍是外功代理，不含热代价（标准没给 kcal 的热放大系数，就不编）；
- 没有热应力规则包时退回旧阶跃，并在读数里明说没按标准折算。
"""

from __future__ import annotations

import math

import pytest

from core.sim_erp.arbiter import DecisionArbiter  # noqa: F401  (保持与原测试同层可导入)
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.models import (
    ActionType,
    EnvironmentSnapshot,
    PhysicalInput,
    WorkContext,
)
from core.sim_erp.physics import PhysicsCore
from core.sim_erp.plugins.builtin import (
    FactoryBreakPolicyPlugin,
    ISO7243HeatPlugin,
    JohnsonGlobalStandardPlugin,
    VNLabor2024Plugin,
)
from core.sim_erp.thermal import assess, resolve_metabolic_level, wbgt_c, wet_bulb_c


def _input(*, temp: float = 30.0, hum: float = 60.0, minutes: int = 240,
           steps: int = 3000, load: float = 0.0, posture: float = 0.0,
           task: str = "assembly") -> PhysicalInput:
    return PhysicalInput(
        time_step_minutes=30.0,
        step_count=steps,
        load_weight_kg=load,
        posture_angle_deg=posture,
        continuous_work_minutes=minutes,
        environment=EnvironmentSnapshot(temperature_c=temp, humidity_percent=hum),
        work_context=WorkContext(task_type=task, zone_id="line-a", shift_id="shift-day",
                                 worker_ref="worker-001", action_type=ActionType.WALK),
    )


def _evaluate(phys: PhysicalInput, *, with_heat: bool = True):
    engine = SimERPEngine()
    engine.audit_trail = type(engine.audit_trail)(storage_path=None)
    plugins = [VNLabor2024Plugin(), JohnsonGlobalStandardPlugin(), FactoryBreakPolicyPlugin()]
    if with_heat:
        plugins.append(ISO7243HeatPlugin())
    return engine.evaluate(phys, plugins)


def _codes(rec):
    return [d.rule_code for d in rec.arbiter_result.decisions]


def test_wet_bulb_agrees_with_iterative_psychrometric_solution():
    """Stull 经验式必须贴着心理测量方程的迭代解，否则 WBGT 是从错的湿球算出来的。"""
    def es(t):
        return 6.1094 * math.exp(17.625 * t / (t + 243.04))

    def iterative(t_db, rh):
        gamma = 0.00066 * 1013.25
        tw = wet_bulb_c(t_db, rh)
        for _ in range(60):
            e = rh / 100.0 * es(t_db)
            f = es(tw) - gamma * (t_db - tw) - e
            d = (es(tw + 0.01) - es(tw)) / 0.01 + gamma
            nxt = tw - f / d
            if abs(nxt - tw) < 1e-7:
                return nxt
            tw = nxt
        return tw

    for t, rh in [(20, 40), (30, 60), (35, 80), (40, 40), (45, 60)]:
        assert abs(wet_bulb_c(t, rh) - iterative(t, rh)) < 1.0


def test_indoor_wbgt_weights_and_globe_assumption_are_stated():
    out = wbgt_c(temperature_c=30.0, humidity_percent=60.0)
    assert out["wet_bulb_c"] == round(wet_bulb_c(30.0, 60.0), 2)
    assert out["globe_used_c"] == 30.0
    assert any("Tg≈Td" in a for a in out["assumptions"])
    assert abs(out["wbgt_c"] - (0.7 * wet_bulb_c(30, 60) + 0.3 * 30)) < 0.02


def test_moderate_work_at_30c_is_within_the_limit_but_40c_is_not():
    cool = _evaluate(_input(temp=30.0, hum=60.0))
    hot = _evaluate(_input(temp=40.0, hum=60.0))
    assert cool.snapshot.wbgt_c < cool.snapshot.tlv_wbgt_c
    assert cool.arbiter_result.final_status == "accepted"
    assert "ISO7243.WBGT.TLV" not in _codes(cool)
    assert hot.snapshot.thermal_exceedance_c > 3.0
    assert hot.arbiter_result.final_status == "rejected"
    assert hot.snapshot.fatigue_score > cool.snapshot.fatigue_score


def test_same_temperature_different_humidity_now_reads_different():
    dry = _evaluate(_input(temp=35.0, hum=40.0))
    humid = _evaluate(_input(temp=35.0, hum=90.0))
    assert humid.snapshot.wbgt_c > dry.snapshot.wbgt_c + 3.0
    assert humid.snapshot.fatigue_score > dry.snapshot.fatigue_score
    assert humid.arbiter_result.final_status == "rejected"


def test_required_rest_scales_with_exceedance():
    slight = _evaluate(_input(temp=36.0, hum=60.0))
    severe = _evaluate(_input(temp=45.0, hum=80.0))
    assert (slight.snapshot.required_rest_fraction or 0) < (severe.snapshot.required_rest_fraction or 0)
    assert severe.snapshot.max_allowable_work_minutes_per_hour < 60 * 0.5


def test_heavier_work_has_tighter_limit_at_the_same_temperature():
    light = _evaluate(_input(temp=33.0, task="inspect"))        # light → 30.5
    heavy = _evaluate(_input(temp=33.0, task="casting"))        # heavy → 26.5
    assert "ISO7243.WBGT.TLV" in _codes(heavy)
    assert heavy.snapshot.tlv_wbgt_c < light.snapshot.tlv_wbgt_c


def test_energy_is_metabolic_rate_times_worked_and_rest_hours():
    """30℃ 不超限 → 满负荷 4 小时；40℃ 被逼出工休 → 同样 4 小时能耗更低。"""
    cool = _evaluate(_input(temp=30.0))
    hot = _evaluate(_input(temp=40.0))
    assert cool.snapshot.energy_basis["method"] == "metabolic_rate_x_time"
    cb = cool.snapshot.energy_basis
    assert cb["worked_kcal"] == pytest.approx(250.0 * 4.0 * float(cb["energy_cost_multiplier"]))
    assert cb["rest_fraction"] == 0.0
    assert hot.snapshot.energy_kcal < cool.snapshot.energy_kcal
    assert hot.snapshot.energy_basis["rest_fraction"] > 0.4
    assert (hot.snapshot.energy_basis["worked_kcal"]
            + hot.snapshot.energy_basis["rested_kcal"]) == pytest.approx(hot.snapshot.energy_kcal)
    # 旧外功代理值留着可核对，且它确实与温度无关（那正是它不能当能耗真相的原因）
    assert cool.snapshot.energy_mechanical_kcal == hot.snapshot.energy_mechanical_kcal == 120.0


def test_energy_scales_with_exposure_duration():
    short = _evaluate(_input(temp=30.0, minutes=60))
    long = _evaluate(_input(temp=30.0, minutes=240))
    assert short.snapshot.energy_kcal < long.snapshot.energy_kcal
    assert long.snapshot.energy_kcal == pytest.approx(short.snapshot.energy_kcal * 4.0)


def test_heavier_intensity_costs_more_energy():
    light = _evaluate(_input(temp=30.0, task="inspect"))     # light 190 kcal/h
    heavy = _evaluate(_input(temp=30.0, task="casting"))     # heavy 370 kcal/h
    assert heavy.snapshot.energy_basis["metabolic_kcal_per_hour"] > \
        light.snapshot.energy_basis["metabolic_kcal_per_hour"]
    assert heavy.snapshot.energy_kcal > light.snapshot.energy_kcal


def test_missing_thermal_pack_falls_back_to_the_legacy_step_and_says_so():
    """没有规则包时不许假装按标准折算过。"""
    rec = _evaluate(_input(temp=35.1), with_heat=False)
    assert rec.snapshot.wbgt_c is None
    assert rec.snapshot.fatigue_score == 4.4          # 老阶跃：×1.3
    d = PhysicsCore.describe_model(thermal_available=False)
    assert d["fatigue_score"]["heat_is_a_step_not_a_curve"] is True
    assert rec.snapshot.energy_mechanical_kcal == rec.snapshot.energy_kcal == 120.0
    assert rec.snapshot.energy_basis["method"] == "mechanical_proxy"


def test_describe_model_moves_humidity_into_fatigue_drivers():
    pack = SimERPEngine().legislation_catalog.load_pack("iso7243_jsoh_heat")
    d = PhysicsCore.describe_model(
        thermal_available=True,
        strain_gain_per_exceedance_c=pack["strain"]["fatigue_gain_per_exceedance_c"],
        tlv_by_level={k: v["wbgt_limit_c"] for k, v in pack["metabolic_levels"].items()},
    )
    assert "environment.humidity_percent" in d["fatigue_score"]["driven_by"]
    assert "environment.humidity_percent" not in d["inert_inputs"]
    assert d["fatigue_score"]["heat_is_a_step_not_a_curve"] is False
    assert d["thermal_outputs"] and "wbgt_c" in d["thermal_outputs"]
    assert d["fatigue_score"]["tlv_by_metabolic_level"]["moderate"] == 29.0


def test_metabolic_lookup_uses_pack_mapping_and_default():
    pack = SimERPEngine().legislation_catalog.load_pack("iso7243_jsoh_heat")
    assert resolve_metabolic_level("assembly", pack)["wbgt_limit_c"] == 29.0
    assert resolve_metabolic_level("没见过的工序", pack)["level"] == pack["default_metabolic_level"]
    assert resolve_metabolic_level("assembly", pack, "heavy")["wbgt_limit_c"] == 26.5


def test_assess_without_pack_refuses_to_convert():
    out = assess(temperature_c=40.0, humidity_percent=60.0, task_type="assembly", pack={})
    assert out["available"] is False and "iso7243_jsoh_heat" in out["why"]

def test_comfort_curve_is_u_shaped_both_ways_from_the_center():
    """21±2 是效率与能耗的最低点，往冷往热都要变差（只罚热不罚冷是上一版的缺陷）。"""
    mid = _evaluate(_input(temp=21.0, hum=60.0))
    center = mid.snapshot.comfort_center_c
    band = mid.snapshot.comfort_band_c
    assert center is not None and band[0] < center < band[1]
    cold = _evaluate(_input(temp=8.0, hum=60.0))
    hot = _evaluate(_input(temp=band[1] + 10.0, hum=60.0))
    assert cold.snapshot.work_efficiency < mid.snapshot.work_efficiency
    assert hot.snapshot.work_efficiency < mid.snapshot.work_efficiency
    assert cold.snapshot.energy_cost_multiplier > 1.0
    assert hot.snapshot.energy_cost_multiplier > 1.0
    assert cold.snapshot.fatigue_score > mid.snapshot.fatigue_score
    assert hot.snapshot.fatigue_score > mid.snapshot.fatigue_score


def test_cold_lowers_efficiency_even_though_attendance_is_fine():
    """10℃ 出勤基本不受影响，但效率上 10℃ 就是冷的 —— 两条轴不能混。"""
    cold = _evaluate(_input(temp=10.0, minutes=240))
    comfy = _evaluate(_input(temp=19.0, minutes=240))
    assert comfy.snapshot.work_efficiency == 1.0
    assert cold.snapshot.work_efficiency < 1.0
    assert cold.snapshot.energy_cost_multiplier > 1.0
    assert cold.snapshot.fatigue_score > comfy.snapshot.fatigue_score
    # 出勤那条只作为独立读数存在，不参与效率
    assert cold.snapshot.energy_basis["attendance_floor_c"] == 10.0


def test_muggy_cold_feels_colder_than_dry_cold():
    """同温不同湿在冷侧也要分开：湿冷比干冷更耗人。"""
    dry = _evaluate(_input(temp=12.0, hum=40.0, minutes=240))
    wet = _evaluate(_input(temp=12.0, hum=95.0, minutes=240))
    assert wet.snapshot.energy_basis["cold_wet_penalty_c"] > dry.snapshot.energy_basis["cold_wet_penalty_c"]
    assert wet.snapshot.energy_basis["apparent_cold_c"] < dry.snapshot.energy_basis["apparent_cold_c"]
    assert wet.snapshot.work_efficiency < dry.snapshot.work_efficiency
    assert wet.snapshot.fatigue_score > dry.snapshot.fatigue_score


def test_heavier_work_shifts_the_comfort_center_down():
    light = _evaluate(_input(temp=21.0, task="inspect"))     # light 190 kcal/h
    heavy = _evaluate(_input(temp=21.0, task="casting"))     # heavy 370 kcal/h
    assert heavy.snapshot.comfort_center_c < light.snapshot.comfort_center_c

def test_mugginess_lowers_efficiency_at_the_same_dry_bulb():
    """同温不同湿必须不等：湿度只走合规轴的话，30℃/95% 会被判成和 30℃/40% 一样舒服。"""
    dry = _evaluate(_input(temp=30.0, hum=40.0))
    muggy = _evaluate(_input(temp=30.0, hum=95.0))
    assert muggy.snapshot.wbgt_c > dry.snapshot.wbgt_c + 5.0
    assert muggy.snapshot.work_efficiency < dry.snapshot.work_efficiency
    assert muggy.snapshot.energy_cost_multiplier > dry.snapshot.energy_cost_multiplier
    assert muggy.snapshot.fatigue_score > dry.snapshot.fatigue_score
    # 干热与闷热两项偏差分开可读，相加后才封顶
    eb = muggy.snapshot.energy_basis
    assert eb["hot_deg_from_dry_bulb"] > 0 and eb["hot_deg_from_wbgt"] > 0
    assert eb["hot_deg_outside_band"] <= 20.0
