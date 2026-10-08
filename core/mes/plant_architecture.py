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

    日产能按 `在册人数 ÷ 该段工序 IE 单件工时 × 实测标称班时` 算 —— 这是**人数读法**，等于该段
    全员都扑在这道工序上的上界；另一读法（stations.capacity_per_hour × 同一班时）单位从没定义过，
    所以两读法取小、并且把矛盾倍数说出来（同一列在两种站里是两种口径）。
    班时取 attendance 打卡中位（与沙箱同一来源），不再写死 8h：同一个工位此前在沙箱按 10h、在这里
    按 8h、在线档案按 11h —— 三个出口三个"台/天"，对撞倍数没法解释。取不到班时就不给日产能。
    """
    from api.services.virtual_run import load_station_capacity

    ops = [dict(r) for r in (await db.execute(STATION_OPS_SQL)).mappings().all()]
    census = await load_station_capacity(db, factory_id)
    stations, shift = census["stations"], (census["shift_hours"] or {})
    shift_hours = float(shift.get("hours") or 0) or None
    rows = []
    for o in ops:
        code = str(o.get("station_code") or "")
        st = stations.get(code)
        if not st:
            continue
        people = float(st["headcount"] or 0) if str(st.get("capacity_unit") or "") == "人" else 0.0
        avg_hours = round(float(o["ie_hours_all_templates"] or 0) / max(1, int(o["templates"] or 1)), 4)
        # standard_hours 是小时/件（成品检验 0.1 = 6 分钟，不可能是 0.1 分钟），所以人数读法是
        # 人÷工时=件/小时，再乘班时；以前乘的是 60（把小时当分钟），每天件数虚高 60 倍
        headcount_bound = (round(people / avg_hours * shift_hours, 2)
                           if (avg_hours > 0 and people > 0 and shift_hours) else 0.0)
        declared = float(st.get("capacity_per_hour") or 0)
        declared_bound = (round(declared * shift_hours, 2)
                          if declared > 0 and shift_hours else 0.0)
        bounds = [b for b in (headcount_bound, declared_bound) if b > 0]
        rows.append({
            "station_code": code, "station_name": st.get("station_name"),
            "station_type": st.get("station_type"), "people": int(people) if people else None,
            "route_steps": int(o["steps"] or 0), "route_templates": int(o["templates"] or 0),
            "ie_hours_per_unit": avg_hours,
            "shift_hours": shift_hours, "shift_basis": shift.get("shift"),
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
            "coverage": f"{len(named)}/{len(stations)} 个在册工位有『路线 + 人头 + IE 工时 + 实测班时』四条齐全的日产能",
            "basis": (f"日产能=min(在册人数÷IE单件工时, capacity_per_hour)×实测标称班时"
                      f"（{shift_hours or '取不到'}h，取该厂行数最多班次的打卡中位；班次 "
                      f"{shift.get('shift') or '—'}、样本 {shift.get('n') or 0} 行）："
                      "前者是该段全员扑在这道工序上的理论的上界，后者单位从没定义过（同一列在两种站里"
                      "是两种口径）→ 两读法取小并报矛盾倍数。没有实测班时就不给日产能，不回落 8h/11h 名义值")}


def _cross_check_reading(verdict: Optional[Dict[str, Any]]) -> str:
    """线声明 vs 工位声明的倍数怎么念：min==max 时不说区间，免得念出「9.09~9.09 倍」。"""
    if not verdict or not verdict.get("compared"):
        return ("对撞：线声明产能与工位自述下界没有可比组 —— 要么没有线档案，"
                "要么路线点名的工位给不出产能读数（这不是『对上了』）")
    lo, hi = verdict.get("min"), verdict.get("max")
    gap = f"{hi} 倍" if lo == hi else f"{lo}~{hi} 倍"
    return (f"对撞：{verdict['compared']} 组『线声明台/天 vs 工位自述下界』差 {gap}"
            f"（最大在 {verdict.get('worst_line')} × {verdict.get('worst_model')}，"
            f"卡在 {verdict.get('worst_station')}）→ 沙箱/交期仍按 line_profiles 的声明出数，"
            "但按工位自己声明的数做不出那个量；哪边是真的要厂里定，引擎不自己取小也不自己取大")


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
    cross = await capacity_cross_check(db, reference_factory_id)
    f = float(scaled["factor"])
    people_by_station = {}
    for row in cap["per_station"]:
        if not row.get("people"):
            continue
        ppl = max(0, int(round(row["people"] * f)))
        people_by_station[row["station_code"]] = ppl
        if row.get("ie_hours_per_unit"):
            row["scaled_people"] = ppl
            # 缩放只改人数这一读法；站点自己声明的那一读（declared×班时）跟人多少无关，
            # 所以缩放后的上界仍是两读法取小 —— 否则放大规模会把站点声明那道墙一起放大
            hb = (round(ppl / row["ie_hours_per_unit"] * row["shift_hours"], 2)
                  if (ppl and row["ie_hours_per_unit"] and row.get("shift_hours")) else None)
            row["scaled_headcount_bound_per_day"] = hb
            row["scaled_bound_per_day"] = (min([b for b in (hb, row.get("declared_bound_per_day")) if b])
                                           if hb else None)
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
        f"（在册人数÷IE单件工时×实测标称班时，再与站点声明取小；全段同口径；这是上界不是可达 —— "
        f"该参照厂 {cap['stations_in_routes']}/{shape['stations']} 个工位有路线点名，"
        f"效率折扣那条腿全厂都是占位 1.0）",
        f"跨厂外推：{('可用' if spread['transferable'] else '不可用')} ——"
        f" 各厂区结构比例极差 {json.dumps(spread['spread'], ensure_ascii=False)}（>{MIN_SPREAD_TO_REFUSE_TRANSFER} 倍即拒绝）",
    ]
    readings.append(_cross_check_reading(cross.get("verdict")))
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
                                 "而且所有工位的效率折扣都是占位 1.0 → 真实可达产能只会更低"),
        },
        "conditions": conditions, "ratio_spread": spread,
        "cross_check": {"pairs": cross["pairs"], "verdict": cross["verdict"],
                        "unit_open_question": cross["unit_open_question"],
                        "rule": cross["rule"]},
        "tiers": ["厂区 → 车间/段（份额来自参照厂台账）→ 工位（stations，含路线点名的）"
                  "→ 班组人数（在册 distinct 工号 × 系数）"
                  "→ 日产能上界（在册人数÷IE单件工时×实测标称班时，与站点声明取小）"],
        "not_derivable": scaled["not_scaled"] + [
            "线数：等比出 0.x 条不是物理配置（见 warnings），要的是『撑起声明产能需要几个人』"],
        "readings": readings,
        "warnings": scaled["warnings"],
    }


LINE_MODEL_SQL = text("""
    SELECT lp.line_code, lp.line_group, lp.hours_per_day, lp.units_per_day, lp.crew_size,
           lp.can_make_models::text AS can_models
    FROM line_profiles lp WHERE lp.factory_id = :fid AND lp.is_active ORDER BY lp.line_code
""")


async def capacity_cross_check(db: AsyncSession, factory_id: str, *, max_models: int = 6) -> Dict[str, Any]:
    """线声明的台/天 vs 工位路线算出的台/天 —— 两条都在台账里，差多少必须说出来。

    沙箱/交期走 line_profiles 的声明产能，工位侧走 `station_route_capacity` —— 就是沙箱用的
    那同一个函数、同一份实测班时。以前这里自己算一遍并乘线档案的 11h，而沙箱乘打卡实测 10h，
    同一个加工车间在这儿是 44 台/天、在那儿是 40 台/天：对撞倍数取决于哪个出口在念。
    `capacity_per_hour` 的单位从没定义过（4 是"整站每小时 4 件"还是"每人每小时 4 件"，差 164 倍），
    所以这里只报矛盾与倍数，不替厂里把哪一条改成真相。
    """
    from api.services.virtual_run import load_station_capacity, station_route_capacity
    from core.mes.route_resolution import route_ops_for_product

    census = await load_station_capacity(db, factory_id)
    stations, shift = census["stations"], (census["shift_hours"] or {})
    shift_hours = float(shift.get("hours") or 0) or None
    lines = [dict(r) for r in (await db.execute(LINE_MODEL_SQL, {"fid": factory_id})).mappings().all()]
    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for ln in lines:
        models = [m.strip().strip("'").strip("\\") for m in str(ln.get("can_models") or "").strip("{}").split(",") if m.strip()]
        for model in models[:max_models]:
            # 按 (线, 机种) 去重：同一条线组的声明各比一次，别让先出现的线把后一条线的对照吃掉
            if (str(ln["line_code"]), model) in seen:
                continue
            seen.add((str(ln["line_code"]), model))
            ops = await route_ops_for_product(db, factory_id, model)
            if not ops:
                rows.append({"model_code": model, "line_code": ln["line_code"], "status": "no_route",
                             "why": "该厂这台机解析不出工艺路线 → 没有工位侧上界可对撞"})
                continue
            if not shift_hours:
                rows.append({"model_code": model, "line_code": ln["line_code"], "status": "no_shift_hours",
                             "why": "这座厂取不到实测标称班时 → 工位侧台/天算不出；"
                                    "不拿线档案 11h 或名义 8h 顶替（那正是两个出口对不上的原因）"})
                continue
            cap = station_route_capacity(ops, stations, shift_hours)
            if cap.get("units_per_day") is None:
                rows.append({"model_code": model, "line_code": ln["line_code"],
                             "status": "no_station_bounds", "why": cap.get("why"),
                             "unmapped_work_centers": cap.get("missing_stations") or []})
                continue
            tight = next((x for x in cap["per_station"]
                          if x.get("station") == cap.get("bottleneck_station")), {})
            declared = float(ln.get("units_per_day") or 0)
            station_bound = cap["units_per_day"]
            rows.append({
                "model_code": model, "line_code": ln["line_code"], "status": "ok",
                "line_declared_units_per_day": declared,
                "station_bound_units_per_day": station_bound,
                "tight_station": cap["bottleneck_station"],
                "tight_station_name": tight.get("station_name"),
                "tight_operation": tight.get("operation"),
                "ratio_line_over_station": (round(declared / station_bound, 2)
                                            if station_bound and declared else None),
                "stations_mapped": len(cap["per_station"]), "route_operations": len(ops),
                "unmapped_work_centers": cap.get("missing_stations") or [],
                "shift_hours": shift_hours, "station_basis": cap.get("basis"),
                "two_reads_conflict": cap.get("two_reads_conflict"),
                "per_station": cap["per_station"],
            })


    comparable = [r for r in rows if r.get("ratio_line_over_station")]
    ratios = [float(r["ratio_line_over_station"]) for r in comparable]
    verdict = None
    if ratios:
        worst = max(comparable, key=lambda r: float(r["ratio_line_over_station"]))
        verdict = {
            "min": min(ratios), "max": max(ratios), "compared": len(comparable),
            "worst_model": worst["model_code"], "worst_line": worst["line_code"],
            "worst_station": worst.get("tight_station_name") or worst.get("tight_station"),
        }
    return {
        "factory_id": factory_id, "pairs": rows, "verdict": verdict,
        "rule": ("线声明产能与工位级下界并存时，沙箱/交期仍按 line_profiles 声明走（那是厂里给的参数），"
                 "但读数里必须并列工位侧自己声明的数与矛盾倍数 —— 取小会把单位未定义的 "
                 "capacity_per_hour 当真相，取大等于没对撞"),
        "unit_open_question": ("stations.capacity_per_hour 的单位（整站/每小时 vs 每人/每小时）没定义过："
                              "加工车间 4 配 164 人、组立一线 110 配 110 人，两种读法差 164 倍"),
    }


async def _delivery_basis(db: AsyncSession, reference_factory_id: str, model: str, *,
                          temperature_c: Optional[float] = None,
                          humidity_percent: Optional[float] = None,
                          task_type: str = "assembly") -> Dict[str, Any]:
    """一次取齐"按规模算交期"要用到的全部依据：基数人头、机种、载体线、日历、到岗、设备。

    单独成一层是因为"要多少人才赶得上"要在同一批依据上试很多个规模 —— 每试一次重取一遍，
    两次读到的到岗率可能已经不是同一天的了，比较就失去意义。
    """
    from datetime import date

    from api.services.virtual_run import (CALENDAR_SQL, LINES_SQL, equipment_rate,
                                          measured_attendance, pick_line, resolve_product)

    shape = await plant_shape(db, reference_factory_id)
    base_people = float(shape.get("people_per_day") or 0)
    if base_people <= 0:
        return {"status": "no_scale_basis",
                "why": "参照厂在 attendance 里没有逐日人头 → 缩放没有基数，不凭空长一座厂"}
    resolved = await resolve_product(db, reference_factory_id, model)
    if resolved.get("status") != "ok":
        return {"status": f"product_{resolved.get('status')}", "model_code": model,
                "candidates": resolved.get("candidates") or [],
                "why": resolved.get("why") or "机种在参照厂产品台账里对不上 → 没有载体机种"}
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": reference_factory_id})).mappings().all()]
    base_line, line_basis = pick_line(resolved["product_id"], lines)
    if base_line is None:
        return {"status": "no_line", "model_code": resolved["product_id"], "factor": None,
                "why": f"{len(lines)} 条在册线里没有一条声明能做 {resolved['product_id']} → 缩放没有载体"}
    if temperature_c is not None:
        from core.mes.data_evidence import workforce_presence_under_conditions

        pres = await workforce_presence_under_conditions(
            db, reference_factory_id, temperature_c=float(temperature_c),
            humidity_percent=float(humidity_percent or 60.0), task_type=task_type,
            step_count=3000)
        ratio, att_basis = pres.get("present_ratio"), pres.get("basis")
        if ratio is None:
            return {"status": "no_attendance_baseline", "why": pres.get("why")}
    else:
        att = await measured_attendance(db, reference_factory_id)
        ratio, att_basis = float(att["present_ratio"]), att.get("basis")
    equip = await equipment_rate(db, reference_factory_id)
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(CALENDAR_SQL, {"fid": reference_factory_id})).mappings().all()} or set(range(1, 7))
    return {
        "status": "ok", "factory_id": reference_factory_id, "model_code": resolved["product_id"],
        "product_resolution": resolved.get("how"), "base_people": base_people,
        "base_line": base_line, "line_basis": line_basis, "present_ratio": float(ratio),
        "attendance_basis": att_basis, "equipment_rate": equip, "shift_days": shift_days,
        "today": date.today(),
        "conditions": (None if temperature_c is None else
                       {"temperature_c": float(temperature_c),
                        "humidity_percent": float(humidity_percent or 60.0)}),
    }


def _scaled_line_at(ctx: Dict[str, Any], headcount: float) -> tuple:
    """把参照厂那条线等比到目标人头，返回 (缩放线, 系数)。只动人数与该线声明的台/天。"""
    base_line = ctx["base_line"]
    factor = float(headcount) / float(ctx["base_people"])
    declared = float(base_line.get("units_per_day") or 0)
    crew = float(base_line.get("crew_size") or 0)
    scaled = {**base_line, "line_code": f"{base_line['line_code']}@{int(headcount)}人(等比 {factor:g})",
              "line_group": None,
              "units_per_day": round(declared * factor, 2) if declared else declared,
              "group_units_per_day": None,
              "crew_size": round(crew * factor, 1) if crew else crew}
    return scaled, factor


async def _run_at_scale(db: AsyncSession, ctx: Dict[str, Any], *, headcount: float,
                        units: float, due_days: int, due_days_basis: str = "user") -> Dict[str, Any]:
    """在一个目标规模上真跑一遍沙箱：出完工天数、比交期早晚、用工，而不是一句台/天。"""
    from datetime import timedelta

    from api.services.virtual_run import run_target

    base_line = ctx["base_line"]
    scaled, factor = _scaled_line_at(ctx, headcount)
    ratio = ctx["present_ratio"]
    run = await run_target(db, ctx["factory_id"], ctx["model_code"], float(units),
                           ctx["today"] + timedelta(days=max(1, int(due_days))), ctx["today"],
                           {d: ratio for d in range(0, 400)}, [scaled], ctx["shift_days"],
                           line_busy_days=0.0, equip_rate=float(ctx["equipment_rate"].get("rate") or 1.0))
    conflict = run.get("line_vs_station") or {}
    finish, late = run.get("finish_day"), run.get("days_late")
    declared = float(base_line.get("units_per_day") or 0)
    head = (f"{int(headcount)} 人规模（等比 {factor:g}，载体 {base_line['line_code']} 声明 "
            f"{declared:g} 台/天 → {scaled['units_per_day']:g} 台/天、班组 "
            f"{scaled['crew_size']:g} 人、到岗 {ratio:g}）：{units:g} 台 {ctx['model_code']}"
            f"（交期按 {due_days} 天{'' if due_days_basis == 'user' else '，是默认假设'}）")
    if finish is not None:
        verdict = f"预计 {finish} 天完工"
        if isinstance(late, (int, float)):
            verdict += f"，比交期晚 {late:g} 天" if late > 0 else f"，比交期早 {-late:g} 天"
    elif run.get("status") == "simulated":
        verdict = ("在这台机剩余可排的 400 天窗口内做不完"
                   f"（已按 {run.get('capacity_after_equipment') or scaled['units_per_day']} 台/天推进）")
    else:
        verdict = f"排不出时间线：{run.get('why') or run.get('status')}"
    tails = [head + verdict]
    if run.get("person_days") is not None:
        tails.append(f"用工 {run['person_days']:g} 人日")
    if run.get("wait_days_for_material"):
        tails.append(f"等料 {run['wait_days_for_material']:g} 天")
    if conflict.get("agrees") is False:
        tails.append(f"工位侧自述只有 {conflict.get('station_bound_units_per_day')} 台/天"
                     f"（差 {conflict.get('ratio_line_over_station')} 倍）")
    return {
        "status": run.get("status") or "ok", "model_code": ctx["model_code"], "units": float(units),
        "product_resolution": ctx["product_resolution"],
        "reference_factory_id": ctx["factory_id"], "headcount": int(headcount),
        "factor": round(factor, 4), "scaled_line": {
            "line_code": scaled["line_code"], "from_line": str(base_line["line_code"]),
            "line_basis": ctx["line_basis"], "units_per_day": scaled["units_per_day"],
            "crew": scaled["crew_size"],
            # line_profiles.hours_per_day 是 numeric：不转 float 就把 Decimal 塞进 chat_messages
            # 的 jsonb，落库时 TypeError，整条 /chat 直接 500（答复文本已经生成好了也白搭）
            "hours_per_day": (float(base_line["hours_per_day"])
                              if base_line.get("hours_per_day") is not None else None),
            "written_to_db": False},
        "due": {"days": int(due_days), "basis": due_days_basis,
                "note": ("交期天数由提问给出" if due_days_basis == "user"
                         else "没给交期 → 按 25 天比对；这个 25 是提问要改的假设，不是台账值")},
        "attendance": {"present_ratio": ratio, "basis": ctx["attendance_basis"],
                       "conditions": ctx["conditions"]},
        "equipment_rate": ctx["equipment_rate"], "line_vs_station": conflict, "run": run,
        "finish_day": finish, "days_late": late,
        "reading": "；".join(tails),
    }


async def scaled_delivery_run(db: AsyncSession, reference_factory_id: str, *, headcount: float,
                              model: str, units: float, due_in_days: Optional[int] = None,
                              temperature_c: Optional[float] = None,
                              humidity_percent: Optional[float] = None,
                              task_type: str = "assembly") -> Dict[str, Any]:
    """把缩放后的产线送进真正的沙箱：出一条时间线，而不是一句"能做 N 台/天"。

    缩放只作用在**人**与**该线声明的台/天**上（两者都是参照厂台账值）；
    来料齐套、提前期、班次日历、设备可用率仍走真表 —— 换规模不换依据。
    生成的线是内存对象，绝不写 line_profiles（那是事实表）。
    """
    ctx = await _delivery_basis(db, reference_factory_id, model, temperature_c=temperature_c,
                                humidity_percent=humidity_percent, task_type=task_type)
    if ctx.get("status") != "ok":
        return ctx
    return await _run_at_scale(db, ctx, headcount=headcount, units=units,
                               due_days=int(due_in_days) if due_in_days else 25,
                               due_days_basis=("user" if due_in_days else "default_25"))


async def min_scale_for_delivery(probe, *, reference_headcount: float, units: float,
                                 due_days: int, max_headcount: float = 200000.0,
                                 tolerance: int = 1) -> Dict[str, Any]:
    """二分出"赶上这个交期至少要多少人"。probe(hc) → run_target 那一条读数，不另立口径。

    完工天数对规模单调（这条线的台/天按人头等比），所以区间收缩成立。三种结论分开给：
    找到最小规模 / 加到上限仍赶不上 / **加人无效** —— 规模差 8 倍而完工天数几乎不动，
    说明剩下来卡的是等料与提前期，不是人力，这时候报"至少要多少人"就是误导。
    """
    seen: Dict[float, tuple] = {}

    async def at(hc: float) -> tuple:
        if hc not in seen:
            r = await probe(hc)
            fin = r.get("finish_day")
            seen[hc] = (fin is not None and float(fin) <= due_days,
                        (float(fin) if fin is not None else None), r)
        return seen[hc]

    ceiling = max(float(reference_headcount) * 2.0, 2.0)
    hi = None
    while ceiling <= max_headcount:
        if (await at(ceiling))[0]:
            hi = ceiling
            break
        ceiling *= 2.0
    if hi is None:
        _fmax, fin_max, r_max = await at(max_headcount)
        _f8, fin_8, _r8 = await at(max_headcount / 8.0)
        stalled = (fin_max is not None and fin_8 is not None and abs(fin_8 - fin_max) < 1.0)
        return {"status": "lead_time_bound" if stalled else "beyond_ceiling",
                "due_days": due_days, "units": float(units),
                "max_headcount_tested": int(max_headcount),
                "finish_day_at_max": fin_max, "finish_day_at_max_div_8": fin_8,
                "wait_days_for_material": (r_max or {}).get("wait_days_for_material"),
                "probes": len(seen),
                "why": (f"加到 {int(max_headcount)} 人（参照厂实测 {reference_headcount:g} 人的 "
                        f"{max_headcount / reference_headcount:g} 倍）仍在 {due_days} 天内做不完"
                        + (f"；届时等料占 {(r_max or {}).get('wait_days_for_material')} 天"
                           if (r_max or {}).get("wait_days_for_material") else "")),
                "note": ("规模再翻 8 倍完工天数几乎不动 → 卡的是等料/提前期，不是人力，"
                         "报『至少要多少人』在这里是误导" if stalled else
                         "上限内还没试到可行规模 → 需要放宽交期或并行多条线")}
    lo = hi / 2.0
    while lo > 1.0 and (await at(lo))[0]:
        lo /= 2.0
    while hi - lo > tolerance:
        mid = (hi + lo) / 2.0
        if (await at(mid))[0]:
            hi = mid
        else:
            lo = mid
    # 二分到的是小数规模，报出去必须是整数人头：向上取整后再往回退，直到"少一个人就赶不上"。
    # 实测踩过：把 2888.5 人截断成 2888 人，还顺手把 2888.5 人的完工天数（25 天）挂在 2888 人
    # 名下 —— 而 2888 人真实是 26 天。报出来的那个人数必须自己就能赶上。
    k = int(-(-hi // 1))
    while k > 1 and (await at(float(k - 1)))[0]:
        k -= 1
    _f, fin, r = await at(float(k))
    return {"status": "found", "due_days": due_days, "min_headcount": k,
            "search_tolerance_headcount": tolerance, "finish_day": fin, "units": float(units),
            "infeasible_one_person_less": (None if k <= 1 else (await at(float(k - 1)))[1]),
            "person_days": (r or {}).get("person_days"), "probes": len(seen),
            "note": (f"最小可行规模按 ±{tolerance} 人分辨率二分得到，判据是缩放线进沙箱的完工天数"
                     "（不是拿平均产能除一个数）")}


async def min_headcount_for_delivery(db: AsyncSession, reference_factory_id: str, *, model: str,
                                     units: float, due_in_days: int,
                                     temperature_c: Optional[float] = None,
                                     humidity_percent: Optional[float] = None,
                                     task_type: str = "assembly") -> Dict[str, Any]:
    """"要多少人才能赶上这个交期"：与 scaled_delivery_run 共用同一批依据与同一条沙箱。"""
    from datetime import timedelta

    from api.services.virtual_run import run_target

    ctx = await _delivery_basis(db, reference_factory_id, model, temperature_c=temperature_c,
                                humidity_percent=humidity_percent, task_type=task_type)
    if ctx.get("status") != "ok":
        return ctx

    async def probe(hc: float) -> Dict[str, Any]:
        scaled, _ = _scaled_line_at(ctx, hc)
        run = await run_target(db, ctx["factory_id"], ctx["model_code"], float(units),
                               ctx["today"] + timedelta(days=int(due_in_days)), ctx["today"],
                               {d: ctx["present_ratio"] for d in range(0, 400)}, [scaled],
                               ctx["shift_days"], line_busy_days=0.0,
                               equip_rate=float(ctx["equipment_rate"].get("rate") or 1.0))
        return {"finish_day": run.get("finish_day"),
                "wait_days_for_material": run.get("wait_days_for_material"),
                "person_days": run.get("person_days"), "status": run.get("status")}

    out = await min_scale_for_delivery(probe, reference_headcount=float(ctx["base_people"]),
                                       units=float(units), due_days=int(due_in_days))
    crew = float(ctx["base_line"].get("crew_size") or 0)
    out["carrier_line"] = str(ctx["base_line"]["line_code"])
    out["carrier_crew"] = crew
    out["reference_headcount"] = ctx["base_people"]
    if out.get("status") == "found":
        out["equivalent_crews"] = (int(-(-out["min_headcount"] // crew)) if crew else None)
        out["reading"] = (f"赶上 {due_in_days} 天交期至少要 {out['min_headcount']} 人"
                          f"（参照厂实测 {ctx['base_people']:g} 人的 "
                          f"{out['min_headcount'] / ctx['base_people']:g} 倍；载体 "
                          f"{out['carrier_line']} 声明 "
                          f"{float(ctx['base_line'].get('units_per_day') or 0):g} 台/天、班组 {crew:g} 人 "
                          f"→ 等效 {out['equivalent_crews']} 个这样的班组），届时完工 {out['finish_day']:g} 天"
                          f"；试了 {out['probes']} 个规模")
    return out


async def attach_delivery(db: AsyncSession, result: Dict[str, Any],
                          args: Dict[str, Any]) -> Dict[str, Any]:
    """把"这一规模下要交付的那张单"接到架构结果上。

    /chat 的工具与 /plant-architecture 走同一条：两条入口各算一遍天数迟早给出两个答案。
    机种或数量缺一项就写清缺哪一项 —— 天数要有一条载体线加一个数量，缺任一项都不许拿
    瓶颈段的上界去除一个数当交期。
    """
    ref = str(result.get("reference_factory_id") or "")
    target = str(args.get("delivery_model") or "").strip()
    units = args.get("delivery_units")
    if not target or not units:
        missing = "、".join(filter(None, [
            "" if target else "机种（这一规模要交付的是哪一台）",
            "" if units else "数量（多少台/件）"]))
        result["delivery"] = {"status": "no_target_order",
                              "why": f"只给了目标规模，没给{missing} → 不出交期天数",
                              "hint": "补一句规模+机种+数量，例如「千人工厂做 8000 台 A-50-04-F，交期 25 天」"}
        return result
    target_hc = (result.get("scaled") or {}).get("target_people")
    if not target_hc:
        result["delivery"] = {"status": "no_scale_basis",
                              "why": "缩放没得出目标人头 → 没有可缩放的基数",
                              "hint": "改给 headcount（如 1000）再问一次"}
        return result
    temp = args.get("temperature_c")
    hum = (float(args["humidity_percent"]) if args.get("humidity_percent") else None)
    task = str(args.get("task_type") or "assembly")
    due_days = int(args["delivery_due_days"]) if args.get("delivery_due_days") else 25
    delivery = await scaled_delivery_run(
        db, ref, headcount=float(target_hc), model=target, units=float(units),
        due_in_days=due_days, temperature_c=(float(temp) if temp is not None else None),
        humidity_percent=hum, task_type=task)
    result["delivery"] = delivery
    # 答复里既然说"赶不上"，就把"那要多少人才赶得上"一起算出来 —— 这是同一批依据、同一条沙箱，
    # 不是另起一个口径。规模够用时不算（它不是一个被问到的问题，也算了会把 8 秒白加上去）。
    late = delivery.get("days_late")
    if (delivery.get("finish_day") is not None or delivery.get("status") == "simulated") and (
            delivery.get("finish_day") is None or (isinstance(late, (int, float)) and late > 0)):
        delivery["min_scale"] = await min_headcount_for_delivery(
            db, ref, model=target, units=float(units), due_in_days=due_days,
            temperature_c=(float(temp) if temp is not None else None),
            humidity_percent=hum, task_type=task)
    return result
