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
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

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


async def auto_tune(db: AsyncSession, factory_id: str, models: List[str], *, rounds: int = 3,
                     days_of_output: float = 6.0, lead_margin: float = 1.15) -> Dict[str, Any]:
    """自己标定 → 自己扫 → 看失败原因 → 改标定/改网格 → 再扫。

    三条调参规则都是从"上一轮哪里白算了"推出来的，不是拍脑袋：
    ① 所有政策都准点 ⇒ 场景太松：收紧交期系数或加大批量，让准点这维真的有区分度；
    ② 没有任何政策准点 ⇒ 场景不可能：把最狠的加急/并联档加进网格，或如实报告
       "以现有提前期这个交期做不到"（这本身就是结论，不是失败）；
    ③ 可行解 ≤2 个 ⇒ 比较没有意义：放宽一档标定或补政策档位，并标注本轮只做可行性筛选。
    """
    trajectory: List[Dict[str, Any]] = []
    grid_extra: List[Dict[str, Any]] = []
    for rnd in range(max(1, rounds)):
        targets = await derive_targets(db, factory_id, models, days_of_output=days_of_output,
                                       lead_margin=lead_margin)
        grid = await build_policy_grid(db, factory_id, targets)
        for extra in grid_extra:
            if extra["name"] not in {g["name"] for g in grid}:
                grid.append(extra)
        scan = await scan_policies(db, factory_id, targets, policies=grid)
        from api.services.pareto_eval import evaluate_by_scenario
        verdict = evaluate_by_scenario(scan["by_scenario"], scan["demand_units"])
        per = {k: {"recommended": (v.get("recommended") or {}).get("name"),
                  "feasible": len(v.get("frontier") or []) + len(v.get("dominated") or []),
                  "eliminated": len(v.get("eliminated") or []),
                  "no_feasible": bool(v.get("no_feasible_solution")),
                  "dead_dims": v.get("non_discriminating_objectives") or []}
               for k, v in (verdict.get("by_scenario") or {}).items()}
        feasible_counts = [p2["feasible"] for p2 in per.values()]
        all_on_time = all(p2["eliminated"] == 0 for p2 in per.values())
        none_on_time = any(p2["no_feasible"] for p2 in per.values())
        action = {
            "round": rnd,
            "calibration": {"days_of_output": days_of_output, "lead_margin": lead_margin},
            "per_scenario": per,
            "robust": (verdict.get("robust_recommendation") or {}).get("policy"),
            "policies_tried": len(grid),
            "diagnosis": None, "next_tweak": None,
        }
        if none_on_time:
            action["diagnosis"] = "有天气场景下没有任何政策能准点交付"
            if lead_margin < 1.6:
                lead_margin = round(lead_margin + 0.15, 2)
                action["next_tweak"] = f"放宽交期系数到 {lead_margin}（先分清是政策不行还是交期本身不可能）"
            else:
                grid_extra.append({"name": "极限加急（提前期压到 2 天）+ 并联开满",
                                   "expedite_lead_days": 2, "parallel_lines": 2})
                action["next_tweak"] = "交期已放宽到 1.6 倍仍无解 → 补一档极限加急政策试试；" \
                                       "再不行就是现有供应链提前期下这个交期做不到（这是结论）"
        elif all_on_time:
            action["diagnosis"] = "所有政策都准点：准点这维没有区分度，场景标得太松"
            lead_margin = round(max(0.8, lead_margin - 0.1), 2)
            action["next_tweak"] = f"收紧交期系数到 {lead_margin}"
        elif feasible_counts and min(feasible_counts) <= 2:
            action["diagnosis"] = "可行解太少（≤2），本轮只做可行性筛选，不宣称择优"
            days_of_output = max(2.0, days_of_output - 1.0)
            action["next_tweak"] = f"批量降到 {days_of_output:g} 天线产量，看中间地带"
        else:
            action["diagnosis"] = "各场景都有 ≥3 个可行解：本轮前沿与后悔比较可用"
        trajectory.append(action)
        if action["diagnosis"].startswith("各场景都有"):
            break
    return {"factory_id": factory_id, "rounds": len(trajectory),
            "targets": targets, "final": trajectory[-1], "trajectory": trajectory,
            "rule": "标定期望落在中间地带：既有政策能准点、也有政策会延期；两边都饱和时比较没有信息。"}


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
    grid.append({"name": "无视已排 backlog 插单", "ignore_backlog": True})
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
                        scenarios: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
      solutions: List[Dict[str, Any]] = []
      for pol in policies:
        per_run: List[Dict[str, Any]] = []
        for t in targets:
            due_day = int(t.get("due_in_days") or 30)
            busy = float((busy_by_line.get(str((pick_line(str(t["model_code"]), lines)[0] or {}).get("line_code") or ""),
                                       {"busy_days": 0.0})).get("busy_days") or 0.0)
            run = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                                   today + timedelta(days=due_day), today, curve, lines, shift_days,
                                   expedite_lead_days=pol.get("expedite_lead_days"),
                                   allow_partial=bool(pol.get("allow_partial", True)),
                                   parallel_lines=int(pol.get("parallel_lines", 1)),
                                   crew_bonus=float(pol.get("crew_bonus", 0.0)),
                                   cached=cache, line_busy_days=(0.0 if pol.get("ignore_backlog") else busy),
                                   equip_rate=float(equip.get("rate") or 1.0))
            per_run.append({"run": run, "due_day": due_day, "units": float(t.get("units") or 0)})
        worst_late = max(_objectives(x["run"], x["units"], x["due_day"])["days_late"] for x in per_run)
        on_time_n = sum(1 for x in per_run
                        if _objectives(x["run"], x["units"], x["due_day"])["on_time_rate"] >= 1.0)
        made = sum(_objectives(x["run"], x["units"], x["due_day"])["throughput_units"] for x in per_run)
        objs = {
            "on_time_rate": round(on_time_n / max(1, len(per_run)), 4),
            "throughput_units": round(made, 2),
            "labor_cost_usd": round(sum(float(x["run"].get("labor_cost_usd") or 0) for x in per_run), 2),
            "expedite_cost_usd": round(sum(float(x["run"].get("expedite_cost_usd") or 0)
                                           for x in per_run), 2),
            "standby_person_days": round(sum(float(x["run"].get("standby_person_days_if_line_held") or 0)
                                             for x in per_run), 1),
            "data_confidence": round(sum(_objectives(x["run"], x["units"], x["due_day"])["data_confidence"]
                                         for x in per_run) / max(1, len(per_run)), 4),
            "load_band_gap": round(sum(_objectives(x["run"], x["units"], x["due_day"])["load_band_gap"]
                                       for x in per_run) / max(1, len(per_run)), 4),  # 区间外才扣分
            # 连续延误天数：0/1 准点率会让"延 1 天"和"延 20 天"在后悔值上一样重
            "days_late_worst": max(_objectives(x["run"], x["units"], x["due_day"])["days_late"]
                                   for x in per_run),
            "line_activation_cost_usd": round(sum(float(x["run"].get("line_activation_cost_usd") or 0)
                                                  for x in per_run), 2),
            "days_late_worst": worst_late,
        }
        solutions.append({
            "id": f"{scen['name']}-pol{len(solutions)}", "name": pol["name"],
            "scenario": scen["name"], "attendance": float(scen.get("attendance", 0.97)),
            "policy": pol,
            "objectives": objs,
            "evidence": {str(x["run"].get("route_basis")): 1 for x in per_run}
                        | {str(x["run"].get("hours_basis")): 1 for x in per_run}
                        | {str(x["run"].get("line_basis")): 1 for x in per_run},
            "detail": [{"model_code": x["run"].get("model_code"),
                        "finish_date": x["run"].get("finish_date"),
                        "status": x["run"].get("status"),
                        "batch_decision": x["run"].get("batch_decision"),
                        "bottleneck_part": x["run"].get("bottleneck_part")} for x in per_run],
        })
      grouped[scen["name"]] = {"attendance": float(scen.get("attendance", 0.97)),
                               "solutions": solutions}
    total = sum(len(v["solutions"]) for v in grouped.values())
    return {"factory_id": factory_id, "today": str(today), "demand_units": demand_units,
            "policies_tried": total, "scenarios": list(grouped),
            "by_scenario": grouped,
            "note": ("前沿在每个天气场景内部各算一次：天气不是可选政策。"
                     "跨场景的推荐按'各场景推荐解里后悔向量最稳的那个'给。")}

