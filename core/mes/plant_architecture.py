"""按规模生成的工厂架构模型：只能长在一座**参照厂**的实测比例上。

为什么要写这个模块：问"百人 / 千人 / 几千人厂能不能仿真"时，正确答案不是"能"也不是"不能"，
而是**哪几层有依据、哪几层一跨厂就崩**。台账里两家厂的结构性比例差得很远
（每工位 37.3 人 vs 70.6 人、每段 87 人 vs 32 人、线档案 3 条 vs 0 条、设备/人 0.078 vs 0.008），
所以"千人厂该有几个工位"没有可迁移的系数 —— 等比缩放必须指名参照厂，
并且把不可迁移的比例、以及缩放后跌破台账可观测下限的层，一并如实报出来。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SHAPE_SQL = text("""
    SELECT (SELECT count(DISTINCT a.operator_id) FROM attendance a WHERE a.factory_id = :fid) AS people_per_day,
           (SELECT count(DISTINCT a.date) FROM attendance a WHERE a.factory_id = :fid) AS ledger_days,
           (SELECT count(DISTINCT h.station)
              FROM attendance a
              JOIN operators o ON o.id = a.operator_id
              JOIN hr_employees h ON h.factory_id = o.factory_id
                   AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
             WHERE a.factory_id = :fid) AS sections_observed,
           (SELECT count(*) FROM stations st
             WHERE st.factory_id = :fid AND COALESCE(st.status, 'active') = 'active') AS stations,
           (SELECT count(*) FROM equipment eq WHERE eq.factory_id = :fid) AS equipment,
           (SELECT count(*) FROM products p WHERE p.factory_id = :fid) AS products,
           (SELECT count(*) FROM routings r WHERE r.factory_id = :fid AND r.is_active = TRUE) AS routes_active,
           (SELECT count(*) FROM line_profiles lp WHERE lp.factory_id = :fid AND lp.is_active) AS lines
""")

SECTION_PEOPLE_SQL = text("""
    SELECT h.station AS section, count(DISTINCT a.operator_id) AS people,
           count(DISTINCT a.date) AS days
    FROM attendance a
    JOIN operators o ON o.id = a.operator_id
    JOIN hr_employees h ON h.factory_id = o.factory_id
         AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
    WHERE a.factory_id = :fid
    GROUP BY 1 HAVING count(DISTINCT a.operator_id) >= :min_people
    ORDER BY people DESC
""")

# 参照比例能不能跨厂用，用两家厂的实测离散度说话，不用"我觉得差不多"
MIN_SPREAD_TO_REFUSE_TRANSFER = 1.5


def _spread(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v and v > 0]
    if len(vals) < 2:
        return None
    return round(max(vals) / min(vals), 2)


async def ratio_spread(db: AsyncSession) -> Dict[str, Any]:
    """同一份"人→工位→段→线"的比例在各厂区之间的差 —— 差多少倍，就有多少倍不能外推。"""
    res = await db.execute(text("SELECT DISTINCT factory_id FROM attendance"))
    fids = [str(r[0]) for r in res.all()]
    per: Dict[str, Dict[str, float]] = {}
    for fid in fids:
        row = dict((await db.execute(SHAPE_SQL, {"fid": fid})).mappings().first() or {})
        ppl = float(row.get("people_per_day") or 0)
        if ppl <= 0:
            continue
        per[fid] = {
            "people_per_station": round(ppl / max(1.0, float(row.get("stations") or 0)), 2),
            "people_per_section": round(ppl / max(1.0, float(row.get("sections_observed") or 0)), 2),
            "equipment_per_person": round(float(row.get("equipment") or 0) / ppl, 4),
            "lines": float(row.get("lines") or 0),
        }
    out: Dict[str, Any] = {"by_factory": per, "spread": {}, "transferable": False}
    for key in ("people_per_station", "people_per_section", "equipment_per_person"):
        sp = _spread([v[key] for v in per.values()])
        if sp:
            out["spread"][key] = sp
    spreads = [v for v in out["spread"].values() if v]
    out["transferable"] = bool(spreads) and max(spreads) <= MIN_SPREAD_TO_REFUSE_TRANSFER
    out["rule"] = (f"厂区之间任一结构比例的极差 ≤{MIN_SPREAD_TO_REFUSE_TRANSFER} 倍才允许跨厂外推；"
                   "否则缩放只能指名一座参照厂等比放大")
    return out


async def plant_shape(db: AsyncSession, factory_id: str, *, min_people: int = 10) -> Dict[str, Any]:
    """参照厂现状架构：全部从台账数出来，一个都不填。"""
    row = dict((await db.execute(SHAPE_SQL, {"fid": factory_id})).mappings().first() or {})
    ppl = float(row.get("people_per_day") or 0)
    sections = [dict(x) for x in (await db.execute(
        SECTION_PEOPLE_SQL, {"fid": factory_id, "min_people": min_people})).mappings().all()]
    share_total = sum(float(x["people"] or 0) for x in sections) or 0.0
    for s in sections:
        s["share"] = round(float(s["people"] or 0) / share_total, 4) if share_total else None
    stations = float(row.get("stations") or 0)
    from core.mes.capacity_math import efficiency_basis_census

    eff = await efficiency_basis_census(db, factory_id)
    return {
        "factory_id": factory_id,
        "people_per_day": int(ppl),
        "ledger_days": int(row.get("ledger_days") or 0),
        "sections_observed": int(row.get("sections_observed") or 0),
        "sections": sections,
        "stations": int(stations),
        "equipment": int(row.get("equipment") or 0),
        "products": int(row.get("products") or 0),
        "routes_active": int(row.get("routes_active") or 0),
        "lines": int(row.get("lines") or 0),
        "ratios": {
            "people_per_station": round(ppl / stations, 2) if stations else None,
            "people_per_section": round(ppl / float(row.get("sections_observed") or 0), 2)
                                  if row.get("sections_observed") else None,
            "equipment_per_person": round(float(row.get("equipment") or 0) / ppl, 4) if ppl else None,
            "lines_per_1000_people": round(float(row.get("lines") or 0) / ppl * 1000, 2) if ppl else None,
        },
        "efficiency_basis": eff,
        "basis": ("attendance 逐日 distinct 工号、stations/equipment/products/routings/line_profiles 计数；"
                  "段=hr_employees.station 经 operators 关联到打卡行"),
    }


def scale_shape(shape: Dict[str, Any], *, headcount: Optional[float] = None,
                factor: Optional[float] = None) -> Dict[str, Any]:
    """按目标人头等比放大参照厂架构；**只放台数/人数这类可等比的量**，不可等的层直接标出来。

    线数不能等比：0.29 条线不是"小厂的线"，是"这条线需要多少人才撑得起来"的另一道题；
    产品族、SKU 数也不随人头缩放（那是订单结构，不是劳动力结构）。
    """
    ppl = float(shape.get("people_per_day") or 0)
    if ppl <= 0:
        return {"ok": False, "why": "参照厂没有逐日到岗人头 → 没有可以放大的基数"}
    if headcount is not None and float(headcount) > 0:
        f = float(headcount) / ppl
        basis = f"目标 {int(headcount)} 人 ÷ 参照厂实测每天 {int(ppl)} 人"
    elif factor and float(factor) > 0:
        f = float(factor)
        basis = f"调用方给的倍数 {float(factor):g}"
    else:
        return {"ok": False, "why": "既没给目标人头也没给倍数 → 不猜规模"}
    target = int(round(ppl * f))
    stations = int(round(float(shape.get("stations") or 0) * f))
    equipment = int(round(float(shape.get("equipment") or 0) * f))
    lines = float(shape.get("lines") or 0) * f
    sections = []
    for s in shape.get("sections") or []:
        people = int(round(float(s.get("people") or 0) * f))
        sections.append({"section": s.get("section"), "share": s.get("share"),
                         "people": people, "stations_share": (people / max(1, target) if target else None)})
    warnings: List[str] = []
    if f < 0.25:
        warnings.append(f"缩放系数 {round(f, 3)}：段级/工位级人数已经跌到台账可观测下限以下，"
                        "段级缺勤率与班时中位数不再有样本支撑 → 这两层只能用全厂值并标明")
    if lines < 1.0:
        warnings.append(f"等比出来的线数 {round(lines, 2)} 条 < 1：线不是可等比层 —— "
                        "小厂的问题应改成『撑起声明产能需要几个人』，引擎不给 0.29 条线")
    if not shape.get("lines"):
        warnings.append("参照厂 line_profiles 0 条 → 线级产能本来就没有依据，缩放不会凭空生出线")
    if int(shape.get("stations") or 0) and float(shape.get("people_per_day") or 0) / float(shape["stations"]) > 25:
        warnings.append("参照厂 stations 每人比 >25：说明工位表只是抽样登记，不是全厂工位台账 → "
                        "工位层放大出来的数不能当物理配置")
    return {"ok": True, "factor": round(f, 4), "basis": basis, "target_people": target,
            "target_stations": stations, "target_equipment": equipment,
            "target_lines_scaled": round(lines, 2),
            "target_products_kept": int(shape.get("products") or 0),
            "sections": sections, "warnings": warnings,
            "not_scaled": ["products/SKU（订单结构，不随人头缩放）",
                           "lines（不可等比，见 warnings）",
                           "外购比例与提前期（按料号，不按人头）"]}


STATION_OPS_SQL = text("""
    SELECT s.work_center AS station_code, count(DISTINCT s.template_id) AS templates,
           count(*) AS steps, sum(COALESCE(s.standard_hours, 0)) AS ie_hours_all_templates
    FROM routing_template_steps s
    WHERE COALESCE(s.standard_hours, 0) > 0
    GROUP BY 1
""")


async def section_capacity_table(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """段/工位的产能依据：路线点名的工作中心 → stations 档案（名字对得上段）→ IE 工时。

    日产能按 `在册人数 × 60 ÷ 该段工序 IE 工时` 算 —— 这是**人数读法**，等于该段全员都扑在
    这道工序上的上界；另一读法（stations.capacity_per_hour）单位从没定义过，所以两读法取小、
    并且把矛盾倍数说出来（同一列在两种站里是两种口径）。
    """
    ops = [dict(r) for r in (await db.execute(STATION_OPS_SQL)).mappings().all()]
    stations = {str(r["station_code"]): dict(r) for r in (await db.execute(text("""
        SELECT station_code, station_name, station_type, capacity, capacity_unit, capacity_per_hour
        FROM stations WHERE factory_id = :fid AND COALESCE(status, 'active') = 'active'
    """), {"fid": factory_id})).mappings().all()}
    rows = []
    for o in ops:
        code = str(o.get("station_code") or "")
        st = stations.get(code)
        if not st:
            continue
        people = float(st["capacity"] or 0) if str(st.get("capacity_unit") or "") == "人" else 0.0
        avg_hours = round(float(o["ie_hours_all_templates"] or 0) / max(1, int(o["templates"] or 1)), 4)
        headcount_bound = round(people * 60.0 / avg_hours, 2) if (avg_hours > 0 and people > 0) else 0.0
        declared = float(st.get("capacity_per_hour") or 0)
        declared_bound = round(declared * 8.0, 2) if declared > 0 else 0.0   # 8h 名义班时折算，单位本身未定义
        bounds = [b for b in (headcount_bound, declared_bound) if b > 0]
        rows.append({
            "station_code": code, "station_name": st.get("station_name"),
            "station_type": st.get("station_type"), "people": int(people) if people else None,
            "route_steps": int(o["steps"] or 0), "route_templates": int(o["templates"] or 0),
            "ie_hours_per_unit": avg_hours,
            "headcount_bound_per_day": headcount_bound or None,
            "declared_bound_per_day": declared_bound or None,
            "bound_used_per_day": (min(bounds) if bounds else None),
            "two_reads_conflict": (round(max(bounds) / min(bounds), 1)
                                   if len(bounds) > 1 and min(bounds) > 0 else None),
        })
    named = [r for r in rows if r["bound_used_per_day"]]
    bottleneck = min(named, key=lambda r: r["bound_used_per_day"]) if named else None
    return {"stations_in_routes": len(rows), "with_bound": len(named),
            "stations_total": len(stations),
            "per_station": sorted(rows, key=lambda r: (r["bound_used_per_day"] or 1e18))[:14],
            "bottleneck": bottleneck,
            "coverage": f"{len(named)}/{len(stations)} 个在册工位有『路线 + 人头 + IE 工时』三条齐全的日产能",
            "basis": ("日产能=min(在册人数×60÷IE工时, capacity_per_hour×8h)：前者是该段全员扑在这道工序上的上界，"
                      "后者单位从没定义过（同一列在两种站里差 1.9~数千倍）→ 两读法取小并报矛盾倍数。"
                      "班时这里用 8h 名义值，实测标称班时另有出处（attendance 打卡中位）")}


async def architecture_model(db: AsyncSession, reference_factory_id: str, *,
                             headcount: Optional[float] = None, factor: Optional[float] = None,
                             temperature_c: Optional[float] = None,
                             humidity_percent: Optional[float] = None,
                             task_type: str = "assembly") -> Dict[str, Any]:
    """按目标规模生成一座厂的分层架构模型（参照厂等比 + 每层的产能/出勤依据）。"""
    from core.mes.data_evidence import absence_baseline, scheduled_headcount, workforce_presence_under_conditions

    spread = await ratio_spread(db)
    shape = await plant_shape(db, reference_factory_id)
    if not shape["people_per_day"]:
        return {"status": "no_reference_ledger", "reference_factory_id": reference_factory_id,
                "why": (f"参照厂 {reference_factory_id} 在 attendance 里没有逐日人头 → "
                        "没有任何可放大的基数，模型不凭空长"),
                "ratio_spread": spread}
    scaled = scale_shape(shape, headcount=headcount, factor=factor)
    if not scaled.get("ok"):
        return {"status": "no_scale_basis", "why": scaled["why"], "measured_shape": shape,
                "ratio_spread": spread}
    cap = await section_capacity_table(db, reference_factory_id)
    f = float(scaled["factor"])
    people_by_station = {}
    for row in cap["per_station"]:
        if not row.get("people"):
            continue
        ppl = max(0, int(round(row["people"] * f)))
        people_by_station[row["station_code"]] = ppl
        if row.get("ie_hours_per_unit"):
            row["scaled_people"] = ppl
            row["scaled_bound_per_day"] = (round(ppl * 60.0 / row["ie_hours_per_unit"], 2)
                                           if ppl and row["ie_hours_per_unit"] else None)
    rows = [r for r in cap["per_station"] if r.get("scaled_bound_per_day")]
    rows.sort(key=lambda r: r["scaled_bound_per_day"])
    plant_bound = rows[0]["scaled_bound_per_day"] if rows else None
    conditions = None
    if temperature_c is not None:
        conditions = []
        for s in (scaled["sections"] or [])[:8]:
            sec = str(s.get("section") or "")
            base = await absence_baseline(db, reference_factory_id, section=(sec or None))
            hc = await scheduled_headcount(db, reference_factory_id, section=(sec or None))
            under = await workforce_presence_under_conditions(
                db, reference_factory_id, temperature_c=float(temperature_c),
                humidity_percent=float(humidity_percent or 60.0), task_type=task_type, section=(sec or None))
            people = int(s.get("people") or 0)
            conditions.append({
                "section": sec, "people": people,
                "ledger_people": hc.get("heads"), "baseline_absence": (base.get("rate") if base.get("available") else None),
                "present_normal": (round(1.0 - float(base["rate"]), 4) if base.get("available") else None),
                "present_hot": under.get("present_ratio"),
                "absent_people_hot": (round((1.0 - float(under["present_ratio"])) * people, 1)
                                       if under.get("present_ratio") is not None and people else None),
                "work_efficiency": under.get("work_efficiency"),
                "extrapolated": bool(hc.get("heads") and people < 10),
                "basis": under.get("basis") or base.get("basis"),
            })
    readings = [
        f"参照厂 {reference_factory_id}：实测每天 {shape['people_per_day']} 人、"
        f"{shape['sections_observed']} 段、{shape['stations']} 个在册工位、{shape['equipment']} 台设备、"
        f"{shape['lines']} 条线档案、{shape['routes_active']} 条有效路线",
        f"目标规模 {scaled['target_people']} 人 ＝ {scaled['basis']}（系数 {f:g}）→ "
        f"工位 {scaled['target_stations']}、设备 {scaled['target_equipment']}、"
        f"段 {len([s for s in scaled['sections'] if s['people'] > 0])} 个（人数按参照厂份额分）",
        f"日产能上界：瓶颈段 {rows[0]['station_name'] if rows else '—'} "
        f"{plant_bound if plant_bound else '算不出'} 件/天"
        f"（人数×60÷IE工时，全段同口径；这是上界不是可达 —— "
        f"该参照厂 {cap['stations_in_routes']}/{shape['stations']} 个工位有路线点名，"
        f"效率折扣那条腿全厂都是占位 1.0）",
        f"跨厂外推：{('可用' if spread['transferable'] else '不可用')} ——"
        f" 各厂区结构比例极差 {json.dumps(spread['spread'], ensure_ascii=False)}（>{MIN_SPREAD_TO_REFUSE_TRANSFER} 倍即拒绝）",
    ]
    if conditions:
        tot = sum(float(c["absent_people_hot"] or 0) for c in conditions)
        readings.append(f"工况 {temperature_c}℃/{humidity_percent or 60}%：模型里前 8 段合计约 {round(tot)} 人这天不到岗"
                        f"（斜率=本厂声明 1.0pp/℃，没有温度实测可对撞）")
    return {
        "status": "ok", "reference_factory_id": reference_factory_id,
        "measured_shape": shape, "scaled": scaled, "capacity": {
            "per_station": rows[:10], "coverage": cap["coverage"], "basis": cap["basis"],
            "plant_bound_units_per_day": plant_bound,
            "plant_bound_note": ("瓶颈段的上界，不等于全厂日产能：产品族不同走的段不同，"
                                 "而且 38 个工位的效率折扣都是占位 1.0 → 真实可达产能只会更低"),
        },
        "conditions": conditions, "ratio_spread": spread,
        "tiers": ["厂区 → 车间/段（份额来自参照厂台账）→ 工位（stations，含路线点名的）"
                  "→ 班组人数（在册 distinct 工号 × 系数）→ 日产能上界（人数×60÷IE 工时）"],
        "not_derivable": scaled["not_scaled"] + [
            "线数：等比出 0.x 条不是物理配置（见 warnings），要的是『撑起声明产能需要几个人』"],
        "readings": readings,
        "warnings": scaled["warnings"],
    }
