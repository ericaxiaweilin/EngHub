"""预计工时的唯一口径：只认厂里声明过的产能，没有出处就不给时间。

为什么要单独建这个模块：现行 961 条排程任务里 881 条不足 1 小时，根因是
routings.steps 的 430 个机械工步里没有一个带工时（standard_hours/time_min/
standard_time 全缺），排程就落到 `0 秒/件 × 数量 + 300 秒换型` 的兜底上。
那个兜底不是"缺数据"，是**编了一个数**：它让 1,180 台的跑步机单看起来 5 分钟做完，
交期风险、产能负荷、闲置成本全部跟着失真。

这里只承认三类出处，按"越具体越优先"排：
① 工步自己声明的工时（route_declared_hours）；
② 厂里落到 line_profiles 的线产能（declared_line_capacity，来源=用户口述）；
③ stations.capacity_per_hour 的工位产能（station_declared_rate）。
三类都给不出时返回 None，让调用方把"没有依据"当成一条要点名的读数，
而不是回落到某个默认值。
"""
from __future__ import annotations

import json

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

BASIS_ROUTE = "route_declared_hours"
BASIS_LINE = "declared_line_capacity"
BASIS_STATION = "station_declared_rate"  # 已不作工时来源；仅保留给产能对撞报告标注
BASIS_NONE = "no_time_basis"

# 线产能与工位瓶颈对撞到这个倍数以外就点名报冲突：同一厂区里
# "一天 300 台"和"焊接工位每小时 4 件"不可能同时成立，需要 IE 来裁哪条是真的。
CONFLICT_RATIO = float(2.0)

STATION_RATES_SQL = """
    SELECT station_code, capacity_per_hour, capacity, capacity_unit, station_name
    FROM stations
    WHERE factory_id = :fid
      AND capacity_per_hour IS NOT NULL
      AND capacity_per_hour > 0
"""

LINE_RATES_SQL = """
    SELECT line_code, line_group, hours_per_day, units_per_day, crew_size,
           parallel_lines, group_units_per_day, default_model,
           can_make_models, cannot_make_models, source
    FROM line_profiles
    WHERE factory_id = :fid
      AND is_active
      AND units_per_day > 0
      AND hours_per_day > 0
"""

# 每个机种在制还欠多少台：预计完工只能用"剩余量 ÷ 产能"，不是计划总量。
OPEN_DEMAND_SQL = """
    SELECT wo.product_id AS model,
           SUM(GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0)) AS remaining
    FROM work_orders wo
    WHERE wo.factory_id = :fid
      AND wo.wo_type IN ('master', 'component')
      AND wo.status IN ('pending', 'released', 'in_progress')
    GROUP BY 1
    HAVING SUM(GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0)) > 0
"""

ROUTE_STEPS_SQL = """
    SELECT r.product_id AS model,
           s ->> 'name' AS op_name,
           s ->> 'station' AS station,
           s ->> 'work_center' AS work_center,
           COALESCE((s ->> 'standard_hours')::numeric, 0)::float AS standard_hours,
           COALESCE((s ->> 'time_min')::numeric, 0)::float AS time_min,
           COALESCE((s ->> 'standard_time')::numeric, 0)::float AS standard_time
    FROM routings r
    CROSS JOIN LATERAL jsonb_array_elements(r.steps) s
    WHERE r.factory_id = :fid
      AND r.is_active
"""


def seconds_from_hourly_rate(pieces_per_hour: Optional[float]) -> Optional[float]:
    """把"每小时几件"换成"每件几秒"；非正数一律视为没有依据。"""
    try:
        rate = float(pieces_per_hour or 0)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return 3600.0 / rate


def declared_step_seconds(step: Dict[str, Any]) -> Optional[float]:
    """工步自己声明的单件工时（秒/件）。没有声明就返回 None，不给默认值。"""
    hours = step.get("standard_hours")
    if hours is not None and float(hours or 0) > 0:
        return float(hours) * 3600.0
    minutes = step.get("time_min")
    if minutes is not None and float(minutes or 0) > 0:
        return float(minutes) * 60.0
    seconds = step.get("standard_time")
    if seconds is not None and float(seconds or 0) > 0:
        # routings.steps 历史口径：standard_time 为秒/件
        return float(seconds)
    return None


def line_models(line: Dict[str, Any]) -> List[str]:
    """一条线能做的机种。cannot_make_models 是反向声明，优先级最高。"""
    blocked = {str(m) for m in (line.get("cannot_make_models") or [])}
    models = {str(m) for m in (line.get("can_make_models") or [])}
    default = line.get("default_model")
    if default:
        models.add(str(default))
    return sorted(models - blocked)


class TimeBasis:
    """一个厂区的工时口径集合：线产能、工位产能、按优先级解析单件工时。"""

    def __init__(self, *, station_rates: Dict[str, float], lines: List[Dict[str, Any]]):
        self.station_rates = {str(k): float(v) for k, v in station_rates.items()}
        self.lines = lines
        # 同一机种可能有多条线能做（bike 组两条）。归属优先于快：
        # 厂里把 A-50-04-F 放在跑步机线上跑，预计完工就得按跑步机线的节拍报，
        # 按"哪条线更快"报会把 4 天报成 1.4 天 —— 那是把可能性当事实。
        # 只有两条线都不是归属线时，才在可做的线里取快的。
        self.line_by_model: Dict[str, Dict[str, Any]] = {}
        for line in lines:
            seconds = seconds_from_hourly_rate(
                float(line["units_per_day"]) / float(line["hours_per_day"])
            )
            if seconds is None:
                continue
            enriched = {**line, "seconds_per_piece": seconds, "models": line_models(line)}
            for model in enriched["models"]:
                current = self.line_by_model.get(model)
                if current is None:
                    self.line_by_model[model] = enriched
                    continue
                mine_is_home = str(enriched.get("default_model") or "") == model
                theirs_is_home = str(current.get("default_model") or "") == model
                if mine_is_home and not theirs_is_home:
                    self.line_by_model[model] = enriched
                elif mine_is_home == theirs_is_home and seconds < current["seconds_per_piece"]:
                    self.line_by_model[model] = enriched

    def seconds_per_piece(
        self, *, model: Optional[str], station: Optional[str], step: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[float], str]:
        """这一道工序每件几秒 —— 只认 IE 给的工时和厂里声明的线产能。

        `stations.capacity_per_hour` 现在**不再当工时来源**（用户 10-06 定口径：IE/HR 为准）：
        那一列单位没人定义过，28 个工位、15 个不同取值，同一行焊接能读成
        22 / 44 / 924 / 2,400 台/天，跨 100 倍。它只留下做产能对撞的证据（bottleneck_rate），
        谁拿它算过时长，读数里就该看不见它。
        """
        declared = declared_step_seconds(step) if step else None
        if declared:
            return declared, BASIS_ROUTE
        line = self.line_by_model.get(str(model)) if model else None
        if line:
            return float(line["seconds_per_piece"]), BASIS_LINE
        return None, BASIS_NONE

    def bottleneck_rate(self, stations: List[str]) -> Optional[float]:
        rates = [self.station_rates[str(s)] for s in stations if str(s) in self.station_rates]
        return min(rates) if rates else None

    def order_flow_estimate(
        self, *, model: Optional[str], qty: float, steps: int
    ) -> Optional[Dict[str, Any]]:
        """流水线口径的整单工时与预计完工天数。

        天数按这条线自己声明的"每天几小时"换算（跑步机线一天 11 小时），不按 24 小时 ——
        按 24 小时会把 3.9 天报成 1.8 天，交期看着宽裕、实际差一倍。
        排程器按"一单一工位串行"放置任务，任务行求和会比这里大好几倍，那是批次
        串行假设、不是产能量；预计完工要用这个数，不能用任务行求和。
        """
        line = self.line_by_model.get(str(model)) if model else None
        if not line or qty <= 0:
            return None
        takt = float(line["seconds_per_piece"])
        hours_per_day = float(line.get("hours_per_day") or 24.0) or 24.0
        working_seconds = qty * takt + max(0, int(steps) - 1) * takt
        return {
            "line_code": str(line["line_code"]),
            "hours_per_day": round(hours_per_day, 2),
            "working_seconds": round(working_seconds, 1),
            "working_hours": round(working_seconds / 3600.0, 2),
            "estimated_days": round(working_seconds / 3600.0 / hours_per_day, 2),
        }

    def flow_order_seconds(self, *, model: Optional[str], qty: float, steps: int) -> Optional[float]:
        estimate = self.order_flow_estimate(model=model, qty=qty, steps=steps)
        return float(estimate["working_seconds"]) if estimate else None


async def load_time_basis(db, factory_id: str) -> TimeBasis:
    station_rows = (await db.execute(text(STATION_RATES_SQL), {"fid": factory_id})).mappings().all()
    line_rows = (await db.execute(text(LINE_RATES_SQL), {"fid": factory_id})).mappings().all()
    return TimeBasis(
        station_rates={
            str(r["station_code"]): float(r["capacity_per_hour"])
            for r in station_rows
            if r["station_code"]
        },
        lines=[dict(r) for r in line_rows],
    )


def capacity_conflicts(
    basis: TimeBasis, route_steps: List[Dict[str, Any]], open_demand: Dict[str, float]
) -> List[Dict[str, Any]]:
    """同一机种上"线产能"与"工位瓶颈"对撞，谁都不肯让步时点名报出来。"""
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for row in route_steps:
        by_model.setdefault(str(row["model"]), []).append(row)

    findings: List[Dict[str, Any]] = []
    for model, steps in sorted(by_model.items()):
        line = basis.line_by_model.get(model)
        if not line:
            continue
        stations = [str(s.get("station") or s.get("work_center") or "") for s in steps]
        stations = [s for s in stations if s]
        bottleneck = basis.bottleneck_rate(stations)
        if not bottleneck:
            continue
        line_rate = float(line["units_per_day"]) / float(line["hours_per_day"])
        ratio = max(line_rate, bottleneck) / max(min(line_rate, bottleneck), 1e-9)
        if ratio < CONFLICT_RATIO:
            continue
        # 同一个工位可能出现在好几道工序上，点名一次就够（报三遍 ST-JG-01 不像结论）
        slow_seen: List[Dict[str, Any]] = []
        slow_codes = set()
        for st in stations:
            if basis.station_rates.get(st) != bottleneck or st in slow_codes:
                continue
            slow_codes.add(st)
            slow_seen.append({
                "station": st,
                "op": next((str(x.get("op_name")) for x in steps
                            if str(x.get("station") or x.get("work_center") or "") == st), ""),
                "pieces_per_hour": basis.station_rates.get(st),
            })
        remaining = float(open_demand.get(model, 0) or 0)
        hours_per_day = float(line.get("hours_per_day") or 24.0) or 24.0
        findings.append({
            "model": model,
            "line_code": line["line_code"],
            "hours_per_day": round(hours_per_day, 2),
            "line_pieces_per_hour": round(line_rate, 3),
            "bottleneck_pieces_per_hour": round(bottleneck, 3),
            "ratio": round(ratio, 2),
            "bottleneck_stations": slow_seen[:3],
            "remaining_qty": remaining,
            # 两个天数都按"一天几小时"折算，同一把尺子才可比；工位侧没有声明班时，
            # 借用这条线的班时，并在 hours_per_day 里写清是哪条线的。
            "days_by_line": round(remaining / line_rate / hours_per_day, 2) if line_rate and remaining else None,
            "days_by_bottleneck": round(remaining / bottleneck / hours_per_day, 2) if bottleneck and remaining else None,
            "action": "IE/PMC 核定：产线日报的日产量与工位主档的每小时产能至少有一条是错的。",
        })
    return findings


WITHDRAW_NON_BLOCKING_SQL = """
    UPDATE followup_tasks
    SET status = 'cancelled',
        result_summary = COALESCE(result_summary, '') || :note,
        closed_at = NOW(),
        updated_at = NOW()
    WHERE source = 'time_basis_auditor'
      AND payload->>'category' = 'capacity_conflict'
      AND status NOT IN ('done', 'cancelled')
      AND COALESCE((payload->>'remaining_qty')::numeric, 0) <= 0
      AND factory_id = :fid
"""


async def withdraw_non_blocking_conflicts(db, factory_id: str, *, apply: bool = True) -> int:
    """收回引擎自己发过、但确实没挡着生产的对撞待办（只动 source 是自己名的那些）。

    判据改了，之前写出去的状态不会自己变回来。人工决定过的一律不碰：
    这里按 source='time_basis_auditor' 划界，别人建的待办不在作用域内。
    """
    if not apply:
        return 0
    updated = await db.execute(text(WITHDRAW_NON_BLOCKING_SQL), {
        "fid": factory_id,
        "note": "；引擎收回：该机型当前没有在制欠量，这条产能对撞没挡着生产，"
                "口径问题仍留在工时体检面里（GET /api/v1/pmc/time-basis）。",
    })
    return int(updated.rowcount or 0)


async def time_basis_review(
    db, factory_id: str, *, apply: bool = True, limit: int = 3
) -> Dict[str, Any]:
    """体检 + 把产能对撞报成 IE/PMC 的一条待办；判重按机种，一轮最多 limit 条。

    这里不发自动动作：口径谁是对的只能人裁定，引擎的职责是把两个数摆在一起并点名
    最慢的那个工位。
    """
    audit = await time_basis_audit(db, factory_id)
    audit["noise_withdrawn"] = await withdraw_non_blocking_conflicts(db, factory_id, apply=apply)
    conflicts = audit.get("capacity_conflicts") or []
    if not apply or not conflicts:
        return {**audit, "tasks_created": 0, "conflicts_blocking_open_work":
                sum(1 for c in conflicts if float(c.get("remaining_qty") or 0) > 0)}

    from api.services.followup_task_service import create_task

    created = 0
    blocking = [row for row in conflicts if float(row.get("remaining_qty") or 0) > 0]
    for row in blocking:
        if created >= limit:
            break
        existing = (await db.execute(text("""
            SELECT 1 FROM followup_tasks
            WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
              AND payload->>'category' = 'capacity_conflict'
              AND payload->>'model' = :model
            LIMIT 1
        """), {"fid": factory_id, "model": row["model"]})).first()
        if existing:
            continue
        evidence = {"category": "capacity_conflict", **row}
        await create_task(
            db, factory_id, created_by="time_basis_auditor",
            title=(f"[产能对撞] {row['model']}：线报 {row['line_pieces_per_hour']} 件/时、"
                   f"工位瓶颈只有 {row['bottleneck_pieces_per_hour']} 件/时（差 {row['ratio']} 倍）"),
            description=(
                f"归属线 {row['line_code']} 声明 {row['line_pieces_per_hour']} 件/时，"
                f"但这条路线上的工位主档只支撑 {row['bottleneck_pieces_per_hour']} 件/时，"
                f"最慢的是 {', '.join(s['station'] for s in row['bottleneck_stations'])}。\n"
                f"· 在制还欠 {row['remaining_qty']:g} 台：按线报要 {row['days_by_line']} 天，"
                f"按工位瓶颈要 {row['days_by_bottleneck']} 天。\n"
                "两个数都来自厂里自己的声明（line_profiles 口述 + stations.capacity_per_hour），"
                "引擎不取平均、也不自动改排产，请核定哪一条是真的。\n"
                f"{row['action']}"
            ),
            agent_key="pmc_agent", item_type="followup", source="time_basis_auditor",
            follow_interval_minutes=1440,
            payload=json.dumps(evidence, ensure_ascii=False),
        )
        created += 1

    return {**audit, "tasks_created": created,
            "conflicts_blocking_open_work": len(blocking)}


async def time_basis_audit(db, factory_id: str) -> Dict[str, Any]:
    """只读体检：工时覆盖率按三类出处统计，再加线/工位产能对撞。"""
    basis = await load_time_basis(db, factory_id)
    step_rows = (await db.execute(text(ROUTE_STEPS_SQL), {"fid": factory_id})).mappings().all()
    demand_rows = (await db.execute(text(OPEN_DEMAND_SQL), {"fid": factory_id})).mappings().all()
    open_demand = {str(r["model"]): float(r["remaining"] or 0) for r in demand_rows}

    coverage: Dict[str, int] = {BASIS_ROUTE: 0, BASIS_LINE: 0, BASIS_STATION: 0, BASIS_NONE: 0}
    for row in step_rows:
        _, used = basis.seconds_per_piece(
            model=str(row["model"]),
            station=str(row["station"] or row["work_center"] or ""),
            step={
                "standard_hours": float(row["standard_hours"] or 0) or None,
                "time_min": float(row["time_min"] or 0) or None,
                "standard_time": float(row["standard_time"] or 0) or None,
            },
        )
        coverage[used] = coverage.get(used, 0) + 1

    total = sum(coverage.values())
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for row in step_rows:
        by_model.setdefault(str(row["model"]), []).append(dict(row))

    eta: List[Dict[str, Any]] = []
    for model, steps in sorted(by_model.items()):
        remaining = float(open_demand.get(model, 0) or 0)
        if remaining <= 0:
            continue
        estimate = basis.order_flow_estimate(model=model, qty=remaining, steps=len(steps))
        if not estimate:
            continue
        eta.append({
            "model": model,
            "remaining_qty": remaining,
            **estimate,
            "basis": BASIS_LINE,
        })

    return {
        "status": "ok",
        "factory_id": factory_id,
        "route_steps": total,
        "coverage": coverage,
        "covered_ratio": round(
            (total - coverage.get(BASIS_NONE, 0)) / total, 4
        ) if total else None,
        "stations_with_rate": len(basis.station_rates),
        "lines": len(basis.lines),
        "models_with_line": len(basis.line_by_model),
        "open_models": len(open_demand),
        "estimated_completion": sorted(eta, key=lambda e: -e["remaining_qty"])[:10],
        "capacity_conflicts": capacity_conflicts(basis, [dict(r) for r in step_rows], open_demand),
        "note": (
            "预计完工按流水线口径（数量 ÷ 线产能 + 首件节拍），比排程任务行求和小 —— "
            "排程器按一单一工位串行放置，那是批次假设，不是产能量。"
        ),
    }
