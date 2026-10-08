"""热应力与输入口径的契约测试（ISO 7243 型 WBGT × JSOH 2025-2026 限值）。

这些断言记录的是"引擎现在真的按什么算"：
- 温度与湿度按 WBGT 折算进入疲劳与判定；30℃/60% 与 40℃/60% 必须不同；
- 能耗 = 强度档代谢率 × 作业小时 + 休息档代谢率 × 工休小时（外功代理值另存在
  `energy_mechanical_kcal`，它才是与温度无关的那个）；
- 强度档由工作量反推（步数×步幅→速度→ACSM 净增项），工序名义值只当非步行时间的基线；
- 取消勾选热应力插件不再让读数退化（WBGT 是物理量）；真正取不到**规则包**时才退回旧阶跃并明说。
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
from core.sim_erp.legislation import LegislationCatalog
from core.sim_erp.thermal import (assess, attendance_impact, derive_intensity,
                           resolve_metabolic_level, wbgt_c, wet_bulb_c)


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


def _evaluate(phys: PhysicalInput, *, with_heat: bool = True, catalog=None, baseline=None):
    engine = SimERPEngine(legislation_catalog=catalog) if catalog else SimERPEngine()
    if catalog and engine.legislation_catalog is not catalog:      # 参数没生效就是假测试
        raise AssertionError("注入的 catalog 没被引擎采用")
    engine.audit_trail = type(engine.audit_trail)(storage_path=None)
    plugins = [VNLabor2024Plugin(), JohnsonGlobalStandardPlugin(), FactoryBreakPolicyPlugin()]
    if with_heat:
        plugins.append(ISO7243HeatPlugin())
    return engine.evaluate(phys, plugins, attendance_baseline=baseline)


def _attendance(phys: PhysicalInput, baseline=None) -> dict:
    return _evaluate(phys, baseline=baseline).snapshot.attendance_impact or {}


class _NoHeatCatalog(LegislationCatalog):
    """模拟"这个厂压根没有热应力规则包"（文件取不到），不是"插件没勾"。

    两者以前被同一条测试混在一起：插件没勾时 WBGT 照样折算（物理量），
    规则包取不到时才退回到旧阶跃 + 外功代理 —— 混起来就会把"没判违规"读成"没超线"。
    """

    def load_pack(self, name):
        if str(name) == "iso7243_jsoh_heat":
            return {}
        return super().load_pack(name)


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
    ib = cool.snapshot.intensity_basis
    # 代谢率是按工作量反推的连续值，不是档位表的代表值：装配名义 250 kcal/h，
    # 3000 步摊进 4 小时窗口再加净增项 —— 按 250 断言会把这条链锁回查表。
    assert ib["route"] == "workload_derived"
    assert ib["components"]["task_baseline_kcal_per_hour"] == 250.0
    assert cb["metabolic_kcal_per_hour"] == pytest.approx(float(ib["kcal_per_hour"]))
    assert cb["metabolic_kcal_per_hour"] > 250.0
    assert cb["worked_kcal"] == pytest.approx(
        float(cb["metabolic_kcal_per_hour"]) * 4.0 * float(cb["energy_cost_multiplier"]), rel=1e-3)
    assert cb["rest_fraction"] == 0.0
    assert hot.snapshot.energy_kcal < cool.snapshot.energy_kcal
    assert hot.snapshot.energy_basis["rest_fraction"] > 0.4
    assert (hot.snapshot.energy_basis["worked_kcal"]
            + hot.snapshot.energy_basis["rested_kcal"]) == pytest.approx(hot.snapshot.energy_kcal)
    # 旧外功代理值留着可核对，且它确实与温度无关（那正是它不能当能耗真相的原因）
    assert cool.snapshot.energy_mechanical_kcal == hot.snapshot.energy_mechanical_kcal == 120.0


def test_energy_scales_with_exposure_duration():
    """同一强度摊到 4 倍时长 → 能耗正好 4 倍；同样步数摊短窗口 → 强度更高，不是线性。"""
    short = _evaluate(_input(temp=30.0, minutes=60, steps=750))
    long = _evaluate(_input(temp=30.0, minutes=240, steps=3000))
    assert short.snapshot.energy_basis["metabolic_kcal_per_hour"] == pytest.approx(
        long.snapshot.energy_basis["metabolic_kcal_per_hour"])
    assert long.snapshot.energy_kcal == pytest.approx(short.snapshot.energy_kcal * 4.0, rel=1e-2)

    same_steps = _evaluate(_input(temp=30.0, minutes=60, steps=3000))
    assert same_steps.snapshot.energy_basis["metabolic_kcal_per_hour"] > \
        long.snapshot.energy_basis["metabolic_kcal_per_hour"]
    assert same_steps.snapshot.energy_kcal < long.snapshot.energy_kcal
    assert same_steps.snapshot.energy_kcal != pytest.approx(
        long.snapshot.energy_kcal / 4.0, rel=0.05)   # 3000 步挤在 1 小时里比摊 4 小时更狠


def test_heavier_intensity_costs_more_energy():
    light = _evaluate(_input(temp=30.0, task="inspect"))     # light 190 kcal/h
    heavy = _evaluate(_input(temp=30.0, task="casting"))     # heavy 370 kcal/h
    assert heavy.snapshot.energy_basis["metabolic_kcal_per_hour"] > \
        light.snapshot.energy_basis["metabolic_kcal_per_hour"]
    assert heavy.snapshot.energy_kcal > light.snapshot.energy_kcal


def test_missing_thermal_pack_falls_back_to_the_legacy_step_and_says_so():
    """没有规则包时不许假装按标准折算过 —— 注入取不到包的 catalog，不是取消勾选插件。"""
    rec = _evaluate(_input(temp=35.1), catalog=_NoHeatCatalog())
    assert rec.snapshot.wbgt_c is None
    assert rec.snapshot.fatigue_score == 4.4          # 老阶跃：×1.3
    d = PhysicsCore.describe_model(thermal_available=False)
    assert d["fatigue_score"]["heat_is_a_step_not_a_curve"] is True
    assert rec.snapshot.energy_mechanical_kcal == rec.snapshot.energy_kcal == 120.0
    assert rec.snapshot.energy_basis["method"] == "mechanical_proxy"


def test_unmounted_heat_plugin_still_converts_wbgt_but_nobody_judges_the_limit():
    """取消勾选热应力插件 ≠ 没超线：WBGT 是物理量照折算，只是没人做超限判定。

    这条是从上面那条拆出来的 —— 以前两者混在一起，于是界面上"没判违规"会被读成"没问题"。
    """
    rec = _evaluate(_input(temp=40.0), with_heat=False)
    assert rec.snapshot.wbgt_c and rec.snapshot.wbgt_c > 30.0
    basis = rec.snapshot.thermal_basis or {}
    assert basis.get("rule_route") == "physics_only"
    assert "没判违规" in (basis.get("rule_route_note") or "")
    assert "ISO7243.WBGT.TLV" not in _codes(rec)
    # 但热代价进的是物理层，不跟着插件一起消失：40℃ 的疲劳必须高于 30℃ 的疲劳
    cool = _evaluate(_input(temp=30.0), with_heat=False)
    assert rec.snapshot.fatigue_score > cool.snapshot.fatigue_score
    assert rec.snapshot.energy_basis["method"] == "metabolic_rate_x_time"


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


# ── 出勤轴与强度反推：这两块的读数以前只在临时脚本里核过，没进仓库 ──────────────
_LEDGER_BASELINE = {"available": True, "rate": 0.0433, "basis": "夹具：金属厂台账实测缺勤 4.33%"}


def test_attendance_starts_moving_before_the_legal_limit_is_breached():
    """33℃/60% 还没超限（限值 29.0），但已经吃掉那 2℃ 余量 → 出勤先动，判定还不响。

    这条是刻意分开的两件事：用超限幅度当驱动的话，33~35℃ 这段的出勤读数永远是 0，
    而人不会等超线那天才开始请假。
    """
    mild = _attendance(_input(temp=33.0), _LEDGER_BASELINE)
    verdict = _evaluate(_input(temp=33.0), baseline=_LEDGER_BASELINE)
    assert "ISO7243.WBGT.TLV" not in _codes(verdict)
    assert mild["wbgt_over_pre_limit_c"] > 0.0
    assert mild["increment_pp"] > 0.0
    assert mild["driver"] == "hot_deg_from_wbgt"

    cool = _attendance(_input(temp=28.0), _LEDGER_BASELINE)
    assert cool["increment_pp"] == 0.0
    assert cool["predicted_absence_rate"] == pytest.approx(0.0433)


def test_attendance_baseline_comes_from_the_ledger_and_never_from_the_pack():
    """增量是百分点，总缺勤率必须有台账基线 —— 没基线就只报增量，不假装知道总数。"""
    hot = _attendance(_input(temp=40.0), _LEDGER_BASELINE)
    assert hot["increment_pp"] == pytest.approx(8.09, abs=0.15)
    assert hot["predicted_absence_rate"] == pytest.approx(0.0433 + hot["increment_pp"] / 100.0)

    without = _attendance(_input(temp=40.0))            # 没传基线（换厂区/该厂无打卡行）
    assert without["increment_pp"] > 0.0
    assert without["predicted_absence_rate"] is None
    assert without["baseline_absence_rate"] is None
    assert "只给增量" in (without["no_baseline_reason"] or "")


def test_attendance_increment_is_capped_and_declared_not_measured():
    """极端读数下增量封顶 15pp，且这条斜率标着 declared_unverified —— 别读成量出来的。"""
    extreme = _attendance(_input(temp=50.0, hum=90.0), _LEDGER_BASELINE)
    assert extreme["increment_capped"] is True
    assert extreme["increment_pp"] == extreme["max_increment_pp"] == 15.0
    assert extreme["sensitivity_status"] == "declared_unverified"
    assert extreme["predicted_absence_rate"] == pytest.approx(0.0433 + 0.15)


def test_cold_side_moves_efficiency_but_not_attendance():
    """厂里口径：10℃ 左右人照常来，但效率照降 —— 两条轴不许并成一条。"""
    cold = _evaluate(_input(temp=10.0, hum=90.0), baseline=_LEDGER_BASELINE)
    ai = cold.snapshot.attendance_impact or {}
    eb = cold.snapshot.energy_basis
    assert eb["cold_deg_outside_band"] > 0.0
    assert ai["cold_increment_pp"] == 0.0
    assert cold.snapshot.work_efficiency < 1.0
    assert cold.snapshot.wbgt_c < cold.snapshot.tlv_wbgt_c      # 冷天不会被热限值判违规


def test_intensity_band_is_derived_from_workload_not_only_the_task_name():
    """同一道工序，走 3000 步与站着不动不该共用一个 WBGT 限值。"""
    pack = SimERPEngine().legislation_catalog.load_pack("iso7243_jsoh_heat")
    walking = derive_intensity(pack=pack, task_meta={"level": "moderate", "kcal_per_hour": 250.0,
                                                     "rmr": 3, "wbgt_limit_c": 29.0},
                               workload={"step_count": 12000, "continuous_work_minutes": 240},
                               explicit_level=None)
    still = derive_intensity(pack=pack, task_meta={"level": "moderate", "kcal_per_hour": 250.0,
                                                   "rmr": 3, "wbgt_limit_c": 29.0},
                             workload={"step_count": 0, "continuous_work_minutes": 240},
                             explicit_level=None)
    assert walking["route"] == "workload_derived"
    assert still["route"] == "task_map_only"
    assert walking["kcal_per_hour"] > still["kcal_per_hour"]
    assert walking["wbgt_limit_c"] <= still["wbgt_limit_c"]     # 更重的活 → 限值更紧

    named = derive_intensity(pack=pack, task_meta={"level": "light", "kcal_per_hour": 190.0,
                                                   "rmr": 2, "wbgt_limit_c": 30.5},
                             workload={"step_count": 12000, "continuous_work_minutes": 240},
                             explicit_level="heavy")
    assert named["route"] == "explicit_level"
    # 点名了就不反推，而且点名的档要**真的生效**：这行以前只把 heavy 那行取出来就丢了，
    # 于是"按 heavy 判"的请求还在用装配工序的 29.0℃ 限值。
    assert named["kcal_per_hour"] == 370.0
    assert named["wbgt_limit_c"] == 26.5 and named["level"] == "heavy"


def test_attendance_impact_formula_is_readable_without_a_pack_lookup():
    """系数改了要能在读数里追到出处，不能只剩一个算好的百分点。"""
    out = attendance_impact(wbgt_over_pre_limit_c=3.0, cold_deg=0.0,
                            pack=SimERPEngine().legislation_catalog.load_pack("iso7243_jsoh_heat"),
                            absence_baseline=None)
    assert out["increment_pp"] == 3.0
    assert out["predicted_absence_rate"] is None      # 没基线就不给总数
    assert out["formula"] and out["coefficient_basis"]
