"""
仿真引擎（core/sim_factory）设计验证套件
=========================================

从项目根运行：``python -m pytest tests/unit/test_sim_factory.py -v``

覆盖：
- 4 个工厂场景 × 多 horizon/seed 跑不变式验证器（validator），断言全过；
- 针对性单测：MTS 平准、MTO 倒排/正排回退、瓶颈识别、延期判定、出库闭合；
- 技能影响产能：``_skill_factor`` 单调 + 同配置仅技能不同 → 高技能产能更高/延期更少；
- 真实花名册：``real_workers`` 非空 → workforce 用真实姓名/技能/身高体重；
- 压力测试：大订单量/紧交期/单瓶颈/多工段 → 不抛异常且不变式成立；
- 校验错误：坏配置抛 ``ValueError``；
- 确定性：同 seed 两次运行结果一致。
"""

from __future__ import annotations

import pytest

from core.sim_factory.engine import FactoryLoadEngine, _skill_factor
from core.sim_factory.models import (
    FactorySimConfig,
    OrderInput,
    Priority,
    ProductionStrategy,
    RealWorkerSeed,
    RoutingDef,
    RoutingOperation,
    SectionConfig,
    WorkshopConfig,
)
from core.sim_factory.scenarios import SCENARIO_REGISTRY, build_default_scenario
from core.sim_factory.validator import validate_result

ENGINE = FactoryLoadEngine()
SCENARIO_IDS = list(SCENARIO_REGISTRY.keys())


# ====================================================================== #
# 工具：最小可控配置构造器
# ====================================================================== #
def _single_section_config(
    skill: int = 3,
    qty: int = 1500,
    due: int = 8,
    strategy: ProductionStrategy = ProductionStrategy.MTO,
    horizon: int = 20,
    workers_n: int = 4,
    real: bool = True,
) -> FactorySimConfig:
    """单工段单订单最小配置，用于技能/排程行为实验。"""
    workshops = [WorkshopConfig(workshop_id="W1", name="车间", working_days_per_week=6)]
    real_workers = (
        [RealWorkerSeed(name=f"工人{i}", skill_level=skill, shift=1,
                        gender="男", height_cm=170.0 + i, weight_kg=65.0 + i)
         for i in range(workers_n)]
        if real else []
    )
    sections = [SectionConfig(
        section_id="S1", name="组立", workshop_id="W1", strategy=strategy,
        workers=workers_n, machines=0, shifts_per_day=1, hours_per_shift=8.0,
        efficiency=0.85, max_overtime_pct=0.2, yield_rate=0.98, role_name="装配工",
        real_workers=real_workers,
    )]
    routings = [RoutingDef(
        routing_id="R1", product_id="P1", product_name="产品",
        operations=[RoutingOperation(op_no=10, name="组立", section_id="S1",
                                     setup_minutes=30, cycle_seconds=600, batch_size=50, move_hours=0)],
    )]
    orders = [OrderInput(order_id="O1", product_id="P1", quantity=qty,
                         release_day=0, due_day=due, priority=Priority.HIGH)]
    return FactorySimConfig(horizon_days=horizon, seed=42, workshops=workshops,
                            sections=sections, routings=routings, orders=orders)


# ====================================================================== #
# 1. 全场景不变式验证（validator 单一真相源）
# ====================================================================== #
class TestValidatorAllScenarios:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_scenario_passes_all_invariants(self, scenario_id):
        cfg = SCENARIO_REGISTRY[scenario_id]["builder"]()
        result = ENGINE.run(cfg)
        report = validate_result(cfg, result, engine=ENGINE, scenario_id=scenario_id)
        failing = [(c.name, c.detail) for c in report.checks if c.status == "fail"]
        assert report.ok, f"场景 {scenario_id} 不变式失败: {failing}"
        assert report.total >= 20  # 检查项数量健全

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("seed", [7, 42, 123])
    def test_scenario_multiple_seeds(self, scenario_id, seed):
        cfg = SCENARIO_REGISTRY[scenario_id]["builder"]().model_copy(update={"seed": seed})
        result = ENGINE.run(cfg)
        report = validate_result(cfg, result, scenario_id=scenario_id)
        assert report.ok, f"{scenario_id} seed={seed} 失败: {[c.name for c in report.checks if c.status == 'fail']}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_scenario_longer_horizon(self, scenario_id):
        base = SCENARIO_REGISTRY[scenario_id]["builder"]()
        cfg = base.model_copy(update={"horizon_days": min(base.horizon_days + 10, 60)})
        result = ENGINE.run(cfg)
        report = validate_result(cfg, result, scenario_id=scenario_id)
        assert report.ok


# ====================================================================== #
# 2. 技能系数纯函数
# ====================================================================== #
class TestSkillFactor:
    def test_l3_is_baseline(self):
        assert _skill_factor(3.0) == pytest.approx(1.0)

    def test_monotonic_increasing(self):
        values = [_skill_factor(float(s)) for s in range(1, 6)]
        assert all(values[i] < values[i + 1] for i in range(len(values) - 1))

    def test_known_values(self):
        assert _skill_factor(1.0) == pytest.approx(0.90)
        assert _skill_factor(5.0) == pytest.approx(1.10)

    def test_clamped_bounds(self):
        # 钳制区间 [0.75, 1.15]：极端平均技能触发上下钳制
        assert _skill_factor(-10.0) == pytest.approx(0.75)  # 下钳制
        assert _skill_factor(10.0) == pytest.approx(1.15)   # 上钳制
        # 有效技能区间 [1,5] 落在 [0.90, 1.10]，不触及钳制边界
        assert 0.75 < _skill_factor(1.0) < _skill_factor(5.0) < 1.15


# ====================================================================== #
# 3. 技能影响产能（行为）
# ====================================================================== #
class TestSkillAffectsCapacity:
    def test_higher_skill_higher_capacity(self):
        caps = {}
        for sk in (1, 3, 5):
            res = ENGINE.run(_single_section_config(skill=sk))
            caps[sk] = res.sections[0].total_capacity_hours
        assert caps[1] < caps[3] < caps[5]

    def test_higher_skill_less_delay(self):
        results = {sk: ENGINE.run(_single_section_config(skill=sk)).orders[0] for sk in (1, 5)}
        # 高技能：更早完工、更少延期
        assert results[5].completion_day <= results[1].completion_day
        assert results[5].delay_days <= results[1].delay_days
        # 强行为断言（确定性引擎，seed=42 可复现）：高技能准时、低技能延期
        assert results[5].on_time is True
        assert results[1].on_time is False

    def test_no_real_workers_baseline_unchanged(self):
        # 无 real_workers → 技能系数 1.0，产能与 L3 真实花名册一致
        res_synth = ENGINE.run(_single_section_config(real=False))
        res_l3 = ENGINE.run(_single_section_config(skill=3, real=True))
        assert res_synth.sections[0].total_capacity_hours == pytest.approx(
            res_l3.sections[0].total_capacity_hours, rel=1e-6)


# ====================================================================== #
# 4. 真实花名册
# ====================================================================== #
class TestRealWorkforce:
    def test_real_workers_mapped_to_roster(self):
        cfg = _single_section_config(skill=4, workers_n=4, real=True)
        res = ENGINE.run(cfg)
        wf = res.workforce[0]
        assert wf.headcount == 4
        assert wf.avg_skill == pytest.approx(4.0)
        names = {w.name for w in wf.workers}
        assert names == {"工人0", "工人1", "工人2", "工人3"}
        # 真实档案：身高体重映射
        for w in wf.workers:
            assert w.height_cm is not None and w.height_cm > 0
            assert w.weight_kg is not None and w.weight_kg > 0
            assert w.skill_level == 4

    def test_synthetic_workforce_when_no_real_workers(self):
        cfg = _single_section_config(real=False, workers_n=3)
        res = ENGINE.run(cfg)
        wf = res.workforce[0]
        # 合成：headcount = workers × shifts = 3 × 1
        assert wf.headcount == 3
        assert all(w.height_cm is None for w in wf.workers)  # 合成工人无身高体重


# ====================================================================== #
# 5. MTS 平准生产
# ====================================================================== #
class TestMTSLeveling:
    def test_mts_sections_never_overload(self):
        # MTS 按产能节拍平准消耗，负荷率恒 ≤ 1.0（不产生尖峰过载）
        cfg = build_default_scenario()
        res = ENGINE.run(cfg)
        mts = [s for s in res.sections if s.strategy == ProductionStrategy.MTS]
        assert mts, "默认场景应含 MTS 工段"
        for s in mts:
            assert s.peak_load_rate <= 1.0 + 1e-2, f"{s.section_id} MTS 出现过载尖峰 {s.peak_load_rate}"

    def test_mts_load_leveled(self):
        # MTS 满载工作日负荷率恒定 ≈1.0（平准），末尾半天为池耗尽的正常收尾
        cfg = build_default_scenario()
        res = ENGINE.run(cfg)
        for s in res.sections:
            if s.strategy != ProductionStrategy.MTS:
                continue
            full_rates = [p.load_rate for p in s.series
                          if p.is_workday and p.load_rate >= 0.95]
            if len(full_rates) >= 2:
                assert max(full_rates) - min(full_rates) < 0.05, \
                    f"{s.section_id} MTS 满载日负荷未平准: {full_rates}"
                assert max(full_rates) <= 1.0 + 1e-2  # 满载不超产能


# ====================================================================== #
# 6. MTO 倒排 / 正排回退
# ====================================================================== #
class TestMTOBackwardForward:
    def test_backward_on_time_when_feasible(self):
        # 产能充足 → 倒排贴近交期、准时完工
        res = ENGINE.run(_single_section_config(skill=5, qty=500, due=10))
        order = res.orders[0]
        assert order.on_time is True
        assert order.completion_day <= order.due_day

    def test_forward_fallback_delays_when_overloaded(self):
        # 产能不足 → 正排回退，完工延伸出计划期、产生延期
        res = ENGINE.run(_single_section_config(skill=1, qty=3000, due=5, horizon=14))
        order = res.orders[0]
        assert order.delay_days > 0
        assert order.completion_day > order.due_day


# ====================================================================== #
# 7. 瓶颈识别
# ====================================================================== #
class TestBottleneck:
    def test_bottleneck_iff_peak_over_one(self):
        res = ENGINE.run(build_default_scenario())
        for s in res.sections:
            assert s.is_bottleneck == (s.peak_load_rate > 1.0 + 1e-6)

    def test_default_scenario_has_bottleneck(self):
        res = ENGINE.run(build_default_scenario())
        assert any(s.is_bottleneck for s in res.sections)
        assert res.kpis.bottleneck_sections == sum(1 for s in res.sections if s.is_bottleneck)


# ====================================================================== #
# 8. 延期判定
# ====================================================================== #
class TestDelayDetermination:
    def test_delay_formula(self):
        res = ENGINE.run(build_default_scenario())
        for o in res.orders:
            assert o.delay_days == max(0, o.completion_day - o.due_day)
            assert o.on_time == (o.delay_days == 0)

    def test_kpi_delayed_orders_matches(self):
        res = ENGINE.run(build_default_scenario())
        assert res.kpis.delayed_orders == sum(1 for o in res.orders if not o.on_time)


# ====================================================================== #
# 9. 出库闭合
# ====================================================================== #
class TestOutboundClosure:
    def test_shipped_iff_completed_in_horizon(self):
        res = ENGINE.run(build_default_scenario())
        horizon = res.horizon_days
        by_id = {o.order_id: o for o in res.orders}
        for ob in res.outbound_orders:
            completed = by_id[ob.order_id].completion_day < horizon
            assert (ob.status == "shipped") == completed

    def test_outbound_covers_all_orders(self):
        res = ENGINE.run(build_default_scenario())
        assert len(res.outbound_orders) == len(res.orders)
        assert res.kpis.total_outbound == sum(
            ob.quantity for ob in res.outbound_orders if ob.status == "shipped")


# ====================================================================== #
# 10. 压力测试
# ====================================================================== #
class TestStress:
    def test_large_orders_tight_due_no_crash(self):
        cfg = _single_section_config(skill=2, qty=20000, due=3, horizon=14)
        res = ENGINE.run(cfg)
        report = validate_result(cfg, res)
        assert report.ok, f"压力场景不变式失败: {[c.name for c in report.checks if c.status == 'fail']}"

    def test_multi_section_heavy_load_invariants_hold(self):
        # 多工段长工艺链 + 大订单 → 不抛异常且不变式成立
        workshops = [WorkshopConfig(workshop_id="W1", name="车间", working_days_per_week=6)]
        sections = [
            SectionConfig(section_id=f"S{i}", name=f"工段{i}", workshop_id="W1",
                          strategy=(ProductionStrategy.MTS if i == 1 else ProductionStrategy.MTO),
                          workers=3, machines=0, shifts_per_day=1, hours_per_shift=8.0,
                          efficiency=0.85, max_overtime_pct=0.2, yield_rate=0.97)
            for i in range(1, 6)
        ]
        routings = [RoutingDef(
            routing_id="R1", product_id="P1", product_name="产品",
            operations=[RoutingOperation(op_no=10 * i, name=f"工序{i}", section_id=f"S{i}",
                                         setup_minutes=30, cycle_seconds=300, batch_size=50, move_hours=4)
                        for i in range(1, 6)],
        )]
        orders = [OrderInput(order_id=f"O{j}", product_id="P1", quantity=5000,
                             release_day=j % 3, due_day=5 + j, priority=Priority.HIGH)
                  for j in range(8)]
        cfg = FactorySimConfig(horizon_days=20, seed=7, workshops=workshops,
                               sections=sections, routings=routings, orders=orders)
        res = ENGINE.run(cfg)
        report = validate_result(cfg, res, engine=ENGINE)
        assert report.ok, f"多工段压力不变式失败: {[c.name for c in report.checks if c.status == 'fail']}"


# ====================================================================== #
# 11. 校验错误
# ====================================================================== #
class TestValidationErrors:
    def test_routing_references_unknown_section(self):
        cfg = _single_section_config()
        cfg.routings[0].operations[0].section_id = "NOT_EXIST"
        with pytest.raises(ValueError):
            ENGINE.run(cfg)

    def test_due_before_release(self):
        cfg = _single_section_config()
        cfg.orders[0] = cfg.orders[0].model_copy(update={"release_day": 5, "due_day": 3})
        with pytest.raises(ValueError):
            ENGINE.run(cfg)

    def test_release_beyond_horizon(self):
        cfg = _single_section_config(horizon=10)
        cfg.orders[0] = cfg.orders[0].model_copy(update={"release_day": 12})
        with pytest.raises(ValueError):
            ENGINE.run(cfg)

    def test_order_without_routing(self):
        cfg = _single_section_config()
        cfg.orders[0] = cfg.orders[0].model_copy(update={"product_id": "NO_ROUTING"})
        with pytest.raises(ValueError):
            ENGINE.run(cfg)


# ====================================================================== #
# 12. 确定性
# ====================================================================== #
class TestDeterminism:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_same_seed_identical(self, scenario_id):
        cfg = SCENARIO_REGISTRY[scenario_id]["builder"]()
        r1 = ENGINE.run(cfg)
        r2 = ENGINE.run(cfg)
        d1 = r1.model_dump(exclude={"simulation_id", "created_at"})
        d2 = r2.model_dump(exclude={"simulation_id", "created_at"})
        assert d1 == d2

    def test_different_seed_may_differ_but_valid(self):
        # 不同 seed 仍满足全部不变式（波动开关下负荷不同，但核算自洽）
        base = build_default_scenario()
        cfg = base.model_copy(update={"seed": 999, "demand_variability_pct": 0.2})
        res = ENGINE.run(cfg)
        report = validate_result(cfg, res)
        assert report.ok
