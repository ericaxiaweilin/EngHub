"""
仿真引擎不变式验证器（单一真相源 / Single Source of Truth）
============================================================

对 ``FactoryLoadEngine.run()`` 的输出做**设计不变式**验证，量化引擎设计质量。
被 pytest 离线验证套件（tests/unit/test_sim_factory.py）与运行时自检 API
（/api/v1/sim-factory/self-test）共用 —— DRY，一处定义、两处复用。

不变式分类：
- conservation  守恒/核算：良品≤产出、报废=产出-良品、累计单调、良品率自洽
- feasibility   产能可行性：负荷率=负荷/产能、瓶颈识别=峰值>1.0
- schedule      排程正确性：工序单调、完工=max(工序结束)、延期/准时自洽、出库闭合、流转因果
- flow          WIP/流转：在制曲线=活跃订单量和
- kpi           KPI 一致：延期数、准时率、人数、产出、PO 计数自洽
- blocking      卡点：严重度降序、rank 连续、0~100、卡点数=过载工段数
- determinism   确定性：同 seed 两次运行结果一致（排除 simulation_id/created_at）
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .models import FactorySimConfig, FactorySimResult

EPS = 1e-6


class InvariantCheck(BaseModel):
    """单条不变式检查结果。"""

    name: str
    category: str                 # conservation / feasibility / schedule / flow / kpi / blocking / determinism
    status: str                   # pass / fail
    detail: str = ""


class ValidationReport(BaseModel):
    """验证报告（pytest 与 self-test API 共用的返回结构）。"""

    engine_version: str = ""
    scenario_id: str = ""
    checks: List[InvariantCheck] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        """序列化为 JSON 友好 dict（property 需显式带出）。"""
        return {
            "engine_version": self.engine_version,
            "scenario_id": self.scenario_id,
            "checks": [c.model_dump() for c in self.checks],
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "ok": self.ok,
        }


def validate_result(
    config: FactorySimConfig,
    result: FactorySimResult,
    engine=None,
    scenario_id: str = "",
) -> ValidationReport:
    """验证一次仿真结果是否满足全部设计不变式。

    :param config: 仿真输入配置
    :param result: 引擎运行结果
    :param engine: 可选，传入引擎实例时额外执行确定性检查（同 seed 复跑）
    :param scenario_id: 场景标识（仅用于报告标注）
    """
    checks: List[InvariantCheck] = []
    sections = {s.section_id: s for s in config.sections}
    orders_by_id = {o.order_id: o for o in config.orders}

    _check_conservation(result, checks)
    _check_feasibility(result, checks)
    _check_schedule(config, result, sections, orders_by_id, checks)
    _check_flow(result, orders_by_id, checks)
    _check_wip(result, checks)
    _check_kpis(config, result, checks)
    _check_blocking(result, checks)

    report = ValidationReport(
        engine_version=result.engine_version,
        scenario_id=scenario_id,
        checks=checks,
    )

    if engine is not None:
        _check_determinism(engine, config, result, checks)

    return report


# ---------------------------------------------------------------------- #
# conservation —— 守恒 / 核算
# ---------------------------------------------------------------------- #
def _check_conservation(result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    k = result.kpis

    checks.append(_mk(
        "good_output_le_total", "conservation",
        k.good_output <= k.total_output,
        f"good_output={k.good_output} total_output={k.total_output}",
    ))
    checks.append(_mk(
        "scrap_eq_output_minus_good", "conservation",
        k.scrap_output == k.total_output - k.good_output,
        f"scrap={k.scrap_output} expect={k.total_output - k.good_output}",
    ))

    # 工段级产出核算
    bad_sec = [
        so.section_id for so in result.section_outputs
        if so.good_qty > so.planned_qty or so.scrap_qty != so.planned_qty - so.good_qty
    ]
    checks.append(_mk(
        "section_output_accounting", "conservation", not bad_sec,
        f"good≤planned & scrap=planned-good 违例工段: {bad_sec}" if bad_sec else "全部工段产出核算自洽",
    ))

    # 日产出：报废=产出-良品 & 累计单调
    bad_day, prev_cum = [], -1
    for op in result.daily_output:
        if op.scrap_qty != op.output_qty - op.good_qty or op.cumulative < prev_cum:
            bad_day.append(op.day)
        prev_cum = op.cumulative
    checks.append(_mk(
        "daily_output_accounting", "conservation", not bad_day,
        f"日产出核算/累计单调违例日: {bad_day}" if bad_day else "日产出核算与累计单调自洽",
    ))

    # 平均良品率自洽
    if k.total_output > 0:
        expect = k.good_output / k.total_output
        ok = abs(k.avg_yield_rate - expect) < 0.01
        checks.append(_mk(
            "avg_yield_rate_consistent", "conservation", ok,
            f"avg_yield={k.avg_yield_rate} expect≈{expect:.4f}",
        ))


# ---------------------------------------------------------------------- #
# feasibility —— 产能可行性
# ---------------------------------------------------------------------- #
def _check_feasibility(result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    # 负荷率核算：load_rate ≈ load / capacity（cap>0）
    bad = []
    for sec in result.sections:
        for pt in sec.series:
            if pt.capacity_hours > EPS:
                expect = pt.load_hours / pt.capacity_hours
                if abs(pt.load_rate - expect) > 0.05:
                    bad.append((sec.section_id, pt.day))
    checks.append(_mk(
        "load_rate_accounting", "feasibility", not bad,
        f"load_rate≠load/cap 违例(工段,日): {bad[:5]}" if bad else "负荷率核算自洽",
    ))

    # 瓶颈识别 = 峰值负荷率 > 1.0
    bad_b = [
        sec.section_id for sec in result.sections
        if sec.is_bottleneck != (sec.peak_load_rate > 1.0 + EPS)
    ]
    checks.append(_mk(
        "bottleneck_identification", "feasibility", not bad_b,
        f"is_bottleneck≠(peak>1.0) 违例工段: {bad_b}" if bad_b else "瓶颈识别自洽",
    ))


# ---------------------------------------------------------------------- #
# schedule —— 排程正确性
# ---------------------------------------------------------------------- #
def _check_schedule(config, result, sections, orders_by_id, checks: List[InvariantCheck]) -> None:
    horizon = result.horizon_days

    # 工序：end≥start & 开工日单调 & 完工日=max(工序结束)
    bad_mono, bad_comp = [], []
    for res in result.orders:
        ops = sorted(res.ops, key=lambda x: x.op_no)
        prev_start = -10 ** 9
        for op in ops:
            if op.end_day < op.start_day or op.start_day < prev_start:
                bad_mono.append((res.order_id, op.op_no))
            prev_start = op.start_day
        if ops and res.completion_day != max(o.end_day for o in ops):
            bad_comp.append(res.order_id)
    checks.append(_mk(
        "op_end_ge_start_monotonic", "schedule", not bad_mono,
        f"工序 end<start 或开工日倒退: {bad_mono[:5]}" if bad_mono else "工序区间有效且开工日单调",
    ))
    checks.append(_mk(
        "completion_eq_max_op_end", "schedule", not bad_comp,
        f"completion≠max(op.end) 订单: {bad_comp}" if bad_comp else "完工日=末道工序结束日",
    ))

    # 首工序开工 ≥ 投放日
    bad_rel = [
        res.order_id for res in result.orders
        if res.ops and min(o.start_day for o in res.ops) < res.release_day
    ]
    checks.append(_mk(
        "first_op_ge_release", "schedule", not bad_rel,
        f"首工序早于投放日: {bad_rel}" if bad_rel else "首工序开工≥投放日",
    ))

    # 延期 / 准时自洽：delay=max(0,completion-due) & on_time=(delay==0)
    bad_delay = [
        res.order_id for res in result.orders
        if res.delay_days != max(0, res.completion_day - res.due_day)
        or res.on_time != (res.delay_days == 0)
    ]
    checks.append(_mk(
        "delay_on_time_consistent", "schedule", not bad_delay,
        f"延期/准时核算违例订单: {bad_delay}" if bad_delay else "延期与准时判定自洽",
    ))

    # 出库闭合：shipped ⟺ 计划期内完工
    res_by_id = {r.order_id: r for r in result.orders}
    bad_ob = [
        ob.outbound_id for ob in result.outbound_orders
        if (ob.status == "shipped") != (res_by_id[ob.order_id].completion_day < horizon)
    ]
    checks.append(_mk(
        "outbound_shipped_iff_completed", "schedule", not bad_ob,
        f"出库状态与完工不符: {bad_ob}" if bad_ob else "出库闭合：期内完工↔shipped",
    ))

    # 流转因果：depart ≤ arrive
    bad_tr = [tr.transfer_id for tr in result.transfers if tr.depart_day > tr.arrive_day]
    checks.append(_mk(
        "transfer_depart_le_arrive", "schedule", not bad_tr,
        f"流转离开晚于到达: {bad_tr}" if bad_tr else "流转因果 depart≤arrive",
    ))


# ---------------------------------------------------------------------- #
# flow —— WIP / 流转
# ---------------------------------------------------------------------- #
def _check_flow(result: FactorySimResult, orders_by_id, checks: List[InvariantCheck]) -> None:
    # 出库总量 = shipped 订单 quantity 和；未出库数 = pending 数
    shipped_qty = sum(ob.quantity for ob in result.outbound_orders if ob.status == "shipped")
    pending_cnt = sum(1 for ob in result.outbound_orders if ob.status == "pending")
    checks.append(_mk(
        "outbound_totals_consistent", "flow",
        result.kpis.total_outbound == shipped_qty and result.kpis.pending_outbound == pending_cnt,
        f"total_outbound={result.kpis.total_outbound}/{shipped_qty} "
        f"pending={result.kpis.pending_outbound}/{pending_cnt}",
    ))


def _check_wip(result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    # 在制曲线 = 活跃订单（首工序开工 ≤ d ≤ 完工）数量之和
    horizon = result.horizon_days
    bad = []
    for d in range(horizon):
        active = [
            o for o in result.orders
            if o.ops and o.ops[0].start_day <= d <= o.completion_day
        ]
        expect_qty = sum(o.quantity for o in active)
        if d < len(result.wip_curve):
            pt = result.wip_curve[d]
            if pt.wip_qty != expect_qty or pt.active_orders != len(active):
                bad.append(d)
    checks.append(_mk(
        "wip_curve_eq_active_orders", "flow", not bad,
        f"WIP 曲线与活跃订单不符日: {bad}" if bad else "WIP 曲线=活跃订单量和",
    ))


# ---------------------------------------------------------------------- #
# kpi —— KPI 一致性
# ---------------------------------------------------------------------- #
def _check_kpis(config: FactorySimConfig, result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    k = result.kpis

    # 延期订单数 = 非准时订单数
    delayed = sum(1 for o in result.orders if not o.on_time)
    checks.append(_mk(
        "delayed_orders_count", "kpi", k.delayed_orders == delayed,
        f"kpi.delayed={k.delayed_orders} expect={delayed}",
    ))

    # 准时率 = 准时 / 总数
    if result.orders:
        expect_rate = sum(1 for o in result.orders if o.on_time) / len(result.orders)
        ok = abs(k.on_time_rate - expect_rate) < 0.01
        checks.append(_mk(
            "on_time_rate_consistent", "kpi", ok,
            f"on_time_rate={k.on_time_rate} expect≈{expect_rate:.4f}",
        ))

    # 全厂人数 = Σ(单班人数 × 班次)
    expect_hc = sum(s.workers * s.shifts_per_day for s in config.sections)
    checks.append(_mk(
        "headcount_consistent", "kpi", k.headcount == expect_hc,
        f"headcount={k.headcount} expect={expect_hc}",
    ))

    # 总产出 = Σ日产出 = 末日累计
    total_daily = sum(op.output_qty for op in result.daily_output)
    cum_end = result.daily_output[-1].cumulative if result.daily_output else 0
    checks.append(_mk(
        "total_output_consistent", "kpi",
        k.total_output == total_daily == cum_end,
        f"total_output={k.total_output} Σdaily={total_daily} cum_end={cum_end}",
    ))

    # PO 计数：completed+delayed = 订单数，且与订单准时状态一致
    po_completed = sum(1 for po in result.production_orders if po.status == "completed")
    po_delayed = sum(1 for po in result.production_orders if po.status == "delayed")
    on_time_cnt = sum(1 for o in result.orders if o.on_time)
    checks.append(_mk(
        "po_counts_consistent", "kpi",
        k.po_completed == po_completed and k.po_delayed == po_delayed
        and po_completed + po_delayed == len(result.orders)
        and po_completed == on_time_cnt,
        f"po_completed={k.po_completed}/{po_completed} po_delayed={k.po_delayed}/{po_delayed}",
    ))


# ---------------------------------------------------------------------- #
# blocking —— 卡点
# ---------------------------------------------------------------------- #
def _check_blocking(result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    bps = result.blocking_points

    # 严重度降序 & rank 连续
    desc_ok = all(
        bps[i].severity >= bps[i + 1].severity - EPS for i in range(len(bps) - 1)
    )
    rank_ok = all(bp.rank == i + 1 for i, bp in enumerate(bps))
    checks.append(_mk(
        "blocking_severity_desc_rank", "blocking", desc_ok and rank_ok,
        f"降序={desc_ok} rank连续={rank_ok}",
    ))

    # 严重度 0~100
    bounds_ok = all(0.0 - EPS <= bp.severity <= 100.0 + EPS for bp in bps)
    checks.append(_mk(
        "blocking_severity_bounds", "blocking", bounds_ok,
        "severity∈[0,100]" if bounds_ok else "severity 越界",
    ))

    # 卡点数 = 过载天数>0 的卡点数
    expect_cnt = sum(1 for bp in bps if bp.overload_days > 0)
    checks.append(_mk(
        "blocking_point_count", "blocking",
        result.kpis.blocking_point_count == expect_cnt,
        f"kpi.blocking_count={result.kpis.blocking_point_count} expect={expect_cnt}",
    ))


# ---------------------------------------------------------------------- #
# determinism —— 确定性
# ---------------------------------------------------------------------- #
def _check_determinism(engine, config: FactorySimConfig,
                       result: FactorySimResult, checks: List[InvariantCheck]) -> None:
    """同配置复跑一次，对比结果（排除 simulation_id / created_at）。"""
    try:
        result2 = engine.run(config)
        d1 = result.model_dump(exclude={"simulation_id", "created_at"})
        d2 = result2.model_dump(exclude={"simulation_id", "created_at"})
        same = _deep_equal(d1, d2)
        checks.append(_mk(
            "determinism_same_seed", "determinism", same,
            "同 seed 复跑结果一致" if same else "同 seed 复跑结果不一致",
        ))
    except Exception as exc:  # noqa: BLE001
        checks.append(_mk("determinism_same_seed", "determinism", False, f"复跑异常: {exc}"))


def _deep_equal(a, b, tol: float = 1e-6) -> bool:
    """递归比较两个 model_dump 结构（浮点带容差）。"""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_deep_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_deep_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= tol
        except (TypeError, ValueError):
            return a == b
    return a == b


def _mk(name: str, category: str, ok: bool, detail: str) -> InvariantCheck:
    return InvariantCheck(
        name=name, category=category,
        status="pass" if ok else "fail", detail=detail,
    )
