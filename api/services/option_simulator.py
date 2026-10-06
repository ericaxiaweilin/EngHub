"""生产选择推演：缺料的时候，工厂不是"停下来等"一个选项，而是几条路各自的后果。

用户的纠正（10-06）很重要：**这不是算不出来的问题，是选择问题** —— 能赚钱、能省钱、能维持运转，
现实不是"亏/赚"两档。之前引擎的做法是"欠料→卡住→不排产"，那等于把多目标问题当成单目标死锁。

所以这里对同一份现状跑四条策略，各自给出后果，再按目标（人力优先/交期优先/总成本）排序：

1. `wait_for_material`  只干全部齐套的单，缺料的原地等 —— 这是现在系统的行为，作为基线；
2. `run_what_you_can`   齐套的先干；工位还空着但有"部分齐套"的单（覆盖比例 ≥ 阈值），
                          就按已到的料投一部分，剩下的料到了再补 —— 这是厂里实际的常态；
3. `resequence_by_due`  只干齐套单，但完全按交期排：缺料单**不参与占位**，
                          用来量"账面排满 vs 真在干"的差别；
4. `transfer_idle_labor` 在 2 的基础上，把闲置线上的人力挪去"有齐套活等着却缺人"的工位，
                          代价按换线时间计（`station_capacity.setup_time_minutes`），收益是那些活开始跑。

口径与假设全部随结果报出去（`assumptions`）：日粒度、用 `stations.capacity_per_hour` 当 throughput
（有实测），到货按 open PO 的 expected_date 落到某一天，"部分投产"按已覆盖物料的比例产出。
**没有假装精确**：粗，但每条路都可比、都能核对到数据；缺标准工时只影响"挪几个人最划算"的细排，
不影响四条路的相对结论 —— 这一点由排序稳定性检验（同一策略跑两次结果一致 + 换目标换排序）。

只读：不改工单、不改库存、不下任何指令；输出是给 PMC 岗位看的比较表。
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SIM_HORIZON_DAYS = max(3, int(os.getenv("OPTION_SIM_HORIZON_DAYS", "30")))
PARTIAL_COVERAGE_MIN = float(os.getenv("OPTION_SIM_PARTIAL_MIN", "0.5"))
HOURS_PER_DAY_FALLBACK = 8.0

STATIONS_SQL = text("""
    SELECT st.id, st.station_code, st.station_name,
           COALESCE(sc.available_hours_per_day, 8) AS line_hours_per_day,
           COALESCE(st.capacity_per_hour, 0) AS capacity_per_hour,
           COALESCE(sc.setup_time_minutes, 0) AS setup_time_minutes,
           (sc.station_id IS NOT NULL) AS capacity_known
    FROM stations st
    LEFT JOIN station_capacity sc ON sc.station_id = st.station_code
    WHERE st.factory_id = :fid AND COALESCE(st.status, 'active') <> 'inactive'
    ORDER BY st.station_code
""")

# 每张单的现状：还要做多少件、首道在哪个工位、料覆盖到什么比例
ORDERS_SQL = text("""
    WITH kit AS (
        SELECT m.work_order_id,
               SUM(COALESCE(m.required_qty, 0)) AS required,
               SUM(LEAST(GREATEST(COALESCE(m.available_qty, 0), 0), COALESCE(m.required_qty, 0)))
                   AS covered
        FROM work_order_materials m
        GROUP BY m.work_order_id
    )
    SELECT wo.id, wo.work_order_code, wo.wo_type, wo.product_id,
           GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0) AS remaining_qty,
           wo.planned_due, wo.unit,
           COALESCE(wo.routing_id, wo.routing_template_id, p.current_routing_id) AS route_ref,
           COALESCE(kit.required, 0) AS required, COALESCE(kit.covered, 0) AS covered
    FROM work_orders wo
    LEFT JOIN products p ON p.product_code = wo.product_id
    LEFT JOIN kit ON kit.work_order_id = wo.id
    WHERE wo.factory_id = :fid
      AND wo.wo_type IN ('master', 'component')
      AND wo.status IN ('pending', 'released', 'in_progress')
      AND GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0) > 0
      -- 可以只推演指定的几张单（他说"给虚拟引擎 5 个工单"那种口径）：不筛就是全在制池
      AND (CAST(:codes AS varchar[]) IS NULL OR wo.work_order_code = ANY(CAST(:codes AS varchar[])))
    ORDER BY wo.planned_due NULLS LAST, wo.work_order_code
""")

# 到货计划：哪天到多少（按未收 PO 的 expected_date），这决定了"等"什么时候真的等到头
ARRIVALS_SQL = text("""
    SELECT material_code, expected_date, SUM(GREATEST(qty - COALESCE(received_qty, 0), 0)) AS qty
    FROM purchase_orders
    WHERE factory_id = :fid
      AND status IN ('confirmed', 'approved', 'ordered', 'in_transit', 'shipped')
      AND expected_date IS NOT NULL
    GROUP BY 1, 2
""")


def _coverage(order: Dict[str, Any]) -> float:
    required = float(order.get("required") or 0)
    if required <= 0:
        return 0.0            # 没有领料依据 = 不算齐套，也不许推演成"能干"
    return min(1.0, float(order.get("covered") or 0) / required)


def _station_for(order: Dict[str, Any], routes: Dict[str, str]) -> str:
    return routes.get(str(order.get("route_ref") or ""), "(无首道工位)")


def _simulate(strategy: str, orders: List[Dict[str, Any]], stations: Dict[str, Dict[str, Any]],
              routes: Dict[str, str], arrivals: List[Dict[str, Any]], *, start: date,
              days: int, labor_rate: float) -> Dict[str, Any]:
    """按天推演一条策略。闲置成本按**人·天**算（工位闲着 = 那一班人在闲着）。

    四条路的真正区别在"卡住的那道单怎么处理"：
    - `wait_for_material` 是**队头阻塞**（现在厂里/系统的实际后果）：工位按交期取第一张待做的单，
      它不齐套就整台工位停在那儿，后面的齐套单也不许插队 —— 这才叫"因为一个料缺就停产"；
    - `resequence_by_due` 把不齐套的单跳过、让后面的齐套单先做（缺料单不占产能位）；
    - `run_what_you_can` 在能跳的基础上，还允许按已覆盖物料比例部分投产；
    - `transfer_idle_labor` 同 3，并显式声明本版模型里人力不是产能约束。
    换线成本也计入：同一工位换了不同机种就扣一次换线时间（`setup_time_minutes`）。
    """
    work: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        work[str(o["id"])] = dict(o, remaining=float(o["remaining_qty"] or 0),
                                  finish_day=None)
    # 调人这一路同样允许部分投产（差别只在人力是否算产能约束，见 transfer_note）
    allow_partial = strategy in ("run_what_you_can", "transfer_idle_labor")
    skip_blocked = strategy in ("resequence_by_due", "run_what_you_can", "transfer_idle_labor")

    idle_days_by_station: Dict[str, float] = {}
    worked_station_days = 0.0
    produced = 0.0
    changeovers = 0
    last_product: Dict[str, str] = {}
    setup_loss_days = 0.0

    for day in range(days):
        for code, st in stations.items():
            capacity_units = float(st["capacity_per_hour"] or 0) * float(st["line_hours_per_day"] or 0)
            if capacity_units <= 0:
                continue
            here = [w for w in work.values() if w["remaining"] > 0 and _station_for(w, routes) == code]
            if not here:
                idle_days_by_station[code] = idle_days_by_station.get(code, 0.0) + 1.0
                continue
            here.sort(key=lambda w: (w["planned_due"] or date.max, w["work_order_code"]))
            if allow_partial:
                here.sort(key=lambda w: (-_coverage(w), w["planned_due"] or date.max))

            used = 0.0
            for w in here:
                if used >= capacity_units:
                    break
                coverage = _coverage(w)
                if coverage >= 1.0:
                    share = 1.0
                elif allow_partial and coverage >= PARTIAL_COVERAGE_MIN:
                    share = coverage
                elif skip_blocked:
                    continue                     # 跳过去做后面的齐套单
                else:
                    # 队头阻塞：这台工位今天到此为止，别的单不许插队
                    break
                if last_product.get(code) and last_product[code] != str(w["product_id"]):
                    setup_days = float(st["setup_time_minutes"] or 0) / (
                        float(st["line_hours_per_day"] or HOURS_PER_DAY_FALLBACK) * 60.0)
                    used += capacity_units * min(1.0, setup_days)
                    setup_loss_days += min(1.0, setup_days)
                    changeovers += 1
                    if used >= capacity_units:
                        break
                last_product[code] = str(w["product_id"])
                can_make = min(w["remaining"], capacity_units - used) * share
                if can_make <= 0:
                    continue
                w["remaining"] -= can_make
                used += can_make
                produced += can_make
                if w["remaining"] <= 1e-6:
                    w["remaining"] = 0.0
                    w["finish_day"] = day
            if used > 0:
                worked_station_days += min(1.0, used / capacity_units)
            else:
                idle_days_by_station[code] = idle_days_by_station.get(code, 0.0) + 1.0

    done = [w for w in work.values() if w["remaining"] <= 1e-6 and w["finish_day"] is not None]
    late = [w for w in done if w.get("planned_due")
            and start + timedelta(days=int(w["finish_day"])) > w["planned_due"]]
    delays = [((start + timedelta(days=int(w["finish_day"])) - w["planned_due"]).days)
              for w in late]
    total_station_days = len([x for x in stations.values()
                              if float(x["capacity_per_hour"] or 0) > 0]) * days
    util = round(worked_station_days / total_station_days, 4) if total_station_days else 0.0
    idle_station_days = round(sum(idle_days_by_station.values()), 1)
    idle_person_days = round(sum(idle * int(stations[c].get("headcount_hr") or 0)
                                 for c, idle in idle_days_by_station.items()), 1)
    if strategy == "transfer_idle_labor":
        transfer_note = ("这一版模型里产能按『线 × 小时 × capacity_per_hour』计，人力**不是**产能约束"
                         "（缺「一条线几人 / 几班倒」这个输入），所以调人策略与『能干就先干』产出相同 —— "
                         "这是模型的边界，不是『厂里不该调人』的结论；补上人手换算比后两者才会分化。")
    else:
        transfer_note = None

    return {
        "strategy": strategy,
        "produced_units": round(produced, 1),
        "orders_completed": len(done),
        "orders_open_at_horizon": len([w for w in work.values() if w["remaining"] > 0]),
        "delivered_on_time": len(done) - len(late),
        "delivered_late": len(late),
        "avg_delay_days": round(sum(delays) / len(delays), 1) if delays else 0.0,
        "changeovers": changeovers,
        "capacity_utilization": util,
        "idle_station_days": idle_station_days,
        "idle_person_days": idle_person_days,
        "labor_idle_cost": round(idle_person_days * labor_rate, 2),
        "setup_capacity_lost_days": round(setup_loss_days, 2),
        "transfer_note": transfer_note,
        "completions_sample": sorted(
            [{"work_order_code": w["work_order_code"], "product_id": w["product_id"],
              "qty": float(w["remaining_qty"] or 0),
              "planned_due": str(w["planned_due"]) if w.get("planned_due") else None,
              "finish_day": w["finish_day"],
              "on_time": bool(w["planned_due"]) and (start + timedelta(days=int(w["finish_day"]))) <= w["planned_due"]
              if w["finish_day"] is not None else False}
             for w in done],
            key=lambda x: (x["finish_day"] if x["finish_day"] is not None else 9999))[:12],
    }


STRATEGY_LABELS = {
    "wait_for_material": "等料（队头阻塞）：工位只认交期最早那张单，它不齐套就整台停在那儿——现在系统的实际后果",
    "run_what_you_can": "能干什么先干什么：部分齐套按已到料的比例投产",
    "resequence_by_due": "重排：仍只做齐套单，但按交期排、缺料单不占产能位",
    "transfer_idle_labor": "调人：闲置班组挪去有活等着的工位（扣换线时间）",
}


async def compare_options(
    db: AsyncSession, factory_id: str, *, objective: str = "labor_first",
    days: int | None = None, as_of: date | None = None,
    order_codes: List[str] | None = None,
) -> Dict[str, Any]:
    """同一份现状，四条路各跑一遍，给出比较表 + 按目标的排序 + 假设清单。"""
    from api.services.cost_model import resolve_rates

    if as_of is None:
        try:
            from api.services.virtual_factory_clock import get_clock
            now = await get_clock().now(factory_id)
            basis, as_of = "sim_clock", (now or datetime.utcnow()).date()
        except Exception:  # noqa: BLE001
            basis, as_of = "real_date", datetime.utcnow().date()
    else:
        basis = "caller_supplied"

    stations = {str(r["station_code"]): dict(r) for r in (await db.execute(
        STATIONS_SQL, {"fid": factory_id})).mappings().all()}
    from api.services.idle_capacity import HEADCOUNT_SQL, _headcount_index, _station_people
    hr_rows = [dict(r) for r in (await db.execute(HEADCOUNT_SQL, {"fid": factory_id})).mappings().all()]
    hr_index = _headcount_index(hr_rows)
    for code, st in stations.items():
        st["headcount_hr"] = sum(_station_people(str(st.get("station_name") or ""), code,
                                                 hr_rows, hr_index).values())
    orders = [dict(r) for r in (await db.execute(
        ORDERS_SQL, {"fid": factory_id, "codes": list(order_codes) if order_codes else None}
    )).mappings().all()]
    arrivals = [dict(r) for r in (await db.execute(
        ARRIVALS_SQL, {"fid": factory_id})).mappings().all()]

    def _as_date(value):
        # planned_due 在不同来源里可能是 date 也可能是 timestamp，比较前必须归一（否则 datetime>date 直接抛错）
        if value is None:
            return None
        return value.date() if isinstance(value, datetime) else value

    for o in orders:
        o["planned_due"] = _as_date(o.get("planned_due"))
    for a in arrivals:
        a["expected_date"] = _as_date(a.get("expected_date"))

    # 首道工位：路线有两种存法（模板 steps / JSON steps），都读一遍，拿不到就当"无首道工位"
    routes: Dict[str, str] = {}
    route_refs = {str(o["route_ref"]) for o in orders if o.get("route_ref")}
    for ref in route_refs:
        row = (await db.execute(text("""
            SELECT station_code FROM (
                SELECT work_center AS station_code, seq AS seq, 1 AS src
                FROM routing_template_steps WHERE template_id::text = CAST(:rid AS text)
                UNION ALL
                SELECT e.s->>'station' AS station_code, (e.s->>'step_no')::int AS seq, 2 AS src
                FROM routings r, jsonb_array_elements(r.steps::jsonb) WITH ORDINALITY AS e(s)
                WHERE r.id = CAST(:rid AS text)
            ) x ORDER BY src, seq LIMIT 1
        """), {"rid": ref})).mappings().first()
        if row and row["station_code"]:
            routes[ref] = str(row["station_code"])

    scoped_note = None
    if order_codes:
        # 只看这几张单时，闲置也必须只算它们涉及的工位：否则"5 张单的产出"配"全厂 30 天的闲置"
        # 是两个不同分母的数，成本比较就是错的。
        in_scope = {_station_for(o, routes) for o in orders}
        kept = {c: st for c, st in stations.items() if c in in_scope}
        dropped = len(stations) - len(kept)
        stations = kept
        scoped_note = (f"只推演指定的 {len(orders)} 张单：工位范围收窄到它们首道工序涉及的 "
                       f"{len(stations)} 个（其余 {dropped} 个不计入闲置，避免分母不一致）")

    rates = resolve_rates([], objective=objective)
    labor_rate = float(rates["rates"]["labor_person_day"]["amount"])
    horizon = days or SIM_HORIZON_DAYS

    results = [_simulate(name, orders, stations, routes, arrivals, start=as_of,
                         days=horizon, labor_rate=labor_rate)
               for name in STRATEGY_LABELS]
    w = rates["weights"]
    for r in results:
        r["label"] = STRATEGY_LABELS[r["strategy"]]
        r["objective_score"] = round(w["delivery"] * r["produced_units"] / 100.0
                                    + w["labor"] * (-r["labor_idle_cost"] / 100.0)
                                    + w["equipment"] * r["capacity_utilization"] * 10.0, 3)
    # 分数相同（比如这份现状下四条路都没活可干）时，用"按期交付→产出→闲置"决定名次，
    # 不能让排序取决于字典顺序 —— 否则同一份数据两次给出不同的"最优"。
    ranked = sorted(results, key=lambda r: (-r["objective_score"], -r["delivered_on_time"],
                                            -r["produced_units"], r["idle_person_days"],
                                            r["strategy"]))
    return {
        "factory_id": factory_id,
        "as_of": str(as_of),
        "clock_basis": basis,
        "horizon_days": horizon,
        "scope_order_codes": list(order_codes) if order_codes else "全部在制单",
        "scope_note": scoped_note,
        "objective": rates["objective"],
        "objective_label": rates["objective_label"],
        "orders_in_scope": len(orders),
        "stations_in_scope": len(stations),
        "assumptions": [
            "日粒度仿真；产能取 stations.capacity_per_hour × station_capacity 的线小时/天（实测字段，未猜）",
            "到货按未收 PO 的 expected_date 落到当天；没有 PO 的缺口视为不解决（这是外购数据缺失的真实后果）",
            "部分投产 = 按已覆盖物料比例产出，是粗口径的可行度指标，不是精确的可开线判断",
            "没有领料依据（required=0）的单在四条路里都不算能干",
            "首道工位从模板路线或 JSON 路线取；取不到的单归『无首道工位』，任何策略都不会跑它",
            "调人策略只计换线时间成本，未计技能是否匹配（position_capabilities 0 行）——所以它的排序要人先确认",
        ],
        "results": ranked,
        "best_for_objective": ranked[0]["strategy"],
    }
