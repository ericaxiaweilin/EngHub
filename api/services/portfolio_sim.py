"""机种组合推演（只读）：按现有线/HR/设备/库存把 N 个机种排队上线，出货期、人力利用、评分。

不写库、不改单：这是对**现有声明数据**能算出什么的读数，不是新事实。三条原则：

1. 时间只认两类出处：线参数（`line_profiles.units_per_day` + `hours_per_day`）或工艺路线声明的
   单件工时；两者都没有就标 `no_time_basis`，这一单**不出货期**，不拿平均值蒙一个。
2. 齐套按 BOM × 现库存算：缺的料号用 `materials.lead_time_days`（有就折算，没有就标 unknown），
   绝不用"通常 7 天"这种假设填数。
3. 评分是加权透明分：每一项扣分都能追溯到哪个输入扣分，并且给"改掉它能涨几分"的杠杆排名 ——
   这就是飞轮：先量出瓶颈，再逐条试杠杆看得分怎么变，而不是猜哪个改动有用。
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from core.mes.route_resolution import route_ops_for_product
from sqlalchemy.ext.asyncio import AsyncSession

# 交付权重：用户口径"要的是交货日期和人力利用"，所以准点与人力两条最重
WEIGHTS = {"delivery": 0.40, "labor": 0.25, "kit": 0.20, "equipment": 0.10, "basis": 0.05}
WEEKEND_OFF = os.getenv("PORTFOLIO_SIM_WEEKEND", "off").lower() != "work"


MODEL_CANDIDATES_SQL = text("""
    SELECT b.product_id AS model_code,
           count(*) AS bom_lines,
           COUNT(DISTINCT b.material_code) AS materials,
           MAX(COALESCE(b.level, 1)) AS bom_levels,
           COUNT(*) FILTER (WHERE COALESCE(b.qty_per_unit, b.quantity, 0) > 0) AS lines_with_qty
    FROM bom_items b
    WHERE b.factory_id = :fid
    GROUP BY b.product_id
    HAVING count(*) >= :min_lines
    ORDER BY count(*) DESC, COUNT(DISTINCT b.material_code) DESC
    LIMIT :lim
""")

BOM_LINES_SQL = text("""
    SELECT material_code, material_name, COALESCE(qty_per_unit, quantity, 0) AS qty_per_unit, unit, level
    FROM bom_items WHERE factory_id = :fid AND product_id = :model
""")

STOCK_SQL = text("""
    SELECT i.material_code, SUM(COALESCE(i.available_qty, 0)) AS available
    FROM inventory i WHERE i.factory_id = :fid AND i.material_code = ANY(CAST(:codes AS text[]))
    GROUP BY i.material_code
""")

LEAD_TIME_SQL = text("""
    SELECT m.material_code AS code, m.lead_time_days, m.default_supplier FROM materials m WHERE m.material_code = ANY(CAST(:codes AS text[]))
""")

LINE_SQL = text("""
    SELECT line_code, line_group, hours_per_day, units_per_day, group_units_per_day,
           crew_size, parallel_lines, can_make_models::text AS can_models, default_model
    FROM line_profiles WHERE factory_id = :fid AND is_active = true ORDER BY line_code
""")

ROUTE_SQL = text("""
    SELECT s.seq, s.operation_name, s.work_center, s.standard_hours
    FROM routing_templates t JOIN routing_template_steps s ON s.template_id = t.id
    WHERE t.factory_id = :fid AND (t.template_name ILIKE :pat OR t.template_code ILIKE :pat)
    ORDER BY s.seq LIMIT 40
""")

STATION_EQUIPMENT_SQL = text("""
    SELECT e.station_id,
           COUNT(*) FILTER (WHERE e.status = 'running') AS running,
           COUNT(*) FILTER (WHERE e.status IN ('maintenance', 'broken')) AS down,
           COUNT(*) AS total
    FROM equipment e WHERE e.factory_id = :fid GROUP BY e.station_id
""")

HR_HEADCOUNT_SQL = text("""
    SELECT COUNT(*) AS people FROM hr_employees
    WHERE factory_id = :fid AND status = 'active'
""")

CALENDAR_SQL = text("""
    SELECT day_of_week AS weekday, start_time, end_time FROM aps_work_calendars
    WHERE (factory_id = :fid OR (factory_id = 'default' AND :fid <> 'default'))
      AND is_active = true
    ORDER BY weekday, start_time
""")


def working_days_needed(units: float, units_per_day: float) -> float:
    if units_per_day <= 0:
        return 0.0
    return round(float(units) / float(units_per_day), 2)


def add_working_days(start: date, days: float, shift_weekdays: set) -> date:
    """按班次日历往后推 N 个工作日（非班次日跳过），小数天按半天算到次日。"""
    whole = int(days)
    current = start
    stepped = 0
    guard = 0
    while stepped < whole and guard < 4000:
        current += timedelta(days=1)
        guard += 1
        if current.isoweekday() in shift_weekdays:
            stepped += 1
    frac = days - whole
    if frac > 0:
        current += timedelta(days=1)
        while current.isoweekday() not in shift_weekdays:
            current += timedelta(days=1)
    return current


def kit_requirement(bom: List[Dict[str, Any]], units: float) -> Dict[str, float]:
    need: Dict[str, float] = {}
    for line in bom:
        code = str(line["material_code"])
        need[code] = need.get(code, 0.0) + float(line["qty_per_unit"] or 0) * float(units)
    return need


def score_delivery(on_time_days: Optional[float], *, has_basis: bool) -> float:
    """准点分：提前或按期 100，逾期按天衰减；算不出货期就是 0 分（不是"及格"）。"""
    if not has_basis or on_time_days is None:
        return 0.0
    late = max(0.0, float(on_time_days))
    return max(0.0, 100.0 - 6.0 * late)


def score_kit(shortage_lines: int, total_lines: int, blocked_forever: bool) -> float:
    if total_lines <= 0:
        return 0.0
    covered = 100.0 * (total_lines - shortage_lines) / total_lines
    if blocked_forever:
        covered = min(covered, 5.0)   # 缺料且没有任何到货依据 = 这单今天做不了
    return round(covered, 1)


def score_labor(utilization: Optional[float]) -> float:
    """人力利用分：这条线班组被占满几成窗口。80%~95% 健康；大片空档和长期超载都扣分。"""
    if utilization is None:
        return 0.0
    u = float(utilization)
    if u <= 0:
        return 0.0
    if 0.80 <= u <= 0.95:
        return 100.0
    if u < 0.80:
        return round(max(0.0, 100.0 - (0.80 - u) * 180.0), 1)
    return round(max(0.0, 100.0 - (u - 0.95) * 200.0), 1)


def weighted_total(parts: Dict[str, float]) -> float:
    return round(sum(parts[k] * WEIGHTS[k] for k in WEIGHTS), 1)


async def simulate(db: AsyncSession, factory_id: str, *, models: Optional[List[Dict[str, Any]]] = None,
                   n: int = 5, units_default: int = 300, demand_date: Optional[date] = None,
                   attendance_factor: Optional[float] = None,
                   extra_line: bool = False, crew_bonus: float = 0.0,
                   horizon_days: int = 30, ie_hours_per_unit: float = 0.0) -> Dict[str, Any]:
    """把 N 个机种按现有资源排队上线，出货期/人力/评分/杠杆。"""
    today = demand_date or date.today()

    if not models:
        picked = (await db.execute(MODEL_CANDIDATES_SQL, {
            "fid": factory_id, "min_lines": 8, "lim": n})).mappings().all()
        models = []
        for r in picked:
            # 批量优先取该机种历史最大工单量：这是厂里真下过的数，不是我设的默认值
            hist = (await db.execute(text("""
                SELECT MAX(planned_qty) AS q FROM work_orders
                WHERE factory_id = :fid AND product_id = :model AND planned_qty > 0
            """), {"fid": factory_id, "model": r["model_code"]})).mappings().first()
            qty = int((hist or {}).get("q") or 0) or int(units_default)
            models.append({"model_code": r["model_code"], "units": qty,
                           "units_basis": f"该机种历史最大工单量 {qty}" if (hist or {}).get("q")
                                          else f"库里没有该机型工单，按默认 {units_default}",
                           "due_date": add_working_days(today, 25, {1, 2, 3, 4, 5, 6})})
    lines = [dict(r) for r in (await db.execute(LINE_SQL, {"fid": factory_id})).mappings().all()]
    cal_rows = (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()
    shift_weekdays = {int(r["weekday"]) + 1 for r in cal_rows} or ({1, 2, 3, 4, 5, 6} if not WEEKEND_OFF else {1, 2, 3, 4, 5})
    total_people = int((await db.execute(HR_HEADCOUNT_SQL, {"fid": factory_id})).scalar() or 0)
    equip = [dict(r) for r in (await db.execute(STATION_EQUIPMENT_SQL, {"fid": factory_id})).mappings().all()]
    down_units = sum(int(r["down"]) for r in equip)
    total_units = sum(int(r["total"]) for r in equip)
    equipment_rate = (1.0 - down_units / total_units) if total_units else 1.0

    # 每条线一个占用游标：同一组线按合并日产能排队（不是简单相加）
    line_free_on: Dict[str, date] = {}
    results: List[Dict[str, Any]] = []
    horizon_working_days = max(1.0, float(horizon_days))

    for req in models:
        model = str(req["model_code"])
        units = float(req.get("units") or units_default)
        due = req.get("due_date") or add_working_days(today, 25, shift_weekdays)

        bom = [dict(r) for r in (await db.execute(BOM_LINES_SQL, {"fid": factory_id, "model": model})).mappings().all()]
        codes = [str(r["material_code"]) for r in bom]
        stock_rows = (await db.execute(STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() \
            if codes else []
        stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}
        lead_rows = (await db.execute(LEAD_TIME_SQL, {"codes": codes})).mappings().all() if codes else []
        lead = {str(r["code"]): r["lead_time_days"] for r in lead_rows}

        need = kit_requirement(bom, units)
        # 料号在库存里查不到 vs 查到但为 0：前者是"BOM 与库存对不上"（#36），不是缺 2 万件
        no_stock_record = sorted(c for c in need if c not in stock)
        shortages = {c: round(need[c] - stock.get(c, 0.0), 3) for c in need if need[c] - stock.get(c, 0.0) > 0}
        unknown_lead = sorted(c for c in shortages if lead.get(c) in (None, ""))
        known_leads = [int(lead[c]) for c in shortages if str(lead.get(c) or "").isdigit()]
        if known_leads:
            kit_ready_on = add_working_days(today, max(known_leads), shift_weekdays)
        elif shortages:
            kit_ready_on = None      # 缺料且没有任何到货期依据：不编一个可开工日
        else:
            kit_ready_on = today

        # 路线只用那份唯一解析口径（工单模板 → 旧版 routings JSON），不在这再写一套匹配
        route = await route_ops_for_product(db, factory_id, model)
        route_hours = round(sum(float(r.get("standard_hours") or 0) for r in route), 4)

        home = next((l for l in lines if model in str(l["can_models"]) and l["default_model"] == model), None)
        usable = [l for l in lines if model in str(l["can_models"])]
        chosen = home or (usable[0] if usable else None)

        assumed_hours = 0.0
        if route_hours <= 0 and ie_hours_per_unit > 0:
            route_hours = round(float(ie_hours_per_unit) * max(1, len(route)), 4)
            assumed_hours = round(float(ie_hours_per_unit), 4)

        if chosen:
            per_day = float(chosen["units_per_day"] or 0)
            if extra_line and chosen["line_group"]:
                group = [l for l in lines if l["line_group"] == chosen["line_group"]]
                per_day = float(group[0]["group_units_per_day"] or per_day) / max(1, len(group)) \
                    if len(group) > 1 else per_day * 2.0
            basis = "line_profiles"
            days = working_days_needed(units, per_day)
            crew = float(chosen["crew_size"] or 0)
        elif route_hours > 0:
            basis = "assumed_ie_hours" if assumed_hours else "routing_template_steps"
            per_day = float((next((l for l in lines if l["line_code"]), {}) or {}).get("hours_per_day") or 11)
            days = round(route_hours * units / per_day, 2)
            crew = 0.0
        else:
            basis = "no_time_basis"
            days = 0.0
            crew = 0.0

        key = chosen["line_code"] if chosen else model
        start_after_line = line_free_on.get(key, today)
        start = max(start_after_line, kit_ready_on) if kit_ready_on else (start_after_line if days else None)
        finish = add_working_days(start, days, shift_weekdays) if (start and days) else None
        if finish:
            line_free_on[key] = finish

        attend = float(attendance_factor if attendance_factor is not None else 1.0)
        present_crew = round(crew * attend * (1.0 + crew_bonus), 1)
        person_days = round(present_crew * days, 1)
        # 分母 = 这条线声明班组在占用天数里应到的工日（不是全厂人数 × 整个窗口，那必然算出个位数利用率）
        # 单条单的"人力利用"看的是它把这条线的班组占满了几成窗口：
        # 只占 1 天而窗口 30 天 = 这条线 96% 时间在等活，那才是该被扣分的东西。
        occupancy = round(min(1.0, days / horizon_working_days), 4) if days else None
        factory_load = round(person_days / max(1.0, total_people * attend * horizon_working_days), 4) if person_days else None
        utilization = occupancy
        units_per_person_day = round(units / person_days, 2) if person_days else None
        on_time_days = None if not finish else round((due - finish).days, 1)

        late_days = 0.0 if (on_time_days is None or on_time_days >= 0) else abs(on_time_days)
        parts = {
            "delivery": score_delivery(late_days, has_basis=bool(finish)),
            "labor": score_labor(utilization),
            "kit": score_kit(len(shortages), len(need), blocked_forever=bool(shortages and kit_ready_on is None)),
            "equipment": round(100.0 * equipment_rate, 1),
            "basis": 100.0 if basis != "no_time_basis" else 0.0,
        }
        total = weighted_total(parts)

        results.append({
            "model_code": model, "units": units, "units_basis": req.get("units_basis"),
            "bom_lines": len(bom), "materials": len(need),
            "due_date": str(due), "time_basis": basis,
            "line": (chosen or {}).get("line_code"), "line_group": (chosen or {}).get("line_group"),
            "units_per_day": round(float((chosen or {}).get("units_per_day") or 0), 1),
            "route_steps": len(route), "route_hours_per_unit": route_hours,
            "assumed_hours_per_step": assumed_hours or None,
            "production_days": days,
            "earliest_start": str(start) if start else None,
            "estimated_finish": str(finish) if finish else None,
            "days_vs_due": on_time_days,
            "crew_declared": crew, "crew_present_after_attendance": present_crew,
            "person_days_used": person_days,
            "labor_utilization": utilization,
            "units_per_person_day": units_per_person_day,
            "factory_load_share": factory_load,
            "bom_materials_without_stock_record": len(no_stock_record),
            "bom_to_stock_match_rate": round(1.0 - len(no_stock_record) / len(need), 4) if need else None,
            "kit_shortage_lines": len(shortages),
            "kit_shortage_units": round(sum(shortages.values()), 1),
            "kit_ready_on": str(kit_ready_on) if kit_ready_on else None,
            "kit_blockers_no_lead_data": unknown_lead[:8],
            "score": total, "score_parts": parts,
            "binding_constraint": (
                "算不出货期：既没有可做的线，也没有路线工时" if basis == "no_time_basis" else
                "缺料且没有任何到货期依据" if shortages and kit_ready_on is None else
                "缺料，等采购提前期" if shortages else
                "产线排队" if start and start_after_line > (kit_ready_on or today) else
                "交期本身（按期可做）"),
        })

    avg = round(sum(r["score"] for r in results) / len(results), 1) if results else 0.0
    return {
        "factory_id": factory_id, "as_of": str(today),
        "models_simulated": len(results),
        "weights": WEIGHTS,
        "portfolio_score": avg,
        "shift_weekdays": sorted(shift_weekdays),
        "attendance_factor": None if attendance_factor is None else round(float(attendance_factor), 4),
        "hr_active_people": total_people,
        "equipment_available_rate": round(equipment_rate, 4),
        "lines": [{k: l[k] for k in ("line_code", "line_group", "units_per_day",
                                     "group_units_per_day", "crew_size", "hours_per_day")} for l in lines],
        "orders": results,
        "levers": levers(results),
        "caveat": ("线参数来自厂里口述（line_profiles，参考级）、路线工时未经 IE 复核、"
                   "库存来自 engflow 镜像；算出的货期是这些输入下的推演结果，不是承诺。"),
    }


def levers(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把"改哪件事能涨几分"排出来：瓶颈类别 × 受影响单数 × 可涨的分。"""
    by_constraint: Dict[str, Dict[str, Any]] = {}
    for r in results:
        key = r["binding_constraint"]
        slot = by_constraint.setdefault(key, {"constraint": key, "orders": 0,
                                             "avg_score": 0.0, "models": []})
        slot["orders"] += 1
        slot["avg_score"] += r["score"]
        slot["models"].append(r["model_code"])
    out = []
    for slot in by_constraint.values():
        slot["avg_score"] = round(slot["avg_score"] / max(1, slot["orders"]), 1)
        slot["potential_lift"] = round((100.0 - slot["avg_score"]) * slot["orders"]
                                       / max(1, len(results)), 1)
        out.append(slot)
    return sorted(out, key=lambda x: x["potential_lift"], reverse=True)
