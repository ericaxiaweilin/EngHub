"""Compliance engine input-effect contracts (温度/湿度/能耗的真实口径).

这些断言是在记录"模型现在到底让什么影响结果"，不是愿望：
能耗不含热代价、湿度完全不进链、高温是 >35℃ 的一次阶跃、连续工时用的是严格大于。
要改这些行为必须同时改规则包与这里，别靠答复里的猜测。
"""

from __future__ import annotations

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
    JohnsonGlobalStandardPlugin,
    VNLabor2024Plugin,
)


def _input(*, temp: float = 30.0, hum: float = 60.0, minutes: int = 240,
           steps: int = 3000, load: float = 0.0, posture: float = 0.0) -> PhysicalInput:
    return PhysicalInput(
        time_step_minutes=30.0,
        step_count=steps,
        load_weight_kg=load,
        posture_angle_deg=posture,
        continuous_work_minutes=minutes,
        environment=EnvironmentSnapshot(temperature_c=temp, humidity_percent=hum),
        work_context=WorkContext(task_type="assembly", zone_id="line-a", shift_id="shift-day",
                                 worker_ref="worker-001", action_type=ActionType.WALK),
    )


def _evaluate(phys: PhysicalInput):
    engine = SimERPEngine()
    engine.audit_trail = type(engine.audit_trail)(storage_path=None)
    return engine.evaluate(phys, [VNLabor2024Plugin(), JohnsonGlobalStandardPlugin(),
                                  FactoryBreakPolicyPlugin()])


def test_heat_threshold_comes_from_the_pack_not_the_physics_constant():
    """35℃ 以下温度不改变任何读数；35.1℃ 一次阶跃（疲劳 ×1.3 + 高温补贴）。"""
    below = _evaluate(_input(temp=35.0))
    above = _evaluate(_input(temp=35.1))
    assert below.snapshot.fatigue_score == 3.5
    assert [d.rule_code for d in below.arbiter_result.decisions] == []
    assert above.snapshot.fatigue_score == 4.4          # 3.0 * 1.3 + 0.5
    assert "VN.HEAT.ALLOWANCE" in [d.rule_code for d in above.arbiter_result.decisions]
    assert above.arbiter_result.total_cost_delta == 30000


def test_energy_has_no_thermal_term_at_all():
    """30℃ 与 40℃ 能耗相同不是 bug，是公式里就没有温度。"""
    cool = _evaluate(_input(temp=30.0))
    hot = _evaluate(_input(temp=40.0))
    assert cool.snapshot.energy_kcal == hot.snapshot.energy_kcal == 120.0
    assert PhysicsCore.describe_model()["energy_kcal"]["temperature_changes_it"] is False


def test_humidity_is_accepted_but_inert_everywhere():
    for hum in (30.0, 60.0, 95.0):
        rec = _evaluate(_input(temp=30.0, hum=hum))
        assert rec.snapshot.fatigue_score == 3.5
        assert rec.snapshot.energy_kcal == 120.0
        assert rec.arbiter_result.decisions == []
    assert "environment.humidity_percent" in PhysicsCore.describe_model()["inert_inputs"]


def test_continuous_work_limit_uses_strict_greater_than():
    """240 分钟恰好等于法律上限不违规；241 分钟才阻断并要求 30 分钟休息。"""
    at_limit = _evaluate(_input(temp=40.0, minutes=240))
    over = _evaluate(_input(temp=40.0, minutes=241))
    assert at_limit.arbiter_result.final_status == "accepted"
    assert over.arbiter_result.final_status == "rejected"
    assert over.arbiter_result.total_penalty_score == 100
    assert over.arbiter_result.max_required_break_minutes == 30


def test_customer_warning_is_penalty_not_blocking():
    rec = _evaluate(_input(steps=12000))
    codes = [d.rule_code for d in rec.arbiter_result.decisions]
    assert "JOHNSON.FATIGUE.WARNING" in codes
    assert rec.arbiter_result.final_status == "accepted"
    assert rec.arbiter_result.total_penalty_score == 20


def test_factory_break_rule_fires_at_its_own_threshold():
    rec = _evaluate(_input(minutes=300))
    assert "FACTORY.REQUIRED.BREAK" in [d.rule_code for d in rec.arbiter_result.decisions]
    assert rec.arbiter_result.max_required_break_minutes == 30  # 法律 30 > 厂规 15


def test_describe_model_publishes_the_drivers_and_inert_inputs():
    d = PhysicsCore.describe_model(heat_threshold_c=35, continuous_limit_minutes=240)
    assert "step_count" in d["energy_kcal"]["driven_by"]
    assert "environment.temperature_c" in d["fatigue_score"]["driven_by"]
    assert d["fatigue_score"]["heat_is_a_step_not_a_curve"] is True
    assert d["rule_thresholds"]["heat_allowance_triggers_above_c"] == 35.0
    assert d["rule_thresholds"]["continuous_work_limit_minutes"] == 240
    assert d["energy_kcal"]["driven_by"] == ["step_count", "load_weight_kg",
                                             "environment.floor_incline_percent",
                                             "environment.terrain"]
