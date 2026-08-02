"""
车间级 / 工段级有限产能负荷仿真引擎

核心建模思想（对应真实工厂）：
1. 工段产能 = min(人力产能, 设备产能) × 综合效率，受车间排班日历（5/6/7 天工作制）约束；
2. MTS 工段（备料 / 零件加工）：面向库存平准生产 —— 将计划期内总工时均匀铺到每个工作日，
   负荷天然均衡（用户场景："可能做备料，负载比较均衡"）；
3. MTO 工段（组立等最终工段）：订单进、订单出 —— 按交期倒排（ALAP），负荷脉冲式贴近交期，
   不同订单结构直接把负荷分化打到不同部门；
4. 产能争用：倒排放不下时自动正排回退，溢出部分记为过载（需要加班 / 外协）；
5. 输出工段×日负荷矩阵、订单甘特排程、订单-工段负荷贡献矩阵、瓶颈/延误/闲置告警、
   负荷不均衡指数（量化"不同订单对不同部门负荷不一样"的程度）。
"""

from __future__ import annotations

import random
import uuid
from math import ceil, floor
from typing import Dict, List, Optional, Tuple

from .models import (
    BlockingPoint,
    FactoryAlert,
    FactoryKPIs,
    FactorySimConfig,
    FactorySimResult,
    OrderInput,
    OrderOpSchedule,
    OrderResult,
    OrderSectionLoad,
    OutputPoint,
    OutboundOrder,
    PoOpResult,
    Priority,
    PRIORITY_RANK,
    ProductionOrderResult,
    ProductionStrategy,
    SectionConfig,
    SectionDayLoad,
    SectionOutput,
    SectionSummary,
    TransferRecord,
    WipPoint,
)
from .workforce import generate_workforce

EPS = 1e-6


class FactoryLoadEngine:
    VERSION = "1.0.0"

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def run(self, config: FactorySimConfig) -> FactorySimResult:
        horizon = config.horizon_days
        workshops = {w.workshop_id: w for w in config.workshops}
        sections = {s.section_id: s for s in config.sections}
        routings = {r.product_id: r for r in config.routings}

        self._validate(config, workshops, sections, routings, horizon)

        # ---------- 1. 排班日历 & 产能矩阵 ---------- #
        def is_workday(workshop_id: str, day: int) -> bool:
            wd = workshops[workshop_id].working_days_per_week
            dow = day % 7  # 0=周一 ... 6=周日
            if wd >= 7:
                return True
            if wd == 6:
                return dow != 6  # 单休：周日休息
            return dow < 5       # 双休：周六周日休息

        base_cap: Dict[str, List[float]] = {}
        ot_cap: Dict[str, List[float]] = {}
        for s in config.sections:
            # 技能影响产能：携带真实员工花名册时，按平均技能等级修正人力产能
            # （无 real_workers 的既有合成场景 sf=1.0，行为不变）
            if s.real_workers:
                avg_skill = sum(w.skill_level for w in s.real_workers) / len(s.real_workers)
                sf = _skill_factor(avg_skill)
            else:
                sf = 1.0
            labor = s.workers * s.shifts_per_day * s.hours_per_shift * s.efficiency * sf
            machine = (
                s.machines * s.shifts_per_day * s.hours_per_shift * s.efficiency
                if s.machines > 0 else float("inf")
            )
            daily = min(labor, machine)
            ot_factor = 1.0 + s.max_overtime_pct if config.overtime_allowed else 1.0
            base_cap[s.section_id] = [
                daily if is_workday(s.workshop_id, d) else 0.0 for d in range(horizon)
            ]
            ot_cap[s.section_id] = [c * ot_factor for c in base_cap[s.section_id]]

        load: Dict[str, List[float]] = {sid: [0.0] * horizon for sid in sections}

        # ---------- 2. 订单展开为工序工时 ---------- #
        expanded: List[Tuple[OrderInput, list]] = []
        for order in sorted(
            config.orders,
            key=lambda o: (PRIORITY_RANK[o.priority], o.due_day, o.release_day),
        ):
            routing = routings[order.product_id]
            ops = []
            for op in sorted(routing.operations, key=lambda x: x.op_no):
                batches = ceil(order.quantity / op.batch_size)
                work_hours = op.setup_minutes * batches / 60.0 + order.quantity * op.cycle_seconds / 3600.0
                ops.append({
                    "op": op,
                    "work_hours": work_hours,
                    "section": sections[op.section_id],
                    "routing_name": op.name,
                    "product_name": routing.product_name,
                })
            expanded.append((order, ops))

        # ---------- 3. MTS 工段：平准生产（按产能节拍稳定产出，池清空即完成） ---------- #
        # 备料/库存生产的真实形态：负荷恒定（均衡），总工时 < 期内产能时提前做完，
        # 超出时延伸出计划期（能力不足）——而不是人为铺满整个计划期
        mts_pool: Dict[str, float] = {sid: 0.0 for sid in sections}
        for _order, ops in expanded:
            for item in ops:
                if item["section"].strategy == ProductionStrategy.MTS:
                    mts_pool[item["section"].section_id] += item["work_hours"]

        # 每工段名义日产能（工作日），用于超出计划期后的虚拟延展
        nominal_daily: Dict[str, float] = {}
        for s in config.sections:
            caps = [c for c in base_cap[s.section_id] if c > EPS]
            nominal_daily[s.section_id] = sum(caps) / len(caps) if caps else 8.0

        # ---------- 4. 订单排程（MTS 产能节拍流 + MTO 倒排/正排回退） ---------- #
        mts_cursor: Dict[str, float] = {sid: 0.0 for sid in sections}
        order_results: List[OrderResult] = []
        order_op_hours: List[Tuple[str, str, float]] = []  # (order_id, section_id, hours)

        for order, ops in expanded:
            sched = self._schedule_order(order, ops, mts_pool, mts_cursor,
                                         base_cap, ot_cap, load, sections,
                                         is_workday, nominal_daily, horizon)
            completion_day = max(item["end_day"] for item in sched.values())
            delay = max(0, completion_day - order.due_day)
            total_wh = sum(i["work_hours"] for i in ops)
            order_results.append(OrderResult(
                order_id=order.order_id,
                product_id=order.product_id,
                product_name=sched[ops[0]["op"].op_no]["product_name"],
                quantity=order.quantity,
                priority=order.priority,
                release_day=order.release_day,
                due_day=order.due_day,
                completion_day=completion_day,
                delay_days=delay,
                on_time=delay == 0,
                total_work_hours=round(total_wh, 1),
                ops=[
                    OrderOpSchedule(
                        op_no=item["op"].op_no,
                        name=item["op"].name,
                        section_id=item["op"].section_id,
                        section_name=item["section"].name,
                        strategy=item["section"].strategy,
                        start_day=item["start_day"],
                        end_day=item["end_day"],
                        work_hours=round(item["work_hours"], 1),
                    )
                    for item in (sched[op["op"].op_no] for op in ops)
                ],
            ))
            for item in ops:
                order_op_hours.append((order.order_id, item["op"].section_id, item["work_hours"]))

        # ---------- 4b. WIP 积压矩阵 & 工序等待间隙（卡点分析数据源） ---------- #
        # wip_matrix[工段][日]：该工段当日在制积压件数（物料堆在此处的数量）
        # section_wait[工段]：各工序开工前等待天数列表（与上工序完工的间隙）
        wip_matrix: Dict[str, List[int]] = {sid: [0] * horizon for sid in sections}
        section_wait: Dict[str, List[int]] = {sid: [] for sid in sections}
        for res in order_results:
            ops_sorted = sorted(res.ops, key=lambda x: x.op_no)
            prev_end_day = res.release_day  # 首工序相对下达日
            for op in ops_sorted:
                s_c = max(op.start_day, 0)
                e_c = min(op.end_day, horizon - 1)
                for d in range(s_c, e_c + 1):
                    wip_matrix[op.section_id][d] += res.quantity
                section_wait[op.section_id].append(max(0, op.start_day - prev_end_day))
                prev_end_day = op.end_day

        # ---------- 5. 日负荷波动（模拟现场不均匀） ---------- #
        if config.demand_variability_pct > 0:
            rng = random.Random(config.seed)
            for sid in sections:
                for d in range(horizon):
                    if load[sid][d] > EPS:
                        factor = 1.0 + rng.uniform(
                            -config.demand_variability_pct, config.demand_variability_pct
                        )
                        load[sid][d] *= factor

        # ---------- 6. 汇总 ---------- #
        section_summaries = self._summarize_sections(
            config, sections, workshops, base_cap, load, is_workday, horizon, wip_matrix
        )
        order_section_loads = self._order_section_loads(order_op_hours, sections, load)
        wip_curve = self._wip_curve(order_results, horizon)
        alerts = self._build_alerts(config, section_summaries, order_results,
                                    base_cap, ot_cap, load, sections, horizon)
        # MTS 备料能力缺口：备料池在计划期内消耗不完
        for s in config.sections:
            if s.strategy == ProductionStrategy.MTS:
                end_f = mts_cursor.get(s.section_id, 0.0)
                if end_f > horizon + EPS:
                    alerts.append(FactoryAlert(
                        level="warning", category="overload",
                        title=f"{s.name} 备料任务在计划期内无法完成",
                        detail=(f"备料池按当前节拍将延续到第{ceil(end_f)}天（计划期 {horizon} 天），"
                                f"建议扩大备料产能或提前投放订单"),
                        section_id=s.section_id,
                    ))
        # ---------- 7. 产出（按工序生产窗口均摊订单量，乘良品率） ---------- #
        order_result_by_id = {o.order_id: o for o in order_results}
        daily_finished = [0] * horizon
        daily_good = [0] * horizon
        order_good: Dict[str, int] = {}
        for order in config.orders:
            res = order_result_by_id[order.order_id]
            last_op = max(res.ops, key=lambda x: x.op_no)
            sec = sections[last_op.section_id]
            y = sec.yield_rate
            start_c = max(last_op.start_day, 0)
            end_c = min(last_op.end_day, horizon - 1)
            prod_days = [d for d in range(start_c, end_c + 1) if is_workday(sec.workshop_id, d)]
            if not prod_days:
                prod_days = [max(0, end_c)]
            alloc = _distribute(order.quantity, len(prod_days))
            ogood = 0
            for d, q in zip(prod_days, alloc):
                daily_finished[d] += q
                g = round(q * y)
                daily_good[d] += g
                ogood += g
            order_good[order.order_id] = ogood

        daily_output: List[OutputPoint] = []
        cum = 0
        for d in range(horizon):
            cum += daily_finished[d]
            daily_output.append(OutputPoint(
                day=d, output_qty=daily_finished[d], good_qty=daily_good[d],
                scrap_qty=daily_finished[d] - daily_good[d], cumulative=cum,
            ))

        # 工段级产出（计划期累计流过总量 × 良品率）
        sec_planned = {sid: 0 for sid in sections}
        for order in config.orders:
            res = order_result_by_id[order.order_id]
            for op in res.ops:
                sec_planned[op.section_id] += order.quantity
        section_outputs: List[SectionOutput] = []
        for s in config.sections:
            planned = sec_planned[s.section_id]
            good = round(planned * s.yield_rate)
            section_outputs.append(SectionOutput(
                section_id=s.section_id, name=s.name, planned_qty=planned,
                good_qty=good, scrap_qty=planned - good, yield_rate=s.yield_rate,
            ))

        # ---------- 8. PO 工单全生命周期 ---------- #
        production_orders: List[ProductionOrderResult] = []
        for order in config.orders:
            res = order_result_by_id[order.order_id]
            first_op = min(res.ops, key=lambda x: x.op_no)
            last_op = max(res.ops, key=lambda x: x.op_no)
            last_sec = sections[last_op.section_id]
            good = order_good.get(order.order_id, round(order.quantity * last_sec.yield_rate))
            status = "delayed" if res.delay_days > 0 else "completed"
            po_ops: List[PoOpResult] = []
            prev_end_day = order.release_day  # 首工序相对下达日
            for op in sorted(res.ops, key=lambda x: x.op_no):
                sec = sections[op.section_id]
                g = round(order.quantity * sec.yield_rate)
                wait = max(0, op.start_day - prev_end_day)
                po_ops.append(PoOpResult(
                    op_no=op.op_no, name=op.name, section_id=op.section_id,
                    section_name=op.section_name, start_day=op.start_day, end_day=op.end_day,
                    qty=order.quantity, good_qty=g, scrap_qty=order.quantity - g,
                    status="delayed" if op.end_day >= horizon else "completed",
                    wait_days=wait,
                ))
                prev_end_day = op.end_day
            production_orders.append(ProductionOrderResult(
                po_id=f"PO-{order.order_id}", order_id=order.order_id,
                product_name=res.product_name, quantity=order.quantity,
                release_day=order.release_day, start_day=first_op.start_day,
                completion_day=res.completion_day, due_day=order.due_day,
                status=status, on_time=res.on_time, good_qty=good,
                scrap_qty=order.quantity - good, current_section=last_sec.name, ops=po_ops,
            ))

        # ---------- 9. 工序间流转记录 ---------- #
        transfers: List[TransferRecord] = []
        for order in config.orders:
            res = order_result_by_id[order.order_id]
            ops_sorted = sorted(res.ops, key=lambda x: x.op_no)
            for i in range(len(ops_sorted) - 1):
                a, b = ops_sorted[i], ops_sorted[i + 1]
                transfers.append(TransferRecord(
                    transfer_id=f"TR-{order.order_id}-{a.op_no}",
                    order_id=order.order_id, product_name=res.product_name,
                    from_section_id=a.section_id, from_section_name=a.section_name,
                    to_section_id=b.section_id, to_section_name=b.section_name,
                    qty=order.quantity, depart_day=a.end_day, arrive_day=b.start_day,
                ))

        # ---------- 9b. 货物出库单（末道工序完工 → 成品出库，闭合下达→流转→出库链条） ---------- #
        outbound_orders: List[OutboundOrder] = []
        for idx, order in enumerate(config.orders, start=1):
            res = order_result_by_id[order.order_id]
            good = order_good.get(order.order_id, 0)
            shipped = res.completion_day < horizon  # 计划期内完工才能出库
            outbound_orders.append(OutboundOrder(
                outbound_id=f"OB-{idx:04d}",
                order_id=order.order_id, po_id=f"PO-{order.order_id}",
                product_name=res.product_name, quantity=order.quantity, good_qty=good,
                outbound_day=min(res.completion_day, horizon - 1),
                on_time=res.on_time, warehouse="成品仓",
                status="shipped" if shipped else "pending",
            ))

        # ---------- 9c. 卡点检测（过载 / WIP 积压 / 工序等待 三信号） ---------- #
        blocking_points = self._blocking_points(
            config, sections, workshops, base_cap, load, wip_matrix, section_wait,
            order_results, horizon,
        )

        # ---------- 10. 工人花名册 ---------- #
        workforce = generate_workforce(config, load, is_workday, horizon)

        kpis = self._kpis(section_summaries, order_results, wip_curve, load, base_cap, horizon,
                          config, production_orders, daily_finished, daily_good,
                          blocking_points, outbound_orders, wip_matrix, section_wait)

        return FactorySimResult(
            simulation_id=str(uuid.uuid4()),
            engine_version=self.VERSION,
            horizon_days=horizon,
            workshop_count=len(config.workshops),
            section_count=len(config.sections),
            order_count=len(config.orders),
            kpis=kpis,
            sections=section_summaries,
            orders=order_results,
            order_section_loads=order_section_loads,
            wip_curve=wip_curve,
            alerts=alerts,
            workforce=workforce,
            daily_output=daily_output,
            section_outputs=section_outputs,
            production_orders=production_orders,
            transfers=transfers,
            blocking_points=blocking_points,
            outbound_orders=outbound_orders,
        )

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate(config, workshops, sections, routings, horizon) -> None:
        for s in config.sections:
            if s.workshop_id not in workshops:
                raise ValueError(f"工段 {s.name}({s.section_id}) 引用了不存在的车间 {s.workshop_id}")
        for r in config.routings:
            for op in r.operations:
                if op.section_id not in sections:
                    raise ValueError(f"工艺路线 {r.routing_id} 工序 {op.name} 引用了不存在的工段 {op.section_id}")
        for o in config.orders:
            if o.product_id not in routings:
                raise ValueError(f"订单 {o.order_id} 的产品 {o.product_id} 没有工艺路线")
            if o.release_day >= horizon:
                raise ValueError(f"订单 {o.order_id} 投放日({o.release_day})超出计划期({horizon}天)")
            if o.due_day < o.release_day:
                raise ValueError(f"订单 {o.order_id} 交期日({o.due_day})早于投放日({o.release_day})")

    # ------------------------------------------------------------------ #
    # 订单排程
    # ------------------------------------------------------------------ #
    def _schedule_order(
        self,
        order: OrderInput,
        ops: list,
        mts_pool: Dict[str, float],
        mts_cursor: Dict[str, float],
        base_cap, ot_cap, load, sections, is_workday, nominal_daily, horizon,
    ) -> Dict[int, dict]:
        """
        返回 {op_no: op item(含 start_day/end_day)}
        MTS 工序：按产能节拍消耗池（负荷恒定=均衡生产），池清空即完成
        MTO 工序：交期倒排（ALAP）；放不下则整单正排回退，溢出记过载
        """
        sched: Dict[int, dict] = {}
        prev_end = float(order.release_day)

        # Pass A：MTS 工序 —— 产能节拍流
        for item in ops:
            sid = item["section"].section_id
            if item["section"].strategy == ProductionStrategy.MTS:
                start_float = max(prev_end, mts_cursor.get(sid, 0.0), float(order.release_day))
                start_day, end_day, end_float = self._consume_mts(
                    sid, item["work_hours"], start_float,
                    base_cap, load, sections[sid].workshop_id,
                    is_workday, nominal_daily, horizon,
                )
                mts_cursor[sid] = end_float
                item["start_day"] = start_day
                item["end_day"] = end_day
                sched[item["op"].op_no] = item
                prev_end = end_float + item["op"].move_hours / 24.0
            else:
                item["_earliest"] = prev_end  # MTO 工序在 Pass B 倒排

        # Pass B：MTO 工序倒排
        mto_items = [it for it in ops if it["section"].strategy != ProductionStrategy.MTS]
        if mto_items:
            anchor = float(min(order.due_day, horizon - 1))  # 最晚完工日（含当天）
            placements: List[Tuple[str, int, float]] = []
            feasible = True
            for item in reversed(mto_items):
                sid = item["section"].section_id
                # 日粒度：当天内可用即可当天开工（end_float 为日内小数位置）
                earliest = int(floor(item["_earliest"] + EPS))
                res = self._pour_backward(
                    sid, item["work_hours"], int(floor(anchor)), earliest,
                    ot_cap, load, horizon,
                )
                if res is None:  # 倒排放不下
                    feasible = False
                    for p_sid, p_day, p_hours in placements:  # 回滚
                        load[p_sid][p_day] -= p_hours
                    break
                start_day, end_day, placed = res
                placements.extend(placed)
                item["start_day"], item["end_day"] = start_day, end_day
                sched[item["op"].op_no] = item
                gap = 0 if item["op"].move_hours < 24 else ceil(item["op"].move_hours / 24)
                anchor = float(start_day - gap)

            if not feasible:
                # 正排回退：从最早可行日开始；容量耗尽时剩余工时延伸到计划期外
                # （完工日延后 + 延期告警如实反映，不伪造负荷尖峰）
                cursor: Optional[int] = None
                for item in mto_items:
                    sid = item["section"].section_id
                    from_day = int(floor(item["_earliest"] + EPS))
                    if cursor is not None:
                        from_day = max(from_day, cursor)
                    start_day, end_day = self._pour_forward(
                        sid, item["work_hours"], from_day, ot_cap, load, horizon
                    )
                    item["start_day"], item["end_day"] = start_day, end_day
                    sched[item["op"].op_no] = item
                    gap = 0 if item["op"].move_hours < 24 else ceil(item["op"].move_hours / 24)
                    cursor = end_day + gap
        return sched

    def _consume_mts(self, sid, work_hours, start_float, base_cap, load,
                     workshop_id, is_workday, nominal_daily, horizon):
        """MTS 池按产能节拍消耗：每个工作日最多消耗基准产能（负荷恒定=均衡生产）。
        池清空即完成；总工时超出计划期产能时按名义产能虚拟延展（返回超出计划期的结束日）。"""
        remaining = work_hours
        cap_day = nominal_daily.get(sid, 8.0)
        d = max(0, int(floor(start_float)))
        frac = start_float - floor(start_float)  # 起始日已过比例
        first_day: Optional[int] = None
        end_float = start_float
        last_day = d
        guard = 0
        while remaining > EPS and guard < 600:
            guard += 1
            if d < horizon:
                base = base_cap[sid][d]
            else:  # 超出计划期：名义产能 + 车间日历
                base = cap_day if is_workday(workshop_id, d) else 0.0
            if base > EPS:
                avail = base * (1.0 - frac) if first_day is None and d == int(floor(start_float)) else base
                if avail > EPS:
                    take = min(remaining, avail)
                    if d < horizon:
                        load[sid][d] += take
                    if first_day is None:
                        first_day = d
                    remaining -= take
                    last_day = d
                    day_start_frac = frac if d == int(floor(start_float)) else 0.0
                    end_float = float(d) + day_start_frac + take / base
            d += 1
        if first_day is None:
            first_day = last_day = max(0, int(floor(start_float)))
        return first_day, last_day, end_float

    def _pour_backward(self, sid, work_hours, latest_day, earliest_day,
                       ot_cap, load, horizon):
        """从 latest_day 向前倒排工时；放不下返回 None"""
        remaining = work_hours
        placed: List[Tuple[str, int, float]] = []
        start_day = end_day = None
        d = min(latest_day, horizon - 1)
        while remaining > EPS and d >= max(earliest_day, 0):
            if is_workday_in_cap(ot_cap, sid, d):
                avail = ot_cap[sid][d] - load[sid][d]
                if avail > EPS:
                    take = min(remaining, avail)
                    load[sid][d] += take
                    placed.append((sid, d, take))
                    remaining -= take
                    if end_day is None:
                        end_day = d
                    start_day = d
            d -= 1
        if remaining > EPS:
            for p_sid, p_day, p_hours in placed:
                load[p_sid][p_day] -= p_hours
            return None
        if start_day is None:  # 工时为 0
            start_day = end_day = max(earliest_day, 0)
        return start_day, end_day, placed

    def _pour_forward(self, sid, work_hours, from_day, ot_cap, load, horizon):
        """从 from_day 向后正排。容量耗尽 → 剩余工时延伸到计划期外（完工日延后）。"""
        remaining = work_hours
        start_day = end_day = None
        d = max(from_day, 0)
        while remaining > EPS and d < horizon:
            if ot_cap[sid][d] > EPS:
                avail = ot_cap[sid][d] - load[sid][d]
                if avail > EPS:
                    take = min(remaining, avail)
                    load[sid][d] += take
                    remaining -= take
                    if start_day is None:
                        start_day = d
                    end_day = d
            d += 1
        if remaining > EPS:
            # 计划期内产能已饱和 → 剩余工时延伸到计划期之外（不伪造负荷尖峰，
            # 通过完工日延后、延期告警如实反映）
            workday_caps = [c for c in ot_cap[sid] if c > EPS]
            daily = sum(workday_caps) / len(workday_caps) if workday_caps else 8.0
            ext = ceil(remaining / daily)
            if end_day is not None:
                end_day = end_day + ext
            else:
                start_day = end_day = max(from_day, horizon - 1) + ext
        if start_day is None:
            start_day = end_day = max(from_day, 0)
        return start_day, end_day

    # ------------------------------------------------------------------ #
    # 汇总
    # ------------------------------------------------------------------ #
    def _summarize_sections(self, config, sections, workshops, base_cap, load,
                            is_workday, horizon, wip_matrix=None) -> List[SectionSummary]:
        summaries: List[SectionSummary] = []
        for s in config.sections:
            ws = workshops[s.workshop_id]
            series: List[SectionDayLoad] = []
            peak_rate, peak_day = 0.0, 0
            ot_used = 0.0
            for d in range(horizon):
                cap = base_cap[s.section_id][d]
                ld = load[s.section_id][d]
                workday = cap > 0
                rate = ld / cap if cap > EPS else (999.0 if ld > EPS else 0.0)
                if workday and rate > peak_rate:
                    peak_rate, peak_day = rate, d
                if workday:
                    ot_used += max(0.0, ld - cap)
                series.append(SectionDayLoad(
                    day=d, load_hours=round(ld, 1), capacity_hours=round(cap, 1),
                    load_rate=round(rate, 2), is_workday=workday,
                    wip_qty=(wip_matrix[s.section_id][d] if wip_matrix else 0),
                ))
            total_load = sum(load[s.section_id])
            total_cap = sum(base_cap[s.section_id])
            avg_rate = total_load / total_cap if total_cap > EPS else 0.0
            summaries.append(SectionSummary(
                section_id=s.section_id, name=s.name,
                workshop_id=s.workshop_id, workshop_name=ws.name,
                strategy=s.strategy,
                workers=s.workers, machines=s.machines,
                shifts_per_day=s.shifts_per_day, hours_per_shift=s.hours_per_shift,
                efficiency=s.efficiency,
                total_load_hours=round(total_load, 1),
                total_capacity_hours=round(total_cap, 1),
                avg_load_rate=round(avg_rate, 3),
                peak_load_rate=round(peak_rate, 2),
                peak_day=peak_day,
                is_bottleneck=peak_rate > 1.0 + EPS,
                overtime_used_hours=round(ot_used, 1),
                series=series,
            ))
        return summaries

    @staticmethod
    def _order_section_loads(order_op_hours, sections, load) -> List[OrderSectionLoad]:
        section_totals = {sid: sum(days) for sid, days in load.items()}
        rows: List[OrderSectionLoad] = []
        for order_id, sid, hours in order_op_hours:
            total = section_totals.get(sid, 0.0)
            rows.append(OrderSectionLoad(
                order_id=order_id, section_id=sid, section_name=sections[sid].name,
                work_hours=round(hours, 1),
                share_pct=round(hours / total * 100, 1) if total > EPS else 0.0,
            ))
        return rows

    @staticmethod
    def _wip_curve(order_results, horizon) -> List[WipPoint]:
        curve: List[WipPoint] = []
        for d in range(horizon):
            active = [
                o for o in order_results
                if o.ops and o.ops[0].start_day <= d <= o.completion_day
            ]
            curve.append(WipPoint(
                day=d,
                wip_qty=sum(o.quantity for o in active),
                active_orders=len(active),
            ))
        return curve

    def _build_alerts(self, config, summaries, order_results,
                      base_cap, ot_cap, load, sections, horizon) -> List[FactoryAlert]:
        alerts: List[FactoryAlert] = []

        # 过载告警（取最严重的前 12 条）
        overloads = []
        for s in config.sections:
            sid = s.section_id
            ot_factor = 1.0 + s.max_overtime_pct if config.overtime_allowed else 1.0
            for d in range(horizon):
                cap = base_cap[sid][d]
                if cap <= EPS:
                    continue
                rate = load[sid][d] / cap
                if rate > 1.0 + EPS:
                    overloads.append((rate, s, d, rate > ot_factor + EPS))
        overloads.sort(key=lambda x: -x[0])
        for rate, s, d, beyond_ot in overloads[:12]:
            if beyond_ot:
                alerts.append(FactoryAlert(
                    level="critical", category="overload",
                    title=f"{s.name} 第{d + 1}天严重过载 {rate * 100:.0f}%",
                    detail=(f"即使加班 {s.max_overtime_pct * 100:.0f}% 仍无法消化，"
                            f"需外协或调整排产；负荷 {load[sid][d]:.0f}h / 产能 {base_cap[sid][d]:.0f}h"),
                    section_id=s.section_id, day=d,
                ))
            else:
                alerts.append(FactoryAlert(
                    level="warning", category="overload",
                    title=f"{s.name} 第{d + 1}天超负荷 {rate * 100:.0f}%",
                    detail=f"需要加班消化（加班上限内）；负荷 {load[sid][d]:.0f}h / 产能 {base_cap[sid][d]:.0f}h",
                    section_id=s.section_id, day=d,
                ))

        # 订单延期
        for o in order_results:
            if not o.on_time:
                alerts.append(FactoryAlert(
                    level="critical" if o.delay_days >= 3 else "warning",
                    category="delay",
                    title=f"订单 {o.order_id} 预计延期 {o.delay_days} 天",
                    detail=(f"{o.product_name} ×{o.quantity}：交期第{o.due_day + 1}天，"
                            f"仿真完成第{o.completion_day + 1}天（优先级 {o.priority.value}）"),
                    order_id=o.order_id,
                ))

        # 瓶颈工段
        for s in summaries:
            if s.is_bottleneck:
                alerts.append(FactoryAlert(
                    level="warning", category="bottleneck",
                    title=f"瓶颈工段：{s.name}（峰值负荷 {s.peak_load_rate * 100:.0f}%）",
                    detail=(f"峰值出现在第{s.peak_day + 1}天；平均负荷 {s.avg_load_rate * 100:.0f}%，"
                            f"加班 {s.overtime_used_hours:.0f}h；建议增员/增设备或拆分批次"),
                    section_id=s.section_id,
                ))

        # 闲置工段
        for s in summaries:
            if s.avg_load_rate < 0.35 and s.total_capacity_hours > 0:
                alerts.append(FactoryAlert(
                    level="info", category="idle",
                    title=f"{s.name} 负荷偏低（平均 {s.avg_load_rate * 100:.0f}%）",
                    detail="产能闲置，可考虑合并班次、支援其他工段或承接备料预投",
                    section_id=s.section_id,
                ))

        # 负荷分化（直接回应"不同订单对不同部门负荷不一样"）
        rates = [s.avg_load_rate for s in summaries if s.total_capacity_hours > 0]
        if rates and (max(rates) - min(rates)) > 0.5:
            hi = max(summaries, key=lambda s: s.avg_load_rate)
            lo = min(summaries, key=lambda s: s.avg_load_rate)
            alerts.append(FactoryAlert(
                level="info", category="imbalance",
                title="订单结构导致工段负荷显著分化",
                detail=(f"{hi.name} 平均负荷 {hi.avg_load_rate * 100:.0f}%，"
                        f"而 {lo.name} 仅 {lo.avg_load_rate * 100:.0f}% —— "
                        f"不同订单对各部门的负荷拉动不一致，可调整订单投放节奏"),
            ))
        return alerts

    # ------------------------------------------------------------------ #
    # 卡点检测（过载 / WIP 积压 / 工序等待 三信号 → 综合严重度排行）
    # ------------------------------------------------------------------ #
    def _blocking_points(self, config, sections, workshops, base_cap, load,
                         wip_matrix, section_wait, order_results, horizon) -> List[BlockingPoint]:
        # 经此工段且延期的订单数
        delayed_by_section: Dict[str, int] = {sid: 0 for sid in sections}
        for res in order_results:
            if not res.on_time:
                for sid in {op.section_id for op in res.ops}:
                    delayed_by_section[sid] += 1

        # 逐工段采集三类原始信号
        raw = []
        for s in config.sections:
            sid = s.section_id
            peak_rate, peak_day = 0.0, 0
            overload_days = 0
            for d in range(horizon):
                cap = base_cap[sid][d]
                if cap <= EPS:
                    continue
                rate = load[sid][d] / cap
                if rate > peak_rate:
                    peak_rate, peak_day = rate, d
                if rate > 1.0 + EPS:
                    overload_days += 1
            wip_peak = max(wip_matrix[sid]) if wip_matrix[sid] else 0
            waits = section_wait.get(sid, [])
            avg_wait = sum(waits) / len(waits) if waits else 0.0
            raw.append({
                "s": s, "peak_rate": peak_rate, "peak_day": peak_day,
                "overload_days": overload_days, "wip_peak": wip_peak,
                "avg_wait": avg_wait, "delayed": delayed_by_section.get(sid, 0),
            })

        max_wip = max((r["wip_peak"] for r in raw), default=0)
        max_wait = max((r["avg_wait"] for r in raw), default=0.0)

        # 归一化到 0~100 后加权：severity = 0.5×过载 + 0.3×积压 + 0.2×等待
        for r in raw:
            overload_norm = min(100.0, max(0.0, r["peak_rate"] - 1.0) * 100.0)
            wip_norm = (r["wip_peak"] / max_wip * 100.0) if max_wip > 0 else 0.0
            wait_norm = (r["avg_wait"] / max_wait * 100.0) if max_wait > EPS else 0.0
            r["severity"] = round(0.5 * overload_norm + 0.3 * wip_norm + 0.2 * wait_norm, 1)
            signals = {"overload": overload_norm, "wip_buildup": wip_norm, "process_wait": wait_norm}
            r["btype"] = max(signals, key=signals.get)

        raw.sort(key=lambda r: -r["severity"])
        points: List[BlockingPoint] = []
        rank = 0
        for r in raw:
            if r["severity"] <= EPS and r["overload_days"] == 0 and r["wip_peak"] == 0:
                continue
            rank += 1
            s = r["s"]
            points.append(BlockingPoint(
                rank=rank, section_id=s.section_id, section_name=s.name,
                workshop_name=workshops[s.workshop_id].name,
                blocking_type=r["btype"], severity=r["severity"],
                peak_day=r["peak_day"], peak_load_rate=round(r["peak_rate"], 2),
                overload_days=r["overload_days"], wip_peak=r["wip_peak"],
                avg_wait_days=round(r["avg_wait"], 1),
                delayed_orders=r["delayed"], detail=self._blocking_detail(r),
            ))
        return points

    @staticmethod
    def _blocking_detail(r) -> str:
        parts = []
        if r["overload_days"] > 0:
            parts.append(f"过载 {r['overload_days']} 天，峰值负荷 {r['peak_rate'] * 100:.0f}%（第{r['peak_day'] + 1}天）")
        if r["wip_peak"] > 0:
            parts.append(f"WIP 积压峰值 {r['wip_peak']} 件")
        if r["avg_wait"] > EPS:
            parts.append(f"工序开工前平均等待 {r['avg_wait']:.1f} 天")
        if r["delayed"] > 0:
            parts.append(f"{r['delayed']} 张订单经此工段后延期")
        return "；".join(parts) if parts else "负荷正常，无明显卡点"

    @staticmethod
    def _kpis(summaries, order_results, wip_curve, load, base_cap, horizon,
              config, production_orders, daily_finished, daily_good,
              blocking_points, outbound_orders, wip_matrix, section_wait) -> FactoryKPIs:
        total_load = sum(s.total_load_hours for s in summaries)
        total_cap = sum(s.total_capacity_hours for s in summaries)
        peak = max((s.peak_load_rate for s in summaries), default=0.0)
        rates = [s.avg_load_rate for s in summaries if s.total_capacity_hours > 0]
        on_time = sum(1 for o in order_results if o.on_time)
        total_output = sum(daily_finished)
        good_output = sum(daily_good)
        scrap_output = total_output - good_output
        headcount = sum(s.workers * s.shifts_per_day for s in config.sections)
        # ---- 全过程 / 卡点指标 ----
        blocking_point_count = sum(1 for bp in blocking_points if bp.overload_days > 0)
        max_section_wip = max((max(row) for row in wip_matrix.values()), default=0) if wip_matrix else 0
        total_outbound = sum(o.quantity for o in outbound_orders if o.status == "shipped")
        pending_outbound = sum(1 for o in outbound_orders if o.status == "pending")
        all_waits = [w for ws in section_wait.values() for w in ws]
        avg_process_wait = round(sum(all_waits) / len(all_waits), 2) if all_waits else 0.0
        return FactoryKPIs(
            total_work_hours=round(total_load, 1),
            total_capacity_hours=round(total_cap, 1),
            avg_load_rate=round(total_load / total_cap, 3) if total_cap > EPS else 0.0,
            peak_load_rate=round(peak, 2),
            on_time_rate=round(on_time / len(order_results), 3) if order_results else 1.0,
            delayed_orders=len(order_results) - on_time,
            bottleneck_sections=sum(1 for s in summaries if s.is_bottleneck),
            wip_peak=max((p.wip_qty for p in wip_curve), default=0),
            imbalance_index=round(max(rates) - min(rates), 3) if rates else 0.0,
            overtime_hours=round(sum(s.overtime_used_hours for s in summaries), 1),
            total_output=total_output,
            good_output=good_output,
            scrap_output=scrap_output,
            avg_yield_rate=round(good_output / total_output, 3) if total_output else 1.0,
            headcount=headcount,
            po_completed=sum(1 for po in production_orders if po.status == "completed"),
            po_delayed=sum(1 for po in production_orders if po.status == "delayed"),
            blocking_point_count=blocking_point_count,
            max_section_wip=max_section_wip,
            total_outbound=total_outbound,
            pending_outbound=pending_outbound,
            avg_process_wait=avg_process_wait,
        )


def is_workday_in_cap(ot_cap, sid: str, day: int) -> bool:
    return ot_cap[sid][day] > EPS


def _skill_factor(avg_skill: float) -> float:
    """技能系数：以 L3 为基准 1.0，随平均技能等级单调递增（每级 ±5%），钳制 [0.75, 1.15]。

    L1≈0.90 / L2≈0.95 / L3=1.00 / L4≈1.05 / L5≈1.10 —— 高技能工段产能更高。
    纯函数，便于独立单测。
    """
    return max(0.75, min(1.15, 1.0 + 0.05 * (avg_skill - 3.0)))


def _distribute(qty: int, n: int) -> List[int]:
    """把 qty 均分到 n 个桶，余数从前向后分配。"""
    if n <= 0:
        return []
    base, rem = divmod(qty, n)
    return [base + (1 if i < rem else 0) for i in range(n)]
