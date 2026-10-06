"""沙箱执行推演：引擎自己拆单、自己开购、自己按天推进，产出一条真实演变的时间线。

跟计算器的区别就在这里 —— 不是 `500 ÷ 300 = 1.7 天`，而是：

1. **没有工单就自己拆**：目标机种 + 数量 → 建一张沙箱工单（不落业务表，只在推演内存里）；
2. **没有路线就从同族借**：同前缀机种（FG-TREAD-*）已有工序序列就直接沿用，并打标
   `borrowed_route_from_family` —— 借来的是依据，不是猜，必须在结果里看得见；
3. **没有工时就用线节拍反推**：`line_profiles.hours_per_day / units_per_day` 给占用秒，打标 `takt_from_line`;
4. **料不够就开采购**：按 `materials.lead_time_days` 逐料号算到货日，自制件递归往下拆一层；
   到货日决定最早开工日 —— 于是"等料"和"生产"是两段时间，不再混成一个天数；
5. **按天推进**：每天先见到货、再看该线班组到岗（天气折算出勤）、再占产能开工、报工、完工入库；
   线空着的日子记成闲置并计价，因为人已经在岗。

输出一条动作时间线（引擎做了什么决策）+ 结果（哪天交、延几天、等料几天、用工多少、多少钱）
+ 分数（交付/人力/齐套/成本）。所有数字都带出处；确实没有依据的（比如没有单价）就明说不折算。
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from core.mes.route_resolution import route_ops_for_product
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LABOR_COST_PER_PERSON_DAY = float(os.getenv("SIM_LABOR_COST_PER_PERSON_DAY", "30"))
# 加急对价：每件每天提前一天要多付的钱（库里没有运费/加急费率，这是内置标定，结果里标明 basis）
SIM_EXPEDITE_COST_PER_UNIT_DAY = float(os.getenv("SIM_EXPEDITE_COST_PER_UNIT_DAY", "0.15"))
# 开第二条线的代价：多一套班组、多一份管理幅度。库里没有这条费率，按"整线班组×班时"标定。
SIM_LINE_ACTIVATION_COST_PER_DAY = float(os.getenv("SIM_LINE_ACTIVATION_COST_PER_DAY", "4500"))


LOAD_HEALTHY_BAND = (0.60, 0.90)


def peak_load_ratio(bottleneck_lead: int, due: date, today: date, units: float,
                    units_per_day: float, parallel_lines: int,
                    attendance_curve: Dict[int, float]) -> float:
    """要赶上交期，每天必须做多少台 ÷ 这段时间实际能做多少台。

    料要在第 N 天才齐，能用的天数就被压短；短到每天要做的台数超过线的实际产能，
    这个比值就 >1（得加班或开第二条线）。比"1/出勤率"有信息量得多，也不会让"多开线"白拿分。
    """
    if units_per_day <= 0 or units <= 0:
        return 0.0
    total_days = max(1, (due - today).days)
    usable_days = max(1, total_days - max(0, int(bottleneck_lead)))
    attend = sum(attendance_curve.get(d, 1.0) for d in range(total_days)) / max(1, total_days)
    available = units_per_day * max(1, int(parallel_lines)) * attend * usable_days
    return round(units / available, 4) if available > 0 else 99.0


def load_band_gap(ratio: float) -> float:
    """离健康区间有多远：区间内 = 0，越偏离越大。这样"多开线把人闲下来"要付分。"""
    lo, hi = LOAD_HEALTHY_BAND
    if ratio < lo:
        return round(lo - ratio, 4)
    if ratio > hi:
        return round((ratio - hi) / (1 - hi) * lo, 4)     # 超载侧按剩余缓冲折算
    return 0.0


def kit_lead_of(kit: Dict[str, Any]) -> int:
    part = kit.get("bottleneck_part") or {}
    return int(part.get("lead_time_days") or 0)
MAX_MAKE_DEPTH = int(os.getenv("SIM_MAX_MAKE_DEPTH", "2"))
IDLE_COST_WEIGHT = float(os.getenv("SIM_IDLE_COST_WEIGHT", "1.0"))

BOM_SQL = text("""
    SELECT b.material_code, b.material_name, b.unit, COALESCE(b.qty_per_unit, b.quantity, 0) AS qty_per_unit,
           b.unit_price, b.total_cost, m.make_or_buy, m.lead_time_days, m.default_supplier
    FROM bom_items b
    LEFT JOIN materials m ON m.material_code = b.material_code AND m.factory_id = b.factory_id
    WHERE b.factory_id = :fid AND b.product_id = :model
""")

STOCK_SQL = text("""
    SELECT i.material_code, SUM(GREATEST(COALESCE(i.available_qty, 0), 0)) AS available
    FROM inventory i
    WHERE i.factory_id = :fid AND i.material_code = ANY(CAST(:codes AS text[]))
    GROUP BY i.material_code
""")

LINES_SQL = text("""
    SELECT line_code, line_group, hours_per_day, units_per_day, group_units_per_day, crew_size,
           can_make_models::text AS can_models, default_model
    FROM line_profiles WHERE factory_id = :fid AND is_active = true ORDER BY line_code
""")

FAMILY_ROUTE_SQL = text("""
    SELECT w.product_id AS from_model, s.seq, s.operation_name, s.work_center, s.standard_hours
    FROM work_orders w
    JOIN routing_template_steps s ON s.template_id::text = w.routing_template_id::text
    WHERE w.factory_id = :fid AND w.product_id LIKE :prefix AND COALESCE(s.standard_hours, 0) > 0
    ORDER BY s.seq LIMIT 40
    """)

CALENDAR_SQL = text("""
    SELECT DISTINCT day_of_week AS weekday FROM aps_work_calendars
    WHERE (factory_id = :fid OR factory_id = 'default') AND is_active = true
""")

# 这条线已经排了多少活：能做的机种的开放工单计划量之和（按声明日产能折算占用天数）
LINE_COMMITMENT_SQL = text("""
    SELECT COALESCE(SUM(w.planned_qty), 0) AS committed_units
    FROM work_orders w
    WHERE w.factory_id = :fid AND w.wo_type = 'master'
      AND w.status IN ('pending', 'released', 'in_progress')
      AND w.product_id = ANY(CAST(:models AS text[]))
""")

EQUIP_RATE_SQL = text("""
    SELECT COUNT(*) FILTER (WHERE status = 'running') AS running,
           COUNT(*) AS total
    FROM equipment WHERE factory_id = :fid
""")


def declared_models(line: Dict[str, Any]) -> List[str]:
    raw = str(line.get("can_models") or "")
    return [m.strip().strip("'").strip("\\") for m in raw.strip("{}").split(",") if m.strip()]


async def line_committed_days(db: AsyncSession, factory_id: str, line: Dict[str, Any]) -> Dict[str, Any]:
    """该线已承诺工单占掉多少天产线 —— 没有这一步，沙箱就是在一条"凭空空出来"的线上排新单。"""
    models = declared_models(line)
    if not models:
        return {"committed_units": 0.0, "busy_days": 0.0}
    row = (await db.execute(LINE_COMMITMENT_SQL,
                            {"fid": factory_id, "models": models})).mappings().first()
    units = float((row or {}).get("committed_units") or 0)
    per_day = float(line.get("units_per_day") or 0) or 1.0
    return {"committed_units": units, "busy_days": round(units / per_day, 2)}


async def equipment_rate(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """设备可用率：停着 9 台保养、1 台故障，产线就不可能按满配跑。"""
    row = (await db.execute(EQUIP_RATE_SQL, {"fid": factory_id})).mappings().first()
    total = int((row or {}).get("total") or 0)
    running = int((row or {}).get("running") or 0)
    return {"running": running, "total": total,
            "rate": round(running / total, 4) if total else 1.0}


PART_BOM_SQL = text("""
    SELECT b.material_code, COALESCE(b.qty_per_unit, b.quantity, 0) AS qty_per_unit,
           m.make_or_buy, m.lead_time_days
    FROM bom_items b
    LEFT JOIN materials m ON m.material_code = b.material_code AND m.factory_id = b.factory_id
    WHERE b.factory_id = :fid AND b.product_id = :part
""")


def family_prefix(model: str) -> str:
    """FG-TREAD-003 → FG-TREAD-%：同族机种共用工艺形状是厂里的常态。"""
    parts = str(model).split("-")
    return "-".join(parts[:2]) + "-%" if len(parts) >= 3 else f"{model}%"


def pick_line(model: str, lines: List[Dict[str, Any]]) -> tuple:
    """先按声明（can_make_models），再按 default_model，最后按同族前缀归线。返回 (线, 依据)。"""
    for l in lines:
        if model in str(l["can_models"]):
            return l, ("line_declared_can_make" if l["default_model"] != model else "line_declared_home")
    for l in lines:
        if str(l["default_model"] or "") == model:
            return l, "line_declared_default_model"
    stem = str(model).split("-")[1] if "-" in str(model) else ""
    for l in lines:
        if stem and stem in str(l["line_code"]):
            return l, "line_inferred_by_family_name"
    return None, "no_line"


def resolve_route(route_own: List[Dict[str, Any]], family_rows: List[Dict[str, Any]]) -> tuple:
    if route_own:
        return route_own, "own_route"
    if family_rows:
        borrowed = [{"operation_name": r["operation_name"], "work_center": r["work_center"],
                     "standard_hours": float(r["standard_hours"] or 0)} for r in family_rows]
        return borrowed, "borrowed_route_from_family"
    return [], "no_route"


def hours_per_unit_from(route: List[Dict[str, Any]], line: Optional[Dict[str, Any]]) -> tuple:
    """单件占用工时：路线给的分钟优先；没有就用线节拍（一天做多少台、一天几个班时）。"""
    declared = round(sum(float(o.get("standard_hours") or 0) for o in route), 4)
    if declared > 0:
        return declared, "route_standard_hours"
    if line and float(line["units_per_day"] or 0) > 0:
        hpd = float(line["hours_per_day"] or 11) or 11.0
        return round(hpd / float(line["units_per_day"]), 4), "takt_from_line_capacity"
    return 0.0, "no_time_basis"


def build_kit(bom: List[Dict[str, Any]], units: float, stock: Dict[str, float],
              start_day: int) -> Dict[str, Any]:
    """齐套与到货计划：外购按提前期到料，自制件先记 needing（由子件满足）。"""
    lines: List[Dict[str, Any]] = []
    buy_arrival_days: List[int] = []
    kit_lead_max: List[Optional[int]] = [None]
    kit_bottleneck: List[Optional[Dict[str, Any]]] = [None]
    blockers: List[str] = []
    cost = 0.0
    cost_unknown = 0.0
    for row in bom:
        code = str(row["material_code"])
        need = float(row["qty_per_unit"] or 0) * float(units)
        if need <= 0:
            continue
        have = float(stock.get(code, 0.0))
        short = max(0.0, need - have)
        kind = str(row["make_or_buy"] or "unknown")
        lead = row["lead_time_days"]
        price = row["unit_price"]
        unit_cost = float(price) if price not in (None, "") else None
        entry = {
            "material_code": code, "need": round(need, 3), "have": round(have, 3),
            "short": round(short, 3), "make_or_buy": kind,
            "supplier": row["default_supplier"] or None,
            "lead_time_days": lead,
        }
        if unit_cost is not None:
            cost += unit_cost * need
        else:
            cost_unknown += 1
        if short > 0 and str(lead or "").isdigit() and kind == "外购":
            lead_days = int(lead)
            if lead_days >= (kit_lead_max[0] or -1):
                kit_lead_max[0] = lead_days
                kit_bottleneck[0] = {"material_code": code, "lead_time_days": lead_days,
                                     "short": round(short, 3),
                                     "supplier": row["default_supplier"] or None,
                                     "unit_price": (float(price) if price not in (None, "") else None)}
        if short > 0:
            if kind == "外购":
                if str(lead or "").isdigit() and int(lead) >= 0:
                    buy_arrival_days.append(start_day + int(lead))
                    entry["action"] = f"开采购 {round(short, 3)}，{int(lead)} 天后到"
                else:
                    entry["action"] = "外购缺料但没有提前期 → 无法排到货日"
                    blockers.append(f"{code} 无提前期")
            elif kind == "自制":
                entry["action"] = f"拆自制子件工单 {round(short, 3)}"
            else:
                entry["action"] = "采购属性未知 → 不假设有货，列为主数据缺口"
                blockers.append(f"{code} 未标自制/外购")
        lines.append(entry)
    return {"lines": lines, "buy_arrival_days": buy_arrival_days,
            "bottleneck_part": kit_bottleneck[0],
            "blockers": blockers, "material_cost": round(cost, 2),
            "materials_without_price": int(cost_unknown)}


def simulate_days(units: float, hours_per_unit: float, hours_per_day: float,
                  crew: float, attendance_by_day: Dict[int, float], shift_days: set,
                  earliest_start: int, cap_per_day: float, today: date) -> Dict[str, Any]:
    """按天推进：等料 → 开工 → 每天占产能、扣班组 → 完工。等料的日子记闲置并计价。"""
    # 人是这条线的瓶颈（跑步机线 300 人配 300 台/天 = 一台一份人力），
    # 所以到岗不足时产能必须一起降：暴雨只来 7 成人，一天就不可能还是 300 台。
    # 不绑人力的装配线可以以后按线打标放开，现在按声明的 人数:台数 比例算。
    units_per_day = cap_per_day if cap_per_day > 0 else (
        max(1.0, hours_per_day / hours_per_unit) if hours_per_unit > 0 else 0.0)
    remaining = float(units)
    day = 0
    started_on: Optional[int] = None
    weekday_of = lambda d: (today + timedelta(days=d)).isoweekday()
    wait_days = 0
    work_days = 0
    person_days = 0.0
    idle_person_days = 0.0
    timeline: List[Dict[str, Any]] = []
    while day < 400 and remaining > 1e-9:
        is_shift = weekday_of(day) in shift_days
        if day < earliest_start:
            if is_shift:
                wait_days += 1
                idle_person_days += crew * attendance_by_day.get(day, 1.0)
            day += 1
            continue
        if not is_shift:
            day += 1
            continue
        if started_on is None:
            started_on = day
            timeline.append({"day": day, "action": "开工", "units_today": 0})
        present = crew * attendance_by_day.get(day, 1.0)
        capacity_today = (units_per_day * min(1.0, present / crew)) if (crew > 0 and units_per_day) else units_per_day
        if capacity_today <= 0:
            capacity_today = units_per_day or 1.0
        make = min(remaining, capacity_today)
        remaining -= make
        work_days += 1
        person_days += present
        timeline.append({"day": day, "action": "报工完工入库", "units_today": round(make, 1),
                         "people_present": round(present, 1), "remaining": round(remaining, 1)})
        day += 1
    return {"started_on_day": started_on, "finished_on_day": (day - 1) if remaining <= 1e-9 else None,
            "wait_days": wait_days, "work_days": work_days,
            "person_days": round(person_days, 1), "idle_person_days_before_start": round(idle_person_days, 1),
            "completed": remaining <= 1e-9, "timeline": timeline}


async def load_family_route(db: AsyncSession, factory_id: str, model: str) -> List[Dict[str, Any]]:
    rows = (await db.execute(FAMILY_ROUTE_SQL,
                             {"fid": factory_id, "prefix": family_prefix(model)})).mappings().all()
    seen, out = set(), []
    for r in rows:
        if r["operation_name"] in seen:
            continue
        seen.add(r["operation_name"])
        out.append(dict(r))
    return out


async def run_target(db: AsyncSession, factory_id: str, model: str, units: float,
                     due: date, today: date, attendance_curve: Dict[int, float],
                     lines: List[Dict[str, Any]], shift_days: set,
                     expedite_lead_days: Optional[int] = None, allow_partial: bool = True,
                     parallel_lines: int = 1, crew_bonus: float = 0.0,
                     cached: Optional[Dict[str, Any]] = None,
                     line_busy_days: float = 0.0, equip_rate: float = 1.0) -> Dict[str, Any]:
    """把一个目标跑成一条演变时间线。"""
    cache = (cached or {}).get(model)
    if not cache:
        bom = [dict(r) for r in (await db.execute(
            BOM_SQL, {"fid": factory_id, "model": model})).mappings().all()]
        codes = [str(r["material_code"]) for r in bom]
        stock_rows = (await db.execute(STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() if codes else []
        stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}
        route_own = await route_ops_for_product(db, factory_id, model)
        family_rows = [] if route_own else await load_family_route(db, factory_id, model)
        cache = {"bom": bom, "stock": stock,
                 "route_own": [dict(o) for o in route_own], "family_rows": family_rows}
    bom, stock = cache["bom"], cache["stock"]
    route_own, family_rows = cache["route_own"], cache["family_rows"]
    route, route_basis = resolve_route(list(route_own), family_rows)
    line, line_basis = pick_line(model, lines)
    hours_per_unit, hours_basis = hours_per_unit_from(route, line)

    kit = build_kit(bom, units, stock, start_day=0)
    if expedite_lead_days is not None and kit["bottleneck_part"]:
        kit["buy_arrival_days"] = [expedite_lead_days if d == kit["bottleneck_part"]["lead_time_days"] else d
                                   for d in kit["buy_arrival_days"]]
    arrival = max(kit["buy_arrival_days"], default=0)
    self_made_children = [l for l in kit["lines"] if l["short"] > 0 and l["make_or_buy"] == "自制"]

    # 自制件要先做出来：按同一条线排队，占的是同一段时间（递归一层，深度有上限）
    child_days = 0
    for child in self_made_children[:MAX_MAKE_DEPTH]:
        child_bom = [dict(r) for r in (await db.execute(
            PART_BOM_SQL, {"fid": factory_id, "part": child["material_code"]})).mappings().all()]
        leads = [int(r["lead_time_days"]) for r in child_bom
                 if str(r["lead_time_days"] or "").isdigit()]
        child_days = max(child_days, (max(leads) + 1) if leads else 0)

    # 开工要排在三件事之后：料齐、子件做完、这条线手上已承诺的活干完
    earliest_start = max(arrival, child_days, int(line_busy_days))
    if hours_basis == "no_time_basis":
        return {"model_code": model, "units": units, "status": "no_time_basis",
                "why": "既没有路线工时，也没有可归属的线节拍（线都没声明能做它）",
                "route_basis": route_basis, "line_basis": line_basis,
                "kit": {k: kit[k] for k in ("buy_arrival_days", "blockers", "material_cost",
                                            "materials_without_price")},
                "due": str(due)}

    hours_per_day = float((line or {}).get("hours_per_day") or 11)
    group_cap = group_capacity(lines, line or {}, parallel_lines)
    crew = round(group_cap["crew"] * (1.0 + crew_bonus), 1)
    cap = round(group_cap["units_per_day"] * max(0.1, min(1.0, equip_rate)), 2)  # 设备可用率折进日产能

    # 引擎的决策（不是计算器会做的事）：现料能做几台就先开几台，剩下的排在到货日之后
    coverable = []
    for l in kit["lines"]:
        per = float(l["need"] / units) if units else 0.0
        coverable.append(int(l["have"] / per) if per > 0 else int(units))
    stock_units = min(coverable, default=0)
    batch_a = min(int(units), max(0, stock_units)) if allow_partial else 0
    batch_b = int(units) - batch_a
    decision = (
        f"现料够先做 {batch_a} 台（第 0 天开工），剩余 {batch_b} 台等料"
        if batch_a and batch_b else
        f"现料够一次做完 {batch_a} 台" if batch_a and not batch_b else
        f"现料一台都开不了，整批 {int(units)} 台等到货日第 {earliest_start} 天开工")

    run_a = simulate_days(batch_a, hours_per_unit, hours_per_day, crew, attendance_curve,
                          shift_days, 0, cap, today) if batch_a else None
    a_finish = (run_a or {}).get("finished_on_day")
    start_b = max((int(a_finish) + 1) if a_finish is not None else 0, earliest_start)
    run_b = simulate_days(batch_b, hours_per_unit, hours_per_day, crew, attendance_curve,
                          shift_days, start_b, cap, today) if batch_b else None
    run = run_b or run_a
    finish_day = run["finished_on_day"]
    finish_date = today + timedelta(days=finish_day) if finish_day is not None else None
    late = (finish_day - (due - today).days) if finish_day is not None else None

    labor_cost = round(run["person_days"] * DEFAULT_LABOR_COST_PER_PERSON_DAY, 2)
    return {
        "model_code": model, "units": units, "status": "simulated",
        "route_steps": len(route), "route_basis": route_basis,
        "line": (line or {}).get("line_code"), "line_basis": line_basis,
        "hours_per_unit": hours_per_unit, "hours_basis": hours_basis,
        "earliest_start_day": earliest_start,
        "material_arrival_day": arrival,
        "self_made_children_days": child_days,
        "batch_a_units": batch_a, "batch_b_units": batch_b, "batch_decision": decision,
        "batch_a_finish_day": a_finish,
        "wait_days_for_material": (run_a or {"wait_days": 0})["wait_days"] + run["wait_days"],
        "work_days": run["work_days"],
        "started_on_day": run["started_on_day"],
        "finish_day": finish_day, "finish_date": str(finish_date) if finish_date else None,
        "due_date": str(due), "days_late": late,
        "people_present_avg": round(run["person_days"] / run["work_days"], 1) if run["work_days"] else None,
        "person_days": run["person_days"],
        "idle_person_days_before_start": run["idle_person_days_before_start"],
        "labor_cost_usd": labor_cost,
        "standby_person_days_if_line_held": run["idle_person_days_before_start"],
        "standby_cost_if_line_held_usd": round(run["idle_person_days_before_start"]
                                               * DEFAULT_LABOR_COST_PER_PERSON_DAY * IDLE_COST_WEIGHT, 2),
        "bottleneck_part": kit["bottleneck_part"],
        # 峰值负载 = 需要的相对人力。健康是 0.70~0.95：太低是养闲，太高没有缓冲。
        # 不能写成"越低越好"，否则引擎会永远多开线（那条线的代价没人付）。
        "load_band_gap": load_band_gap(peak_load_ratio(kit_lead_of(kit), due, today, units,
                                                        float((line or {}).get("units_per_day") or 0),
                                                        parallel_lines, attendance_curve)),
        "line_activation_cost_usd": (max(1, int(parallel_lines)) - 1) * SIM_LINE_ACTIVATION_COST_PER_DAY
                                    * max(1, int(run.get("work_days") or 1)),
        "expedite_cost_usd": (round(float(units) * max(0, (kit_lead_of(kit) - expedite_lead_days))
                                    * SIM_EXPEDITE_COST_PER_UNIT_DAY, 2)
                              if expedite_lead_days is not None and kit.get("bottleneck_part") else 0.0),
        "evidence": {route_basis: len(route) or 1,
                    hours_basis: len(route) or 1,
                    line_basis: 1},
        "policy": {"allow_partial": allow_partial, "parallel_lines": parallel_lines,
                   "crew_bonus": crew_bonus, "expedite_lead_days": expedite_lead_days},
        "line_busy_days_before_order": line_busy_days,
        "equipment_rate_applied": round(equip_rate, 4),
        "capacity_after_equipment": cap,
        "capacity_basis": group_cap["capacity_basis"],
        "standby_note": ("等料那几天这条线是空的；只有把整班人守着这条线才算损失。"
                         "厂里还有几百张单没排，空档可以承接 —— 所以这笔是上限，不是必然发生的钱。"),
        "material_cost_usd": kit["material_cost"],
        "materials_without_price": kit["materials_without_price"],
        "kit_shortage_lines": sum(1 for l in kit["lines"] if l["short"] > 0),
        "kit_lines": len(kit["lines"]),
        "blockers": kit["blockers"],
        "actions": [a for a in run["timeline"]][:40],
        "po_lines": [l for l in kit["lines"] if l["short"] > 0 and l["make_or_buy"] == "外购"][:12],
    }


# 厂里真会对外承诺的交期口径：瓶颈件提前期 × 这个系数。标定可以放宽去找有信息量的区间，
# 但比承诺还宽的场景只能当诊断，不能拿它的"准点"当结论 —— 那是把题目改简单了。
PROMISE_LEAD_MARGIN = float(os.getenv("SIM_PROMISE_LEAD_MARGIN", "1.15"))
# 场景标定要落在"有信息量"的区间：全可行或全不可行都白算一轮。
FEASIBLE_BAND = (0.25, 0.90)
MARGIN_BOUNDS = (0.8, 1.6)
BATCH_BOUNDS = (2.0, 12.0)


def regret_profile(sol: Dict[str, Any]) -> Tuple[float, ...]:
    """与 pareto_eval 的择优同口径：把该解的各目标后悔从最坏到最好排成一个向量。"""
    reg = sol.get("regret_by_objective") or {}
    from api.services.pareto_eval import FIXED_ORDER
    return tuple(sorted((float(reg.get(k) or 0.0) for k in FIXED_ORDER), reverse=True))


def scenario_discrimination(res: Dict[str, Any], n_policies: int) -> Dict[str, Any]:
    """这一轮这个场景到底比出了什么 —— 判"有没有信息"，不判"分数好不好看"。

    runner_up_regret_gap 用字典序口径而不是 max_regret 之差：实测前沿只有 2~4 个点时
    每个点都在某一维全场最差，max_regret 清一色等于 1.0，做差恒为 0，
    看着像"全并列"其实是量错了。真正要比的是择优那串字典序里**第一个不相等的分量**。
    gap=0 才是真的并列（抛硬币），gap=None 是连两个可比解都没有。
    """
    pool = (res.get("frontier") or []) + (res.get("dominated") or [])
    profiles = sorted(regret_profile(s) for s in pool)
    tied = len([x for x in profiles[1:] if x == profiles[0]]) if profiles else 0
    # 并列的那些不算次优：gap 要比到第一个**真的不一样**的解，否则永远读出 0
    runner = next((x for x in profiles[1:] if x != profiles[0]), None) if len(profiles) > 1 else None
    if runner is not None:
        gap = next((round(b - a, 4) for a, b in zip(profiles[0], runner)
                    if abs(b - a) > 1e-9), 0.0)
    else:
        gap = None
    dead = res.get("non_discriminating_objectives") or []
    live = len([k for k in (res.get("objectives") or []) if k not in dead])
    feasible_ratio = round(len(pool) / max(1, int(n_policies or 1)), 2)
    in_band = FEASIBLE_BAND[0] <= feasible_ratio <= FEASIBLE_BAND[1]
    report_only = bool(res.get("report_only_comparison"))
    return {
        "recommended": (res.get("recommended") or {}).get("name"),
        "feasible": len(pool),
        "eliminated": len(res.get("eliminated") or []),
        "feasible_ratio": feasible_ratio,
        "frontier_size": len(res.get("frontier") or []),
        "live_objectives": live,
        "dead_dims": dead,
        "runner_up_regret_gap": gap,
        "tied_with_recommended": len(res.get("recommended_tied_with") or []),
        "no_feasible": bool(res.get("no_feasible_solution")),
        "report_only_comparison": report_only,
        "informative": bool(len(pool) >= 3 and in_band and gap and live >= 1 and not report_only),
    }


def promise_ceiling() -> float:
    """标定最多能放宽到哪儿 = 厂里真会承诺的交期口径。

    越过承诺去调标定等于把题目改简单再宣布"能做到" —— 那正是用户警告过的过拟合。
    放宽只到承诺口径为止；到顶还是没人能准点，就如实报"以现有提前期做不到"。
    """
    return round(min(MARGIN_BOUNDS[1], PROMISE_LEAD_MARGIN), 2)


def _tune_one(cal: Dict[str, float], disc: Dict[str, Any]) -> Optional[str]:
    """按场景调自己的标定；返回这一格做了什么调整（None = 这轮不用动）。"""
    ceiling = promise_ceiling()
    ratio = disc["feasible_ratio"]
    if disc["no_feasible"] or ratio < FEASIBLE_BAND[0]:
        # 触发原因要分清：没有任何准点解 ≠ 可行比例低（降级比较时可行比例可以是 100%）
        reason = ("没有任何准点解" if disc["no_feasible"] else f"可行比例 {ratio:.0%} 太低")
        if cal["lead_margin"] < ceiling:
            cal["lead_margin"] = round(min(ceiling, cal["lead_margin"] + 0.1), 2)
            return f"{reason} → 交期系数放宽到 {cal['lead_margin']:g}（承诺口径上限 {ceiling:g}）"
        if ratio < FEASIBLE_BAND[0] and cal["days_of_output"] > BATCH_BOUNDS[0]:
            cal["days_of_output"] = round(max(BATCH_BOUNDS[0], cal["days_of_output"] - 1.0), 2)
            return (f"交期已到承诺口径上限还几乎无解 → 批量降到 {cal['days_of_output']:g} 天线产量，"
                    f"分清是批量定大了还是以现有提前期就是做不到")
        return None     # 标定已到底：做不到就是结论，不再用调参把它调成"做得到"
    if cal["lead_margin"] > ceiling and disc["feasible"]:
        # 上一轮为了诊断放宽过，这轮有准点解就收回来：不许赖在简单模式里刷可行解
        cal["lead_margin"] = round(max(ceiling, cal["lead_margin"] - 0.1), 2)
        return (f"这一格还停在比承诺口径（{ceiling:g}）更宽的交期上、且已经有准点解 → "
                f"交期系数收回 {cal['lead_margin']:g}，不靠改题目拿可行解")
    if ratio > FEASIBLE_BAND[1]:
        # 全（或几乎全）可行不一定是坏事：目标维度还能取舍就不许再收紧交期去制造"延不延期"的假区分度
        if disc["informative"] or (disc["live_objectives"] >= 2 and disc["runner_up_regret_gap"]):
            return None
        if cal["lead_margin"] > MARGIN_BOUNDS[0]:
            cal["lead_margin"] = round(max(MARGIN_BOUNDS[0], cal["lead_margin"] - 0.1), 2)
            return (f"{ratio:.0%} 的政策都准点、且推荐解与次优解的后悔并列 "
                    f"→ 交期系数收紧到 {cal['lead_margin']:g}")
        return None
    if disc["feasible"] <= 2 or disc["live_objectives"] == 0:
        if cal["days_of_output"] > BATCH_BOUNDS[0]:
            cal["days_of_output"] = round(max(BATCH_BOUNDS[0], cal["days_of_output"] - 1.0), 2)
            return (f"可行解只有 {disc['feasible']} 个/目标维度全平 → "
                    f"批量降到 {cal['days_of_output']:g} 天线产量，找中间地带")
    return None



# "有没有人动过"要一次问全三类台账：只查 purchase_orders 会把请购/申购当成没落地，
# 而厂里催一个料通常先走请购或申购，PO 是后面的事。
FOLLOWTHROUGH_SQL = text("""
    SELECT m.material_code, m.lead_time_days AS lead_now, m.default_supplier,
           (SELECT COUNT(*) FROM purchase_orders po
             WHERE po.factory_id = :fid AND po.material_code = m.material_code
               AND po.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(po.status, '')) <> 'CANCELLED') AS pos_since,
           (SELECT COUNT(*) FROM purchase_requests pr
             WHERE pr.factory_id = :fid AND pr.material_code = m.material_code
               AND pr.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(pr.status, '')) NOT IN ('CANCELLED', 'REJECTED')) AS req_since,
           (SELECT COUNT(*) FROM purchase_requisitions rq
             WHERE rq.factory_id = :fid AND rq.material_code = m.material_code
               AND rq.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(rq.status, '')) NOT IN ('CANCELLED', 'REJECTED')) AS requis_since
    FROM materials m
    WHERE m.factory_id = :fid AND m.material_code = ANY(CAST(:codes AS text[]))
""")


async def recommendation_followthrough(db: AsyncSession, factory_id: str,
                                       actions: List[Dict[str, Any]],
                                       *, since: Optional[datetime] = None) -> Dict[str, Any]:
    """上一轮建议的动作到底做没做 —— 引擎得能发现自己是不是一直在对空气提建议。

    只看台账里已有的证据：物料主档的提前期压到建议值没有、这段时间对这个料号开过采购单没有、
    缺供应商的料号补齐没有。查不到证据就说查不到，不猜"可能口头催过了"。
    """
    wanted = [a for a in (actions or []) if a.get("material_code")]
    codes = sorted({str(a["material_code"]) for a in wanted})
    if not codes:
        return {"checked": 0, "adopted": [], "not_acted": [],
                "note": "本轮建议没点名到料号，无复查对象"}
    until = since or (datetime.utcnow() - timedelta(days=7))
    if getattr(until, "tzinfo", None) is not None:
        until = until.replace(tzinfo=None)
    rows = (await db.execute(FOLLOWTHROUGH_SQL,
                             {"fid": factory_id, "codes": codes, "since": until})).mappings().all()
    by_code = {str(r["material_code"]): dict(r) for r in rows}
    adopted: List[Dict[str, Any]] = []
    not_acted: List[Dict[str, Any]] = []
    no_master: List[str] = []
    for a in wanted:
        code = str(a["material_code"])
        row = by_code.get(code)
        if row is None:
            no_master.append(code)
            continue
        lead_now = row.get("lead_now")
        target = int(a.get("target_lead_days") or 0)
        pos = int(row.get("pos_since") or 0)
        evidence = {"purchase_orders": pos,
                    "purchase_requests": int(row.get("req_since") or 0),
                    "purchase_requisitions": int(row.get("requisition_since") or 0)}
        raised = sum(evidence.values())
        if str(a.get("type")) == "supplier_master_missing":
            item = {"material_code": code, "check": "补供应商",
                    "default_supplier": row.get("default_supplier")}
            (adopted if row.get("default_supplier") else not_acted).append(item)
            continue
        pressed = lead_now is not None and target and int(lead_now) <= target
        (adopted if (pressed or raised > 0) else not_acted).append(
            {"material_code": code,
             "check": f"提前期压到 {target} 天，或采购/请购/申购里查到记录",
             "lead_now": lead_now, "lead_target": target,
             "evidence": evidence, "records_since": raised})
    verdict = ("建议有下落：提前期已压缩，或采购/请购/申购里查到了记录" if adopted and not not_acted else
               ("建议还没落地：主档提前期没变，采购/请购/申购三类台账都查不到记录"
                if not_acted and not adopted else
                "部分落地：见明细，未落地的部分继续挂在建议里"))
    return {"checked": len(wanted), "adopted": adopted, "not_acted": not_acted,
            "no_master_row": sorted(set(no_master)), "since": str(until),
            "verdict": verdict,
            "note": ("复查只看台账证据：materials.lead_time_days 是否压到建议值，"
                     "以及 purchase_orders / purchase_requests / purchase_requisitions 里该料号"
                     "在建议之后有没有新增单据（取消/驳回的不算）。查不到就说查不到，不猜有没有人口头催过")}


# 动作排序：先"今天就能下单/开工"的，再"要人去确认"的，最后是主数据缺口。
_ACTION_PRIORITY = {"expedite_purchase": 0, "supplier_master_missing": 1, "start_first_batch": 2,
                    "schedule_second_batch_after_arrival": 3, "activate_parallel_line": 4,
                    "authorize_overtime": 5, "model_data_gap": 6, "master_data_gap": 7}


def recommendation_actions(scan: Dict[str, Any], verdict: Dict[str, Any],
                           *, today: Optional[date] = None,
                           max_actions: int = 30) -> List[Dict[str, Any]]:
    """把"稳健推荐的政策"翻译成能执行的动作：催哪个料、哪天到货、先开哪一批、开哪条线。

    政策名不是动作 —— 人要的是"找谁、买多少、几号到"。三条诚实规矩：
    ① 缺口料号没有供应商主数据就不许编一个供应商，改成补数据动作（卡住交付的是数据不是产能）；
    ② 开并联线要说清人手从哪来，技能矩阵还是 0 行就标 crew_verified=false，不假装人能调；
    ③ 动作只落在沙箱建议里（sandbox_only），不写 MES/WMS，也不自动生成采购单。
    依据取"该政策最紧的那个天气场景"：按好天的到货日下单，暴雨天就直接失约。
    """
    today = today or date.today()
    robust = ((verdict or {}).get("robust_recommendation") or {}).get("policy")
    if not robust:
        return []
    binding: Dict[str, Dict[str, Any]] = {}     # model -> 该模型最紧场景的 detail + 政策
    for name, block in (scan.get("by_scenario") or {}).items():
        for sol in (block.get("solutions") or []):
            if str(sol.get("name")) != str(robust):
                continue
            for d in (sol.get("detail") or []):
                m = str(d.get("model_code"))
                score = (int(d.get("days_late") or 0), int(d.get("material_arrival_day") or 0))
                cur = binding.get(m)
                if cur is None or score > (int(cur.get("days_late") or 0),
                                           int(cur.get("material_arrival_day") or 0)):
                    entry = dict(d)
                    entry["_scenario"] = name
                    entry["_policy"] = sol.get("policy") or {}
                    binding[m] = entry

    out: List[Dict[str, Any]] = []
    for m, d in sorted(binding.items()):
        pol = d.get("_policy") or {}
        scen = d.get("_scenario")
        due = d.get("due_date")
        base = {"model_code": m, "scenario": scen, "due_date": due,
                "planned_finish_date": d.get("finish_date"), "sandbox_only": True}
        if d.get("status") and str(d.get("status")) != "simulated":
            # 这台机种从比较里摘掉了：不是厂里做不到，是模型没有能算工时的依据 —— 要补的是数据
            out.append({**base, "type": "model_data_gap", "units_excluded": d.get("units"),
                        "detail": f"{m}：{d.get('status')} — {d.get('why')}",
                        "note": "它不进产量底线也不进这轮推荐；补上工时依据（IE 标准工时或线声明节拍）才能推演"})
            continue
        if int(pol.get("parallel_lines") or 1) > 1:
            out.append({**base, "type": "activate_parallel_line", "line": d.get("line"),
                        "capacity_basis": d.get("capacity_basis"), "crew_verified": False,
                        "note": ("开第二条线按组内声明的合并产能算（不是单线×线数）；"
                                 "要的人手没有技能矩阵佐证，先按'能开'算钱、按'待确认'报人")})
        if float(pol.get("crew_bonus") or 0) > 0:
            out.append({**base, "type": "authorize_overtime",
                        "extra_crew_share": round(float(pol["crew_bonus"]), 3),
                        "note": f"加班加人 {float(pol['crew_bonus']):.0%}，成本已计入人工口径"})
        bp = d.get("bottleneck_part") or {}
        if pol.get("expedite_lead_days") is not None and bp and float(bp.get("short") or 0) > 0:
            target = int(pol["expedite_lead_days"])
            cur_lead = int(bp.get("lead_time_days") or 0)
            arrival = int(d.get("material_arrival_day") or 0)
            pull = max(0, cur_lead - target)
            # arrival 已经是加急之后的到货日（run_target 里换过一遍），不能再减一次 pull：
            # 那样催购要到的日期会比第二批开工的日期还早，两张动作自相矛盾。
            act = {**base, "material_code": bp.get("material_code"),
                   "qty_short": round(float(bp.get("short") or 0), 3),
                   "current_lead_days": cur_lead, "target_lead_days": target,
                   "order_by_date": str(today),
                   "required_arrival_date": str(today + timedelta(days=arrival)),
                   "pulled_in_days": pull,
                   "arrival_note": f"按 {target} 天提前期推演的到货日；不催的话要到 {today + timedelta(days=arrival + pull)}"}
            if bp.get("supplier"):
                act.update({"type": "expedite_purchase", "supplier": bp["supplier"],
                            "note": f"向 {bp['supplier']} 把 {cur_lead} 天提前期压到 {target} 天；"
                                    f"下单每晚一天，出货日就晚一天"})
            else:
                act.update({"type": "supplier_master_missing",
                            "note": ("这个缺口料号在物料主档里没有默认供应商 —— 催购没有对象。"
                                     "卡住交付的是数据不是产能：先补料号供应商，再谈加急价")})
            out.append(act)
        a = float(d.get("batch_a_units") or 0)
        b = float(d.get("batch_b_units") or 0)
        if a > 0:
            out.append({**base, "type": "start_first_batch", "units": round(a, 3),
                        "start_date": str(today),
                        "note": f"现料够先做 {a:g} 台，不等齐套；这批可以马上进排产预排"})
        if b > 0:
            out.append({**base, "type": "schedule_second_batch_after_arrival",
                        "units": round(b, 3),
                        "not_before": str(today + timedelta(days=int(d.get("material_arrival_day") or 0))),
                        "note": "第二批卡在到货日，提前开工只会做出做不完的半成品"})
        for gap in (d.get("blockers") or []):
            out.append({**base, "type": "master_data_gap", "detail": str(gap),
                        "note": "齐套算不下去的缺口在这里：不是产能，也不是人手"})

    # 同一个主数据缺口会在多台单上重复出现：合成一条并列出受影响的机种，
    # 否则动作清单被重复行占满，真正要催的那条反而看不见
    merged: Dict[Tuple, Dict[str, Any]] = {}
    order: List[Tuple] = []
    for a in out:
        ident = str(a.get("material_code") or a.get("detail") or "")
        # 没有"料号/缺口"身份的动作（分批、开线）每台单都是独立的一条，
        # 不能拿空身份当 key —— 那样第二台单的分批建议会被当成重复项吃掉
        key = (a["type"], ident) if ident else (a["type"], str(a.get("model_code") or ""), len(order))
        if key[1] and a["type"] in ("master_data_gap", "supplier_master_missing"):
            if key not in merged:
                merged[key] = dict(a, models=[])
                order.append(key)
            merged[key]["models"].append(a["model_code"])
            merged[key].pop("model_code", None)
            continue
        if key not in merged:
            merged[key] = a
            order.append(key)
    # 能花钱/能开工的动作排在前面，主数据缺口垫底：待办正文只放得下前几条，
    # 让"今天该给谁下单"占位、"哪个料号没标自制外购"占位是两种完全不同的损失
    ranked = sorted((merged[k] for k in order),
                    key=lambda a: (_ACTION_PRIORITY.get(str(a.get("type")), 9),
                                   str(a.get("model_code") or "")))
    return ranked[:max(1, int(max_actions))]


def _seed_calibration(seed: Optional[Dict[str, Any]], days_of_output: float,
                     lead_margin: float) -> Dict[str, Dict[str, float]]:
    """每 15 分钟一轮，标定不能每轮从 1.15 重新摸索一遍 —— 那等于每轮都把已知的
    "哪个天气场景该多紧"重新忘掉，既白算也永远收敛不到中间地带。"""
    calib = {s["name"]: {"days_of_output": round(float(days_of_output), 2),
                         "lead_margin": round(float(lead_margin), 2)} for s in WEATHER_SCENARIOS}
    for name, val in (seed or {}).items():
        if name not in calib or not isinstance(val, dict):
            continue
        try:
            batch = float(val.get("days_of_output"))
            margin = float(val.get("lead_margin"))
        except (TypeError, ValueError):
            continue
        if batch > 0 and margin > 0:
            # 历史标定若越出承诺口径（上一版允许放宽到 1.6 时留下的），热启动就收回来
            calib[name] = {"days_of_output": min(BATCH_BOUNDS[1], max(BATCH_BOUNDS[0], batch)),
                           "lead_margin": min(promise_ceiling(), max(MARGIN_BOUNDS[0], margin))}
    return calib


async def auto_tune(db: AsyncSession, factory_id: str, models: List[str], *, rounds: int = 3,
                    days_of_output: float = 6.0, lead_margin: float = 1.15,
                    calibration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """自己**按每个天气场景**标定 → 扫 → 看哪里白算 → 改标定 → 再扫。

    标定从全局改成按场景，是上一轮自审抓出来的洞：可行度按场景分布，标定却是全局的 ——
    暴雨一收紧，好天场景就退化成"13 个政策全可行、0 个淘汰"，那一轮同样没有信息量；
    反过来全局放宽，暴雨又全不可行，还是比不出东西。

    每格调的是什么，判据是"这一轮有没有区分度"，不是分数好不好看：
    ① 可行比例 < 0.25（几乎没人能准点）⇒ 先放宽该场景交期系数；到上限再降批量，
       分清是"量定大了"还是"以现有提前期就是做不到"（后者是结论，不是失败）；
    ② 可行比例 > 0.90 且推荐解与次优解的后悔并列 ⇒ 收紧该场景交期系数；
       若目标维度还能取舍（人力/加急/开线/负载比不一样），就**不许**再收紧 ——
       准点这维本来就是空的，硬造"延不延期"的区分度是自欺；
    ③ 可行解 ≤2 或目标维度全平 ⇒ 该场景批量降一档，去看中间地带。
    """
    calib = _seed_calibration(calibration, days_of_output, lead_margin)
    seeded = bool(calibration)
    trajectory: List[Dict[str, Any]] = []
    grid_extra: List[Dict[str, Any]] = []
    extreme_added = False
    final: Dict[str, Any] = {}
    targets: List[Dict[str, Any]] = []
    for rnd in range(max(1, int(rounds))):
        targets_by_scenario: Dict[str, List[Dict[str, Any]]] = {}
        for name, cal in calib.items():
            targets_by_scenario[name] = await derive_targets(
                db, factory_id, models, days_of_output=cal["days_of_output"],
                lead_margin=cal["lead_margin"])
        targets = targets_by_scenario[WEATHER_SCENARIOS[0]["name"]]
        grid = await build_policy_grid(db, factory_id, targets)
        for extra in grid_extra:
            if extra["name"] not in {g["name"] for g in grid}:
                grid.append(extra)
        scan = await scan_policies(db, factory_id, targets, policies=grid,
                                   targets_by_scenario=targets_by_scenario)
        from api.services.pareto_eval import evaluate_by_scenario
        # 标定已放宽到超过承诺系数的场景只作诊断，不参与跨场景稳健推荐
        within_promise = [n for n, c in calib.items()
                          if c["lead_margin"] <= PROMISE_LEAD_MARGIN + 1e-9]
        verdict = evaluate_by_scenario(scan["by_scenario"], scan["demand_by_scenario"],
                                       robust_scenarios=within_promise or None)
        per: Dict[str, Any] = {}
        tweaks: List[str] = []
        for scen in WEATHER_SCENARIOS:
            name = scen["name"]
            res = (verdict.get("by_scenario") or {}).get(name) or {}
            disc = scenario_discrimination(res, len(grid))
            cal = calib[name]
            tweak = _tune_one(cal, disc)
            if tweak:
                tweaks.append(f"{name}：{tweak}")
            # 交期这个旋钮已经拧到承诺口径上限，再没有"把题目改简单"的余地：
            # 这时还没准点解就该去试极限杠杆，而不是先看批量降到多小
            ceiling_reached = cal["lead_margin"] >= promise_ceiling()
            # 触发条件不能只看可行比例：降级比较时可行比例可以高达 92%（全都算进来了），
            # 而真相是本场景没有任何准点解 —— 那才是"补极限加急/报做不到"的信号
            if (disc["no_feasible"] or disc["feasible_ratio"] < FEASIBLE_BAND[0]) and ceiling_reached:
                if not extreme_added:
                    grid_extra.append({"name": "极限加急（提前期压到 2 天）+ 并联开满",
                                       "expedite_lead_days": 2, "parallel_lines": 2})
                    extreme_added = True
                    tweaks.append(f"{name}：标定已到边界仍无准点解 → 补一档极限加急政策试试")
                else:
                    disc["verdict"] = ("以现有供应商提前期，这个天气场景做不到准点交付 —— "
                                       "这是结论。标定不再往里压，避免把'做不到'调成'做得到'")
            elif tweak is None:
                # 每格都要有自己的说法，不能留 None 让人去猜这一轮到底算不算数
                if disc["report_only_comparison"]:
                    disc["verdict"] = "没有解达到产量底线：这一轮只摆数据，不择优"
                elif disc["no_feasible"]:
                    disc["verdict"] = ("本场景没有任何准点解（含放宽后的口径）：已降级按延误天数比较，"
                                       "这是结论不是失败")
                elif disc["feasible_ratio"] > FEASIBLE_BAND[1]:
                    disc["verdict"] = (f"{disc['feasible_ratio']:.0%} 的政策都能准点：准点这维在本场景是空的，"
                                       f"政策靠目标维度取舍（推荐解赢次优解的后悔差 "
                                       f"{disc['runner_up_regret_gap']}）")
                elif disc["tied_with_recommended"]:
                    disc["verdict"] = (f"推荐解与 {disc['tied_with_recommended']} 个政策的后悔向量每一位都相同："
                                       f"本轮只筛掉了明显更差的，没说哪个最好 —— 要分高下得给目标定优先级")
                elif disc["runner_up_regret_gap"] in (0.0, None):
                    disc["verdict"] = "没有一个可比解与推荐解的后悔不同：本轮等于抛硬币，不能当结论"
                else:
                    disc["verdict"] = "落在有信息量的区间：可行比例在带内，推荐解与次优解有后悔差"
            blocked = {(b.get("model_code"), str(b.get("status")))
                       for s in ((scan["by_scenario"].get(name) or {}).get("solutions") or [])
                       for b in (s.get("blocked_models") or [])}
            disc["beyond_promise"] = cal["lead_margin"] > PROMISE_LEAD_MARGIN + 1e-9
            if disc["beyond_promise"]:
                disc["diagnostic_only"] = (
                    f"这一格把交期放宽到提前期 ×{cal['lead_margin']:g}（承诺口径是 ×"
                    f"{PROMISE_LEAD_MARGIN:g}）：只用来判断'做不到是政策不够还是交期本身不可能'，"
                    f"它的准点不算交付承诺，也不参与跨场景稳健推荐")
            per[name] = {"calibration": dict(cal),
                         "demand_units": scan["demand_by_scenario"].get(name),
                         "blocked_models": [{"model_code": mc, "status": st} for mc, st in sorted(blocked)],
                         "recommended_objectives": (res.get("recommended") or {}).get("objectives"),
                         "recommended_off_frontier": res.get("recommended_off_frontier"),
                         **disc}
        row = {
            "round": rnd,
            # 兼容老的记分卡字段（单场景标定字符串），同时给出按场景的完整标定
            "calibration": "；".join(
                f"{s['name']}：批量 {calib[s['name']]['days_of_output']:g} 天线产量、"
                f"交期系数 {calib[s['name']]['lead_margin']:g}" for s in WEATHER_SCENARIOS),
            "calibration_by_scenario": {k: dict(v) for k, v in calib.items()},
            "per_scenario": per,
            "robust": (verdict.get("robust_recommendation") or {}).get("policy"),
            "robust_pool": verdict.get("robust_scenario_pool") or [],
            "diagnostic_only_scenarios": verdict.get("diagnostic_only_scenarios") or [],
            "promise_margin": PROMISE_LEAD_MARGIN,
            "robust_why": (verdict.get("robust_recommendation") or {}).get("why"),
            "robust_tied_with": (verdict.get("robust_recommendation") or {}).get("tied_with") or [],
            "policies_tried": len(grid),
            "notes": [n for r in (verdict.get("by_scenario") or {}).values()
                      for n in (r.get("notes") or [])],
            "scenario_divergence": verdict.get("scenario_divergence") or {},
            "diagnosis": ("；".join(tweaks) if tweaks else (
                "各场景都有区分度：可行比例在带内、推荐解与次优解有后悔差，本轮前沿与后悔比较可用"
                if all(p.get("informative") for p in per.values()) else
                "标定已到承诺口径上限（×%g），各场景仍在降级比较（没有准点解）："
                "本轮只按延误天数排先后，不宣称谁能准点" % PROMISE_LEAD_MARGIN)),
            "next_tweak": tweaks[0] if tweaks else None,
            "tweaks": tweaks,
        }
        trajectory.append(row)
        final = row
        if not tweaks:
            break
    all_beyond = all((c["lead_margin"] > PROMISE_LEAD_MARGIN + 1e-9) for c in calib.values())
    final_per = (trajectory[-1].get("per_scenario") or {}) if trajectory else {}
    conclusion = None
    if final_per and all(p.get("no_feasible") for p in final_per.values()):
        worst = max(int(((p.get("recommended_objectives") or {}).get("days_late_worst")) or 0)
                    for p in final_per.values())
        conclusion = (f"以承诺交期（瓶颈提前期 ×{PROMISE_LEAD_MARGIN:g}、批量 "
                      f"{calib[WEATHER_SCENARIOS[0]['name']]['days_of_output']:g} 天线产量）"
                      f"这 {len(models)} 台做不到准点：连后悔最小的政策也要延 {worst} 天。"
                      f"要兑现得压提前期/加急或改承诺交期 —— 而不是把标定放宽，那只是把题目改简单。")
    elif all_beyond:
        conclusion = (f"以承诺交期（瓶颈提前期 ×{PROMISE_LEAD_MARGIN:g}）这 {len(models)} 台做不到准点；"
                      f"要准点得压提前期/加急，或把交期改成 ×{min(c['lead_margin'] for c in calib.values()):g} 以上 —— "
                      f"本轮放宽之后的推荐只说明'交期这么定就行'，不说明现有承诺能兑现")
    return {"factory_id": factory_id, "rounds": len(trajectory), "warm_started": seeded,
            "all_scenarios_beyond_promise": all_beyond,
            "nothing_on_time_at_promise": bool(final_per) and all(
                p.get("no_feasible") for p in final_per.values()),
            "conclusion": conclusion,
            "targets": targets, "final": final, "trajectory": trajectory,
            "final_scan": scan, "final_verdict": verdict,
            "calibration_by_scenario": {k: dict(v) for k, v in calib.items()},
            "rule": ("标定按天气场景各调各的，目标是每一轮都有区分度：可行比例落在 "
                     f"{FEASIBLE_BAND[0]:.0%}~{FEASIBLE_BAND[1]:.0%}，且推荐解与次优解的后悔不相等。"
                     "调参只为了让比较有意义，不为把分数调高 —— 调到底还做不到的场景如实报做不到。")}



async def run_sandbox(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                      *, today: Optional[date] = None,
                      attendance_curve: Optional[Dict[int, float]] = None,
                     expedite_lead_days: Optional[int] = None) -> Dict[str, Any]:
    """跑一批目标（每台一个时间线），并汇总组合结果。targets: [{model_code, units, due_in_days}]"""
    today = today or date.today()
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or {1, 2, 3, 4, 5, 6}
    curve = attendance_curve or {d: 0.97 for d in range(0, 200)}

    runs = []
    for t in targets:
        due = today + timedelta(days=int(t.get("due_in_days") or 25))
        run = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                               due, today, curve, lines, shift_days)
        if expedite_lead_days is not None and run.get("bottleneck_part"):
            alt = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                                   due, today, curve, lines, shift_days,
                                   expedite_lead_days=expedite_lead_days)
            run["expedite_whatif"] = {
                "to_lead_days": expedite_lead_days,
                "finish_date": alt.get("finish_date"), "finish_day": alt.get("finish_day"),
                "days_pulled_in": (int(run.get("finish_day") or 0) - int(alt.get("finish_day") or 0))
                                  if alt.get("finish_day") is not None else None,
                "standby_days_saved": (float(run.get("standby_person_days_if_line_held") or 0)
                                       - float(alt.get("standby_person_days_if_line_held") or 0)),
            }
        runs.append(run)
    ok = [r for r in runs if r["status"] == "simulated"]
    total_late = sum(max(0, int(r["days_late"] or 0)) for r in ok)
    on_time = sum(1 for r in ok if (r["days_late"] or 0) <= 0)
    return {
        "factory_id": factory_id, "today": str(today), "targets": len(runs),
        "simulated": len(ok), "no_basis": len(runs) - len(ok),
        "on_time_orders": on_time, "total_days_late": total_late,
        "person_days_total": round(sum(float(r["person_days"] or 0) for r in ok), 1),
        "standby_person_days_total": round(sum(float(r["standby_person_days_if_line_held"] or 0) for r in ok), 1),
        "material_cost_usd": round(sum(float(r["material_cost_usd"] or 0) for r in ok), 2),
        "labor_cost_usd": round(sum(float(r["labor_cost_usd"] or 0) for r in ok), 2),
        "standby_cost_total_usd": round(sum(float(r["standby_cost_if_line_held_usd"] or 0) for r in ok), 2),
        "runs": runs,
        "assumptions": {
            "attendance_curve": "按天到岗率（沙箱默认 0.97，可传曲线：干旱/雨/暴雨档）",
            "labor_cost_per_person_day": DEFAULT_LABOR_COST_PER_PERSON_DAY,
            "labor_cost_basis": "default_calibration（库里没有薪资列，钱只到量级）",
            "material_price_source": "bom_items.unit_price（缺价就单列 materials_without_price，不折算）",
            "lead_time_source": "materials.lead_time_days（外购全部有值）",
        },
    }

async def build_policy_grid(db: AsyncSession, factory_id: str,
                            targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """政策档位从库里长出来，不写死：加急到几天、能并联几条线、能加多少人，都由现有数据决定。"""
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    grid: List[Dict[str, Any]] = [{"name": "现况（分批开工）", "allow_partial": True},
                                  {"name": "等齐套才开工（不分批）", "allow_partial": False}]
    leads = set()
    for t in targets:
        bom = [dict(r) for r in (await db.execute(
            BOM_SQL, {"fid": factory_id, "model": str(t["model_code"])})).mappings().all()]
        for r in bom:
            lead = str(r.get("lead_time_days") or "")
            if lead.isdigit() and int(lead) > 2:
                leads.add(int(lead))
    for lead in sorted(leads, reverse=True)[:3]:
        for factor, label in ((2, "减半"), (4, "压到 1/4")):
            value = max(1, lead // factor)
            grid.append({"name": f"瓶颈件提前期 {lead} 天 → {value} 天（{label}）",
                         "expedite_lead_days": value})
    groups: Dict[str, int] = {}
    for l in lines:
        groups[str(l.get("line_group") or l["line_code"])] = groups.get(
            str(l.get("line_group") or l["line_code"]), 0) + 1
    for grp, n in groups.items():
        if n >= 2:
            grid.append({"name": f"同组并联开满（{grp}={n} 条线）", "parallel_lines": n})
    grid.append({"name": "加班加人 15%", "crew_bonus": 0.15})
    grid.append({"name": "加班加人 30%", "crew_bonus": 0.30})
    # 这不是产能，是把已经答应该做的活往后推：必须点名"插单"，并且默认不许靠它宣布准点
    grid.append({"name": "插单（抢占已在排的活）", "ignore_backlog": True,
                 "displaces_committed_work": True})
    grid.append({"name": "加急 1/4 + 并联开满", "expedite_lead_days": (
        max(1, sorted(leads, reverse=True)[0] // 4) if leads else 5), "parallel_lines": 2})
    return grid


def group_capacity(lines: List[Dict[str, Any]], line: Dict[str, Any],
                   parallel_lines: int) -> Dict[str, Any]:
    """并联产能只能按线组声明的合并产能算 —— 跑步机线 11h/300 台、bike 单线 400 台但
    **两线合并 700 不是 800**（用户 10-06 第三次口述定稿）。按 n×单线乘出来的产能会凭空多出 14% 富余，
    而这 14% 正好会改变"缺料能不能靠另一条线追回"的结论。"""
    single = float(line.get("units_per_day") or 0)
    group = str(line.get("line_group") or "")
    n = max(1, int(parallel_lines))
    if n <= 1 or not group:
        return {"units_per_day": single, "capacity_basis": "single_line",
                "crew": float(line.get("crew_size") or 0)}
    members = [l for l in lines if str(l.get("line_group") or "") == group]
    group_total = float((members[0] if members else {}).get("group_units_per_day") or 0)
    crew_total = sum(float(l.get("crew_size") or 0) for l in members[:n]) if members else float(
        line.get("crew_size") or 0) * n
    if group_total > 0:
        # 合并产能是厂里声明的上限，最多用到它，不许按线数乘出来
        return {"units_per_day": round(min(single * n, group_total), 2),
                "capacity_basis": f"group_declared({group}={group_total:g}/天)",
                "crew": round(crew_total, 1)}
    return {"units_per_day": single * n, "capacity_basis": f"multiplied({n} lines, 组内未声明合并产能)",
            "crew": round(crew_total, 1)}


async def default_models(db: AsyncSession, factory_id: str, n: int = 2) -> List[str]:
    """默认取 BOM 最完整的 n 个机种，不从代码里写死机种名。"""
    rows = (await db.execute(text("""
        SELECT product_id FROM bom_items WHERE factory_id = :fid
        GROUP BY product_id HAVING count(*) >= 8 ORDER BY count(*) DESC LIMIT :n
    """), {"fid": factory_id, "n": n})).scalars().all()
    return [str(r) for r in rows]


async def derive_targets(db: AsyncSession, factory_id: str, models: List[str],
                         *, days_of_output: float = 6.0, lead_margin: float = 1.15
                         ) -> List[Dict[str, Any]]:
    """场景自己标定，不拍脑袋。

    批量 = 该线若干天的产量（少到 1 天就能做完的话，产能/人力/线这些维度全都没区分度）；
    交期 = 瓶颈件提前期 × 系数（比提前期还宽的话，所有政策都准点，准点这维也是废的）。
    这是上一轮自己发现的偏差：300 台配 30 天交期，12 个政策全部"准点 1.00"，比较不出任何东西。
    """
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    targets: List[Dict[str, Any]] = []
    for model in models:
        line, line_basis = pick_line(model, lines)
        per_day = float((line or {}).get("units_per_day") or 0)
        bom = [dict(r) for r in (await db.execute(
            BOM_SQL, {"fid": factory_id, "model": model})).mappings().all()]
        codes = [str(r["material_code"]) for r in bom]
        lead_rows = (await db.execute(text("""
            SELECT MAX(COALESCE(m.lead_time_days, 0)) AS max_lead
            FROM materials m WHERE m.factory_id = :fid AND m.material_code = ANY(CAST(:codes AS text[]))
        """), {"fid": factory_id, "codes": codes})).mappings().first() if codes else None
        max_lead = int((lead_rows or {}).get("max_lead") or 0)
        units = int(per_day * days_of_output) if per_day > 0 else 300
        due_in_days = int(max(1, round(max(1, max_lead) * lead_margin)))
        targets.append({"model_code": model, "units": units, "due_in_days": due_in_days,
                        "calibration": f"批量={days_of_output:g} 天线产量（线 {per_day:g} 台/天）；"
                                       f"交期={max_lead} 天瓶颈提前期 × {lead_margin:g}"})
    return targets


# 可控政策（引擎能决定的事）与环境场景（只能接受的事）分开：
# 把天气当成"可选政策"放进同一个前沿比后悔是错的 —— 厂里没人能选天气。
POLICIES: List[Dict[str, Any]] = [
    {"name": "现况（分批开工·正常出勤）", "allow_partial": True},
    {"name": "等齐套才开工（不分批）", "allow_partial": False},
    {"name": "瓶颈件加急到 10 天", "expedite_lead_days": 10},
    {"name": "瓶颈件加急到 5 天", "expedite_lead_days": 5},
    {"name": "开并联第二条线", "parallel_lines": 2},
    {"name": "加班加人 15%", "crew_bonus": 0.15},
    {"name": "加急 10 天 + 开并联线", "expedite_lead_days": 10, "parallel_lines": 2},
    {"name": "开并联线 + 加班 15%", "parallel_lines": 2, "crew_bonus": 0.15},
]

WEATHER_SCENARIOS: List[Dict[str, Any]] = [
    {"name": "好天（到岗 0.97）", "attendance": 0.97},
    {"name": "雨季（到岗 0.92）", "attendance": 0.92},
    {"name": "暴雨（到岗 0.70）", "attendance": 0.70},
]


def _objectives(run: Dict[str, Any], demand_units: float, due_day: int) -> Dict[str, Any]:
    finish = run.get("finish_day")
    late = max(0, int(finish) - int(due_day)) if finish is not None else max(0, due_day)
    made = float(run.get("units") or 0) if finish is not None else 0.0
    on_time = 1.0 if finish is not None and finish <= due_day else 0.0
    conf = {
        "route_standard_hours": 1.0, "own_route": 1.0,
        "line_declared_can_make": 1.0, "line_declared_home": 1.0, "line_declared_default_model": 1.0,
        "borrowed_route_from_family": 0.4, "takt_from_line_capacity": 0.35,
        "line_inferred_by_family_name": 0.5, "assumed_ie_hours": 0.3, "no_route": 0.0,
        "no_time_basis": 0.0, "no_line": 0.0,
    }

    def _c(v: Optional[str]) -> float:
        return conf.get(str(v), 0.6)
    weights = [_c(run.get("route_basis")), _c(run.get("hours_basis")), _c(run.get("line_basis"))]
    return {
        "on_time_rate": on_time,
        "throughput_units": made,
        "labor_cost_usd": float(run.get("labor_cost_usd") or 0),
        "expedite_cost_usd": float(run.get("expedite_cost_usd") or 0),
        "standby_person_days": float(run.get("standby_person_days_if_line_held") or 0),
        "data_confidence": round(sum(weights) / len(weights), 4),
        "load_band_gap": float(run.get("load_band_gap") or 0),
        "days_late": late,
        "finish_date": run.get("finish_date"),
    }


async def scan_policies(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                        *, today: Optional[date] = None,
                        policies: Optional[List[Dict[str, Any]]] = None,
                        scenarios: Optional[List[Dict[str, Any]]] = None,
                        targets_by_scenario: Optional[Dict[str, List[Dict[str, Any]]]] = None
                        ) -> Dict[str, Any]:
    """让引擎自己扫政策组合：同一批目标在多种产能/出勤/采购/分批政策下的多目标结果。

    这里刻意不给"唯一总分"。每个政策产出一个目标向量，交给 pareto_eval 判前沿与平衡解 ——
    工厂是取舍，不是考试。
    """
    today = today or date.today()
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or {1, 2, 3, 4, 5, 6}
    policies = policies or await build_policy_grid(db, factory_id, targets)
    scenarios = scenarios or WEATHER_SCENARIOS
    demand_units = sum(float(t.get("units") or 0) for t in targets)
    demand_by_scenario: Dict[str, float] = {}

    equip = await equipment_rate(db, factory_id)
    busy_by_line: Dict[str, Dict[str, Any]] = {}
    for l in lines:
        busy_by_line[l["line_code"]] = await line_committed_days(db, factory_id, l)
    # 同组线共享已承诺量：一条线排着的活，并联时也占同一批人力/同一组产能
    group_busy: Dict[str, float] = {}
    for l in lines:
        grp = str(l.get("line_group") or l["line_code"])
        group_busy[grp] = max(group_busy.get(grp, 0.0),
                              float(busy_by_line[l["line_code"]]["busy_days"]))
    cache: Dict[str, Any] = {}
    grouped: Dict[str, Any] = {}
    for scen in scenarios:
      curve = {d: float(scen.get("attendance", 0.97)) for d in range(0, 400)}
      # 每个天气场景可以用自己标定的目标（批量/交期系数），全局值兜底
      scen_targets = (targets_by_scenario or {}).get(scen["name"]) or targets
      demand_by_scenario[scen["name"]] = 0.0   # 逐政策算，只算"能推演的那部分需求"
      solutions: List[Dict[str, Any]] = []
      for pol in policies:
        per_run: List[Dict[str, Any]] = []
        # 本轮模拟出来的单也要排队：同一条线组的产能是它们一起占的。以前每台单只吃
        # "真实已承诺量"，于是三台跑步机机种各占 GROUP-TREAD 十几天却互不遮挡，
        # 交期普遍算得偏乐观 —— 而"谁先做"本来是引擎要做的决定，不是背景假设。
        allocated: Dict[str, float] = {} if pol.get("ignore_backlog") else dict(group_busy)
        ordered = sorted(scen_targets, key=lambda x: (int(x.get("due_in_days") or 999),
                                                      str(x.get("model_code"))))
        for t in ordered:
            due_day = int(t.get("due_in_days") or 30)
            line_of_t = pick_line(str(t["model_code"]), lines)[0] or {}
            grp = str(line_of_t.get("line_group") or line_of_t.get("line_code") or "")
            busy = float(allocated.get(grp, 0.0) or 0.0)
            run = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                                   today + timedelta(days=due_day), today, curve, lines, shift_days,
                                   expedite_lead_days=pol.get("expedite_lead_days"),
                                   allow_partial=bool(pol.get("allow_partial", True)),
                                   parallel_lines=int(pol.get("parallel_lines", 1)),
                                   crew_bonus=float(pol.get("crew_bonus", 0.0)),
                                   cached=cache, line_busy_days=(0.0 if pol.get("ignore_backlog") else busy),
                                   equip_rate=float(equip.get("rate") or 1.0))
            allocated[grp] = busy + float(run.get("work_days") or 0)
            per_run.append({"run": run, "due_day": due_day, "units": float(t.get("units") or 0)})
        # 没有工时依据/没有可归属线的机种不算"厂里做不到"，是模型还代表不了它 —— 缺的是数据。
        # 把它们留在需求量里，每个政策都会卡产量底线，整轮扫描退化成"全都不可行"（实测踩过）。
        work = [x for x in per_run if x["run"].get("status") == "simulated"]
        blocked = [{"model_code": x["run"].get("model_code"), "units": x["units"],
                    "status": x["run"].get("status"), "why": x["run"].get("why")}
                   for x in per_run if x["run"].get("status") != "simulated"]
        if not work:
            solutions.append({"id": f"{scen['name']}-pol{len(solutions)}", "name": pol["name"],
                              "scenario": scen["name"],
                              "attendance": float(scen.get("attendance", 0.97)),
                              "policy": pol, "objectives": {}, "evidence": {},
                              "blocked_models": blocked, "detail": [],
                              "displaces_committed_work": bool(pol.get("ignore_backlog")),
                              "note": "这些机种都没有可推演的依据（缺工时/缺可归属线），本轮不产出解"})
            continue
        demand_by_scenario[scen["name"]] = round(sum(float(x["units"] or 0) for x in work), 2)
        worst_late = max(_objectives(x["run"], x["units"], x["due_day"])["days_late"] for x in work)
        on_time_n = sum(1 for x in work
                        if _objectives(x["run"], x["units"], x["due_day"])["on_time_rate"] >= 1.0)
        made = sum(_objectives(x["run"], x["units"], x["due_day"])["throughput_units"] for x in work)
        objs = {
            "on_time_rate": round(on_time_n / max(1, len(work)), 4),
            "throughput_units": round(made, 2),
            "labor_cost_usd": round(sum(float(x["run"].get("labor_cost_usd") or 0) for x in work), 2),
            "expedite_cost_usd": round(sum(float(x["run"].get("expedite_cost_usd") or 0)
                                           for x in work), 2),
            "standby_person_days": round(sum(float(x["run"].get("standby_person_days_if_line_held") or 0)
                                             for x in work), 1),
            "data_confidence": round(sum(_objectives(x["run"], x["units"], x["due_day"])["data_confidence"]
                                         for x in work) / max(1, len(work)), 4),
            "load_band_gap": round(sum(_objectives(x["run"], x["units"], x["due_day"])["load_band_gap"]
                                       for x in work) / max(1, len(work)), 4),  # 区间外才扣分
            "line_activation_cost_usd": round(sum(float(x["run"].get("line_activation_cost_usd") or 0)
                                                  for x in work), 2),
            # 连续延误天数：0/1 准点率会让"延 1 天"和"延 20 天"在后悔值上一样重
            "days_late_worst": worst_late,
        }
        solutions.append({
            "id": f"{scen['name']}-pol{len(solutions)}", "name": pol["name"],
            "scenario": scen["name"], "attendance": float(scen.get("attendance", 0.97)),
            "policy": pol,
            "objectives": objs,
            "blocked_models": blocked,
            "displaces_committed_work": bool(pol.get("ignore_backlog")),
            "sequencing": ("同一线组按交期先后排队（EDD）：每台单占用它自己的工时天数，"
                           "后面的单要等前面的做完才能上；"
                           "'插单'政策放开的是真实已排的活，默认不参与择优（见 pareto_eval）"),
            "evidence": {str(x["run"].get("route_basis")): 1 for x in work}
                        | {str(x["run"].get("hours_basis")): 1 for x in work}
                        | {str(x["run"].get("line_basis")): 1 for x in work},
            "detail": [{"model_code": x["run"].get("model_code"),
                        "units": x["run"].get("units"), "finish_date": x["run"].get("finish_date"),
                        "due_date": x["run"].get("due_date"), "days_late": x["run"].get("days_late"),
                        "status": x["run"].get("status"), "line": x["run"].get("line"),
                        "why": x["run"].get("why"),
                        "queue_days_before_this_order": x["run"].get("line_busy_days_before_order"),
                        "capacity_basis": x["run"].get("capacity_basis"),
                        "material_arrival_day": x["run"].get("material_arrival_day"),
                        "batch_a_units": x["run"].get("batch_a_units"),
                        "batch_b_units": x["run"].get("batch_b_units"),
                        "batch_decision": x["run"].get("batch_decision"),
                        "blockers": x["run"].get("blockers"),
                        "po_lines": x["run"].get("po_lines"),
                        "bottleneck_part": x["run"].get("bottleneck_part")} for x in per_run],
        })
      grouped[scen["name"]] = {"attendance": float(scen.get("attendance", 0.97)),
                               "solutions": solutions}
    total = sum(len(v["solutions"]) for v in grouped.values())
    return {"factory_id": factory_id, "today": str(today), "demand_units": demand_units,
            "demand_by_scenario": demand_by_scenario,
            "policies_tried": total, "scenarios": list(grouped),
            "by_scenario": grouped,
            "note": ("前沿在每个天气场景内部各算一次：天气不是可选政策。"
                     "跨场景的推荐按'各场景推荐解里后悔向量最稳的那个'给。")}

