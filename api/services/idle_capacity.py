"""闲置产能台账：把"这条线今天有几个人、能干活的时间有多少、账面排了多少、真能干多少"算成一张表。

为什么先算这个而不是先算钱：成本判断的形状是这样的 ——
  缺料 3 天 + 这个工艺没别的单可做 → 人力是**在岗即付的硬支出**，所以这 3 天是确定的损失；
  设备全款的话停着只是折旧，不是现金出去，所以"要不要为了喂机器加班"和"要不要为了人不空转调线"
  是两套完全不同的决定。
工资单价、设备原值/是否贷款这些数**库里没有**（实测：`hr_employees` 1,747 人只有部门/工位/岗位/
班次/技能，没有任何薪资列；`equipment` 有 purchase_date/warranty 但没有原值），
所以这里只算到"人·小时"这一层，钱由 cost_parameters 一旦有人填就自动乘上去（缺参数就报缺，不编数）。

口径（三条都跟着"不停产"这个现实走）：
- `scheduled_hours`：这一版生效方案落在该工位的工时；
- `blocked_hours`：这些工时里，属于**缺料单**的部分 —— 账面排满了，实际开不了工，
  这正是现在系统最容易骗自己的地方（用开不了工的活占住产能，看上去很忙）；
- `runnable_hours` = scheduled − blocked：真能干的；
- `idle_hours` = available − runnable：**真闲置**；
- `fillable_orders` / `fillable_steps`：该工位是首道工序、且按物料已经齐套、却**根本没被排进这一版**的单 ——
  也就是说闲置不是没活干，是活没排过来。这一列直接给出"能不能就地填满"的答案。

只读，不写任何状态。人力归位沿用催办那套工位别名口径（stations 写"涂装车间"、HR 写"涂装"），
不再另立一份映射。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.material_followup import _station_aliases

# 一版生效方案里，各工位的排定工时；缺料单的那部分单独标出来（material_ready=false）
STATION_HOURS_SQL = text("""
    WITH cur AS (
        SELECT s.id
        FROM aps_schedules s
        WHERE s.factory_id = :fid AND s.is_current = TRUE
        ORDER BY s.created_at DESC
        LIMIT 1
    ),
    -- 窗口用这一版方案自己的时间跨度：按"今天"切一刀会把整版方案都算成 0 工时，
    -- 于是每个工位都"全天空转"，那是把口径 bug 报成经营结论（第一版就是这么错的）。
    win AS (
        SELECT date_trunc('day', MIN(t.planned_start)) AS d0,
               date_trunc('day', MAX(t.planned_end)) + INTERVAL '1 day' AS d1,
               GREATEST(1, CEIL(EXTRACT(EPOCH FROM (MAX(t.planned_end) - MIN(t.planned_start))) / 86400.0)::int)
                   AS days
        FROM aps_schedule_tasks t
        JOIN cur c ON c.id = t.schedule_id
        WHERE t.planned_start IS NOT NULL AND t.planned_end IS NOT NULL
    ),
    t AS (
        SELECT st.station_code,
               t.work_order_id,
               COALESCE(t.material_ready, TRUE) AS ready,
               EXTRACT(EPOCH FROM GREATEST(
                   LEAST(t.planned_end, (SELECT d1 FROM win)) -
                   GREATEST(t.planned_start, (SELECT d0 FROM win)),
                   INTERVAL '0 second')) / 3600.0 AS hours
        FROM aps_schedule_tasks t
        JOIN cur c ON c.id = t.schedule_id
        LEFT JOIN stations st ON st.station_code = t.station_id AND st.factory_id = :fid
        WHERE t.planned_start IS NOT NULL AND t.planned_end IS NOT NULL
    )
    SELECT st.id AS station_id, st.station_code, st.station_name, st.workshop_id,
           (SELECT days FROM win) AS window_days,
           COALESCE(sc.available_hours_per_day, 8) * (SELECT days FROM win) AS available_hours,
           (sc.station_id IS NOT NULL) AS capacity_known,
           sc.available_hours_per_day AS capacity_hours_per_day,
           COALESCE(sc.efficiency_rate, 1) AS efficiency_rate,
           COALESCE(sc.setup_time_minutes, 0) AS setup_time_minutes,
           sc.required_skills AS required_skills,
           COALESCE(SUM(t.hours), 0) AS scheduled_hours,
           COALESCE(SUM(t.hours) FILTER (WHERE NOT t.ready), 0) AS blocked_hours,
           count(DISTINCT t.work_order_id) AS scheduled_orders
    FROM stations st
    LEFT JOIN t ON t.station_code = st.station_code
    -- station_capacity.station_id 存的是**工位编码**（实测 38 行全是 'ST-ASSY-LINE' 这种，
    -- 而 stations.id 是 uuid）：按 id 关联一行都匹配不上，会静默退回默认 8 小时/天，
    -- 把 120 小时的装配线也算成 8 小时 —— 这版报表第一遍就是这么错的。
    LEFT JOIN station_capacity sc ON sc.station_id = st.station_code
    WHERE st.factory_id = :fid AND COALESCE(st.status, 'active') <> 'inactive'
    GROUP BY st.id, st.station_code, st.station_name, st.workshop_id,
             sc.station_id, sc.available_hours_per_day, sc.efficiency_rate, sc.setup_time_minutes,
             sc.required_skills
    ORDER BY (COALESCE(SUM(t.hours) FILTER (WHERE NOT t.ready), 0)) DESC, st.station_code
""")

# 齐套但没排进这一版的单：它们的首道工序落在哪个工位（= 闲置能不能就地填掉）
FILLABLE_SQL = text("""
    WITH cur AS (
        SELECT s.id FROM aps_schedules s
        WHERE s.factory_id = :fid AND s.is_current = TRUE
        ORDER BY s.created_at DESC LIMIT 1
    )
    SELECT wo.id, wo.work_order_code, wo.planned_qty,
           COALESCE(wo.routing_id, p.current_routing_id) AS routing_id,
           wo.routing_template_id
    FROM work_orders wo
    LEFT JOIN products p ON p.product_code = wo.product_id
    WHERE wo.factory_id = :fid
      AND wo.wo_type IN ('master', 'component')
      AND wo.status = 'pending'
      -- 有依据：至少一行真有领料需求
      AND EXISTS (SELECT 1 FROM work_order_materials m
                  WHERE m.work_order_id = wo.id AND COALESCE(m.required_qty, 0) > 0)
      -- 齐套：没有任何缺口
      AND NOT EXISTS (SELECT 1 FROM work_order_materials m
                      WHERE m.work_order_id = wo.id AND COALESCE(m.shortage_qty, 0) > 0)
      -- 且有工艺（不然排不了）
      AND COALESCE(wo.routing_id, p.current_routing_id, wo.routing_template_id) IS NOT NULL
      -- 没进这一版
      AND NOT EXISTS (SELECT 1 FROM aps_schedule_tasks t
                      WHERE t.schedule_id = (SELECT id FROM cur) AND t.work_order_id = wo.id)
""")

# 路线有两种存法：模板看 routing_template_steps（列是 seq/work_center/standard_hours/is_parallel），
# 旧版看 routings.steps 的 JSON（station / step_no）。两边都要能读，否则"这活归哪个工位"就查不出来。
FIRST_STEP_SQL = text("""
    SELECT step_seq, station_code, standard_hours, is_parallel FROM (
        SELECT st.seq AS step_seq, st.work_center AS station_code,
               st.standard_hours::numeric AS standard_hours, COALESCE(st.is_parallel, FALSE) AS is_parallel, 1 AS src
        FROM routing_template_steps st
        WHERE st.template_id::text = CAST(:rid AS text)
        UNION ALL
        SELECT (e.ordinality)::int,
               COALESCE(e.s->>'station_code', e.s->>'station', e.s->>'work_center'),
               (e.s->>'standard_hours')::numeric, FALSE, 2
        FROM routings r, jsonb_array_elements(r.steps::jsonb) WITH ORDINALITY AS e(s, ordinality)
        WHERE r.id = :rid
    ) x ORDER BY src, step_seq LIMIT 1
""")

ROUTE_HOURS_SQL = text("""
    SELECT COALESCE(SUM(standard_hours), 0) AS hours_per_unit, count(*) AS steps FROM (
        SELECT st.standard_hours::numeric AS standard_hours FROM routing_template_steps st WHERE st.template_id::text = CAST(:rid AS text)
        UNION ALL
        SELECT (e.s->>'standard_hours')::numeric
        FROM routings r, jsonb_array_elements(r.steps::jsonb) AS e(s) WHERE r.id = :rid
    ) x
""")

HEADCOUNT_SQL = text("""
    SELECT station, position, count(*) AS people
    FROM hr_employees
    WHERE factory_id = :fid AND status = 'active'
    GROUP BY 1, 2
""")


def _headcount_index(rows: List[Any]) -> Dict[str, List[str]]:
    """HR 里"工位"的写法归一成别名 -> 原始写法集合。

    HR 写"涂装"、stations 写"涂装车间"是两边的叫法差异，不是两个工位；
    别名索引只用来**找到原始行**，人数永远按原始行加一次，避免多个别名命中同一行导致重复计数。
    """
    index: Dict[str, List[str]] = {}
    for r in rows:
        raw = str(r["station"] or "")
        for alias in _station_aliases(raw):
            bucket = index.setdefault(alias, [])
            if raw not in bucket:
                bucket.append(raw)
    return index


def _station_people(name: str, code: str, rows: List[Any],
                    index: Dict[str, List[str]]) -> Dict[str, int]:
    """该工位上在岗的人按岗位汇总（HR 侧）。匹配不到就返回空 —— 不猜人数。"""
    wanted = set()
    for key in _station_aliases(name or "") + _station_aliases(code or ""):
        wanted.update(index.get(key, []))
    out: Dict[str, int] = {}
    if not wanted:
        return out
    for r in rows:
        if str(r["station"] or "") in wanted:
            role = str(r["position"] or "(未写岗位)")
            out[role] = out.get(role, 0) + int(r["people"] or 0)
    return out


async def idle_capacity_report(
    db: AsyncSession, factory_id: str, *, as_of: date | None = None,
    objective: str | None = None,
) -> Dict[str, Any]:
    """按仿真日历算一遍当天：各工位排了多少、其中多少开不了工、真闲置多少、能不能就地填满。"""
    if as_of is None:
        try:
            from api.services.virtual_factory_clock import get_clock
            now = await get_clock().now(factory_id)
            clock_basis = "sim_clock"
        except Exception:  # noqa: BLE001
            now, clock_basis = datetime.utcnow(), "real_date"
        as_of = (now or datetime.utcnow()).date()
    else:
        # 调用方指定了日期：依据要跟着结果走，否则读数的人会以为这是仿真时钟算出来的
        clock_basis = "caller_supplied"

    stations = (await db.execute(STATION_HOURS_SQL, {"fid": factory_id, "as_of": as_of})).mappings().all()
    hr = [dict(r) for r in (await db.execute(
        HEADCOUNT_SQL, {"fid": factory_id})).mappings().all()]
    hr_index = _headcount_index(hr)
    fillable = (await db.execute(FILLABLE_SQL, {"fid": factory_id})).mappings().all()

    # 齐套未排的单按"首道工序工位"归堆：闲置要能被填掉才算得了数
    fill_by_station: Dict[str, Dict[str, Any]] = {}
    for f in fillable:
        rid = str(f["routing_id"] or f["routing_template_id"] or "")
        if not rid:
            continue
        first = (await db.execute(FIRST_STEP_SQL, {"rid": rid})).mappings().first()
        code = str(first["station_code"]) if first and first["station_code"] else "(首道没写工位)"
        hours = (await db.execute(ROUTE_HOURS_SQL, {"rid": rid})).mappings().first()
        qty = int(f["planned_qty"] or 0)
        # 需要的人时 = 路线标准工时/件 × 数量（模板没写标准工时就是 0，如实报，不按经验值猜）
        need_hours = float((hours or {}).get("hours_per_unit") or 0) * qty
        bucket = fill_by_station.setdefault(code, {
            "orders": 0, "qty": 0, "need_hours": 0.0, "steps": 0, "samples": []})
        bucket["orders"] += 1
        bucket["qty"] += qty
        bucket["need_hours"] = round(bucket["need_hours"] + need_hours, 1)
        bucket["steps"] = max(bucket["steps"], int((first or {}).get("step_seq") or 0))
        if len(bucket["samples"]) < 3:
            bucket["samples"].append(str(f["work_order_code"]))

    lines: List[Dict[str, Any]] = []
    window_days = int((stations[0]["window_days"] if stations else 1) or 1)
    for s in stations:
        scheduled = round(float(s["scheduled_hours"] or 0), 2)
        blocked = round(float(s["blocked_hours"] or 0), 2)
        available = round(float(s["available_hours"] or 0), 2)
        runnable = round(max(0.0, scheduled - blocked), 2)
        idle = round(max(0.0, available - runnable), 2)
        people = _station_people(str(s["station_name"] or ""), str(s["station_code"] or ""), hr, hr_index)
        headcount = sum(people.values())
        fill = fill_by_station.get(str(s["station_code"]), None)
        labor_available = round(headcount * 8.0 * window_days, 1)
        idle_ratio = round(idle / available, 4) if available > 0 else 0.0
        lines.append({
            "station_code": s["station_code"],
            "station_name": s["station_name"],
            "headcount_hr": headcount,
            "positions_by_role": people,
            "available_hours": available,
            "scheduled_hours": scheduled,
            "blocked_hours": blocked,
            "runnable_hours": runnable,
            "idle_hours": idle,
            # 人·小时是按"该工位在岗人数 × 8h × 天数"折算的估算：一条线几条、几班倒、几人同做一道工序
            # 库里没有（station_capacity 只有线小时，HR 只有 shift 字样），所以这是**带假设的数**，
            # 不是账。假设随结果一起报出去，别让人把它读成财务口径。
            "labor_hours_available_estimated": labor_available,
            # 闲置人数占比 = 该工位净闲置线小时 / 可用线小时（线小时本身已含多线/多班并行），
            # 再乘在岗人时 —— 直接 idle×人数会超过可用工时（第一版就超了一倍，那是重复计数不是闲置）。
            "idle_ratio": idle_ratio,
            "idle_person_hours_estimated": round(labor_available * idle_ratio, 1),
            "scheduled_orders": int(s["scheduled_orders"] or 0),
            "fillable_kitted_orders": (fill or {}).get("orders", 0),
            "fillable_need_hours": (fill or {}).get("need_hours", 0.0),
            "fillable_samples": (fill or {}).get("samples", []),
            "setup_time_minutes": float(s["setup_time_minutes"] or 0),
            # 产能参数是不是真的来自表：8 小时/天只是兜底，被兜底的工位要能看出来
            "capacity_basis": "station_capacity" if s["capacity_known"] else "默认8小时/天(缺参数)",
            "required_skills": str(s["required_skills"]) if s["required_skills"] else None,
        })

    tot_idle = round(sum(l["idle_hours"] for l in lines), 2)
    tot_blocked = round(sum(l["blocked_hours"] for l in lines), 2)
    tot_person_idle = round(sum(l["idle_person_hours_estimated"] for l in lines), 1)
    tot_labor_available = round(sum(l["labor_hours_available_estimated"] for l in lines), 1)
    fillable_total = sum(l["fillable_kitted_orders"] for l in lines)
    out = {
        "factory_id": factory_id,
        "as_of": str(as_of),
        "clock_basis": clock_basis,
        "plan_window_days": window_days,
        "stations": len(lines),
        "idle_hours": tot_idle,
        "blocked_hours_on_paper": tot_blocked,
        "idle_person_hours_estimated": tot_person_idle,
        "labor_hours_available_estimated": tot_labor_available,
        "person_hour_basis": ("估算：在岗人数 × 8 小时 × 方案天数 × 净闲置线小时占比。库里没有"
                              "「一条线几人 / 几班倒」的换算比（HR 只有 shift 字样：常日班/白班/"
                              "夜班/两班倒），所以这不是财务数，是给成本模型用的量。"),
        "kitted_unscheduled_orders_fillable": fillable_total,
        "cost_note": ("单价库里没有（hr_employees 1,747 人 0 个薪资列、equipment 无原值），"
                      "下面这些钱是**内置默认标定**乘出来的，每项的 basis/来源在 cost_basis 里，"
                      "填了 cost_parameters 就换掉对应项。"),
        "capacity_missing_stations": sum(1 for l in lines
                                         if l["capacity_basis"] != "station_capacity"),
        "top_idle": sorted(lines, key=lambda l: -l["idle_person_hours_estimated"])[:10],
    }

    # 钱的部分：默认标定 × 上面这些量。换目标（人力优先/交期优先/总成本）就换排序，
    # 参数被 cost_parameters 覆盖过就在 basis 里显示 override + 来源。
    from api.services.cost_model import (RATE_OVERRIDES_SQL, cost_lines, reallocation_options,
                                         resolve_rates)

    overrides = [dict(x) for x in (await db.execute(
        RATE_OVERRIDES_SQL, {"fid": factory_id})).mappings().all()]
    rates = resolve_rates(overrides, objective=objective)
    costed = cost_lines(lines, rates)
    days = max(1, window_days)
    out = {
        **out,
        "currency": rates["currency"],
        "objective": rates["objective"],
        "objective_label": rates["objective_label"],
        "cost_basis": {code: {k: v for k, v in spec.items() if k in ("amount", "unit", "hard", "basis", "source")}
                       for code, spec in rates["rates"].items()},
        "cost_totals": {
            "labor_idle_cost_window": round(sum(c["labor_idle_cost"] for c in costed), 2),
            "labor_idle_cost_per_day": round(sum(c["labor_idle_cost"] for c in costed) / days, 2),
            "equipment_idle_depreciation_window": round(
                sum(c["equipment_idle_depreciation"] for c in costed), 2),
            "equipment_idle_hard_window": round(sum(c["equipment_idle_hard"] for c in costed), 2),
            "hard_cash_cost_window": round(sum(c["hard_cost_total"] for c in costed), 2),
            "energy_avoided_by_idle_window": round(
                sum(c["energy_avoided_by_idle"] for c in costed), 2),
        },
        "cost_by_station": sorted(costed, key=lambda c: -c["labor_idle_cost"])[:10],
        "reallocation_options": reallocation_options(costed, lines, rates),
    }
    return out
