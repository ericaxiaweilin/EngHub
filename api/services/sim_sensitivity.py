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
from typing import Any, Dict, List, Optional, Tuple

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
    {"key": "days_of_output", "label": "订单大小（每台单下几天产量·会改总需求量）", "kind": "batch",
     "step": 1.0, "levels": [2.0, 4.0, 6.0, 9.0], "base": 6.0,
     "not_a_scheduling_lever": True,
     "reads_as": "这一格改的是「要多少台」，不是「怎么排」：少下单当然又快又省，不能当优化杠杆引用"},
    {"key": "batches", "label": "同一张单拆几批投放（总量不变）", "kind": "perturb_int", "step": 1.0,
     "levels": [1.0, 2.0, 4.0, 8.0], "base": 1.0,
     "reads_as": "拆批只计换型工时（系统里唯一数字=APS 默认 300 秒/次）；搬运/清线/再齐套没建模，"
                 "所以这一档只能证伪「拆批免费」，不能证明拆批免费"},
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
                "days_late_per_model": {}, "finish_date_per_model": {},
                "labor_cost_usd": 0.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "first_batch_units": 0.0, "waiting_for_material_units": 0.0,
                "crew_before_staffing_sum": 0.0, "crew_effective_sum": 0.0}
    sol = sols[0]
    objs = sol.get("objectives") or {}
    detail = sol.get("detail") or []
    dates = sorted(str(d.get("finish_date")) for d in detail if d.get("finish_date"))
    blocked = [{"model_code": b.get("model_code"), "status": b.get("status"),
                "why": b.get("why")} for b in (sol.get("blocked_models") or [])]
    binding = sorted({str(d.get("capacity_binding")) for d in detail if d.get("capacity_binding")})
    terms = sorted({str(t) for d in detail for t in (d.get("binding_terms") or [])})
    return {"binding": "+".join(binding) or None, "binding_terms": terms,
            "binding_per_model": {str(d.get("model_code")): d.get("binding_terms") for d in detail},
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
            "waiting_for_material_units": round(sum(float(d.get("batch_b_units") or 0) for d in detail), 2),
            "capacity_line_declared_max": max([float(d.get("capacity_line_declared") or 0) for d in detail] or [0.0]),
            "capacity_basis": sorted({str(d.get("capacity_basis")) for d in detail if d.get("capacity_basis")}),
            # 人头按"每台机占用的班组"加总：同一条线被两台机共用会各算一次，口径是占用不是编外新增
            "crew_before_staffing_sum": round(sum(
                float((d.get("staffing") or {}).get("crew_before_staffing") or 0) for d in detail), 1),
            "crew_effective_sum": round(sum(
                float((d.get("staffing") or {}).get("crew_effective") or 0) for d in detail), 1),
            # 每台机自己的完工日与延误：料号级报价要把"省下的天数"归到具体那台机
            "days_late_per_model": {str(d.get("model_code")): float(d["days_late"])
                                    for d in detail if d.get("days_late") is not None},
            "finish_date_per_model": {str(d.get("model_code")): str(d["finish_date"])
                                      for d in detail if d.get("finish_date")},
            "blocked_models": blocked,
            # 卡住的东西要点名：瓶颈件、到货关键件、用了哪条线 —— 否则"卡在料上"是一句空话
            "bottleneck_parts": {str(d.get("model_code")): d.get("bottleneck_part")
                                 for d in detail if d.get("bottleneck_part")},
            "arrival_critical_parts": {str(d.get("model_code")): (d.get("arrival_critical_parts") or [])
                                       for d in detail if d.get("arrival_critical_parts")},
            "material_arrival_days": {str(d.get("model_code")): d.get("material_arrival_day")
                                      for d in detail if d.get("material_arrival_day") is not None},
            "lines_used": sorted({
                str((d.get("staffing") or {}).get("line") or d.get("line"))
                for d in detail
                if (d.get("staffing") or {}).get("line") or d.get("line")}),
            }


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
    # 局部值与整条曲线的最小二乘拟合一起给：拟合是"平均效应"，局部是"跨门槛那一档的效应"。
    # 提前期/库存这类曲线只在跨过到货门槛那一档跳，线性外推会低报（实测两者差 20 倍）。
    xs = [float(r["level"]) - base for r in usable]
    ys = [float(r.get("days_vs_base") or 0) for r in usable]
    denom = sum(x * x for x in xs)
    fit_days = round((sum(x * y for x, y in zip(xs, ys)) / denom) * step, 3) if denom > 1e-12 else None
    ys2 = [float(r.get("on_time_models") or 0) - float(bn.get("on_time_models") or 0) for r in usable]
    fit_on_time = round((sum(x * y for x, y in zip(xs, ys2)) / denom) * step, 3) if denom > 1e-12 else None
    # 台阶形状有两种表现：近处有跳变而平均低报，或近处一动不动、远处才跳。都算非线性。
    per_step_all = []
    for r in usable:
        d = float(r["level"]) - base
        if abs(d) > 1e-12:
            per_step_all.append((abs(float(r.get("days_vs_base") or 0) / d * step),
                                 float(r["level"])))
    steepest = max(per_step_all, key=lambda x: x[0]) if per_step_all else (0.0, None)
    steepest_days = round(steepest[0], 3)
    local_abs = abs(per_step_days)
    # 判"台阶"看每档换算成同一档距后的效果差多少：有一档为 0 而另一档不为 0，
    # 或最大档效应超过最小档两倍 —— 都说明线性引用会骗人。
    magnitudes = sorted(x[0] for x in per_step_all)
    lo_mag = next((m for m in magnitudes if m > 1e-9), 0.0)
    hi_mag = magnitudes[-1] if magnitudes else 0.0
    nonlinear = bool(len(magnitudes) >= 2 and (any(m <= 1e-9 for m in magnitudes)
                                               or (lo_mag > 0 and hi_mag > 2.0 * lo_mag)))
    # 每档的代价不能只算人工：加急与开线也是这一档花出去的钱。只按人工折算时
    # "外购提前期 每天值 $0" 这种话会把 $6,030 的加急费抹平 —— 那是把贵的说成免费的。
    per_step_expedite = round((pick.get("expedite_delta_usd") or 0) * (step / span) * sign, 2)
    per_step_activation = round((pick.get("activation_delta_usd") or 0) * (step / span) * sign, 2)
    cost_per_step = round(abs(per_step_labor) + abs(per_step_expedite) + abs(per_step_activation), 2)
    return {"computable": True, "base_level": round(base, 4),
            "unit": f"每 {lever['label']} ±{format(step, 'g')}",
            "days_per_step": per_step_days, "labor_usd_per_step": per_step_labor,
            "expedite_usd_per_step": per_step_expedite,
            "activation_usd_per_step": per_step_activation, "cost_usd_per_step": cost_per_step,
            "on_time_models_per_step": round(on_time_delta, 3),
            "days_per_step_fit": fit_days, "on_time_models_per_step_fit": fit_on_time,
            "steepest_days_per_step": steepest_days, "steepest_at_level": steepest[1],
            "nonlinear": bool(nonlinear),
            "shape_note": ("这条曲线是台阶型的：按档距线性引用会低报（近处 0 天、跨门槛那档才跳），"
                           "引用时要用 steepest 那一档并说明门槛在哪"
                           if nonlinear else "局部与拟合一致，可按线性引用"),
            "measured_between": [base, float(pick["level"])],
            "direction": "把该输入加大一档",
            # 倍数与政策是两件事：lead_multiplier 改的是"台账提前期有多准"（数据带宽，不花钱），
            # expedite_lead_days 才是"掏钱把到货往前拽"。共享受约束项时把前者报成 $0/天，
            # 会被读成"压提前期免费" —— 那是把数据问题说成了采购决策。
            "cost_note": ("这一档改的是台账依据的带宽（数据准不准），不是花钱加急；"
                          "要价签看加急政策那一档"
                          if lever.get("key") in ("lead_multiplier", "hours_multiplier", "stock_multiplier")
                          and cost_per_step == 0 and abs(per_step_days) > 1e-9 else None),
            "money_per_day_saved": (round(cost_per_step / abs(per_step_days), 2)
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
    # 同一政策在暴雨那一档的结果一起给：只报好天的数就是挑好看的看
    storm = await _run_one(db, factory_id, base_targets, pol, attendance=0.70,
                           perturb={"equip_rate": base_eq} if base_eq else None)
    out: List[Dict[str, Any]] = []
    for lever in LEVERS:
        rows: List[Dict[str, Any]] = []
        if lever["kind"] in ("ratio", "batch", "margin", "perturb_int"):
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
            elif lever["kind"] == "perturb_int":
                perturb[lever["key"]] = float(level)
                perturb["changeover_hours"] = float(vr.SIM_CHANGEOVER_HOURS)
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
                "first_batch_units": m["first_batch_units"], "waiting_for_material_units": m["waiting_for_material_units"],
                "dated_models": m["dated_models"], "on_time_models": m.get("on_time_models"),
                "capacity_line_declared_max": m.get("capacity_line_declared_max"),
                "capacity_basis": m.get("capacity_basis"),
                "days_late_worst": m.get("days_late_worst"), "on_time_rate": m.get("on_time_rate"),
                "binding": m.get("binding")})
        out.append({"label": lever["label"], "key": lever["key"], "kind": lever["kind"],
                    "not_a_scheduling_lever": bool(lever.get("not_a_scheduling_lever")),
                    "reads_as": lever["reads_as"], "curve": rows,
                    "base_level": round(base_level, 4),
                    "slope": slope_per_step(rows, lever, base_level)})
    return {"factory_id": factory_id, "models": models,
            "targets": [{"model_code": t["model_code"], "units": t["units"],
                         "due_in_days": t["due_in_days"]} for t in base_targets],
            "base": {**base, "lead_margin": margin, "days_of_output": days_of_output,
                     "attendance": attendance, "policy": pol["name"],
                     "worst_weather": {k: storm.get(k) for k in ("finish_date", "days_late_worst",
                                                                "labor_cost_usd", "binding_terms")}},
            "levers": out,
            "note": ("基准档按好天（到岗 0.97）算，base.worst_weather 给暴雨（0.70）下同一政策的结果，"
                     "两个数都要看，别只报好看的那个。斜率只取基准两侧的局部档，不做全局回归："
                     "提前期/库存这类曲线会阶跃，平均值会把台阶抹平。所有档位都用同一条推演路径跑（scan_policies），"
                     "不另建第二套算法。")}


async def mapping_accuracy(db: AsyncSession, factory_id: str,
                           models: List[str]) -> Dict[str, Any]:
    """每台机型的输入里有多少是真数据：逐项给覆盖率、依据标签与允许误差。"""
    lines = [dict(r) for r in (await db.execute(vr.LINES_SQL, {"fid": factory_id})).mappings().all()]
    per_model: List[Dict[str, Any]] = []
    for model in models:
        bom = (await vr.sim_bom_lines(db, factory_id, model, 1.0))["rows"]
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


def lead_error_band(coverage: float) -> float:
    """外购提前期的允许误差：覆盖率够就把 ±20% 当底线，覆盖不足按缺口放大（单一出处）。"""
    return 0.20 if float(coverage) >= 0.8 else max(0.20, 1.0 - float(coverage))


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
            lead_err = lead_error_band(lead_cov)
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


def _reads_as(meta: Dict[str, Any], sl: Dict[str, Any],
              rows_meta: Optional[List[Dict[str, Any]]] = None) -> str:
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
    caps = [float(r.get("capacity_line_declared_max") or 0) for r in (rows_meta or [])]
    if meta.get("key") == "parallel_lines" and len(set(caps)) <= 1 and caps:
        bits.append(f"这条线上产能声明没变（{caps[0]:g} 台/天）：该线组只登记了一条线，"
                    f"「开第二条」在现在的主数据里是 0 产能，不是 0 效果")
    if sl.get("nonlinear") and float(sl.get("steepest_days_per_step") or 0) > 0:
        # 近处那档 0 天不代表这项不重要 —— 门槛在远处，漏说就会被人当成"不动"
        bits.append(f"台阶型：近处档位看不出效果，跨过门槛那一档才跳 "
                    f"{sl.get('steepest_days_per_step')} 天/档（在 {sl.get('steepest_at_level')} 那档）")
    if not bits:
        return f"{label}：动一档交期与准点都不变（这项当前不进约束，别为它花钱）"
    if sl.get("nonlinear"):
        bits.append(f"（台阶型：平均只有 {sl.get('days_per_step_fit')} 天/档，按档距引用会低报）")
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
        if sl.get("nonlinear"):
            power = max(power, abs(float(sl.get("days_per_step_fit") or 0)) +
                        abs(float(sl.get("on_time_models_per_step_fit") or 0)))
        ranked.append({"lever": lever["label"], "base_level": lever.get("base_level"),
                       "days_per_step": sl.get("days_per_step"),
                       "on_time_models_per_step": sl.get("on_time_models_per_step"),
                       "labor_usd_per_step": sl.get("labor_usd_per_step"),
                       "money_per_day_saved": sl.get("money_per_day_saved"),
                       "power": round(power, 3),
                       "not_a_scheduling_lever": bool(lever.get("not_a_scheduling_lever")),
                       "reads_as": _reads_as(meta.get(lever["key"]) or {"label": lever["label"]},
                                             sl, lever.get("curve")),
                       "binding_terms": lever.get("binding_terms")})
    ranked.sort(key=lambda r: -float(r["power"]))
    # 「订单大小」那格改的是需求量而不是排法，不能和真杠杆混在同一份"最值钱"清单里
    actionable = [r for r in ranked if not r.get("not_a_scheduling_lever")]
    return {"ranked": actionable, "ranked_all": ranked,
            "not_scheduling_levers": [r["lever"] for r in ranked if r.get("not_a_scheduling_lever")],
            "overall_accuracy": acc.get("overall_accuracy"),
            "base": sens.get("base"), "models": models,
            "note": ("斜率是局部值（基准两侧最近两档），只在小步长内成立；"
                     "power=|天/档|+|准点台/档|，只用于排序不改判")}


async def report(db: AsyncSession, factory_id: str, models: List[str], *,
                 include_risk: bool = False, include_repair: bool = False,
                 include_crew_margin: bool = False, include_promise: bool = False,
                 include_volume: bool = False,
                 **kw: Any) -> Dict[str, Any]:
    acc = await mapping_accuracy(db, factory_id, models)
    sens = await sensitivity(db, factory_id, models, **kw)
    inter = await interactions(db, factory_id, models, **kw)
    unc = propagate_uncertainty(sens, acc)
    priced = sum(1 for m in acc.get("models") or []
                 if float((m.get("components") or {}).get("price", {}).get("score") or 0) > 0)
    economy = {
        "cost_side": "人工（率 $30/人日·标定）、加急、开线、换型 —— 都在台账里算出来",
        "revenue_side": ("缺：延误罚则/客户违约成本/单价覆盖率 0 —— 没有收益侧的数，"
                         "所以「划不划算」「无收益」这类判断在这份数据上算不出来"),
        "usable_for": ("只能用于「同一批单内谁更省时省工」的排序；"
                       "不能作为投资决策，也不能对外说某个杠杆「无收益」"),
        "priced_models": priced, "models": len(models),
        "claim_guard": ("任何写成「省 $X / 值 $Y」的结论都必须同时写"
                        "「收益侧未建模，这只是成本差值」"),
    }
    out = {"factory_id": factory_id, "models": models, "economic_readiness": economy,
           "accuracy": acc, "sensitivity": sens, "uncertainty": unc, "interactions": inter,
           "how_to_read": ("要交期就给交期：base.finish_date 是这批的组合完工日，"
                           "curves 给每个输入动一档之后的完工日/人工/加急差值，"
                           "uncertainty 给这些数现在可信到几成、补哪项数据能压掉几天，"
                           "interactions 给两个杠杆一起上时多出来（或白花）的那部分，"
                           "risk（include_risk=true 时）给按已声明误差带抽出来的完工日分布，"
                           "data_repair（include_repair=true 时）给每条误差带修到下限之后毛边窄几天，"
                           "crew_margin（include_crew_margin=true 时）给要加多少人才让 P90 也赶上承诺，"
                           "promise（include_promise=true 时）给有把握能承诺的最早日期，"
                           "volume（include_volume=true 时）给保住现承诺最多能做几台。")}
    if include_risk:
        out["risk"] = await schedule_risk(db, factory_id, models, **kw)
    if include_repair:
        out["data_repair"] = await data_repair_experiment(db, factory_id, models, **kw)
    if include_crew_margin:
        out["crew_margin"] = await crew_margin_for_p90(db, factory_id, models, **kw)
    if include_promise:
        out["promise"] = await promise_headroom(db, factory_id, models, **kw)
    if include_volume:
        out["volume"] = await volume_ceiling_for_promise(db, factory_id, models, **kw)
    return out


# 两个杠杆一起上才看得出来的东西：各自的边际是"在别的都卡着"的前提下测的，
# 那前提本身可能正是另一个杠杆要解掉的瓶颈。
INTERACTION_LEVERS: List[Dict[str, Any]] = [
    {"key": "expedite_lead_days", "label": "压瓶颈件提前期（→7 天）", "on": {"expedite_lead_days": 7},
     "buys": "到货日"},
    {"key": "crew_bonus", "label": "加班加人 30%", "on": {"crew_bonus": 0.30}, "buys": "人手"},
    {"key": "parallel_lines", "label": "同组并联开满（2 条线）", "on": {"parallel_lines": 2},
     "buys": "线"},
]

# 交互项小于这个天数就当作"可加"（一天的差别在这套台账上是噪声级）
INTERACTION_TOLERANCE_DAYS = 0.5


def classify_interaction(inter_days: float, solo_a: float, solo_b: float) -> Tuple[str, str]:
    """把 Δ(AB)−Δ(A)−Δ(B) 翻成能引用的话：可加 / 替代 / 互补。

    替代（负）= 两个杠杆抢的是同一个瓶颈，第二个白花钱；互补（正）= 必须先上一个，
    另一个才 effective。0 不代表"两个都一样有用"，只代表这一个的钱能单独算。
    """
    if abs(inter_days) <= INTERACTION_TOLERANCE_DAYS:
        return ("additive",
                f"交互 {inter_days:+g} 天（≤±{INTERACTION_TOLERANCE_DAYS:g} 天视为可加）："
                "两个杠杆各解各的，钱可以分开算")
    if inter_days < 0:
        return ("substitutable",
                f"交互 {inter_days:+g} 天：一起上比分别上少买 {abs(inter_days):g} 天 —— "
                "它们解的是同一个瓶颈，第二个的钱白花，先挑便宜的那个")
    return ("complementary",
            f"交互 {inter_days:+g} 天：一起上比分别上多买 {inter_days:g} 天 —— "
            "有一个是另一个的前提（先上前提那个，单独上另一个会白花钱）")


async def interactions(db: AsyncSession, factory_id: str, models: List[str], *,
                       days_of_output: float = 6.0, lead_margin: Optional[float] = None,
                       attendance: float = 0.97,
                       levers: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """两两组合扫描：单独效果、联合效果与交互项（天 + 钱），走的还是 scan_policies 那一条路。"""
    margin = lead_margin if lead_margin is not None else vr.PROMISE_LEAD_MARGIN
    picks = levers or INTERACTION_LEVERS
    pol = {"name": "基准政策（分批开工）", "allow_partial": True}
    targets = await vr.derive_targets(db, factory_id, models,
                                      days_of_output=days_of_output, lead_margin=margin)

    async def measure(policy: Dict[str, Any]) -> Dict[str, Any]:
        m = await _run_one(db, factory_id, targets, policy, attendance=attendance)
        cost = (float(m.get("labor_cost_usd") or 0) + float(m.get("expedite_cost_usd") or 0)
                + float(m.get("line_activation_cost_usd") or 0))
        return {"m": m, "cost": round(cost, 2),
                "days_late_worst": (float(m["days_late_worst"])
                                    if m.get("days_late_worst") is not None else None)}

    base = await measure(pol)
    solo = {str(l["key"]): await measure({**pol, **l["on"]}) for l in picks}

    def saved(x: Dict[str, Any]) -> Optional[float]:
        """买回来的天数 = 基准延误 − 该政策的延误（正数=提前）。"""
        if x["days_late_worst"] is None or base["days_late_worst"] is None:
            return None
        return round(base["days_late_worst"] - x["days_late_worst"], 2)

    rows: List[Dict[str, Any]] = []
    for i in range(len(picks)):
        for j in range(i + 1, len(picks)):
            a, b = picks[i], picks[j]
            both = await measure({**pol, **a["on"], **b["on"]})
            d_a, d_b, d_ab = saved(solo[a["key"]]), saved(solo[b["key"]]), saved(both)
            c_a = round(solo[a["key"]]["cost"] - base["cost"], 2)
            c_b = round(solo[b["key"]]["cost"] - base["cost"], 2)
            c_ab = round(both["cost"] - base["cost"], 2)
            if None in (d_a, d_b, d_ab):
                rows.append({"pair": f"{a['label']} × {b['label']}", "status": "no_late_reading",
                             "why": "基准或该政策没有延天数读数（推演没给出日期）→ 不算交互"})
                continue
            inter = round(d_ab - d_a - d_b, 2)
            kind, reading = classify_interaction(inter, d_a, d_b)
            rows.append({
                "pair": f"{a['label']} × {b['label']}", "status": "ok",
                "keys": [str(a["key"]), str(b["key"])],
                "solo_days_saved": {"a": d_a, "b": d_b, "label_a": a["label"], "label_b": b["label"]},
                "joint_days_saved": d_ab, "interaction_days": inter,
                "cost_usd": {"a": c_a, "b": c_b, "joint": c_ab, "joint_minus_sum": round(c_ab - c_a - c_b, 2)},
                "relation": kind,
                "cheapest_path_usd_per_day": (round(min([c for c in (c_a, c_b, c_ab) if c > 0], default=0.0), 2)),
                "reading": reading,
            })
    return {"factory_id": factory_id, "models": models, "attendance": attendance,
            "base": {"days_late_worst": base["days_late_worst"], "cost_usd": base["cost"],
                     "finish_date": base["m"].get("finish_date"), "binding": base["m"].get("binding")},
            "solo": {str(l["key"]): {"days_saved": saved(solo[l["key"]]),
                                     "cost_usd": round(solo[l["key"]]["cost"] - base["cost"], 2),
                                     "finish_date": solo[l["key"]]["m"].get("finish_date"),
                                     "label": l["label"], "buys": l["buys"]} for l in picks},
            "pairs": rows, "tolerance_days": INTERACTION_TOLERANCE_DAYS,
            "note": ("单杠杆斜率是在『其它约束都还在』的前提下测的，所以它会说『加班买 0 天』；"
                     "这一格测的是把两个杠杆一起打开之后多出来（或少掉）的那部分 —— "
                     "替代关系为负意味着第二个的钱白花，互补为正意味着有一个是另一个的前提。"
                     "钱的口径=人工+加急+开线，收益侧未建模，所以只是成本差值。")}


# 蒙特卡洛抽的四个因子。误差带一律复用上面已声明的出处（ERROR_BAND / lead_error_band /
# 天气标定），这里不另立一套分布假设。
RISK_ATTENDANCE_LEVELS = (0.97, 0.92, 0.70)

RISK_FACTORS: List[Dict[str, Any]] = [
    {"input": "purchase_lead_time", "label": "外购提前期", "perturb": "lead_multiplier",
     "band_from": "lead_error_band(覆盖率)"},
    {"input": "unit_work_hours", "label": "单件工时", "perturb": "hours_multiplier",
     "band_from": "每台机自己的 hours_error_band"},
    {"input": "crew_attendance", "label": "到岗比例", "levels": list(RISK_ATTENDANCE_LEVELS),
     "band_from": "天气标定（用户 10-06 给的三档）"},
    {"input": "equipment_availability", "label": "设备可用率", "perturb": "equip_rate",
     "band_from": "台账实测 ±2pp"},
]


def _risk_summary(rows: List[Dict[str, Any]], *, factory_id: str, models: List[str],
                  policy_name: str, samples: int, seed: int, bands: Dict[str, Any],
                  with_date_note: str) -> Dict[str, Any]:
    """把一串同序抽样读数压成分位数读数。"""
    from datetime import date, timedelta

    dated = [r for r in rows if r.get("finish_date")]
    if not dated:
        return {"status": "no_dates", "policy": policy_name, "samples": samples,
                "why": "抽到的每一轮都推不出完工日（机种没有可推演的 BOM/依据）→ 给不出分布",
                "bindings_seen": sorted({str(r.get("binding")) for r in rows})}
    ordered = sorted(dated, key=lambda r: str(r["finish_date"]))
    lates = [float(r["days_late_worst"] or 0) for r in ordered]
    # 承诺日 = 每抽的（完工日 − 该抽延误）取最早：这台机被承诺到哪天才叫"准点"
    due = min(date.fromisoformat(str(r["finish_date"])) - timedelta(days=int(r["days_late_worst"] or 0))
              for r in dated)

    def pct(frac: float) -> Dict[str, Any]:
        idx = min(len(ordered) - 1, max(0, int(round(frac * (len(ordered) - 1)))))
        return {"percentile": int(frac * 100), "finish_date": str(ordered[idx]["finish_date"]),
                "days_late_worst": ordered[idx]["days_late_worst"]}

    p_on_time = round(sum(1 for x in lates if x <= 0) / len(lates), 3)
    p_late7 = round(sum(1 for x in lates if x > 7) / len(lates), 3)
    p10, p50, p90 = pct(0.10), pct(0.50), pct(0.90)

    def _gap_days(earlier: Dict[str, Any], later: Dict[str, Any]) -> int:
        return (date.fromisoformat(str(later["finish_date"]))
                - date.fromisoformat(str(earlier["finish_date"]))).days
    p90_p50 = _gap_days(p50, p90)
    p50_p10 = _gap_days(p10, p50)
    by_att: Dict[float, List[float]] = {}
    for r in dated:
        by_att.setdefault(float(r["attendance"]), []).append(float(r["days_late_worst"] or 0))
    return {
        "status": "ok", "factory_id": factory_id, "models": models, "policy": policy_name,
        "samples": samples, "seed": seed, "with_date": len(dated), "no_date": len(rows) - len(dated),
        "promise_date": str(due), "percentiles": [p10, p50, p90],
        "p90_p50_gap_days": p90_p50, "p50_p10_gap_days": p50_p10,
        "p_on_time": p_on_time, "p_late_gt_7_days": p_late7,
        "days_late_min": min(lates), "days_late_max": max(lates),
        "rough_days": round(max(lates) - min(lates), 1),
        "worst_seen": {"finish_date": str(ordered[-1]["finish_date"]),
                       "days_late_worst": ordered[-1]["days_late_worst"]},
        "by_attendance": [{"attendance": k, "samples": len(v),
                           "mean_days_late": round(sum(v) / len(v), 2),
                           "share_of_samples": round(len(v) / len(dated), 3)}
                          for k, v in sorted(by_att.items())],
        "bands_used": bands, "basis": with_date_note,
        "how_to_quote": ("引用时给 P50、P90 与准点概率三件；P90 与 P50 差几天就是这条交期的毛边，"
                         "只报 P50 等于把毛边藏起来"),
        "reading": (f"{samples} 抽 {len(dated)} 次有完工日：P50={p50['finish_date']}、"
                    f"P90={p90['finish_date']}（承诺 {due}）；毛边 P90−P50 = {p90_p50} 天；"
                    f"准点概率 {p_on_time:.0%}，延超过 7 天概率 {p_late7:.0%}；"
                    f"延误跨度 {min(lates):g}~{max(lates):g} 天"),
    }


def _risk_draws(n: int, seed: int, *, lead_band: float, hours_band: float,
                base_equip: float) -> List[Dict[str, Any]]:
    """抽出一串固定的工况序列（到岗/提前期/工时/设备）。

    多条政策共用**同一串**：各抽各的再相减，差里混着抽样噪声，会被读成政策的功效；
    同序配对之后，逐抽之差才是这一档政策在那种工况下买到的天数。
    """
    import random

    rng = random.Random(seed)
    draws: List[Dict[str, Any]] = []
    for _ in range(n):
        draws.append({"attendance": rng.choice(RISK_ATTENDANCE_LEVELS),
                      "lead_multiplier": round(1.0 + rng.uniform(-lead_band, lead_band), 4),
                      "hours_multiplier": round(1.0 + rng.uniform(-hours_band, hours_band), 4),
                      "equip_rate": round(max(0.05, min(1.0, base_equip + rng.uniform(-0.02, 0.02))), 4)})
    return draws


def _paired_delta(base_rows: List[Dict[str, Any]], other_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """同序配对后的逐抽差：正数=这一档政策把延误压掉几天。"""
    pairs = [(a, b) for a, b in zip(base_rows, other_rows)
             if a.get("days_late_worst") is not None and b.get("days_late_worst") is not None]
    if not pairs:
        return {"computable": False, "why": "两条政策没有可配对的同抽读数"}
    saved = sorted(round(float(a["days_late_worst"]) - float(b["days_late_worst"]), 2) for a, b in pairs)
    n = len(saved)
    half = n // 2
    median = saved[half] if n % 2 else round((saved[half - 1] + saved[half]) / 2.0, 2)
    # 天数是"少延误为好"(基准−对照)，钱是"多花为负"(对照−基准)：两个方向不能套同一个减法
    extra = sorted(round((float(b.get("expedite_cost_usd") or 0) + float(b.get("line_activation_cost_usd") or 0))
                         - (float(a.get("expedite_cost_usd") or 0) + float(a.get("line_activation_cost_usd") or 0)), 2)
                   for a, b in pairs)
    cost_median = extra[half] if n % 2 else round((extra[half - 1] + extra[half]) / 2.0, 2)
    return {"computable": True, "paired_draws": n,
            "days_saved_min": saved[0], "days_saved_median": median,
            "days_saved_p90": saved[min(n - 1, int(round(0.90 * (n - 1))))], "days_saved_max": saved[-1],
            "draws_where_it_helps": sum(1 for x in saved if x > 0),
            "draws_where_it_is_neutral": sum(1 for x in saved if x == 0),
            "draws_where_it_is_worse": sum(1 for x in saved if x < 0),
            "median_extra_cost_usd": cost_median,
            "cost_per_day_saved_usd": (round(cost_median / median, 2) if median else None),
            "note": ("逐抽同序配对：>0 是这一档真买到的时间；<0 说明某些工况下它反而拖后 —— "
                     "只看两个分布的分位数相减会把这两种情况抹平")}


async def _risk_setup(db: AsyncSession, factory_id: str, models: List[str], *,
                      days_of_output: float = 6.0, lead_margin: Optional[float] = None,
                      samples: int = 48, seed: int = 20261008) -> Dict[str, Any]:
    """抽样前的全部依据：目标单、每台机自己的带宽、设备实测率、固定抽次序列。

    交期分布和数据修复实验必须共用这一份，否则两边的毛边不是同一条抽样序列，
    差值就掺了抽样噪声。
    """
    margin = lead_margin if lead_margin is not None else vr.PROMISE_LEAD_MARGIN
    n = max(6, min(200, int(samples)))
    targets = await vr.derive_targets(db, factory_id, models,
                                      days_of_output=days_of_output, lead_margin=margin)
    base_eq = float((await vr.equipment_rate(db, factory_id)).get("rate") or 1.0)
    acc = await mapping_accuracy(db, factory_id, models)
    per_model = acc.get("models") or []
    worst_hours = max(per_model, key=lambda m: float(m.get("hours_error_band") or 0.0),
                      default=None) if per_model else None
    hours_band = float((worst_hours or {}).get("hours_error_band") or 0.0) if worst_hours else 0.0
    lead_covs = [float(((m.get("components") or {}).get("lead_time") or {}).get("score") or 0)
                 for m in per_model]
    lead_cov = min(lead_covs) if lead_covs else 0.0
    lead_band = lead_error_band(lead_cov) if lead_covs else 0.20
    return {"targets": targets, "base_equip": base_eq, "n": n, "seed": seed,
            "lead_band": round(lead_band, 3), "hours_band": round(hours_band, 3),
            "lead_coverage": round(lead_cov, 3),
            "hours_basis": str((((worst_hours or {}).get("components") or {}).get("hours") or {})
                               .get("basis") or "—"),
            "bands": {"purchase_lead_time": round(lead_band, 3), "unit_work_hours": round(hours_band, 3),
                      "crew_attendance_levels": list(RISK_ATTENDANCE_LEVELS),
                      "equipment_plus_minus": 0.02},
            "draws": _risk_draws(n, seed, lead_band=lead_band, hours_band=hours_band,
                                 base_equip=base_eq)}


async def _sample_rows(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                       one_policy: Dict[str, Any], draws: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按给定抽次序列逐抽推演一次（同序，所以两条政策/两种带宽的行能逐抽相减）。"""
    rows: List[Dict[str, Any]] = []
    for d in draws:
        perturb = {k: v for k, v in d.items() if k != "attendance"}
        m = await _run_one(db, factory_id, targets, one_policy,
                           attendance=d["attendance"], perturb=perturb)
        rows.append({"attendance": d["attendance"], **perturb, "binding": m.get("binding"),
                     "finish_date": m.get("finish_date"),
                     "days_late_worst": (float(m["days_late_worst"])
                                         if m.get("days_late_worst") is not None else None),
                     "labor_cost_usd": m.get("labor_cost_usd"),
                     "crew_before_staffing_sum": m.get("crew_before_staffing_sum"),
                     "crew_effective_sum": m.get("crew_effective_sum"),
                     "days_late_per_model": m.get("days_late_per_model") or {},
                     "finish_date_per_model": m.get("finish_date_per_model") or {},
                     "expedite_cost_usd": m.get("expedite_cost_usd"),
                     "line_activation_cost_usd": m.get("line_activation_cost_usd")})
    return rows


async def schedule_risk(db: AsyncSession, factory_id: str, models: List[str], *,
                        days_of_output: float = 6.0, lead_margin: Optional[float] = None,
                        policy: Optional[Dict[str, Any]] = None, samples: int = 48,
                        seed: int = 20261008,
                        against: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """把"可信到几成"换成一条日期分布：按已声明的误差带抽样，给 P50/P90 与准点概率。

    不确定度传导只有一个标量（±1.6 天），而决策要问的是"这版完工日有几成概率赶上承诺"。
    抽样不加新假设：提前期与工时按**每台机自己那条依据**允许的误差均匀抽（借同族路线 ±40%、
    自家路线 ±5%，一批机型共用乘子所以取最差那条），到岗按天气标定三档离散抽（不是正态），
    设备可用率按台账实测 ±2pp。种子固定 —— 这条分布必须能被重算核对。

    `against` 给一两档政策（如 {"name":"加急到 7 天","expedite_lead_days":7}）时，
    它们与基准共用同一串抽样，返回里给出同序配对的"每天数收窄"与中位多花的钱 ——
    这才是"这笔加急费买到的毛边收窄几天"。
    """
    pol = policy or {"name": "基准政策（分批开工）", "allow_partial": True}
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    basis_note = ("提前期按 lead_error_band(覆盖率)、工时按每台机自己的 hours_error_band，"
                  "两者都取这批里最差的那条；到岗按天气标定三档离散抽；设备可用率=台账实测 ±2pp。"
                  "没有引入新的分布假设，种子固定可重算。")

    async def sample(one_policy: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await _sample_rows(db, factory_id, setup["targets"], one_policy, setup["draws"])

    base_rows = await sample(pol)
    out = _risk_summary(base_rows, factory_id=factory_id, models=models, policy_name=pol["name"],
                        samples=n, seed=seed, bands=bands, with_date_note=basis_note)
    if out.get("status") != "ok":
        out["against"] = []
        return out

    comparisons: List[Dict[str, Any]] = []
    for alt in (against or []):
        one = {**pol, **alt}
        name = str(one.get("name") or f"政策 {alt}")
        alt_rows = await sample(one)
        alt_sum = _risk_summary(alt_rows, factory_id=factory_id, models=models, policy_name=name,
                               samples=n, seed=seed, bands=bands, with_date_note=basis_note)
        paired = _paired_delta(base_rows, alt_rows)
        entry = {"policy": name, "settings": {k: v for k, v in alt.items() if k != "name"}}
        if alt_sum.get("status") != "ok":
            entry["status"] = alt_sum.get("status")
            entry["why"] = alt_sum.get("why")
        else:
            entry.update({
                "status": "ok", "percentiles": alt_sum["percentiles"],
                "p_on_time": alt_sum["p_on_time"], "p_late_gt_7_days": alt_sum["p_late_gt_7_days"],
                "rough_days": alt_sum["rough_days"], "reading": alt_sum["reading"],
                "paired": paired,
                "rough_days_narrowed": (round(float(out["rough_days"]) - float(alt_sum["rough_days"]), 1)
                                        if out.get("rough_days") is not None else None),
            })
            if paired.get("computable") and paired.get("days_saved_median"):
                entry["headline"] = (f"同序配对：{paired['paired_draws']} 抽里 {paired['draws_where_it_helps']} 抽"
                                     f"买到时间、{paired['draws_where_it_is_worse']} 抽反而拖后，"
                                     f"中位数省 {paired['days_saved_median']:g} 天"
                                     f"（P90 那抽省 {paired['days_saved_p90']:g} 天）；"
                                     f"中位多花 ${paired['median_extra_cost_usd']:,.0f}"
                                     + (f"，每省一天约 ${paired['cost_per_day_saved_usd']:,.0f}"
                                        if paired.get("cost_per_day_saved_usd") else ""))
        comparisons.append(entry)
    out["against"] = comparisons
    return out


# 数据修复实验：毛边不是只能"接受"，它由几条已声明的误差带撑着。
# 把其中一条按现场能做到的下限收窄，同一串抽样重跑一次 —— 窄下来的天数就是这张数据的报价。
BAND_KEY = {"purchase_lead_time": "lead_multiplier", "unit_work_hours": "hours_multiplier",
            "equipment_availability": "equip_rate", "crew_attendance": "attendance"}

DATA_REPAIR_TARGETS: List[Dict[str, Any]] = [
    {"input": "purchase_lead_time", "label": "外购提前期逐料号实测", "repairable": True,
     "floor_band": 0.20, "floor_note": "覆盖率≥80% 时 lead_error_band 的底线就是 ±20%",
     "evidence_meaning": "覆盖率统计的是外购料号有没有提前期那个数（铺进去的默认值也算有数），"
                         "不是这一单量过没量过",
     "how": "把请购→到货的实测提前期按料号回填，替掉铺进去的默认值"},
    {"input": "unit_work_hours", "label": "单件工时按 IE 实测填实", "repairable": True,
     "floor_band": ERROR_BAND["route_standard_hours"], "floor_note": "IE 声明工时的已声明误差 ±5%",
     "evidence_meaning": "这条带宽取的是这批机型最差的那条工时依据"
                         "（IE 声明 ±5%／借同族路线 ±40%／线节拍反推 ±30%）",
     "how": "借同族路线（±40%）或线节拍反推（±30%）的那批工序，换成自家路线的实测工时"},
    {"input": "equipment_availability", "label": "设备可用率逐台按日打点", "repairable": True,
     "floor_band": 0.0, "floor_note": "±2pp 之外厂里没有声明下限，所以这一档按归零算=乐观上界",
     "evidence_meaning": "±2pp 是台账批量快照之间的抖动，不是逐台逐日量出来的",
     "how": "台账里那 ±2pp 是批量快照的抖动，逐台按日打点后不再是估计"},
    {"input": "crew_attendance", "label": "到岗波动（三档天气标定）", "repairable": False,
     "floor_band": 0.0, "floor_note": "这不是数据：是天气/节假日的真实波动，修台账不动它",
     "evidence_meaning": "三档是天气/季节标定的到岗档（0.97/0.92/0.70），不是某项数据的精度",
     "how": "放进来只为了把毛边分成可修/不可修两半，不进修复优先级"},
]


def _rescale_draws(draws: List[Dict[str, Any]], base_equip: float,
                   *, narrowed: Dict[str, float]) -> List[Dict[str, Any]]:
    """把某些因子的抽样偏移按比例收窄，其余因子逐抽原样保留。

    必须用**同一条随机序列**再乘比例，而不是重抽：重抽的话两次分布的差里混着抽样噪声，
    看着就像"修数据买到了几天"。
    """
    out: List[Dict[str, Any]] = []
    levels = sorted({d["attendance"] for d in draws})
    median_level = levels[len(levels) // 2] if levels else 0.92
    for d in draws:
        e = dict(d)
        for inp, keep in (narrowed or {}).items():
            keep = float(keep)
            if inp == "crew_attendance":
                e["attendance"] = median_level
            elif inp == "equipment_availability":
                e["equip_rate"] = round(max(0.05, min(1.0,
                                       base_equip + (float(d["equip_rate"]) - base_equip) * keep)), 4)
            else:
                key = BAND_KEY[inp]
                e[key] = round(1.0 + (float(d[key]) - 1.0) * keep, 4)
        out.append(e)
    return out


async def data_repair_experiment(db: AsyncSession, factory_id: str, models: List[str], *,
                                 samples: int = 24, seed: int = 20261008,
                                 days_of_output: float = 6.0,
                                 lead_margin: Optional[float] = None,
                                 policy: Optional[Dict[str, Any]] = None,
                                 only: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """逐条把误差带修到已声明的下限，重跑同一串抽样，报"这条数据值几天毛边"。

    与 propagate_uncertainty 的区别要写清：那边是 |斜率|×带宽 的线性折算（只单条杠杆、
    不含约束切换）；这里是真的把带宽改了再推演一遍，所以包含非线性，但只到"分布收窄"
    这一层 —— 它不承诺修完数据交期就提前，只承诺同一条交期可信度变高。
    """
    pol = policy or {"name": "基准政策（分批开工）", "allow_partial": True}
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    basis_note = ("抽样序列与交期分布同一串（同 seed）；每条修复只改自己那条带宽，"
                  "其余因子逐抽原样 —— 所以差值是这条数据的，不是抽样的。")

    async def run(draws: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
        rows = await _sample_rows(db, factory_id, setup["targets"], pol, draws)
        return _risk_summary(rows, factory_id=factory_id, models=models, policy_name=name,
                             samples=n, seed=seed, bands=bands, with_date_note=basis_note)

    base = await run(setup["draws"], pol["name"])
    if base.get("status") != "ok":
        return {**base, "repairs": [], "first_fix": None,
                "reading": [f"数据修复实验没跑成：{base.get('why')} —— 抽不出完工日就无从比较带宽"]}

    band_now = {"purchase_lead_time": setup["lead_band"], "unit_work_hours": setup["hours_band"],
                "equipment_availability": bands["equipment_plus_minus"],
                "crew_attendance": None}
    cov_now = {"purchase_lead_time": setup["lead_coverage"], "unit_work_hours": setup["hours_basis"],
               "equipment_availability": setup["base_equip"], "crew_attendance": None}

    targets_to_try = [t for t in DATA_REPAIR_TARGETS
                      if (not only) or t["input"] in set(only)]
    repairs: List[Dict[str, Any]] = []
    for t in targets_to_try:
        inp = t["input"]
        cur = band_now[inp]
        entry = {"input": inp, "label": t["label"], "repairable": t["repairable"],
                 "how": t["how"], "band_now": cur, "band_after": None,
                 "current_evidence": cov_now[inp], "evidence_meaning": t["evidence_meaning"],
                 "floor_note": t["floor_note"]}
        if not t["repairable"]:
            entry.update({"status": "not_repairable", "days_narrowed": None,
                          "why": ("这一档不是数据带宽：到岗三档是天气/节假日的真实波动，"
                                  "修台账不会让它变窄 —— 它只进可修/不可修那两半的账")})
            repairs.append(entry)
            continue
        if cur is None or float(cur) <= float(t["floor_band"]):
            entry.update({"status": "already_at_floor",
                          "why": (f"这条带宽现在 ±{cur}，已经不在下限 ±{t['floor_band']} 之上 —— "
                                  f"修它不会让毛边变窄，先去修别的那条（{t['evidence_meaning']}）"),
                          "days_narrowed": 0.0})
            repairs.append(entry)
            continue
        keep = float(t["floor_band"]) / float(cur)
        after = await run(_rescale_draws(setup["draws"], setup["base_equip"], narrowed={inp: keep}),
                          t["label"])
        if after.get("status") != "ok":
            entry.update({"status": "no_dates", "why": after.get("why"), "days_narrowed": None})
            repairs.append(entry)
            continue
        entry.update({
            "status": "ok", "band_after": t["floor_band"], "narrow_factor": round(keep, 3),
            "rough_days_now": base["rough_days"], "rough_days_after": after["rough_days"],
            "days_narrowed": round(float(base["rough_days"]) - float(after["rough_days"]), 1),
            "gap_days_now": base["p90_p50_gap_days"], "gap_days_after": after["p90_p50_gap_days"],
            "gap_days_narrowed": round(float(base["p90_p50_gap_days"])
                                       - float(after["p90_p50_gap_days"]), 1),
            "p_on_time_now": base["p_on_time"], "p_on_time_after": after["p_on_time"],
            "on_time_uplift_pp": round(100.0 * (float(after["p_on_time"]) - float(base["p_on_time"])), 1),
            "reading": after["reading"],
        })
        repairs.append(entry)

    measurable = [t for t in targets_to_try if t["repairable"]]
    narrowed: Dict[str, float] = {}
    for t in measurable:
        cur = band_now[t["input"]]
        if cur and float(cur) > float(t["floor_band"]):
            narrowed[t["input"]] = float(t["floor_band"]) / float(cur)
    floor = (await run(_rescale_draws(setup["draws"], setup["base_equip"], narrowed=narrowed),
                       "三条可修数据同时到下限") if narrowed else None)
    floor_ok = bool(floor and floor.get("status") == "ok")
    gap_now = float(base["p90_p50_gap_days"])
    gap_change = (round(gap_now - float(floor["p90_p50_gap_days"]), 1) if floor_ok else None)
    decomposition = {
        "rough_days_now": base["rough_days"], "gap_days_now": gap_now,
        "gap_days_if_all_repaired": (float(floor["p90_p50_gap_days"]) if floor_ok else None),
        "gap_change_if_all_repaired": gap_change,
        "repairable_gap_days": (max(0.0, gap_change) if floor_ok else None),
        "wider_by_days_if_all_repaired": (max(0.0, -gap_change) if floor_ok else None),
        "not_repairable_gap_days": (float(floor["p90_p50_gap_days"]) if floor_ok else None),
        "meaning": ("把可修的几条带宽一起压到已声明下限之后剩下的那几天，就是这套台账修不掉的毛边 —— "
                    "它来自到岗真实波动与约束本身，不是数据质量问题。合修反而变宽时（这条不为负），"
                    "说明带宽不是加性的：收窄一条会让约束换到另一条上"),
    }
    ranked = sorted([r for r in repairs if r.get("status") == "ok"],
                    key=lambda r: -(r["gap_days_narrowed"] or 0))
    pays = [r for r in ranked if (r["gap_days_narrowed"] or 0) > 0]
    first = pays[0] if pays else None
    lines = [
        f"毛边构成：{n} 抽 P50={base['percentiles'][1]['finish_date']}、"
        f"P90={base['percentiles'][2]['finish_date']} → 毛边 {base['p90_p50_gap_days']} 天"
        f"（跨度 {base['rough_days']} 天）、准点概率 {base['p_on_time']:.0%}",
    ]
    if floor_ok and gap_change > 0:
        lines.append(
            f"可修/不可修：三条可修数据同时到下限 → 毛边 {gap_now:g} 天收窄到 "
            f"{floor['p90_p50_gap_days']} 天，其中 {gap_change:g} 天是数据能修的"
            f"（占 {gap_change / max(1.0, gap_now):.0%}），"
            f"剩下 {floor['p90_p50_gap_days']} 天修台账不动它（到岗真实波动+约束本身）")
    elif floor_ok and gap_change < 0:
        lines.append(f"可修/不可修：三条同时到下限之后毛边反而宽了 {-gap_change:g} 天"
                     f"（{gap_now:g}→{floor['p90_p50_gap_days']}）—— 带宽不是加性的，"
                     f"收窄一条就有别的约束顶上来。这几天毛边不是这三条带宽造成的，"
                     f"报'数据能修掉 X 天'在这份数据上就是假话")
    elif floor_ok:
        lines.append(f"可修/不可修：三条同时到下限，毛边 {gap_now:g} 天一天没窄 —— "
                     f"这条毛边全在到岗真实波动与约束本身那一侧，不是测量误差")
    elif not narrowed:
        lines.append("可修/不可修：没有一条带宽在已声明下限之上，合修那一档就等于现在这条分布 —— "
                     "这一层分不出可修/不可修，不给比例")
    else:
        lines.append("可修/不可修：合修那一档抽不出完工日 —— 单独每条的数在下面，合起来的数不给")
    if pays:
        lines.append("先修哪条（按窄下来的天数排序）：" + " ＞ ".join(
            f"{r['label']}（带宽 ±{r['band_now']:.2f}→±{r['band_after']:.2f}，毛边窄 "
            f"{r['gap_days_narrowed']:g} 天、准点 {r['on_time_uplift_pp']:+g}pp）" for r in pays))
    else:
        at_floor = [f"{r['label']} 带宽 ±{r['band_now']} 已经等于下限 ±{r['band_after'] or r['band_now']}"
                    for r in repairs if r.get("status") == "already_at_floor"]
        measured = [f"{r['label']} ±{r['band_now']:.2f}→±{r['band_after']:.2f} "
                    + ("毛边没变" if not r["gap_days_narrowed"]
                       else (f"反而宽 {-r['gap_days_narrowed']:g} 天" if r["gap_days_narrowed"] < 0
                             else f"窄 {r['gap_days_narrowed']:g} 天"))
                    for r in ranked]
        parts = []
        if at_floor:
            parts.append("已经在下限的：" + "、".join(at_floor))
        if measured:
            parts.append("重跑过但压不动毛边的：" + "、".join(measured))
        lines.append("先修哪条：没有一条数据能压掉毛边" + (" —— " + "；".join(parts) if parts else "")
                     + "。要动的是约束口径，不是台账")
    if first:
        lines.append(f"这一条的依据：{first['how']}｜{first['floor_note']}")
    zeroed = [r for r in repairs if r.get("status") == "ok" and (r["gap_days_narrowed"] or 0) < 0]
    if zeroed:
        lines.append("反向：" + "、".join(
            f"{r['label']} 修到下限反而把毛边撑开 {-r['gap_days_narrowed']:g} 天（约束切换所致，"
            f"不是算错）" for r in zeroed))
    if not only:
        lines.append("这些带宽各自量的是什么：" + "；".join(
            f"{r['label']}＝{r['evidence_meaning']}" for r in repairs if r.get("evidence_meaning")))
    return {
        "status": "ok", "factory_id": factory_id, "models": models, "policy": pol["name"],
        "samples": n, "seed": seed, "bands_now": band_now, "evidence_now": cov_now,
        "baseline": base, "repairs": repairs, "all_repaired": floor,
        "decomposition": decomposition, "first_fix": first, "reading": lines,
        "method": ("带宽改了再重跑同一串抽样，取 P90−P50 的差 = 这条数据的报价；"
                   "与 propagate_uncertainty 的 |斜率|×带宽 线性折算不是同一个数（那个不含约束切换）"),
        "claim_guard": ("修数据只把毛边变窄，不会把完工日提前 —— 报'省几天'之前要分清说的是毛边还是交期；"
                        "下限之外厂里没有声明更准的数，所以归零那一档（设备）是乐观上界"),
    }


# 加多少人赶得上承诺 —— 这格必须逐档真跑：斜率那一格在好天档测出"加班 0 天"，
# 而毛边几乎全来自暴雨档，所以"要不要加人"只能在抽过样的分布上判。
CREW_LADDER = (0.10, 0.20, 0.30, 0.50, 0.75, 1.00)


def _part_names(parts: Any) -> List[str]:
    """瓶颈件要点名到料号＋缺口＋提前期＋供应商＋依据，不然"卡在料上"是空话。

    台账里 bottleneck_part 是字典（有时是字符串/空），两种形状都要能吃，且不许因为
    字典不可哈希就在 set() 里炸掉整张卡。
    """
    out: List[str] = []
    values = list(parts.values()) if isinstance(parts, dict) else list(parts or [])
    for v in values:
        if isinstance(v, dict):
            bits = [str(v.get("material_code") or "?")]
            if v.get("short") is not None:
                bits.append(f"缺 {v['short']:g} 件")
            if v.get("lead_time_days") is not None:
                bits.append(f"提前 {v['lead_time_days']} 天")
            if v.get("supplier"):
                bits.append(f"供应商 {v['supplier']}")
            if v.get("lead_evidence"):
                bits.append(f"依据 {v['lead_evidence']}")
            out.append("·".join(bits))
        elif v:
            out.append(str(v))
    return sorted(set(out))


def _g(value: Any, when_missing: str = "—") -> str:
    """人头/天数缺读数时给一个明写的占位，不让格式串把整格炸掉。"""
    return when_missing if value is None else f"{float(value):g}"


def _median(values: List[Any]) -> Optional[float]:
    from statistics import median

    vals = [float(v) for v in values if v is not None]
    return round(float(median(vals)), 2) if vals else None


def _paired_median_delta(base_rows: List[Dict[str, Any]], alt_rows: List[Dict[str, Any]],
                         key: str) -> Optional[float]:
    """同序配对的逐抽中位差（钱：alt−base，正数=多花；人头同理）。"""
    from statistics import median

    pairs = [(float(a.get(key) or 0), float(b.get(key) or 0)) for a, b in zip(base_rows, alt_rows)]
    return round(float(median([b - a for a, b in pairs])), 2) if pairs else None


def _p90(summary: Dict[str, Any]) -> Dict[str, Any]:
    return next((p for p in (summary.get("percentiles") or [])
                 if int(p.get("percentile") or 0) == 90), {})


def _p50(summary: Dict[str, Any]) -> Dict[str, Any]:
    return next((p for p in (summary.get("percentiles") or [])
                 if int(p.get("percentile") or 0) == 50), {})


async def crew_margin_for_p90(db: AsyncSession, factory_id: str, models: List[str], *,
                              samples: int = 16, seed: int = 20261008,
                              on_time_required: float = 0.90,
                              ladder: Tuple[float, ...] = CREW_LADDER,
                              days_of_output: float = 6.0,
                              lead_margin: Optional[float] = None,
                              policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """逐档加人（crew_bonus）在**同一串抽样**上真跑，找出第一个准点概率达标的档位。

    报出来的档位必须自己就成立：给 k_min，同时给低一档 k_below 实测到达的准点概率，
    这样"加 30% 人手"不是插值猜出来的。人头按向上取整报（人是整数，向下取整就少人了）。
    加人买到的时间集中在暴雨档 —— 好天/雨季那两档卡的是线声明产能上限，这格把它分开报。
    """
    pol = policy or {"name": "基准政策（分批开工）", "allow_partial": True}
    req = max(0.50, min(0.99, float(on_time_required)))
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    note = ("抽样与交期分布同一串（同 seed）；每档只改 crew_bonus，"
            "到岗/提前期/工时/设备逐抽原样 —— 所以档位之间的差是人手的功劳。")

    async def one(k: float) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        rows = await _sample_rows(db, factory_id, setup["targets"], {**pol, "crew_bonus": float(k)},
                                  setup["draws"])
        return rows, _risk_summary(rows, factory_id=factory_id, models=models,
                                   policy_name=f"{pol['name']}＋加人 {k:.0%}", samples=n, seed=seed,
                                   bands=bands, with_date_note=note)

    base_rows, base = await one(0.0)
    if base.get("status") != "ok":
        return {**base, "ladder_tried": [], "verdict": "no_dates", "on_time_required": req,
                "reading": [f"加人档位实验没跑成：{base.get('why')} —— 抽不出完工日就谈不上赶不赶得上"]}
    base_heads = _median([r.get("crew_before_staffing_sum") for r in base_rows])
    out: Dict[str, Any] = {"status": "ok", "factory_id": factory_id, "models": models,
                           "samples": n, "seed": seed, "on_time_required": req,
                           "promise_date": base["promise_date"],
                           "baseline": {"p_on_time": base["p_on_time"],
                                        "p90": _p90(base), "rough_days": base["rough_days"],
                                        "crew_per_day": base_heads,
                                        "by_attendance": base["by_attendance"]},
                           "bands_used": bands, "ladder_tried": [], "verdict": None, "reading": []}

    if float(base["p_on_time"]) >= req:
        out["verdict"] = {"kind": "already_ok", "crew_bonus": 0.0,
                          "note": f"不加人也已经 {base['p_on_time']:.0%} 准点（≥{req:.0%}）"}
        out["reading"] = [f"准点概率已经 {base['p_on_time']:.0%} ≥ 要求的 {req:.0%} —— 不用加人；"
                          f"要动的是别的（看毛边构成那一格）"]
        return out

    attempts: List[Dict[str, Any]] = []
    reach_rows: Optional[List[Dict[str, Any]]] = None
    reach_sum: Optional[Dict[str, Any]] = None
    reach_k: Optional[float] = None
    for k in ladder:
        rows, s = await one(k)
        if s.get("status") != "ok":
            attempts.append({"crew_bonus": k, "status": s.get("status"), "why": s.get("why")})
            continue
        p90 = _p90(s)
        rec = {"crew_bonus": k, "p_on_time": s["p_on_time"],
               "p90_days_late": p90.get("days_late_worst"), "p90_finish_date": p90.get("finish_date"),
               "rough_days": s["rough_days"],
               "crew_per_day": _median([r.get("crew_before_staffing_sum") for r in rows]),
               "median_extra_heads": _paired_median_delta(base_rows, rows, "crew_before_staffing_sum"),
               "median_extra_labor_cost_usd": _paired_median_delta(base_rows, rows, "labor_cost_usd"),
               "binding_seen": sorted({str(r.get("binding")) for r in rows if r.get("binding")}),
               "by_attendance": s["by_attendance"], "reading": s["reading"]}
        attempts.append(rec)
        if float(s["p_on_time"]) >= req:
            reach_rows, reach_sum, reach_k = rows, s, k
            break

    below = next((a for a in reversed(attempts[:-1]) if "p_on_time" in a), None)
    if below is None:
        below = {"crew_bonus": 0.0, "p_on_time": base["p_on_time"]}
    def attendance_effect(rows_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        before = {float(x["attendance"]): float(x["mean_days_late"]) for x in base["by_attendance"]}
        after = {float(x["attendance"]): float(x["mean_days_late"])
                 for x in (rows_summary or {}).get("by_attendance") or []}
        return [{"attendance": a, "days_late_before": before.get(a), "days_late_after": after.get(a),
                 "days_bought": (round(before[a] - after[a], 2) if a in before and a in after else None)}
                for a in sorted(set(before) | set(after))]

    out["ladder_tried"] = attempts
    if reach_sum is None:
        rungs = [a for a in attempts if "p_on_time" in a]
        top = rungs[-1] if rungs else None          # 最高那一档，不是"最不差"的那一档
        binding = sorted({b for a in attempts for b in (a.get("binding_seen") or [])})
        out["verdict"] = {
            "kind": "not_crew_bound", "top_crew_bonus": (top or {}).get("crew_bonus", max(ladder)),
            "best_p_on_time": max((float(a["p_on_time"]) for a in rungs), default=0.0),
            "top_p_on_time": (top or {}).get("p_on_time"),
            "top_p90_days_late": (top or {}).get("p90_days_late"),
            "top_extra_heads_per_day": (top or {}).get("median_extra_heads"),
            "top_median_extra_labor_cost_usd": (top or {}).get("median_extra_labor_cost_usd"),
            "by_attendance_effect": attendance_effect(top or {}),
            "binding_seen": binding,
            "note": (f"加到 {(top or {}).get('crew_bonus', max(ladder)):.0%} 也只到 "
                     f"{(top or {}).get('p_on_time', 0):.0%} 准点（要求 {req:.0%}）—— "
                     f"这串抽样里卡的一直是 {'、'.join(binding) or '未明'}，不是人手不够")}
        ladder_text = "、".join(
            f"{float(a['crew_bonus']):.0%}→{float(a['p_on_time']):.0%}"
            for a in attempts if "p_on_time" in a)
        moved = [h for h in out["verdict"]["by_attendance_effect"] if (h["days_bought"] or 0) > 0]
        spread = (max(h["days_late_before"] for h in out["verdict"]["by_attendance_effect"]
                      if h.get("days_late_before") is not None)
                  - min(h["days_late_before"] for h in out["verdict"]["by_attendance_effect"]
                        if h.get("days_late_before") is not None)
                  if out["verdict"]["by_attendance_effect"] else 0.0)
        out["reading"] = [
            f"加人解不到：加到 {(top or {}).get('crew_bonus', max(ladder)):.0%}"
            f"（每天多 {(top or {}).get('median_extra_heads') or 0:g} 人、中位人工多 "
            f"${(top or {}).get('median_extra_labor_cost_usd') or 0:,.0f}/批）"
            f"仍然只 {(top or {}).get('p_on_time', 0):.0%} 准点，P90 还延 "
            f"{(top or {}).get('p90_days_late')} 天｜这串抽样里卡的一直是 "
            f"{'、'.join(binding) or '未明'} —— 是料与线声明产能的上限，不是班组人数",
            f"准点概率随加人：{ladder_text or '没有一档出得了完工日'}",
            "加人买到的时间在哪儿：" + ("、".join(
                f"{h['attendance']:.2f} 档 延 {h['days_late_before']}→{h['days_late_after']} 天"
                f"（买到 {h['days_bought']:g} 天）" for h in moved)
                if moved else (
                    f"哪一档都没买到 —— 各档延误在加人前后一模一样。补一句：到岗本身确实改延误"
                    f"（这批里最紧档与最松档差 {spread:g} 天），但加人换不回来 —— "
                    f"到岗影响交期走的不是『班组人数×单件工时』这条通道，具体哪一条还得再核")),
        ]
        return out

    reach_heads = _median([r.get("crew_before_staffing_sum") for r in reach_rows or []])
    from math import ceil

    heads_known = base_heads is not None and reach_heads is not None
    extra_heads = (int(ceil(max(0.0, float(reach_heads) - float(base_heads))))
                   if heads_known else None)
    extra_cost = _paired_median_delta(base_rows, reach_rows or [], "labor_cost_usd")
    below_txt = f"低一档 {below['crew_bonus']:.0%} 实测只到 {below['p_on_time']:.0%} 准点"
    helps = attendance_effect(reach_sum)
    out["verdict"] = {
        "kind": "found", "crew_bonus": reach_k, "below_crew_bonus": (below or {}).get("crew_bonus"),
        "below_p_on_time": (below or {}).get("p_on_time"),
        "p_on_time_at_level": reach_sum["p_on_time"],
        "p90_days_late_at_level": _p90(reach_sum).get("days_late_worst"),
        "p90_finish_date_at_level": _p90(reach_sum).get("finish_date"),
        "crew_per_day_at_level": reach_heads, "extra_heads_per_day": extra_heads,
        "median_extra_labor_cost_usd": extra_cost, "by_attendance_effect": helps,
        "note": (f"加 {reach_k:.0%} 人手把准点概率抬到 {reach_sum['p_on_time']:.0%}（要求 {req:.0%}）；"
                 f"{below_txt} —— 报 {reach_k:.0%} 是因为它自己就成立")}
    out["reading"] = [
        f"现状：{n} 抽准点概率 {base['p_on_time']:.0%}（要求 ≥{req:.0%}），P90 完工 "
        f"{_p90(base).get('finish_date')}（延 {_p90(base).get('days_late_worst')} 天，承诺 "
        f"{base['promise_date']}），班组每天到站中位 {_g(base_heads)} 人",
        f"赶得上要加：人手 +{reach_k:.0%} ＝ 每天多 {_g(extra_heads, '算不出')} 人"
        f"（{_g(base_heads)}→{_g(reach_heads)} 人），"
        f"准点概率到 {reach_sum['p_on_time']:.0%}；{below_txt}",
        f"这档的钱：人工中位多花 ${extra_cost or 0:,.0f}/批｜口径：收益侧未建模，只有成本差值"
        f"（$30/人日·标定），不构成投资回报",
        "加人买到的时间在哪儿：" + "、".join(
            f"{h['attendance']:.2f} 档 延 {h['days_late_before']}→{h['days_late_after']} 天"
            + (f"（买到 {h['days_bought']:g} 天）" if (h['days_bought'] or 0) > 0 else "（买不到）")
            for h in helps) + " —— 到岗高的那档买不到，是因为它卡在线声明产能上限",
    ]
    out["method"] = ("逐档真跑同一串抽样的 crew_bonus，报第一个达标档位并附低一档的实测读数；"
                     "人头按占用班组加总（同线被两台机共用会各算一次），向上取整")
    out["claim_guard"] = ("这是'要让 P90 也赶上承诺'的人手余量，不是'加人就能提前'——"
                          "好天档加人不换时间；钱只是人工成本差值，收益侧未建模")
    return out



# 承诺这一格不该问"赶不赶得上"（答案已经知道：赶不上），要问"有 9 成把握的话最早能报哪天"。
# 逐条政策在**同一串抽样**上取 P90 完工日，最早的那个就是可承诺日；多花的钱按同序配对算差值。
PROMISE_POLICIES: List[Dict[str, Any]] = [
    {"name": "现政策（分批开工）", "allow_partial": True},
    {"name": "压瓶颈件提前期→7 天", "allow_partial": True, "expedite_lead_days": 7},
    {"name": "压提前期＋并联开满 2 条线", "allow_partial": True, "expedite_lead_days": 7,
     "parallel_lines": 2},
    {"name": "压提前期＋并联＋加班加人 30%", "allow_partial": True, "expedite_lead_days": 7,
     "parallel_lines": 2, "crew_bonus": 0.30},
]


def _earliest_then_cheapest(options: List[Dict[str, Any]]) -> Dict[str, Any]:
    """可承诺日取最早；同一天有几条政策做得到时取台账算出来最便宜的那条。

    并列不等于随便挑 —— 实测并联开线与只加急的 P90 都是 11-28，差着 $180,630/批。
    """
    return min(options, key=lambda o: (str(o.get("p90_finish_date")),
                                       float(o.get("median_total_cost_usd") or 0),
                                       str(o.get("policy"))))


async def promise_headroom(db: AsyncSession, factory_id: str, models: List[str], *,
                           samples: int = 24, seed: int = 20261008,
                           required: float = 0.90, days_of_output: float = 6.0,
                           lead_margin: Optional[float] = None,
                           policies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """把"能不能赶上"换成"最早能承诺哪天"：每条政策取自己那串抽样的 P90 完工日。

    P90 不是最优而是"九成情况下不会晚于这天"，所以它是可以写进承诺的那个数；
    报出来的日期必须带着它靠哪条政策、比现承诺晚几天、多花多少钱一起出去。
    """
    from datetime import timedelta

    req = max(0.50, min(0.99, float(required)))
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    note = ("抽样与交期分布同一串（同 seed）；每条政策只换政策字典，"
            "到岗/带宽逐抽原样 —— 所以日期差是政策的，不是抽样的。")

    base_rows: Optional[List[Dict[str, Any]]] = None
    options: List[Dict[str, Any]] = []
    for pol in (policies or PROMISE_POLICIES):
        name = str(pol.get("name") or "政策")
        rows = await _sample_rows(db, factory_id, setup["targets"], pol, setup["draws"])
        s = _risk_summary(rows, factory_id=factory_id, models=models, policy_name=name,
                          samples=n, seed=seed, bands=bands, with_date_note=note)
        if base_rows is None:
            base_rows = rows
        if s.get("status") != "ok":
            options.append({"policy": name, "status": s.get("status"), "why": s.get("why")})
            continue
        p90 = _p90(s)
        promise = s["promise_date"]
        later = (date.fromisoformat(str(p90["finish_date"]))
                 - date.fromisoformat(str(promise))).days
        money = _median([float(r.get("labor_cost_usd") or 0) + float(r.get("expedite_cost_usd") or 0)
                         + float(r.get("line_activation_cost_usd") or 0) for r in rows])
        options.append({
            "policy": name, "status": "ok",
            "settings": {k: v for k, v in pol.items() if k not in ("name",)},
            "promise_date": promise, "p50_finish_date": _p50(s).get("finish_date"),
            "p90_finish_date": p90.get("finish_date"), "p90_days_late": p90.get("days_late_worst"),
            "p90_vs_promise_days": later, "p_on_time": s["p_on_time"],
            "rough_days": s["rough_days"], "median_total_cost_usd": money,
            "median_extra_cost_vs_now": _paired_median_delta(
                [r for r in (base_rows or []) if r.get("labor_cost_usd") is not None],
                rows, "labor_cost_usd"),
            "binding_seen": sorted({str(r.get("binding")) for r in rows if r.get("binding")}),
            "reading": s["reading"],
        })

    usable = [o for o in options if o.get("status") == "ok"]
    if not usable:
        return {"status": "no_dates", "factory_id": factory_id, "models": models,
                "options": options, "verdict": None, "on_time_required": req,
                "reading": [f"可承诺日算不出：{len(options)} 条政策没有一条抽得出完工日 —— "
                            f"机种没有可推演的 BOM/依据时这一格不给日期"]}
    best = _earliest_then_cheapest(usable)
    now_opt = usable[0]
    out: Dict[str, Any] = {
        "status": "ok", "factory_id": factory_id, "models": models, "samples": n, "seed": seed,
        "on_time_required": req, "current_promise": now_opt["promise_date"],
        "bands_used": bands, "options": options,
        "verdict": {
            "earliest_defensible_promise": best["p90_finish_date"],
            "policy": best["policy"], "settings": best["settings"],
            "days_later_than_current": int(best["p90_vs_promise_days"]),
            "p_on_time_at_current_promise": best["p_on_time"],
            "median_total_cost_usd": best["median_total_cost_usd"],
            "current_policy_p90": now_opt["p90_finish_date"],
            "days_saved_by_policy": (int(now_opt["p90_vs_promise_days"])
                                     - int(best["p90_vs_promise_days"])),
            "binding_seen": best["binding_seen"],
        },
    }
    v = out["verdict"]
    lines = [
        f"现承诺 {out['current_promise']}：现政策下 P90 完工 {now_opt['p90_finish_date']}"
        f"（晚 {now_opt['p90_vs_promise_days']} 天），准点概率 {now_opt['p_on_time']:.0%} "
        f"—— 要 {req:.0%} 把握的话这个日期报不出去",
        f"有 {req:.0%} 把握能承诺的最早日期：{v['earliest_defensible_promise']}"
        f"（比现承诺晚 {v['days_later_than_current']} 天），用的是『{v['policy']}』；"
        f"这条政策自己把 P90 拉回 {v['days_saved_by_policy']} 天",
    ]
    cheaper = [o for o in usable if o["policy"] != now_opt["policy"]]
    if cheaper:
        lines.append("逐条政策的 P90：" + "、".join(
            f"{o['policy']}→{o['p90_finish_date']}（晚 {o['p90_vs_promise_days']} 天、"
            f"准点 {o['p_on_time']:.0%}）" for o in usable))
    if v["days_later_than_current"] <= 0 and v["p_on_time_at_current_promise"] >= req:
        lines.append("结论：现承诺就在这条政策的 9 成线内 —— 不用改日期，改的是排产那侧的执行")
    else:
        lines.append(
            f"结论：要把 {req:.0%} 把握写进承诺，只能报 {v['earliest_defensible_promise']}；"
            f"现承诺 {out['current_promise']} 在扫过的 {len(usable)} 条政策里都没有 9 成 —— "
            f"该改日期或减量，不是再加杠杆")
    out["reading"] = lines
    out["method"] = ("可承诺日 = 各政策在同一串抽样上的 P90 完工日取最早；"
                     "P90 是『九成情况下不会晚于这天』，所以是能写进承诺的那个数，不是最好看的数")
    out["claim_guard"] = ("引擎只给『哪天有 9 成』，不代做承诺 —— 改承诺日要企业授权流程确认；"
                          "钱只是台账算出的成本差值，收益侧与违约罚则未建模")
    return out

# 承诺对不上时有四条路：改日期、加杠杆、修数据、减量。前三条都已经各自成格并给了"换不动"的实测，
# 这一格补第四条：要保住现承诺且有 9 成把握，这批单最多能做几台。
VOLUME_LADDER = (1.0, 0.75, 0.50, 0.35, 0.20)


def _adjacent_above(rungs: List[Dict[str, Any]], ratio: Any) -> Dict[str, Any]:
    """紧邻的"多做一档"：比这个量大的档位里取最小的那个，不是取最大的。

    报"减到 N 台就有 9 成"时，反面必须贴着它 —— 拿 100% 那档当反例会把"多做一点就崩"说轻。
    """
    bigger = [x for x in rungs if x.get("status") == "ok" and float(x["ratio"]) > float(ratio)]
    if not bigger:
        return {}
    return min(bigger, key=lambda x: float(x["ratio"]))


async def volume_ceiling_for_promise(db: AsyncSession, factory_id: str, models: List[str], *,
                                     samples: int = 20, seed: int = 20261008,
                                     required: float = 0.90,
                                     ladder: Tuple[float, ...] = VOLUME_LADDER,
                                     days_of_output: float = 6.0,
                                     lead_margin: Optional[float] = None,
                                     policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按量扫同一串抽样，找"仍然有 9 成把握赶上现承诺"的最大量；报的是台数不是百分比。

    减量与加人不一样：它是把需求削到产能与等料窗口里，所以达标也要说清"少做的是哪几台、
    少多少台"。一档都不达标时如实说"减量也换不到时间"，这时候卡的是等料窗口不是量。
    """
    pol = policy or {"name": "现政策（分批开工）", "allow_partial": True}
    req = max(0.50, min(0.99, float(required)))
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    note = ("抽样与交期分布同一串（同 seed）；每档只改 targets 的 units，"
            "到岗/带宽/政策逐抽原样 —— 所以准点概率的差是量造成的。")
    full_units = sum(int(t.get("units") or 0) for t in setup["targets"])

    rungs: List[Dict[str, Any]] = []
    reach: Optional[Dict[str, Any]] = None
    for r in ladder:
        scaled = [{**t, "units": max(1, int(round(float(t.get("units") or 0) * float(r))))}
                  for t in setup["targets"]]
        rows = await _sample_rows(db, factory_id, scaled, pol, setup["draws"])
        s = _risk_summary(rows, factory_id=factory_id, models=models,
                          policy_name=f"{pol['name']}·量 {r:.0%}", samples=n, seed=seed,
                          bands=bands, with_date_note=note)
        total = sum(int(t["units"]) for t in scaled)
        rec = {"ratio": float(r), "units_total": total,
               "units_per_model": {str(t["model_code"]): int(t["units"]) for t in scaled}}
        if s.get("status") != "ok":
            rec.update({"status": s.get("status"), "why": s.get("why")})
            rungs.append(rec)
            continue
        p90 = _p90(s)
        rec.update({"status": "ok", "p_on_time": s["p_on_time"],
                    "p50_finish_date": _p50(s).get("finish_date"),
                    "p90_finish_date": p90.get("finish_date"),
                    "p90_days_late": p90.get("days_late_worst"),
                    "rough_days": s["rough_days"],
                    "promise_date": s["promise_date"],
                    "median_labor_cost_usd": _median([r0.get("labor_cost_usd") for r0 in rows]),
                    "binding_seen": sorted({str(x.get("binding")) for x in rows if x.get("binding")}),
                    "meets_required": float(s["p_on_time"]) >= req})
        rungs.append(rec)
        if float(s["p_on_time"]) >= req and reach is None:
            reach = rec

    usable = [x for x in rungs if x.get("status") == "ok"]
    if not usable:
        return {"status": "no_dates", "factory_id": factory_id, "models": models,
                "ladder_tried": rungs, "verdict": None, "on_time_required": req,
                "reading": [f"减量测算没跑成：{len(rungs)} 档都抽不出完工日 —— "
                            f"没有日期就没有'减量换不换来'这格的答案"]}
    out: Dict[str, Any] = {"status": "ok", "factory_id": factory_id, "models": models,
                           "samples": n, "seed": seed, "on_time_required": req,
                           "calibrated_units": full_units, "promise_date": usable[0]["promise_date"],
                           "bands_used": bands, "ladder_tried": rungs}
    if usable[0]["meets_required"]:
        out["verdict"] = {"kind": "already_ok", "ratio": 1.0, "units_total": usable[0]["units_total"],
                          "p_on_time": usable[0]["p_on_time"],
                          "note": "标定场景的量本来就有 9 成把握 —— 不用减量，问题在别处"}
        out["reading"] = [f"现量 {full_units:,} 台已经有 {usable[0]['p_on_time']:.0%} 准点"
                          f"（要求 {req:.0%}）—— 减量不是这条路要动的东西"]
        return out
    if reach is None:
        smallest = min(usable, key=lambda x: float(x["ratio"]))
        base_p = float(usable[0]["p_on_time"])
        best_p = max(float(x["p_on_time"]) for x in usable)
        binding = sorted({b for x in usable for b in (x.get("binding_seen") or [])})
        helps = best_p > base_p
        out["verdict"] = {
            "kind": ("volume_helps_but_not_enough" if helps else "volume_not_the_lever"),
            "smallest_ratio": float(smallest["ratio"]), "units_at_smallest": int(smallest["units_total"]),
            "units_cut_at_smallest": full_units - int(smallest["units_total"]),
            "base_p_on_time": base_p, "best_p_on_time": best_p,
            "p90_days_late_at_base": usable[0].get("p90_days_late"),
            "p90_days_late_at_smallest": smallest.get("p90_days_late"),
            "binding_seen": binding,
            "note": (f"砍到 {float(smallest['ratio']):.0%}（{int(smallest['units_total']):,} 台）"
                     f"准点概率只从 {base_p:.0%} 抬到 {best_p:.0%}，仍不到要求的 {req:.0%} —— "
                     f"减量有用但不够，最后那几天卡的是 {'、'.join(binding) or '未明'}")}
        curve = "、".join(
            "{:.0%}→{:.0%}".format(float(x["ratio"]), float(x["p_on_time"])) for x in usable)
        days_curve = "、".join(
            "{:.0%}→延{}".format(float(x["ratio"]), x.get("p90_days_late")) for x in usable)
        out["reading"] = [
            f"减量换不到 9 成（{n} 抽·同一串抽样）：{full_units:,} 台砍到 "
            f"{int(smallest['units_total']):,} 台（少 "
            f"{full_units - int(smallest['units_total']):,} 台）"
            + (f"准点概率从 {base_p:.0%} 抬到 {best_p:.0%}，仍不到 {req:.0%}"
               if helps else f"准点概率一点没动（{base_p:.0%}）"),
            f"P90 延误随量：{days_curve} —— 省下的是 "
            f"{float(usable[0].get('p90_days_late') or 0) - float(smallest.get('p90_days_late') or 0):g} 天，"
            f"最后那 {float(smallest.get('p90_days_late') or 0):g} 天不是量能换的（卡的是 "
            f"{'、'.join(binding) or '未明'}）",
            f"准点概率随量：{curve}",
            "要继续追这单：看承诺上限那一格（改日期）或提前期那一格（压瓶颈件）；"
            "再往下砍就只是少卖，不是早交",
        ]
        out["claim_guard"] = ("这条读数只说明'减到最小档也拿不到 9 成'，不许被引用成'量多了所以延期'；"
                              "减量的确有把 P90 拉早（见 P90 延误随量那一行），只是不够达标")
        out["method"] = ("同一串抽样上逐档改 targets.units，报每一档的准点概率与 P90 延误；"
                         "没有一档达标就不给'最多能做几台'这个数，不插值")
        return out

    full = usable[0]
    out["verdict"] = {
        "kind": "found", "ratio": reach["ratio"], "units_total": reach["units_total"],
        "units_per_model": reach["units_per_model"], "p_on_time": reach["p_on_time"],
        "p90_finish_date": reach["p90_finish_date"], "promise_date": reach["promise_date"],
        "units_cut": full_units - int(reach["units_total"]),
        # "多做一档"取紧邻的那一档，不是最大的那一档 —— 阈值要它自己就成立
        "next_ratio_fails": _adjacent_above(usable, reach["ratio"])["ratio"],
        "next_ratio_p_on_time": _adjacent_above(usable, reach["ratio"])["p_on_time"],
        "median_labor_cost_usd": reach["median_labor_cost_usd"],
        "labor_released_usd": round(float(full.get("median_labor_cost_usd") or 0)
                                    - float(reach.get("median_labor_cost_usd") or 0), 2),
        "note": (f"最多做 {reach['units_total']:,} 台（比标定场景少 "
                 f"{full_units - int(reach['units_total']):,} 台）仍有 {reach['p_on_time']:.0%} 准点；"
                 f"多做一档（{_adjacent_above(usable, reach['ratio'])['ratio'] or 0:.0%}）就掉到 "
                 f"{_adjacent_above(usable, reach['ratio'])['p_on_time'] or 0:.0%}"),
    }
    out["reading"] = [
        f"现量 {full_units:,} 台：准点概率 {full['p_on_time']:.0%}（要求 ≥{req:.0%}），"
        f"P90 完工 {full['p90_finish_date']}（承诺 {full['promise_date']}）",
        f"要保住 {full['promise_date']} 且有 {req:.0%} 把握（{n} 抽·同一串抽样）："
        f"最多做 {reach['units_total']:,} 台"
        f"（砍 {full_units - int(reach['units_total']):,} 台，-{100 - reach['ratio'] * 100:.0f}%），"
        f"此时准点概率 {reach['p_on_time']:.0%}、P90 完工 {reach['p90_finish_date']}",
        f"每台怎么砍：{'、'.join(f'{k} {v:,} 台' for k, v in (reach['units_per_model'] or {}).items())}",
        f"这省下的人工中位 ${out['verdict']['labor_released_usd']:,.0f}/批"
        f"（少做=少卖，收益侧不折算，这里只记产能侧省下的钱）",
    ]
    out["claim_guard"] = ("减量是把需求削到窗口里，不是把交期提前 —— 少做的那些台仍然要做，"
                          "只是不赶这个承诺日；要按客户优先级决定砍哪几台，引擎不替厂里挑客户")
    out["method"] = ("同一串抽样上逐档改 targets.units，取'仍有 9 成准点'的最大量；"
                     "并报多做一档（上一档）实测到达的准点概率，所以这个台数自己就成立")
    return out

# 交付做不到时该动什么：四条路（改日期 / 加杠杆 / 修数据 / 减量）各跑一档粗筛，
# 一屏给完"每条路实测换到什么、因此不该拿什么当结论"。细数字看各自的端点，这一格只给判定。
PROMISE_COARSE: List[Dict[str, Any]] = [
    {"name": "现政策（分批开工）", "allow_partial": True},
    {"name": "压瓶颈件提前期→7 天", "allow_partial": True, "expedite_lead_days": 7},
]
CREW_COARSE: Tuple[float, ...] = (0.30, 1.00)
VOLUME_COARSE: Tuple[float, ...] = (1.0, 0.50, 0.20)
BLOCK_ENDPOINTS = {
    "date": "/api/v1/pmc/sim-promise-headroom",
    "crew": "/api/v1/pmc/sim-crew-margin",
    "data": "/api/v1/pmc/sim-data-repair",
    "volume": "/api/v1/pmc/sim-volume-ceiling",
}


async def delivery_blockers(db: AsyncSession, factory_id: str, models: List[str], *,
                            samples: int = 8, seed: int = 20261008,
                            required: float = 0.90, days_of_output: float = 6.0,
                            lead_margin: Optional[float] = None) -> Dict[str, Any]:
    """把"这单为什么做不到、该动什么"收成一次可核对的判定。

    每条路都用同一种粗筛（默认 8 抽 × 少数档），够用来回答"能不能靠它救"，
    不给精细台阶 —— 精细数在各自端点里，读数里把端点路径带上。
    五段都要跑（分布 + 四条路），所以这一格慢；慢是诚实的代价，写在 took_seconds 里。
    """
    import time

    started = time.time()
    req = max(0.50, min(0.99, float(required)))
    base = await schedule_risk(db, factory_id, models, samples=samples, seed=seed)
    if base.get("status") != "ok":
        return {"status": "no_dates", "factory_id": factory_id, "models": models,
                "why": base.get("why"), "paths": [],
                "reading": [f"判定卡没生成：{base.get('why')} —— 连一条完工日分布都抽不出来，"
                            f"四条路就无从比较"]}
    prom = await promise_headroom(db, factory_id, models, samples=samples, seed=seed,
                                  required=req, days_of_output=days_of_output,
                                  lead_margin=lead_margin, policies=PROMISE_COARSE)
    crew = await crew_margin_for_p90(db, factory_id, models, samples=samples, seed=seed,
                                     on_time_required=req, ladder=CREW_COARSE,
                                     days_of_output=days_of_output, lead_margin=lead_margin)
    vol = await volume_ceiling_for_promise(db, factory_id, models, samples=samples, seed=seed,
                                           required=req, ladder=VOLUME_COARSE,
                                           days_of_output=days_of_output, lead_margin=lead_margin)
    rep = await data_repair_experiment(db, factory_id, models, samples=samples, seed=seed,
                                       days_of_output=days_of_output, lead_margin=lead_margin,
                                       only=("purchase_lead_time", "unit_work_hours",
                                             "equipment_availability"))

    def late(value: Any) -> Optional[float]:
        return None if value is None else float(value)

    base_p90_late = late((base.get("percentiles") or [{}])[-1].get("days_late_worst"))         if base.get("percentiles") else None
    for p in (base.get("percentiles") or []):
        if int(p.get("percentile") or 0) == 90:
            base_p90_late = late(p.get("days_late_worst"))
    prom_v = prom.get("verdict") or {}
    crew_rungs = [x for x in (crew.get("ladder_tried") or []) if "p90_days_late" in x]
    crew_top = crew_rungs[-1] if crew_rungs else {}
    vol_rungs = vol.get("ladder_tried") or []
    vol_smallest = min((x for x in vol_rungs if x.get("status") == "ok"),
                       key=lambda x: float(x["ratio"]), default={})
    rep_best = max((x.get("gap_days_narrowed") or 0) for x in (rep.get("repairs") or [])
                   if x.get("status") == "ok") if any(
        x.get("status") == "ok" for x in (rep.get("repairs") or [])) else None

    paths = [
        {"path": "改日期（承诺上限）", "key": "date", "endpoint": BLOCK_ENDPOINTS["date"],
         "moves_days": prom_v.get("days_saved_by_policy"), "moves_unit": "P90 少延天数",
         "can_reach_required": None,
         "measured": (f"有 {req:.0%} 把握最早能报 {prom_v.get('earliest_defensible_promise')}"
                      f"（现承诺 {prom.get('current_promise')}，晚 "
                      f"{prom_v.get('days_later_than_current')} 天；靠"
                      f"『{prom_v.get('policy')}』）" if prom_v else "承诺上限那一格没出数"),
         "therefore_not": "不许拿 P50 当承诺日，也不许把改日期说成引擎批的"},
        {"path": "加人手（杠杆）", "key": "crew", "endpoint": BLOCK_ENDPOINTS["crew"],
         "moves_days": (round(base_p90_late - late(crew_top.get("p90_days_late")), 1)
                        if base_p90_late is not None and crew_top.get("p90_days_late") is not None
                        else None),
         "moves_unit": "P90 少延天数",
         "can_reach_required": (crew.get("verdict") or {}).get("kind") == "found",
         "measured": ((f"加到 {(crew.get('verdict') or {}).get('top_crew_bonus', 0):.0%} 人手"
                       f"（每天多 {_g((crew.get('verdict') or {}).get('top_extra_heads_per_day'))} 人）"
                       f"准点概率 {(crew.get('verdict') or {}).get('top_p_on_time', 0):.0%}")
                      if (crew.get("verdict") or {}).get("kind") == "not_crew_bound" else
                      (f"加 {(crew.get('verdict') or {}).get('crew_bonus', 0):.0%} 人手就到 "
                       f"{(crew.get('verdict') or {}).get('p_on_time_at_level', 0):.0%} 准点"
                       if (crew.get("verdict") or {}).get("kind") == "found" else
                       "现况已达标，不用加人")),
         "therefore_not": "不许把'到岗影响延误'说成'加人能补回到岗'——两件事实测分开"},
        {"path": "修数据（误差带）", "key": "data", "endpoint": BLOCK_ENDPOINTS["data"],
         "moves_days": rep_best, "moves_unit": "毛边收窄天数（不改交期）",
         "can_reach_required": None,
         "measured": ((rep.get("reading") or [None])[1] or "") if len(rep.get("reading") or []) > 1
         else "修数据那一格没出数",
         "therefore_not": "覆盖率≠量过；也不许拿'修数据'去承诺交期提前"},
        {"path": "减量（需求侧）", "key": "volume", "endpoint": BLOCK_ENDPOINTS["volume"],
         "moves_days": (round(base_p90_late - late(vol_smallest.get("p90_days_late")), 1)
                        if base_p90_late is not None
                        and vol_smallest.get("p90_days_late") is not None else None),
         "moves_unit": "P90 少延天数",
         "can_reach_required": (vol.get("verdict") or {}).get("kind") == "found",
         "measured": ((vol.get("reading") or [None])[0] or "") if vol.get("reading") else "减量那一格没出数",
         "therefore_not": "减量是'少做'不是'早交'；砍掉的台数仍然要做，只是不赶这个承诺日"},
    ]

    probe = await _run_one(db, factory_id, (await _risk_setup(
        db, factory_id, models, days_of_output=days_of_output, lead_margin=lead_margin,
        samples=1, seed=seed))["targets"], {"name": "现政策", "allow_partial": True},
        attendance=RISK_ATTENDANCE_LEVELS[0])
    what = {
        "bottleneck_parts": probe.get("bottleneck_parts") or {},
        "arrival_critical_parts": probe.get("arrival_critical_parts") or {},
        "material_arrival_days": probe.get("material_arrival_days") or {},
        "lines_used": probe.get("lines_used") or [],
        "line_declared_units_per_day_max": probe.get("capacity_line_declared_max"),
        "binding": probe.get("binding"),
        "note": ("这两处才是延期的入口：瓶颈件到料日（等料）与所用线的声明台/天（产能上限）。"
                 "四格的实测都落在它们身上时才谈得上改善交付"),
    }
    out = {"status": "ok", "factory_id": factory_id, "models": models, "samples": base["samples"],
           "seed": seed, "on_time_required": req,
           "promise_date": base["promise_date"], "p50": base["percentiles"][1]["finish_date"],
           "p90": base["percentiles"][2]["finish_date"], "p_on_time": base["p_on_time"],
           "rough_days": base["rough_days"], "paths": paths, "what_moves_it": what,
           "took_seconds": round(time.time() - started, 1),
           "reading": [
               f"结论（{len(models)} 台机·{samples} 抽·seed {seed}）：承诺 {base['promise_date']} 做不到 —— "
               f"现政策 P50={base['percentiles'][1]['finish_date']}、"
               f"P90={base['percentiles'][2]['finish_date']}（延 "
               f"{base['percentiles'][2]['days_late_worst']} 天）、准点概率 {base['p_on_time']:.0%}",
               f"能动的是两处：等料（瓶颈件 {'、'.join(_part_names(what['bottleneck_parts'])[:3]) or '未点名'}"
               f"，到料第 {'/'.join(sorted(set(str(v) for v in (what['material_arrival_days'] or {}).values()))[:3]) or '未'} 天）"
               f"与线声明产能（{'、'.join(what['lines_used'][:3]) or '未'} 最多 "
               f"{float(what['line_declared_units_per_day_max'] or 0):g} 台/天，"
               f"binding={what['binding'] or '未明'}）",
           ] + [f"{p['path']}：{p['measured']}"
                + (f"｜{p.get('moves_unit', 'P90 少延天数')} {p['moves_days']:g} 天"
                   if p.get("moves_days") else f"｜{p.get('moves_unit', 'P90 少延天数')} 0 天")
                + f"｜不该做的：{p['therefore_not']}" for p in paths],
           "method": ("每条路在同一串抽样上跑少数几档做粗筛（默认 8 抽）；"
                      "'P90 换到几天'是这条路实测能买到/买不到的天数，不是承诺"),
           "claim_guard": ("这一格只回答'该动哪一处'，不回答'该不该接单'；"
                           "改承诺日、砍台数、花加急费都是企业授权动作，引擎只给数"),
           }
    return out

# 判定卡点名了瓶颈件，接下来现场要问的是"压这个件值几天、花多少钱、那个天数量过没有"。
EXPEDITE_LEAD_DAYS = (5, 7, 10)
# 只有量过的天数才配拿去做加急报价：其它依据标签的"省几天"是拿假设当事实
MEASURED_EVIDENCE = ("measured",)


def _per_model_median(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """逐抽同序配对后按机种取中位延误（组合数只能看整体，归不到件上）。"""
    from statistics import median

    out: Dict[str, Optional[float]] = {}
    for code in sorted({c for r in rows for c in (r.get("days_late_per_model") or {})}):
        vals = [float(r["days_late_per_model"][code]) for r in rows
                if code in (r.get("days_late_per_model") or {})]
        out[code] = round(float(median(vals)), 2) if vals else None
    return out


async def expedite_price_by_part(db: AsyncSession, factory_id: str, models: List[str], *,
                                 samples: int = 12, seed: int = 20261008,
                                 lead_days: Tuple[int, ...] = EXPEDITE_LEAD_DAYS,
                                 days_of_output: float = 6.0,
                                 lead_margin: Optional[float] = None,
                                 policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把瓶颈件压到 D 天，逐档真跑同一串抽样：省几天归到机种与料号，钱按同序配对取中位。

    依据标签决定这条报价能不能用：`measured` 是按请购→到货量过的，可以拿去谈价；
    `unverified_default` 那个天数是铺进台账的默认值 —— 省下来的天数是算出来的假数，
    所以照常给数但标成不可用，并说明先量哪个数。
    """
    pol = policy or {"name": "现政策（分批开工）", "allow_partial": True}
    setup = await _risk_setup(db, factory_id, models, days_of_output=days_of_output,
                              lead_margin=lead_margin, samples=samples, seed=seed)
    n, bands = setup["n"], setup["bands"]
    note = ("抽样与交期分布同一串（同 seed）；每档只加 expedite_lead_days，"
            "到岗/带宽逐抽原样 —— 所以天数差是加急的，不是抽样的。")

    async def sample(one_policy: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        rows = await _sample_rows(db, factory_id, setup["targets"], one_policy, setup["draws"])
        return rows, _risk_summary(rows, factory_id=factory_id, models=models,
                                   policy_name=one_policy.get("name") or "政策", samples=n,
                                   seed=seed, bands=bands, with_date_note=note)

    base_rows, base = await sample(pol)
    if base.get("status") != "ok" or not _per_model_median(base_rows):
        return {"status": "no_dates", "factory_id": factory_id, "models": models, "runs": [],
                "reading": ["加急报价没跑成：这一串抽样里没有一台机推得出完工日 —— "
                            "没有机种级延误就归不出哪个件值钱"]}
    probe = await _run_one(db, factory_id, setup["targets"], pol,
                           attendance=RISK_ATTENDANCE_LEVELS[0])
    parts = probe.get("bottleneck_parts") or {}
    base_pm = _per_model_median(base_rows)

    runs: List[Dict[str, Any]] = []
    for d in lead_days:
        one = {**pol, "name": f"{pol['name']}＋瓶颈件加急到 {d} 天", "expedite_lead_days": int(d)}
        rows, s = await sample(one)
        pm = _per_model_median(rows)
        bought = {c: (round(base_pm[c] - pm[c], 2)
                      if base_pm.get(c) is not None and pm.get(c) is not None else None)
                  for c in pm}
        runs.append({
            "expedite_lead_days": int(d), "status": s.get("status"),
            "p_on_time": s.get("p_on_time"), "p90_finish_date": _p90(s).get("finish_date"),
            "p90_days_late": _p90(s).get("days_late_worst"),
            "p90_days_late_saved": (round(float(_p90(base).get("days_late_worst") or 0)
                                          - float(_p90(s).get("days_late_worst") or 0), 1)
                                    if s.get("status") == "ok" else None),
            "days_bought_per_model": bought,
            "median_expedite_cost_usd": _median([r.get("expedite_cost_usd") for r in rows]),
            "median_extra_expedite_cost_usd": _paired_median_delta(base_rows, rows, "expedite_cost_usd"),
            "binding_seen": sorted({str(r.get("binding")) for r in rows if r.get("binding")}),
        })

    priced = [r for r in runs if r.get("status") == "ok"]
    per_part: List[Dict[str, Any]] = []
    for model, part in (parts or {}).items():
        if not isinstance(part, dict):
            continue
        best = max(priced, key=lambda r: float((r["days_bought_per_model"] or {}).get(model) or -999),
                   default=None) if priced else None
        bought = (best or {}).get("days_bought_per_model", {}).get(model)
        evidence = str(part.get("lead_evidence") or "unknown")
        unit_price = part.get("unit_price")
        usable = evidence in MEASURED_EVIDENCE
        per_part.append({
            "material_code": part.get("material_code"), "bottlenecks_model": model,
            "supplier": part.get("supplier"), "short_units": part.get("short"),
            "ledger_lead_time_days": part.get("ledger_lead_time_days"),
            "effective_lead_time_days": part.get("lead_time_days"),
            "lead_evidence": evidence, "unit_price_usd": unit_price,
            "days_bought": bought,
            "expedite_lead_days": (best or {}).get("expedite_lead_days"),
            # 这一档的钱是整包政策费（台数×压短天数×$0.15/件·天），多个件共用，不是这一个件的价格
            "policy_extra_expedite_cost_usd": (best or {}).get("median_extra_expedite_cost_usd"),
            "cost_scope": "整档加急政策的中位费（该档所有缺口外购件共用），不是这一个件的价格",
            "unit_price_missing": part.get("unit_price") in (None, 0, 0.0, "0"),
            "usable_for_pricing": usable,
            "why": (None if usable else
                    f"依据标签是 {evidence}：这个提前期不是量出来的，省下来的天数是算出来的假数 —— "
                    f"先把这条件的请购→到货逐单量过，再谈加急费"),
            # 加急费公式与单价无关（台数×压短天数×0.15），单价缺失影响的是金额折算那一格，
            # 不许再挂到这一格上（virtual_run 里已有一次错误归因被配对验算推翻）
            "unit_price_affects_this_quote": False,
        })
    per_part.sort(key=lambda x: -(float(x.get("days_bought") or 0)))
    usable_parts = [p for p in per_part if p["usable_for_pricing"]]

    out: Dict[str, Any] = {
        "status": "ok", "factory_id": factory_id, "models": models, "samples": n, "seed": seed,
        "promise_date": base.get("promise_date"), "bands_used": bands,
        "base_days_late_per_model": base_pm,
        "base_p90": {"finish_date": _p90(base).get("finish_date"),
                     "days_late": _p90(base).get("days_late_worst")},
        "runs": runs, "parts": per_part,
        "first_escalation": (usable_parts or [None])[0],
        "usable_quote_count": len(usable_parts),
        "unverified_parts": [str(p.get("material_code")) for p in per_part
                             if not p["usable_for_pricing"]],
        "reading": [
            f"现政策（{n} 抽·同一条分布）：组合 P90 完工 {_p90(base).get('finish_date')}"
            f"（承诺 {base.get('promise_date')}、延 {_p90(base).get('days_late_worst')} 天）、"
            f"准点概率 {base.get('p_on_time'):.0%}；按机种的中位延误："
            + "、".join(f"{k} 延 {v:g} 天" for k, v in base_pm.items()),
            "加急档位：" + "；".join(
                f"压到 {r['expedite_lead_days']} 天 → 组合 P90 少延 "
                f"{r.get('p90_days_late_saved') if r.get('p90_days_late_saved') is not None else '—'} 天、"
                f"准点 {r.get('p_on_time') or 0:.0%}、整包加急费中位 "
                f"${r.get('median_extra_expedite_cost_usd') or 0:,.0f}" for r in priced)
            or "没有一档跑出完工日",
            "按料号：" + "；".join(
                f"{p['material_code']}（{p['lead_evidence']}·台账 {p['ledger_lead_time_days']} 天·"
                f"缺 {p['short_units']:g} 件·{p['supplier'] or '无供应商记录'}）"
                f"压到 {p['expedite_lead_days']} 天省 {p['days_bought']:g} 天"
                + ("｜可用" if p["usable_for_pricing"] else f"｜不可用（{p['why']}）")
                for p in per_part[:6]) or "这一轮没有带瓶颈件的机种（齐套表没缺口行？）",
        ],
        "method": ("逐档 expedite_lead_days 在同一串抽样上真跑，机种级延误按同序配对取中位差；"
                   "加急费＝台数 × 压短天数 × SIM_EXPEDITE_COST_PER_UNIT_DAY(标定 0.15 $/件·天)，"
                   "是该档政策的整包费用、与件单价无关；收益侧与违约罚则未建模"),
        "claim_guard": ("报价只给'省几天/整包加急费多少'，不给'该不该加急'；"
                        "依据不是 measured 的那几条，天数本身没量过 —— 先量数再谈钱，"
                        "否则这份报价是拿默认值当事实。$0.15/件·天 是内置标定不是厂里报价"),
    }
    return out
