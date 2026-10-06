"""建模精度与敏感度：把"输入差多少 → 结论差多少"算成数。

三段全是量，没有叙述：
① 敏感度：每个输入（单件工时、外购提前期、可用库存、到岗率、设备可用率、批量）按档扫一遍，
   给出组合完工日 / 延误 / 人工 / 加急的差值，并折算成"每一档值几天、每天值多少钱"。
② 映射精度：每台机型的每一项输入里，多少是真数据、多少是借来或反推的，各自允许误差多大。
③ 误差传导：用①的斜率 × ②的允许误差 = 交期的不确定区间；再把某项数据的误差压到可信档，
   看区间缩多少 —— 这就是补这项数据的量化价值，不用人来猜值不值得做。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.services import virtual_run as vr

# 每一项输入不可信时按多大误差算。取可辩护的保守档，不是拍出来的点数。
ERROR_BAND = {
    "route_standard_hours": 0.05, "own_route": 0.05,
    "borrowed_route_from_family": 0.40, "assumed_ie_hours": 0.40,
    "takt_from_line_capacity": 0.30, "declared_line_capacity": 0.30,
    "line_inferred_by_family_name": 0.25, "line_declared_home": 0.25,
    "no_time_basis": 1.00, "no_route": 1.00, "no_line": 1.00,
}
HOURS_CONFIDENCE = {"route_standard_hours": 1.0, "borrowed_route_from_family": 0.4,
                    "takt_from_line_capacity": 0.35, "no_time_basis": 0.0}
ACCURACY_WEIGHTS = {"hours": 0.30, "lead_time": 0.25, "supplier": 0.15,
                    "stock": 0.15, "make_or_buy": 0.10, "price": 0.05}

LEVERS: List[Dict[str, Any]] = [
    {"key": "hours_multiplier", "label": "单件工时", "kind": "ratio", "step": 0.10,
     "levels": [0.8, 0.9, 1.0, 1.1, 1.2, 1.4], "base": 1.0,
     "reads_as": "工时估低/估高几成，组合完工日与人工怎么动"},
    {"key": "lead_multiplier", "label": "外购提前期", "kind": "ratio", "step": 0.10,
     "levels": [0.25, 0.5, 0.75, 1.0, 1.5], "base": 1.0,
     "reads_as": "瓶颈件提前期压到几成，交期早几天、值多少钱"},
    {"key": "stock_multiplier", "label": "可用库存", "kind": "ratio", "step": 0.10,
     "levels": [0.5, 1.0, 1.5, 2.0, 3.0], "base": 1.0,
     "reads_as": "账上料多备/少备几成，先开批次能开几台、交期差几天"},
    {"key": "attendance", "label": "到岗率", "kind": "absolute", "step": 0.05,
     "levels": [0.70, 0.85, 0.97, 1.0], "base": 0.97,
     "reads_as": "暴雨到满勤之间，人力绑定的那条线一天出几台"},
    {"key": "equip_rate", "label": "设备可用率", "kind": "absolute", "step": 0.05,
     "levels": [0.60, 0.78, 0.90, 1.00], "base": None,
     "reads_as": "停机台数折进日产能后，交期与用工怎么变"},
    {"key": "days_of_output", "label": "批量（几天产量）", "kind": "batch", "step": 1.0,
     "levels": [2.0, 4.0, 6.0, 9.0], "base": 6.0,
     "reads_as": "一批下几天产量时，组合交期与线组排队怎么变"},
    {"key": "parallel_lines", "label": "并联开线（条）", "kind": "policy", "step": 1.0,
     "levels": [1.0, 2.0], "base": 1.0,
     "reads_as": "同组再开一条线（按组内声明的合并产能，不是单线×条数）换几天"},
    {"key": "crew_bonus", "label": "加班加人", "kind": "policy", "step": 0.05,
     "levels": [0.0, 0.10, 0.20, 0.30], "base": 0.0,
     "reads_as": "多给 5%/10% 人手，工时上限松开之后交期与人工各变多少"},
    {"key": "allow_partial", "label": "分批开工", "kind": "policy", "step": 1.0,
     "levels": [0.0, 1.0], "base": 1.0,
     "reads_as": "等齐套才开工 vs 现料先开一批：先开量与交期"},
    {"key": "lead_margin", "label": "承诺交期系数", "kind": "margin", "step": 0.10,
     "levels": [1.15, 1.4, 1.7, 2.0], "base": 1.15,
     "reads_as": "交期口径放宽几成之后，准点率从几个场景变成几个场景（不改变产能，只改变是否算误期）"},
]


def _metrics(scan: Dict[str, Any], scenario: str = "基准") -> Dict[str, Any]:
    """从一轮单政策扫描里取组合读数（完工日取最晚的那台，成本取合计）。"""
    block = ((scan.get("by_scenario") or {}).get(scenario) or {})
    sols = block.get("solutions") or []
    if not sols:
        return {"dated_models": 0, "finish_date": None, "blocked_models": [],
                "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "first_batch_units": 0.0, "queued_units": 0.0}
    sol = sols[0]
    objs = sol.get("objectives") or {}
    detail = sol.get("detail") or []
    dates = sorted(str(d.get("finish_date")) for d in detail if d.get("finish_date"))
    blocked = [{"model_code": b.get("model_code"), "status": b.get("status"),
                "why": b.get("why")} for b in (sol.get("blocked_models") or [])]
    binding = sorted({str(d.get("capacity_binding")) for d in detail if d.get("capacity_binding")})
    return {"binding": "+".join(binding) or None,
            "dated_models": len(dates), "models_total": len(detail),
            "finish_date": dates[-1] if dates else None,
            "days_late_worst": objs.get("days_late_worst"),
            "on_time_rate": objs.get("on_time_rate"),
            "labor_cost_usd": round(float(objs.get("labor_cost_usd") or 0), 2),
            "expedite_cost_usd": round(float(objs.get("expedite_cost_usd") or 0), 2),
            "line_activation_cost_usd": round(float(objs.get("line_activation_cost_usd") or 0), 2),
            "load_band_gap": objs.get("load_band_gap"),
            "on_time_models": sum(1 for d in detail
                                  if d.get("finish_date") and not d.get("days_late")),
            "first_batch_units": round(sum(float(d.get("batch_a_units") or 0) for d in detail), 2),
            "queued_units": round(sum(float(d.get("batch_b_units") or 0) for d in detail), 2),
            "blocked_models": blocked}


def _days_between(later: Optional[str], earlier: Optional[str]) -> Optional[int]:
    if not later or not earlier:
        return None
    try:
        a = date.fromisoformat(str(earlier)[:10])
        b = date.fromisoformat(str(later)[:10])
    except ValueError:
        return None
    return (b - a).days


async def _run_one(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                   policy: Dict[str, Any], *, attendance: float,
                   perturb: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    scan = await vr.scan_policies(db, factory_id, targets, policies=[policy],
                                  scenarios=[{"name": "基准", "attendance": attendance}],
                                  perturb=perturb or {})
    return _metrics(scan)


def slope_per_step(rows: List[Dict[str, Any]], lever: Dict[str, Any],
                   base_level: float) -> Dict[str, Any]:
    """把曲线压成一个可引用的斜率：每动一档，交期与人工各变多少。

    只拿基准两侧最近的两档算（局部线性），不做全局回归 —— 提前期那类曲线在
    跨过到货日之后会阶跃，全局斜率会把台阶抹平成一个假的平均数。
    """
    step = float(lever.get("step") or 0.1)
    base = float(base_level)
    usable = [r for r in rows if r.get("finish_date")]
    lo = [r for r in usable if float(r["level"]) < float(base)]
    hi = [r for r in usable if float(r["level"]) > float(base)]
    bn = next((r for r in usable if abs(float(r["level"]) - float(base)) < 1e-6), None)
    if not bn or not (lo or hi):
        return {"computable": False, "why": "基准档或对比档缺失，算不出局部斜率"}
    # 一律读成"把这个输入加大一档会怎样"：有上档就用上档，只有下档就把差值取反。
    # 混着来会读成反话 —— 到岗率那档曾报成"每 ±0.05 → 交期 +0.8 天"，其实是人少了才晚。
    near_hi = min(hi, key=lambda r: float(r["level"])) if hi else None
    near_lo = max(lo, key=lambda r: float(r["level"])) if lo else None
    # 取离基准更近的那一档（更接近局部斜率），符号统一换算成"加大一档"的后果
    if near_hi is not None and (near_lo is None
                                or abs(float(near_hi["level"]) - base) <= abs(float(near_lo["level"]) - base)):
        pick, sign = near_hi, 1.0
    else:
        pick, sign = near_lo, -1.0
    span = abs(float(pick["level"]) - float(base))
    if span <= 0:
        return {"computable": False, "why": "档位间距为 0"}
    per_step_days = round((pick["days_vs_base"] or 0) * (step / span) * sign, 3)
    per_step_labor = round((pick["labor_delta_usd"] or 0) * (step / span) * sign, 2)
    on_time_delta = (float(pick.get("on_time_models") or 0)
                     - float(bn.get("on_time_models") or 0)) * (step / span) * sign
    return {"computable": True, "base_level": round(base, 4),
            "unit": f"每 {lever['label']} ±{format(step, 'g')}",
            "days_per_step": per_step_days, "labor_usd_per_step": per_step_labor,
            "on_time_models_per_step": round(on_time_delta, 3),
            "measured_between": [base, float(pick["level"])],
            "direction": "把该输入加大一档",
            "money_per_day_saved": (round(abs(per_step_labor) / abs(per_step_days), 2)
                                    if per_step_days else None)}


async def sensitivity(db: AsyncSession, factory_id: str, models: List[str], *,
                      days_of_output: float = 6.0, lead_margin: Optional[float] = None,
                      attendance: float = 0.97, policy: Optional[Dict[str, Any]] = None,
                      equip_rate: Optional[float] = None) -> Dict[str, Any]:
    """逐杠杆扫档，输出每个输入的局部斜率与整条曲线。"""
    margin = lead_margin if lead_margin is not None else vr.PROMISE_LEAD_MARGIN
    pol = policy or {"name": "基准政策（分批开工）", "allow_partial": True}
    base_targets = await vr.derive_targets(db, factory_id, models,
                                           days_of_output=days_of_output, lead_margin=margin)
    # 设备可用率不是假设值：取台账实测（可用台数 ÷ 总台数），否则斜率没有基准
    base_eq = equip_rate if equip_rate is not None else float(
        (await vr.equipment_rate(db, factory_id)).get("rate") or 1.0)
    base = await _run_one(db, factory_id, base_targets, pol, attendance=attendance,
                          perturb={"equip_rate": base_eq} if base_eq else None)
    out: List[Dict[str, Any]] = []
    for lever in LEVERS:
        rows: List[Dict[str, Any]] = []
        if lever["kind"] in ("ratio", "batch", "margin"):
            base_level = float(lever.get("base") or days_of_output)
            levels = list(lever["levels"])
        elif lever["kind"] == "policy":
            base_level = float(pol.get(lever["key"], lever.get("base") or 0) or 0)
            levels = sorted(set(list(lever["levels"]) + [base_level]))
        else:
            base_level = {"attendance": attendance, "equip_rate": base_eq}[lever["key"]]
            levels = sorted(set(list(lever["levels"]) + [round(float(base_level), 4)]))
        for level in levels:
            perturb: Dict[str, float] = {}
            att, tgts, lvl_policy = attendance, base_targets, pol
            if base_eq:
                perturb["equip_rate"] = base_eq
            if lever["kind"] == "ratio":
                perturb[lever["key"]] = float(level)
            elif lever["kind"] == "batch":
                tgts = await vr.derive_targets(db, factory_id, models,
                                               days_of_output=float(level), lead_margin=margin)
            elif lever["kind"] == "margin":
                tgts = await vr.derive_targets(db, factory_id, models,
                                               days_of_output=days_of_output, lead_margin=float(level))
            elif lever["kind"] == "policy":
                lvl_policy = dict(pol)
                lvl_policy[lever["key"]] = (bool(level) if lever["key"] == "allow_partial"
                                            else int(level) if lever["key"] == "parallel_lines"
                                            else float(level))
            elif lever["key"] == "attendance":
                att = float(level)
            else:                                    # equip_rate 这一档直接替换设备可用率
                perturb["equip_rate"] = float(level)
            m = await _run_one(db, factory_id, tgts, lvl_policy, attendance=att, perturb=perturb)
            rows.append({"level": round(float(level), 4),
                        "is_base": abs(float(level) - base_level) < 1e-6,
                "finish_date": m.get("finish_date"),
                "days_vs_base": _days_between(m.get("finish_date"), base.get("finish_date")),
                "labor_delta_usd": round(m["labor_cost_usd"] - base["labor_cost_usd"], 2),
                "expedite_delta_usd": round(m["expedite_cost_usd"] - base["expedite_cost_usd"], 2),
                "activation_delta_usd": round(m["line_activation_cost_usd"] - base["line_activation_cost_usd"], 2),
                "first_batch_units": m["first_batch_units"], "queued_units": m["queued_units"],
                "dated_models": m["dated_models"], "on_time_models": m.get("on_time_models"),
                "days_late_worst": m.get("days_late_worst"), "on_time_rate": m.get("on_time_rate"),
                "binding": m.get("binding")})
        out.append({"label": lever["label"], "key": lever["key"], "kind": lever["kind"],
                    "reads_as": lever["reads_as"], "curve": rows,
                    "base_level": round(base_level, 4),
                    "slope": slope_per_step(rows, lever, base_level)})
    return {"factory_id": factory_id, "models": models,
            "targets": [{"model_code": t["model_code"], "units": t["units"],
                         "due_in_days": t["due_in_days"]} for t in base_targets],
            "base": {**base, "lead_margin": margin, "days_of_output": days_of_output,
                     "attendance": attendance, "policy": pol["name"]},
            "levers": out,
            "note": ("斜率只取基准两侧的局部档，不做全局回归：提前期/库存这类曲线会阶跃，"
                     "平均值会把台阶抹平。所有档位都用同一条推演路径跑（scan_policies），"
                     "不另建第二套算法。")}


async def mapping_accuracy(db: AsyncSession, factory_id: str,
                           models: List[str]) -> Dict[str, Any]:
    """每台机型的输入里有多少是真数据：逐项给覆盖率、依据标签与允许误差。"""
    lines = [dict(r) for r in (await db.execute(vr.LINES_SQL, {"fid": factory_id})).mappings().all()]
    per_model: List[Dict[str, Any]] = []
    for model in models:
        bom = [dict(r) for r in (await db.execute(
            vr.BOM_SQL, {"fid": factory_id, "model": model})).mappings().all()]
        codes = [str(r["material_code"]) for r in bom]
        stock_rows = (await db.execute(vr.STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() \
            if codes else []
        stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}
        route_own = await vr.route_ops_for_product(db, factory_id, model)
        family_rows = [] if route_own else await vr.load_family_route(db, factory_id, model)
        route, route_basis = vr.resolve_route(list(route_own), family_rows)
        line, line_basis = vr.pick_line(model, lines)
        _hours, hours_basis = vr.hours_per_unit_from(list(route), line)

        n = max(1, len(bom))
        buy = [r for r in bom if str(r.get("make_or_buy") or "unknown") == "外购"]
        nbuy = max(1, len(buy))
        def _num(v: Any) -> bool:
            return str(v or "").isdigit()
        comps = {
            "hours": {"score": HOURS_CONFIDENCE.get(str(hours_basis), 0.6),
                      "basis": str(hours_basis), "route_basis": str(route_basis),
                      "line_basis": str(line_basis),
                      "note": "单件工时来自 IE 声明 / 借同族路线 / 线节拍反推，允许误差分别是 5%/40%/30%"},
            "lead_time": {"score": round(sum(1 for r in buy if _num(r.get("lead_time_days"))) / nbuy, 3),
                          "basis": f"{sum(1 for r in buy if _num(r.get('lead_time_days')))}/{len(buy)} 个外购料号有提前期",
                          "note": "没有提前期的外购件排不出到货日，交期只能标'无法计算'"},
            "supplier": {"score": round(sum(1 for r in buy if r.get("default_supplier")) / nbuy, 3),
                         "basis": f"{sum(1 for r in buy if r.get('default_supplier'))}/{len(buy)} 个外购料号有供应商",
                         "note": "没有供应商 = 催购没有对象（卡的是数据，不是产能）"},
            "stock": {"score": round(sum(1 for r in bom if str(r["material_code"]) in stock) / n, 3),
                      "basis": f"{sum(1 for r in bom if str(r['material_code']) in stock)}/{len(bom)} 个料号在库存台账里有行",
                      "note": "没有行按 0 可用处理（不假设有货）"},
            "make_or_buy": {"score": round(sum(1 for r in bom
                                               if str(r.get("make_or_buy") or "unknown") != "unknown") / n, 3),
                            "basis": f"{sum(1 for r in bom if str(r.get('make_or_buy') or 'unknown') != 'unknown')}/{len(bom)} 行标了自制/外购",
                            "note": "没标的行不进采购也不进自制，齐套算不动"},
            "price": {"score": round(sum(1 for r in bom if r.get("unit_price") not in (None, "")) / n, 3),
                      "basis": f"{sum(1 for r in bom if r.get('unit_price') not in (None, ''))}/{len(bom)} 行有单价",
                      "note": "单价缺失时钱这一维只能报'无法折算'，不估算"},
        }
        score = round(100.0 * sum(ACCURACY_WEIGHTS[k] * float(v["score"]) for k, v in comps.items()), 1)
        worst = sorted(((k, v) for k, v in comps.items()), key=lambda x: float(x[1]["score"]))[:2]
        per_model.append({"model_code": model, "accuracy_score": score, "bom_lines": len(bom),
                          "components": comps,
                          "hours_error_band": ERROR_BAND.get(str(hours_basis), 0.30),
                          "drags": [{"input": k, "coverage": v["score"], "basis": v["basis"]}
                                    for k, v in worst]})
    overall = round(sum(p["accuracy_score"] for p in per_model) / max(1, len(per_model)), 1)
    return {"factory_id": factory_id, "overall_accuracy": overall, "models": per_model,
            "weights": ACCURACY_WEIGHTS,
            "error_bands": {"IE 声明工时": ERROR_BAND["route_standard_hours"],
                            "借同族路线": ERROR_BAND["borrowed_route_from_family"],
                            "线节拍反推": ERROR_BAND["takt_from_line_capacity"],
                            "外购提前期": 0.20},
            "note": ("精度分只统计**输入有没有真依据**，不给结果打分；权重是我定的口径"
                     "（工时 30%、提前期 25%、供应商 15%、库存 15%、自制外购 10%、单价 5%），"
                     "要改口径得改这一处。")}


def propagate_uncertainty(sens: Dict[str, Any], acc: Dict[str, Any],
                          *, repaired: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """把映射误差按敏感度斜率折算成天数：这台机器现在能给出几天宽的区间，补完数据能压到几天。"""
    repaired = repaired or {"hours_multiplier": 0.05, "lead_multiplier": 0.05}
    slopes = {l["key"]: l.get("slope") for l in sens.get("levers") or []}
    out: List[Dict[str, Any]] = []
    for m in acc.get("models") or []:
        parts: List[Dict[str, Any]] = []
        hours_slope = (slopes.get("hours_multiplier") or {}).get("days_per_step")
        lead_slope = (slopes.get("lead_multiplier") or {}).get("days_per_step")
        comps = m.get("components") or {}
        hours_band_now = float(comps.get("hours", {}).get("score") or 0)
        hours_err = float(m.get("hours_error_band") or 0.30)
        hours_err_after = min(hours_err, repaired.get("hours_multiplier", hours_err))
        zero_notes: List[Dict[str, Any]] = []
        if not hours_slope or abs(float(hours_slope)) < 1e-9:
            zero_notes.append({"input": "单件工时", "uncertainty_days": 0.0,
                               "because": ("当前线组声明的台/天是产能上限，工时不 binding（capacity_binding=line_declared）"
                                           "→ IE 工时补到多准都不改交期；要让它进约束，得补瓶颈工位口径")})
        if hours_slope and hours_err < 1.0:
            parts.append({"input": "单件工时", "days_per_step": hours_slope, "error_band": hours_err,
                          "uncertainty_days_now": round(abs(hours_slope) * (hours_err / 0.10), 2),
                          "if_repaired_to": hours_err_after,
                          "uncertainty_days_after": round(abs(hours_slope) * (hours_err_after / 0.10), 2)})
        if lead_slope:
            lead_cov = float(comps.get("lead_time", {}).get("score") or 0)
            lead_err = 0.20 if lead_cov >= 0.8 else max(0.20, 1.0 - lead_cov)
            lead_after = min(lead_err, repaired.get("lead_multiplier", lead_err))
            parts.append({"input": "外购提前期", "days_per_step": lead_slope, "error_band": lead_err,
                          "uncertainty_days_now": round(abs(lead_slope) * (lead_err / 0.10), 2),
                          "if_repaired_to": lead_after,
                          "uncertainty_days_after": round(abs(lead_slope) * (lead_after / 0.10), 2),
                          "note": f"提前期覆盖率 {lead_cov:.0%}"})
        now = round(max((p["uncertainty_days_now"] for p in parts), default=0.0), 2)
        after = round(sum(p["uncertainty_days_after"] for p in parts), 2)
        out.append({"model_code": m["model_code"], "accuracy_score": m.get("accuracy_score"),
                    "hours_coverage": round(hours_band_now, 3),
                    "items": parts, "insensitive_inputs": zero_notes,
                    "uncertainty_days_worst_item": now,
                    "uncertainty_days_sum": round(sum(p["uncertainty_days_now"] for p in parts), 2),
                    "uncertainty_days_after_repair": after})
    ranked = sorted(out, key=lambda r: -(r["uncertainty_days_sum"] - r["uncertainty_days_after_repair"]))
    return {"binding_constraint": (sens.get("base") or {}).get("binding"),
            "per_model": out,
            "value_of_repair": [{"model_code": r["model_code"],
                                 "days_removed": round(r["uncertainty_days_sum"]
                                                      - r["uncertainty_days_after_repair"], 2)}
                                for r in ranked if r["uncertainty_days_sum"] > 0],
            "method": ("不确定天数 = |局部斜率| × (允许误差 ÷ 档位步长)；多项数据的不确定按线性相加报，"
                       "不做平方和开根 —— 那些误差不是独立测量，相加是保守口径")}


def _reads_as(meta: Dict[str, Any], sl: Dict[str, Any]) -> str:
    label = meta.get("label") or "?"
    if not sl.get("computable"):
        return f"{label}：{sl.get('why', '算不出局部斜率')}"
    bits = []
    if sl.get("days_per_step"):
        bits.append(f"每 ±{format(float(meta.get('step') or 0.1), 'g')} → 交期 {sl['days_per_step']:+g} 天")
    if sl.get("on_time_models_per_step"):
        bits.append(f"准点 {sl['on_time_models_per_step']:+g} 台")
    if sl.get("labor_usd_per_step"):
        bits.append(f"人工 {sl['labor_usd_per_step']:+,.0f} USD")
    if not bits:
        return f"{label}：动一档交期与准点都不变（这项当前不进约束，别为它花钱）"
    return f"{label}：" + "，".join(bits)


async def lever_headline(db: AsyncSession, factory_id: str, models: List[str]) -> Dict[str, Any]:
    """给记分卡与待办用的短账：按"每档效果"排序，最有用的杠杆在前。

    只报实测数与'动一档'的后果，不下"该不该做"的判断 —— 判断要人结合钱的口径与现场，
    引擎负责把差值算准并摆在同一条推演路径上。
    """
    if not models:
        return {"ranked": [], "overall_accuracy": None}
    acc = await mapping_accuracy(db, factory_id, models)
    sens = await sensitivity(db, factory_id, models)
    ranked: List[Dict[str, Any]] = []
    meta = {l["key"]: l for l in LEVERS}
    for lever in sens.get("levers") or []:
        sl = lever.get("slope") or {}
        power = abs(float(sl.get("days_per_step") or 0)) + abs(float(sl.get("on_time_models_per_step") or 0))
        ranked.append({"lever": lever["label"], "base_level": lever.get("base_level"),
                       "days_per_step": sl.get("days_per_step"),
                       "on_time_models_per_step": sl.get("on_time_models_per_step"),
                       "labor_usd_per_step": sl.get("labor_usd_per_step"),
                       "money_per_day_saved": sl.get("money_per_day_saved"),
                       "power": round(power, 3),
                       "reads_as": _reads_as(meta.get(lever["key"]) or {"label": lever["label"]}, sl)})
    ranked.sort(key=lambda r: -float(r["power"]))
    return {"ranked": ranked, "overall_accuracy": acc.get("overall_accuracy"),
            "base": sens.get("base"), "models": models,
            "note": ("斜率是局部值（基准两侧最近两档），只在小步长内成立；"
                     "power=|天/档|+|准点台/档|，只用于排序不改判")}


async def report(db: AsyncSession, factory_id: str, models: List[str], **kw: Any) -> Dict[str, Any]:
    acc = await mapping_accuracy(db, factory_id, models)
    sens = await sensitivity(db, factory_id, models, **kw)
    unc = propagate_uncertainty(sens, acc)
    return {"factory_id": factory_id, "models": models,
            "accuracy": acc, "sensitivity": sens, "uncertainty": unc,
            "how_to_read": ("要交期就给交期：base.finish_date 是这批的组合完工日，"
                            "curves 给每个输入动一档之后的完工日/人工/加急差值，"
                            "uncertainty 给这些数现在可信到几成、补哪项数据能压掉几天。")}
