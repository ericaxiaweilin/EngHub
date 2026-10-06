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
    SELECT line_code, line_group, hours_per_day, units_per_day, crew_size,
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
                     expedite_lead_days: Optional[int] = None) -> Dict[str, Any]:
    """把一个目标跑成一条演变时间线。"""
    bom = [dict(r) for r in (await db.execute(
        BOM_SQL, {"fid": factory_id, "model": model})).mappings().all()]
    codes = [str(r["material_code"]) for r in bom]
    stock_rows = (await db.execute(STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() if codes else []
    stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}

    route_own = await route_ops_for_product(db, factory_id, model)
    family_rows = [] if route_own else await load_family_route(db, factory_id, model)
    route, route_basis = resolve_route([dict(o) for o in route_own], family_rows)
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

    earliest_start = max(arrival, child_days)
    if hours_basis == "no_time_basis":
        return {"model_code": model, "units": units, "status": "no_time_basis",
                "why": "既没有路线工时，也没有可归属的线节拍（线都没声明能做它）",
                "route_basis": route_basis, "line_basis": line_basis,
                "kit": {k: kit[k] for k in ("buy_arrival_days", "blockers", "material_cost",
                                            "materials_without_price")},
                "due": str(due)}

    hours_per_day = float((line or {}).get("hours_per_day") or 11)
    crew = float((line or {}).get("crew_size") or 0)
    cap = float((line or {}).get("units_per_day") or 0)

    # 引擎的决策（不是计算器会做的事）：现料能做几台就先开几台，剩下的排在到货日之后
    coverable = []
    for l in kit["lines"]:
        per = float(l["need"] / units) if units else 0.0
        coverable.append(int(l["have"] / per) if per > 0 else int(units))
    stock_units = min(coverable, default=0)
    batch_a = min(int(units), max(0, stock_units))
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


