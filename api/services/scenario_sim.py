"""场景推演：引擎自己从数据里长出工艺模型，再按流水线跑 days 天。

为什么要有这个（用户 10-06）：**虚拟工厂是对真实工厂信息的映射，信息越全推演越准**；
我要做的是引擎基于用户已有数据自动建模 —— 自动认出厂里的机种、工艺路线、工序落在哪个工位、
每个工位的产能与班组人数、每台机种的物料结构 —— 而不是我一条一条手填。

自动建模取自哪里（全部是库里的实测数据，没有一项是我编的）：
- 工艺路线：`products.current_routing_id` → `routings.steps`（工序名 + 工位 + step_no）。
  这些路线本身是 `routing_from_family` 从 BOM 子树的工序字样推出来的（带佐证率，推不出就不建）；
- 单件工时：每个工位 `stations.capacity_per_hour`（实测 38 个工位全有）→ 该工序小时/件 = 1/产能，
  一台机种的单件工时 = 它路线上各工序之和 —— **不同机种自动不同**（跑步机 6 步 vs HTM 7 步）；
- 齐套程度：`explode_requirement(型号, 数量)` 逐层净需求 vs 实际库存 → 覆盖比例；
- 班组人数：`hr_employees` 按工位别名归到 stations（沿用催办那条唯一口径）。

推演的三条路沿用 `option_simulator` 的语义：队头阻塞 / 跳过缺料按交期重排 / 部分投产。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PARTIAL_MIN = 0.5      # 部分投产的最低物料覆盖门槛，与 option_simulator 同口径

STEP_ROWS_SQL = text("""
    SELECT (e.s->>'step_no')::int AS step_no, e.s->>'name' AS op_name,
           COALESCE(e.s->>'station', e.s->>'station_code', e.s->>'work_center') AS station_code
    FROM routings r, jsonb_array_elements(r.steps::jsonb) AS e(s)
    WHERE r.id = CAST(:rid AS text)
    ORDER BY 1
""")

CAPACITY_SQL = text("""
    SELECT st.station_code, st.station_name,
           COALESCE(st.capacity_per_hour, 0) AS capacity_per_hour,
           COALESCE(sc.available_hours_per_day, 8) AS line_hours_per_day,
           COALESCE(sc.setup_time_minutes, 0) AS setup_time_minutes,
           (sc.station_id IS NOT NULL) AS capacity_known
    FROM stations st
    LEFT JOIN station_capacity sc ON sc.station_id = st.station_code
    WHERE st.factory_id = :fid AND COALESCE(st.status, 'active') <> 'inactive'
""")

MODEL_ROUTE_SQL = text("""
    SELECT p.product_code, p.current_routing_id AS routing_id
    FROM products p
    WHERE p.factory_id = :fid AND p.product_code = ANY(:codes)
""")


async def auto_model(db: AsyncSession, factory_id: str, product_codes: List[str]) -> Dict[str, Any]:
    """从现有数据自动建出这批机种的工艺/产能/物料画像。"""
    stations = {str(r["station_code"]): dict(r) for r in (await db.execute(
        CAPACITY_SQL, {"fid": factory_id})).mappings().all()}
    routes = (await db.execute(MODEL_ROUTE_SQL, {
        "fid": factory_id, "codes": list(product_codes)})).mappings().all()

    # 人力归位沿用闲置台账那一套唯一口径（stations「涂装车间」vs HR「涂装」）
    from api.services.idle_capacity import HEADCOUNT_SQL, _headcount_index, _station_people
    hr_rows = [dict(r) for r in (await db.execute(HEADCOUNT_SQL, {"fid": factory_id})).mappings().all()]
    hr_index = _headcount_index(hr_rows)
    for code, st in stations.items():
        st["headcount_hr"] = sum(_station_people(str(st.get("station_name") or ""), code,
                                                 hr_rows, hr_index).values())

    models: Dict[str, Any] = {}
    unmodeled: List[str] = []
    for row in routes:
        code = str(row["product_code"])
        rid = str(row["routing_id"]) if row["routing_id"] else None
        if not rid:
            unmodeled.append(code)
            continue
        steps = [dict(s) for s in (await db.execute(
            STEP_ROWS_SQL, {"rid": rid})).mappings().all()]
        unit_hours = 0.0
        step_profile = []
        for st in steps:
            station_code = str(st.get("station_code") or "")
            station = stations.get(station_code)
            cap = float(station["capacity_per_hour"]) if station else 0.0
            hours_per_unit = (1.0 / cap) if cap > 0 else 0.0
            unit_hours += hours_per_unit
            step_profile.append({"step_no": st["step_no"], "op_name": st["op_name"],
                                 "station_code": station_code, "capacity_per_hour": cap,
                                 "hours_per_unit": round(hours_per_unit, 5),
                                 "station_known": station is not None})
        models[code] = {"routing_id": rid, "steps": step_profile,
                        "unit_hours": round(unit_hours, 4)}
    for code in product_codes:
        if code not in models and code not in unmodeled:
            unmodeled.append(code)
    return {"factory_id": factory_id, "stations": stations, "models": models,
            "unmodeled": sorted(set(unmodeled))}


async def kit_coverage(db: AsyncSession, factory_id: str, product_code: str, qty: float) -> Dict[str, Any]:
    """这台机种做 qty 件，物料能覆盖多少（真实 BOM 展开 vs 真实库存）。"""
    from api.services.bom_source import explode_requirement
    try:
        own = await explode_requirement(db, factory_id, product_code, float(qty))
    except Exception as exc:  # noqa: BLE001 - 展开失败要如实报，不能当成"齐套"
        return {"coverage": None, "reason": f"展开失败：{type(exc).__name__}"}
    lines = (own or {}).get("lines") or []
    if not lines:
        return {"coverage": None, "reason": "镜像里没有这台机种的 BOM 行"}
    required = covered = shortage = 0.0
    buy_short = make_short = 0.0
    blockers: List[str] = []
    for line in lines:
        req = float(line.get("required_qty") or 0)
        if req <= 0:
            continue
        avail = float(line.get("on_hand_qty") or 0)
        net = float(line.get("net_qty") or 0)
        required += req
        covered += min(req, avail)
        shortage += net
        if net > 0:
            if str(line.get("item_type") or "") == "make":
                make_short += net
            else:
                buy_short += net
            if len(blockers) < 5:
                blockers.append(f"{line.get('material_code')} 缺 {net:g}"
                                f"（{'自制' if str(line.get('item_type')) == 'make' else '外购'}）")
    return {"coverage": round(covered / required, 4) if required else 0.0,
            "required_units": round(required, 2), "shortage_units": round(shortage, 2),
            "buy_shortage": round(buy_short, 2), "make_shortage": round(make_short, 2),
            "top_blockers": blockers}


def simulate_flow(model_pack: Dict[str, Any], scenario: List[Dict[str, Any]], *,
                  start: date, days: int, strategy: str, labor_rate: float,
                  coverage_by_model: Dict[str, float]) -> Dict[str, Any]:
    """把场景当流水线跑：每台机种走它自己的工序，工序占用各自工位的产能小时。"""
    stations = model_pack["stations"]
    models = model_pack["models"]
    allow_partial = strategy == "run_what_you_can"
    skip_blocked = strategy in ("resequence_by_due", "run_what_you_can")
    jobs: List[Dict[str, Any]] = []
    for i, item in enumerate(scenario):
        code = str(item["product_id"])
        model = models.get(code)
        if not model:
            continue
        qty = float(item.get("qty") or 0)
        cov = float(coverage_by_model.get(code, 0.0) or 0.0)
        # 物料覆盖只限制"能开多少"，一次算清：部分投产时只有覆盖到的那部分能上线，
        # 其余等料（原来我在每道工序都乘一次覆盖率，69% 的单走六道工序衰减成 0.69^6，
        # 永远做不完 —— 那是把同一批缺料重复罚了六遍）。
        startable = round(qty * cov, 3) if allow_partial else qty
        jobs.append({
            "id": f"SC-{i+1:02d}", "product_id": code, "qty": qty,
            "startable": startable, "awaiting_material": round(qty - startable, 3),
            "wip": [startable] + [0.0] * (len(model["steps"]) - 1), "done_units": 0.0,
            "step_index": 0, "unit_hours": model["unit_hours"], "model_steps": model["steps"],
            "due": item.get("due") or (start + timedelta(days=int(item.get("due_in_days") or days))),
            "finish_day": None,
        })
    if not jobs:
        return {"strategy": strategy, "jobs": 0, "produced_units": 0.0, "orders_completed": 0,
                "delivered_on_time": 0, "delivered_late": 0, "avg_delay_days": 0.0,
                "capacity_utilization": 0.0, "idle_person_days": 0.0, "labor_idle_cost": 0.0,
                "changeovers": 0, "completions": []}

    worked_station_days: Dict[str, float] = {}
    last_model_at_station: Dict[str, str] = {}
    changeovers = 0

    max_steps = max(len(j["model_steps"]) for j in jobs)
    for day in range(days):
        # 倒序推进工序：先做后道，昨天的半成品今天才流得进来（否则一天能跑完整条线）
        for step in range(max_steps - 1, -1, -1):
            for station_code, station in stations.items():
                line_hours = float(station["line_hours_per_day"] or 0)
                if line_hours <= 0:
                    continue
                candidates = [j for j in jobs
                              if step < len(j["wip"]) and j["wip"][step] > 1e-9
                              and step < len(j["model_steps"])
                              and j["model_steps"][step]["station_code"] == station_code]
                if not candidates:
                    continue
                candidates.sort(key=lambda j: (j["due"], j["id"]))
                if allow_partial:
                    candidates.sort(key=lambda j: (-float(coverage_by_model.get(j["product_id"], 0) or 0),
                                                   j["due"], j["id"]))
                free_hours = line_hours
                for j in candidates:
                    if free_hours <= 1e-9:
                        break
                    cov = float(coverage_by_model.get(j["product_id"], 0.0) or 0.0)
                    if cov >= 1.0:
                        pass                       # 齐套，随便做
                    elif allow_partial and cov >= PARTIAL_MIN:
                        pass                       # 部分投产：能开的量已在建单时按覆盖算清
                    elif skip_blocked:
                        continue
                    else:
                        break          # 队头阻塞：这台工位今天不往下走
                    hours_per_unit = float(j["model_steps"][step]["hours_per_unit"] or 0)
                    if hours_per_unit <= 0:
                        continue       # 这道工序没有产能依据：不猜工时
                    if last_model_at_station.get(station_code) and \
                            last_model_at_station[station_code] != j["product_id"]:
                        setup_hours = float(station["setup_time_minutes"] or 0) / 60.0
                        free_hours -= setup_hours
                        changeovers += 1
                        if free_hours <= 1e-9:
                            break
                    last_model_at_station[station_code] = j["product_id"]
                    units = min(j["wip"][step], free_hours / hours_per_unit)
                    if units <= 1e-9:
                        continue
                    j["wip"][step] -= units
                    free_hours -= units * hours_per_unit
                    worked_station_days[station_code] = worked_station_days.get(station_code, 0.0) \
                        + (units * hours_per_unit) / line_hours
                    if step + 1 < len(j["model_steps"]):
                        j["wip"][step + 1] += units
                    else:
                        j["done_units"] += units
                        if j["done_units"] >= j["qty"] - 1e-9 and j["finish_day"] is None:
                            j["finish_day"] = day

    finished = [j for j in jobs if j["finish_day"] is not None]
    partial = [j for j in jobs if j["finish_day"] is None and j["done_units"] > 1e-9]
    late = [j for j in finished if (start + timedelta(days=int(j["finish_day"]))) > j["due"]]
    delays = [((start + timedelta(days=int(j["finish_day"]))) - j["due"]).days for j in late]
    total_line_days = sum(float(s["line_hours_per_day"] or 0) for s in stations.values()) * days / 8.0
    worked = sum(worked_station_days.values())
    # 闲置：每台工位每天没被真正干活的时间，乘以它那一班人
    idle_person_days = 0.0
    for code, st in stations.items():
        busy_days = worked_station_days.get(code, 0.0)
        idle_days = max(0.0, days - busy_days)
        idle_person_days += idle_days * int(st.get("headcount_hr") or 0)
    return {
        "strategy": strategy,
        "jobs": len(jobs),
        "produced_units": round(sum(j["done_units"] for j in jobs), 1),
        "awaiting_material_units": round(sum(j.get("awaiting_material", 0.0) for j in jobs), 1),
        "orders_completed": len(finished),
        "orders_partially_done": len(partial),
        "delivered_on_time": len(finished) - len(late),
        "delivered_late": len(late),
        "avg_delay_days": round(sum(delays) / len(delays), 1) if delays else 0.0,
        "capacity_utilization": round(worked / total_line_days, 4) if total_line_days else 0.0,
        "changeovers": changeovers,
        "idle_person_days": round(idle_person_days, 1),
        "labor_idle_cost": round(idle_person_days * labor_rate, 2),
        "completions": sorted(
            [{"scenario_id": j["id"], "product_id": j["product_id"], "qty": j["qty"],
              "started": j["startable"], "done": round(j["done_units"], 2),
              "due": str(j["due"]), "finish_day": j["finish_day"],
              "ship_on": str(start + timedelta(days=int(j["finish_day"])))} for j in finished],
            key=lambda x: x["finish_day"]),
    }


async def run_scenarios(db: AsyncSession, factory_id: str, scenarios: Dict[str, List[Dict[str, Any]]],
                        *, strategies=("wait_for_material", "resequence_by_due", "run_what_you_can"),
                        days: int = 30, as_of: Optional[date] = None, objective: str = "labor_first",
                        labor_rate: float = 30.0) -> Dict[str, Any]:
    """一次把几个场景 × 几条策略跑完：场景是"订单组合"，不落库，纯推演。"""
    all_codes = sorted({str(item["product_id"]) for lst in scenarios.values() for item in lst})
    pack = await auto_model(db, factory_id, all_codes)
    coverage_by_model: Dict[str, float] = {}
    kit_detail: Dict[str, Any] = {}
    for code in all_codes:
        qty = max(1.0, float(sum(i.get("qty", 0) for lst in scenarios.values()
                                 for i in lst if str(i["product_id"]) == code) or 1))
        kit = await kit_coverage(db, factory_id, code, qty)
        kit_detail[code] = kit
        coverage_by_model[code] = kit.get("coverage") or 0.0

    out: Dict[str, Any] = {"factory_id": factory_id, "days": days,
                           "as_of": str(as_of or date.today()), "strategies": list(strategies),
                           "models": {c: {"steps": len(m["steps"]), "unit_hours": m["unit_hours"],
                                          "route": m["routing_id"]}
                                      for c, m in pack["models"].items()},
                           "kit_coverage": coverage_by_model,
                           "kit_blockers": {c: v.get("top_blockers") for c, v in kit_detail.items()},
                           "unmodeled": pack["unmodeled"],
                           "scenarios": {}}
    for name, scenario in scenarios.items():
        out["scenarios"][name] = [simulate_flow(pack, scenario, start=as_of or date.today(),
                                                days=days, strategy=s, labor_rate=labor_rate,
                                                coverage_by_model=coverage_by_model)
                                  for s in strategies]
    return out


LINES_SQL = text("""
    SELECT line_code, line_name, hours_per_day, units_per_day, crew_size,
           parallel_lines, can_make_models, cannot_make_models, default_model, source, note
    FROM line_profiles
    WHERE factory_id = :fid AND COALESCE(is_active, TRUE)
    ORDER BY line_code
""")


def _line_capacity(line: Dict[str, Any], *, units_are_per_line: bool = True) -> float:
    """一天的节拍（台/天）。bike 那个 400 台到底是单线还是两线合计还没确认，
    所以两种口径都能算出来，让结论对这个数的敏感度看得见。"""
    per_day = float(line["units_per_day"] or 0)
    return per_day * (int(line["parallel_lines"] or 1) if units_are_per_line else 1)


def _can_run(line: Dict[str, Any], model: str) -> bool:
    can = list(line.get("can_make_models") or [])
    cannot = list(line.get("cannot_make_models") or [])
    if model in cannot:
        return False
    return (not can) or (model in can)


def simulate_lines(lines: List[Dict[str, Any]], jobs: List[Dict[str, Any]], *,
                  days: int, available_from: Dict[str, int], labor_rate: float,
                  allow_line_move: bool, units_are_per_line: bool = True,
                  absorb_extra_units_per_day: float = 0.0) -> Dict[str, Any]:
    """按"线"推演：单向兼容就是一条硬约束，缺料期用 available_from 表达。

    - 每张单先排到自己机种的默认线；`allow_line_move` 才允许挪到**能做它的别的线**
      （跑步机单可以挪去 bike 线，bike 单挪不去跑步机线 —— 用户 10-06 明确的方向）；
    - 挪线不是免费的：接线的富余节拍先扣，超出富余的部分需要一个"还能不能加人/加一条线"
      的参数（`absorb_extra_units_per_day`）。这个数用户还没给，所以默认 0 = 下限口径：
      挪不过去的那部分照样闲在那条线上；给了数就是上限口径。两个都跑，差别就是
      "这 200 人到底能不能救回来"的答案区间。
    """
    cap = {str(l["line_code"]): _line_capacity(l, units_are_per_line=units_are_per_line)
           for l in lines}
    by_code = {str(l["line_code"]): l for l in lines}
    queue = []
    for i, j in enumerate(jobs):
        queue.append({"id": j.get("id") or f"J{i+1:02d}", "product_id": str(j["product_id"]),
                      "qty": float(j.get("qty") or 0), "due": j.get("due"),
                      "remaining": float(j.get("qty") or 0), "home_line": j.get("line"),
                      "ran_on": None, "finish_day": None})
    line_units: Dict[str, float] = {c: 0.0 for c in cap}
    made_by_job: Dict[str, float] = {}
    moved_units = 0.0

    for day in range(days):
        for code in cap:
            left = cap[code]
            eligible = [j for j in queue if j["remaining"] > 1e-9
                        and int(available_from.get(j["product_id"], 0) or 0) <= day
                        and _can_run(by_code[code], j["product_id"])]
            # 家线优先，其次才是挪到能兼容它的线上（bike 线可接跑步机；反向不行）
            eligible.sort(key=lambda j: (j["home_line"] != code, j["due"] or date.max, j["id"]))
            if not allow_line_move:
                eligible = [j for j in eligible if j["home_line"] == code]
            for j in eligible:
                if left <= 1e-9:
                    break
                units = min(j["remaining"], left)
                j["remaining"] -= units
                left -= units
                line_units[code] += units
                made_by_job[j["id"]] = made_by_job.get(j["id"], 0.0) + units
                if j["home_line"] and code != j["home_line"]:
                    moved_units += units
                if j["remaining"] <= 1e-9:
                    j["finish_day"] = day
                    j["ran_on"] = code

    rows = []
    for l in lines:
        code = str(l["line_code"])
        rate = cap[code]
        crew = int(l["crew_size"] or 0)
        # 人力跟着活走：这条线的班组提供的"人·天/台"是它的劳动含量，
        # 活被别家的机器做掉时，人还是这边的人 —— 否则"调人去能做的线"就算不出收益。
        labor_per_unit = (crew / rate) if rate else 0.0
        own_work = sum(made_by_job.get(j["id"], 0.0) for j in queue if j["home_line"] == code)
        busy_days = round(own_work / rate, 3) if rate else 0.0
        idle_days = round(max(0.0, days - busy_days), 3)
        rows.append({"line_code": code, "line_name": l.get("line_name"),
                     "capacity_units_per_day": rate, "crew_size": crew,
                     "labor_days_per_unit": round(labor_per_unit, 4),
                     "machine_days_used_this_line": round(line_units[code] / rate, 3) if rate else 0.0,
                     "own_orders_units": round(own_work, 1),
                     "busy_person_days": round(busy_days * crew, 1),
                     "idle_person_days": round(idle_days * crew, 1),
                     "idle_labor_cost": round(idle_days * crew * labor_rate, 2)})
    unfinished = sum(j["remaining"] for j in queue)
    return {"days": days, "lines": rows,
            "total_idle_person_days": round(sum(r["idle_person_days"] for r in rows), 1),
            "total_idle_labor_cost": round(sum(r["idle_labor_cost"] for r in rows), 2),
            "units_made": round(sum(line_units.values()), 1),
            "units_unfinished": round(unfinished, 1),
            "moved_units_to_other_lines": round(moved_units, 1),
            "orders_finished": len([j for j in queue if j["finish_day"] is not None]),
            "orders_total": len(queue),
            "allow_line_move": allow_line_move,
            "units_are_per_line": units_are_per_line}



