"""
生产看板聚合 API

将真实 MES 数据（工单/报工/工位/设备/人员/出库）聚合为与仿真结果相同的
FactorySimResult 结构，供生产看板复用仿真结果 UI 组件。

重要原则：
- 本接口返回 is_simulation=False，数据来源为真实生产记录
- 与仿真结果看板（/api/v1/sim-factory/dashboard-summary, is_simulation=True）严格分离
- 前端复用相同的展示组件，但数据语义完全不同
"""

from fastapi import APIRouter, Depends, Query
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, String

from database.db_config import get_db
from database.models import (
    WorkOrder, ProductionReport, Station, Equipment, Product,
    Routing, OutboundOrder, EmployeeSkill, User,
)
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/production-dashboard", tags=["production-dashboard"])

# 标准工时参数（用于负荷估算）
SHIFTS_PER_DAY = 2
HOURS_PER_SHIFT = 8


def _day_index(dt: Optional[datetime], base_date) -> int:
    """日期 → 相对于窗口起始日的天索引"""
    if not dt:
        return 0
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0, (dt.date() - base_date).days)


def _priority_map(p: str) -> str:
    return p if p in ("urgent", "high", "medium", "low") else "medium"


@router.get("/summary")
async def production_dashboard_summary(
    factory_id: str = Query(default="F01", description="厂区 ID"),
    horizon_days: int = Query(default=14, ge=7, le=30, description="回溯天数窗口"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """生产看板全量聚合数据（真实生产数据，is_simulation=False）。

    结构与仿真结果看板一致，前端可复用同一套结果组件渲染。
    """
    now = datetime.utcnow()
    base_date = (now - timedelta(days=horizon_days - 1)).date()

    # ===== 1. 拉取真实数据 =====
    wo_res = await db.execute(
        select(WorkOrder).where(WorkOrder.factory_id == factory_id)
    )
    work_orders: List[WorkOrder] = list(wo_res.scalars().all())

    rpt_res = await db.execute(
        select(ProductionReport).where(ProductionReport.factory_id == factory_id)
    )
    reports: List[ProductionReport] = list(rpt_res.scalars().all())

    st_res = await db.execute(select(Station).where(Station.factory_id == factory_id))
    stations: List[Station] = list(st_res.scalars().all())

    eq_res = await db.execute(select(Equipment).where(Equipment.factory_id == factory_id))
    equipment: List[Equipment] = list(eq_res.scalars().all())

    pd_res = await db.execute(select(Product).where(Product.factory_id == factory_id))
    products: List[Product] = list(pd_res.scalars().all())
    product_map = {p.id: p for p in products}

    rt_res = await db.execute(select(Routing).where(Routing.factory_id == factory_id))
    routings: List[Routing] = list(rt_res.scalars().all())
    routing_map = {r.id: r for r in routings}

    ob_res = await db.execute(
        select(OutboundOrder).where(OutboundOrder.factory_id == factory_id)
    )
    outbounds: List[OutboundOrder] = list(ob_res.scalars().all())

    # 人员技能（按厂区用户）
    # employee_skills.user_id 和 users.id 均为 uuid 类型，直接 JOIN
    skill_res = await db.execute(
        select(EmployeeSkill, User)
        .join(User, EmployeeSkill.user_id == User.id)
        .where(User.factory_id == factory_id)
    )
    skill_rows = skill_res.all()

    # ===== 2. 工位 → 工段汇总 =====
    station_map = {s.id: s for s in stations}
    eq_per_station: Dict[str, int] = defaultdict(int)
    for eq in equipment:
        if eq.station_id:
            eq_per_station[eq.station_id] += 1

    # 报工按工位×日聚合（负荷 = 产出耗时 / 可用工时）
    station_day_hours: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    station_output: Dict[str, Dict[str, int]] = defaultdict(lambda: {"good": 0, "defect": 0, "scrap": 0})
    for r in reports:
        day = _day_index(r.created_at, base_date)
        st = station_map.get(r.station_id)
        cph = st.capacity_per_hour if st and st.capacity_per_hour else 20
        hours = (r.good_qty + r.defect_qty) / max(cph, 1)
        station_day_hours[r.station_id][day] += hours
        so = station_output[r.station_id]
        so["good"] += r.good_qty
        so["defect"] += r.defect_qty
        so["scrap"] += r.scrap_qty or 0

    # 人员按车间分组
    workshop_workers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen_users = set()
    for row in skill_rows:
        emp_skill, u = row[0], row[1]
        if u.id in seen_users:
            continue
        seen_users.add(u.id)
        dept = getattr(u, "department", None) or "综合车间"
        level_str = emp_skill.level or "L3"
        try:
            level_num = int(level_str.replace("L", "").replace("l", ""))
        except (ValueError, AttributeError):
            level_num = 3
        workshop_workers[dept].append({
            "worker_id": str(u.id)[:8],
            "name": u.full_name or u.username,
            "section_id": dept,
            "section_name": dept,
            "role": getattr(u, "position", None) or "操作工",
            "skill_level": level_num,
            "shift": 1,
            "attendance_rate": 0.95,
        })

    sections_out: List[Dict[str, Any]] = []
    workshop_ids = set()
    for s in stations:
        ws_id = s.workshop_id or "default"
        ws_name = s.workshop_id or "综合车间"
        workshop_ids.add(ws_id)
        daily = station_day_hours.get(s.id, {})
        cap_per_day = SHIFTS_PER_DAY * HOURS_PER_SHIFT
        total_load = sum(daily.values())
        total_cap = horizon_days * cap_per_day
        series = []
        peak_rate, peak_day = 0.0, 0
        for d in range(horizon_days):
            load_h = daily.get(d, 0.0)
            rate = load_h / cap_per_day if cap_per_day else 0
            if rate > peak_rate:
                peak_rate, peak_day = rate, d
            # WIP：当天在该工位报工但未完成的数量（简化估算）
            series.append({
                "day": d,
                "load_hours": round(load_h, 1),
                "capacity_hours": cap_per_day,
                "load_rate": round(rate, 3),
                "is_workday": True,
                "wip_qty": station_output.get(s.id, {}).get("good", 0) if d == horizon_days - 1 else 0,
            })
        avg_rate = total_load / total_cap if total_cap else 0
        workers_in_ws = len(workshop_workers.get(ws_name, []))
        sections_out.append({
            "section_id": s.id,
            "name": s.station_name,
            "workshop_id": ws_id,
            "workshop_name": ws_name,
            "strategy": "push",
            "workers": max(workers_in_ws, 1),
            "machines": eq_per_station.get(s.id, 0),
            "shifts_per_day": SHIFTS_PER_DAY,
            "hours_per_shift": HOURS_PER_SHIFT,
            "efficiency": 1.0,
            "total_load_hours": round(total_load, 1),
            "total_capacity_hours": total_cap,
            "avg_load_rate": round(avg_rate, 3),
            "peak_load_rate": round(peak_rate, 3),
            "peak_day": peak_day,
            "is_bottleneck": peak_rate > 1.0,
            "overtime_used_hours": round(max(0, total_load - total_cap), 1),
            "series": series,
        })

    # ===== 3. 工单 → 订单结果 =====
    orders_out: List[Dict[str, Any]] = []
    production_orders_out: List[Dict[str, Any]] = []
    order_section_loads: List[Dict[str, Any]] = []

    for wo in work_orders:
        prod = product_map.get(wo.product_id)
        pname = prod.product_name if prod else wo.product_id
        release_day = _day_index(wo.planned_start or wo.created_at, base_date)
        due_day = _day_index(wo.planned_due, base_date)
        complete_day = _day_index(wo.actual_complete, base_date) if wo.actual_complete else (
            horizon_days - 1 if wo.status in ("completed", "pending_inbound") else 0
        )
        delay = max(0, complete_day - due_day) if wo.actual_complete else (
            max(0, (now.date() - (wo.planned_due.date() if wo.planned_due else now.date())).days)
            if wo.status not in ("completed", "cancelled") else 0
        )
        on_time = delay <= 0

        # 工艺路线 → 工序
        routing = routing_map.get(wo.routing_id) if wo.routing_id else None
        steps = (routing.steps if routing else []) or []
        ops: List[Dict[str, Any]] = []
        po_ops: List[Dict[str, Any]] = []
        n_steps = max(len(steps), 1)
        step_span = max(1, (max(complete_day, due_day) - release_day) // n_steps) if due_day > release_day else 1

        # 该工单的报工按工位分组 → 工序实际
        wo_reports = [r for r in reports if r.work_order_id == wo.id]
        wo_station_days: Dict[str, List[int]] = defaultdict(list)
        for r in wo_reports:
            wo_station_days[r.station_id].append(_day_index(r.created_at, base_date))

        for i, step in enumerate(steps or [{"step_no": 1, "name": "生产", "station_type": "assembly"}]):
            st_id = wo.assigned_station_id or (stations[0].id if stations else "unknown")
            st = station_map.get(st_id)
            st_name = st.station_name if st else "未知工位"
            s_day = release_day + i * step_span
            e_day = s_day + step_span
            work_h = ((wo.planned_qty or 0) / max(st.capacity_per_hour if st else 20, 1)) if st else 4
            ops.append({
                "op_no": step.get("step_no", i + 1),
                "name": step.get("name", f"工序{i+1}"),
                "section_id": st_id,
                "section_name": st_name,
                "strategy": "push",
                "start_day": min(s_day, horizon_days - 1),
                "end_day": min(e_day, horizon_days - 1),
                "work_hours": round(work_h, 1),
            })
            # PO 工序状态
            cur_step = wo.current_routing_step if wo.current_routing_step is not None else -1
            if wo.status == "completed":
                op_status = "done"
            elif cur_step > i:
                op_status = "done"
            elif cur_step == i and wo.status == "in_progress":
                op_status = "in_progress"
            else:
                op_status = "pending"
            days_at_station = wo_station_days.get(st_id, [])
            po_ops.append({
                "op_no": step.get("step_no", i + 1),
                "name": step.get("name", f"工序{i+1}"),
                "section_id": st_id,
                "section_name": st_name,
                "start_day": min(s_day, horizon_days - 1),
                "end_day": min(e_day, horizon_days - 1),
                "qty": wo.planned_qty,
                "good_qty": wo.good_qty if op_status == "done" else 0,
                "scrap_qty": wo.scrap_qty if op_status == "done" else 0,
                "status": op_status,
                "wait_days": max(0, (min(days_at_station) - s_day)) if days_at_station else 0,
            })
            order_section_loads.append({
                "order_id": wo.id,
                "section_id": st_id,
                "section_name": st_name,
                "work_hours": round(work_h, 1),
                "share_pct": round(100.0 / n_steps, 1),
            })

        total_wh = sum(o["work_hours"] for o in ops)
        wo_status_map = {
            "pending": "released", "released": "released", "in_progress": "in_progress",
            "pending_inbound": "in_progress", "completed": "done", "cancelled": "cancelled",
            "on_hold": "in_progress",
        }
        orders_out.append({
            "order_id": wo.id,
            "product_id": wo.product_id,
            "product_name": pname,
            "quantity": wo.planned_qty,
            "priority": _priority_map(wo.priority),
            "release_day": min(release_day, horizon_days - 1),
            "due_day": min(due_day, horizon_days - 1),
            "completion_day": min(complete_day, horizon_days - 1),
            "delay_days": delay,
            "on_time": on_time,
            "total_work_hours": round(total_wh, 1),
            "ops": ops,
        })
        production_orders_out.append({
            "po_id": f"PO-{wo.work_order_code}",
            "order_id": wo.id,
            "product_name": pname,
            "quantity": wo.planned_qty,
            "release_day": min(release_day, horizon_days - 1),
            "start_day": min(_day_index(wo.actual_start or wo.planned_start or wo.created_at, base_date), horizon_days - 1),
            "completion_day": min(complete_day, horizon_days - 1),
            "due_day": min(due_day, horizon_days - 1),
            "status": wo_status_map.get(wo.status, "in_progress"),
            "on_time": on_time,
            "good_qty": wo.good_qty,
            "scrap_qty": wo.scrap_qty,
            "current_section": station_map[wo.assigned_station_id].station_name if wo.assigned_station_id in station_map else (stations[0].station_name if stations else "-"),
            "ops": po_ops,
        })

    # ===== 4. 日产出曲线 =====
    day_agg: Dict[int, Dict[str, int]] = defaultdict(lambda: {"output": 0, "good": 0, "scrap": 0})
    for r in reports:
        d = _day_index(r.created_at, base_date)
        if d < horizon_days:
            day_agg[d]["output"] += r.good_qty + r.defect_qty
            day_agg[d]["good"] += r.good_qty
            day_agg[d]["scrap"] += r.scrap_qty or 0
    wip_curve: List[Dict[str, Any]] = []
    daily_output: List[Dict[str, Any]] = []
    cumulative = 0
    for d in range(horizon_days):
        agg = day_agg.get(d, {"output": 0, "good": 0, "scrap": 0})
        cumulative += agg["good"]
        daily_output.append({
            "day": d, "output_qty": agg["output"], "good_qty": agg["good"],
            "scrap_qty": agg["scrap"], "cumulative": cumulative,
        })
        # WIP = 在制工单的未完工量（简化：按天递减估算）
        active = len([wo for wo in work_orders if wo.status == "in_progress"])
        wip_curve.append({
            "day": d,
            "wip_qty": sum(max(0, (wo.planned_qty or 0) - (wo.completed_qty or 0)) for wo in work_orders if wo.status in ("in_progress", "released")),
            "active_orders": active,
        })

    # ===== 5. 流转记录（同一工单在不同工位的报工序列 → 工位间流转）=====
    transfers: List[Dict[str, Any]] = []
    wo_sorted_reports: Dict[str, List[ProductionReport]] = defaultdict(list)
    for r in reports:
        wo_sorted_reports[r.work_order_id].append(r)
    t_idx = 0
    for wo_id, rpts in wo_sorted_reports.items():
        rpts_sorted = sorted(rpts, key=lambda x: x.created_at)
        for i in range(1, len(rpts_sorted)):
            prev, cur = rpts_sorted[i - 1], rpts_sorted[i]
            if prev.station_id != cur.station_id:
                wo = next((w for w in work_orders if w.id == wo_id), None)
                prod = product_map.get(wo.product_id) if wo else None
                from_st = station_map.get(prev.station_id)
                to_st = station_map.get(cur.station_id)
                transfers.append({
                    "transfer_id": f"TR-{t_idx:04d}",
                    "order_id": wo_id,
                    "product_name": prod.product_name if prod else "-",
                    "from_section_id": prev.station_id,
                    "from_section_name": from_st.station_name if from_st else prev.station_id,
                    "to_section_id": cur.station_id,
                    "to_section_name": to_st.station_name if to_st else cur.station_id,
                    "qty": cur.good_qty + cur.defect_qty,
                    "depart_day": _day_index(prev.created_at, base_date),
                    "arrive_day": _day_index(cur.created_at, base_date),
                })
                t_idx += 1

    # ===== 6. 出库记录 =====
    outbound_out: List[Dict[str, Any]] = []
    for ob in outbounds:
        wo = next((w for w in work_orders if w.id == ob.work_order_id), None)
        prod = product_map.get(ob.material_id)
        ob_day = _day_index(ob.completed_at or ob.created_at, base_date)
        outbound_out.append({
            "outbound_id": ob.outbound_code,
            "order_id": ob.work_order_id or "-",
            "po_id": f"PO-{wo.work_order_code}" if wo else "-",
            "product_name": prod.product_name if prod else ob.material_id,
            "quantity": ob.quantity,
            "good_qty": ob.quantity,
            "outbound_day": min(ob_day, horizon_days - 1),
            "on_time": True,
            "warehouse": ob.warehouse_id[:8] if ob.warehouse_id else "-",
            "status": "shipped" if ob.status == "completed" else "pending",
        })

    # ===== 7. 卡点分析 =====
    blocking_points: List[Dict[str, Any]] = []
    rank = 1
    for sec in sections_out:
        if sec["peak_load_rate"] > 1.0:
            blocking_points.append({
                "rank": rank,
                "section_id": sec["section_id"],
                "section_name": sec["name"],
                "workshop_name": sec["workshop_name"],
                "blocking_type": "overload",
                "severity": min(10, round(sec["peak_load_rate"] * 5)),
                "peak_day": sec["peak_day"],
                "peak_load_rate": sec["peak_load_rate"],
                "overload_days": sum(1 for s in sec["series"] if s["load_rate"] > 1.0),
                "wip_peak": max((s["wip_qty"] for s in sec["series"]), default=0),
                "avg_wait_days": 0,
                "delayed_orders": 0,
                "detail": f"峰值负荷率 {sec['peak_load_rate']*100:.0f}%，存在产能瓶颈",
            })
            rank += 1
    # 故障设备 → 卡点
    for eq in equipment:
        if eq.status == "fault" and eq.station_id in station_map:
            st = station_map[eq.station_id]
            blocking_points.append({
                "rank": rank,
                "section_id": eq.station_id,
                "section_name": st.station_name,
                "workshop_name": st.workshop_id or "综合车间",
                "blocking_type": "process_wait",
                "severity": 8,
                "peak_day": horizon_days - 1,
                "peak_load_rate": 0,
                "overload_days": 0,
                "wip_peak": 0,
                "avg_wait_days": 0,
                "delayed_orders": 0,
                "detail": f"设备 {eq.equipment_name} 故障停机，工序等待",
            })
            rank += 1

    # ===== 8. 告警 =====
    alerts: List[Dict[str, Any]] = []
    for wo in work_orders:
        if wo.status not in ("completed", "cancelled") and wo.planned_due:
            if wo.planned_due < now:
                alerts.append({
                    "level": "critical", "category": "delay",
                    "title": f"工单 {wo.work_order_code} 已逾期",
                    "detail": f"交期 {wo.planned_due.strftime('%m-%d')}，当前状态 {wo.status}",
                    "section_id": wo.assigned_station_id, "order_id": wo.id, "day": horizon_days - 1,
                })
    for eq in equipment:
        if eq.status == "fault":
            alerts.append({
                "level": "critical", "category": "bottleneck",
                "title": f"设备 {eq.equipment_name} 故障",
                "detail": f"设备编码 {eq.equipment_code}，需维修",
                "section_id": eq.station_id, "order_id": None, "day": horizon_days - 1,
            })
        elif eq.status == "maintenance":
            alerts.append({
                "level": "info", "category": "idle",
                "title": f"设备 {eq.equipment_name} 保养中",
                "detail": f"设备编码 {eq.equipment_code}，计划保养",
                "section_id": eq.station_id, "order_id": None, "day": horizon_days - 1,
            })
    for sec in sections_out:
        if sec["peak_load_rate"] > 1.0:
            alerts.append({
                "level": "warning", "category": "overload",
                "title": f"工位 {sec['name']} 负荷过载",
                "detail": f"峰值负荷率 {sec['peak_load_rate']*100:.0f}%",
                "section_id": sec["section_id"], "order_id": None, "day": sec["peak_day"],
            })

    # ===== 9. 人员花名册 =====
    workforce_out: List[Dict[str, Any]] = []
    for ws_name, workers in workshop_workers.items():
        if not workers:
            continue
        avg_skill = sum(w["skill_level"] for w in workers) / len(workers)
        workforce_out.append({
            "section_id": ws_name,
            "name": ws_name,
            "headcount": len(workers),
            "per_shift": max(1, len(workers) // SHIFTS_PER_DAY),
            "shift_headcount": {"1": len(workers) // 2 + len(workers) % 2, "2": len(workers) // 2},
            "avg_skill": round(avg_skill, 1),
            "avg_attendance": 0.95,
            "labor_utilization": round(min(1.0, len(workers) / max(len(stations), 1)), 2),
            "workers": workers,
        })

    # ===== 10. KPI 汇总 =====
    total_good = sum(r.good_qty for r in reports)
    total_defect = sum(r.defect_qty for r in reports)
    total_scrap = sum(r.scrap_qty or 0 for r in reports)
    total_output = total_good + total_defect
    delayed_orders = len([o for o in orders_out if not o["on_time"]])
    active_wo = len([wo for wo in work_orders if wo.status == "in_progress"])
    running_eq = len([e for e in equipment if e.status == "running"])
    total_load_h = sum(s["total_load_hours"] for s in sections_out)
    total_cap_h = sum(s["total_capacity_hours"] for s in sections_out)
    rates = [s["avg_load_rate"] for s in sections_out if s["total_capacity_hours"] > 0]
    po_completed = len([po for po in production_orders_out if po["status"] == "done"])
    po_delayed = len([po for po in production_orders_out if not po["on_time"]])

    kpis = {
        "total_work_hours": round(total_load_h, 1),
        "total_capacity_hours": total_cap_h,
        "avg_load_rate": round(total_load_h / total_cap_h, 3) if total_cap_h else 0,
        "peak_load_rate": round(max((s["peak_load_rate"] for s in sections_out), default=0), 3),
        "on_time_rate": round(1 - delayed_orders / max(len(orders_out), 1), 3),
        "delayed_orders": delayed_orders,
        "bottleneck_sections": len([s for s in sections_out if s["is_bottleneck"]]),
        "wip_peak": max((p["wip_qty"] for p in wip_curve), default=0),
        "imbalance_index": round(max(rates) - min(rates), 3) if rates else 0,
        "overtime_hours": round(sum(s["overtime_used_hours"] for s in sections_out), 1),
        "total_output": total_output,
        "good_output": total_good,
        "scrap_output": total_scrap,
        "avg_yield_rate": round(total_good / max(total_output, 1), 3),
        "headcount": sum(w["headcount"] for w in workforce_out),
        "po_completed": po_completed,
        "po_delayed": po_delayed,
        "blocking_point_count": len(blocking_points),
        "max_section_wip": max((p["wip_qty"] for p in wip_curve), default=0),
        "total_outbound": sum(ob.quantity for ob in outbounds if ob.status == "completed"),
        "pending_outbound": len([ob for ob in outbounds if ob.status != "completed"]),
        "avg_process_wait": 0,
    }

    # ===== 组装返回（与仿真结果同构，is_simulation=False）=====
    return {
        "is_simulation": False,  # 明确标记：真实生产数据
        "factory_id": factory_id,
        "simulation_id": f"production-{factory_id}-{now.strftime('%Y%m%d%H%M')}",
        "created_at": now.isoformat(),
        "engine_version": "MES-REAL",
        "horizon_days": horizon_days,
        "workshop_count": len(workshop_ids) or 1,
        "section_count": len(stations),
        "order_count": len(work_orders),
        "kpis": kpis,
        "sections": sections_out,
        "orders": orders_out,
        "order_section_loads": order_section_loads,
        "wip_curve": wip_curve,
        "alerts": alerts,
        "workforce": workforce_out,
        "daily_output": daily_output,
        "section_outputs": [
            {
                "section_id": sid,
                "name": station_map[sid].station_name if sid in station_map else sid,
                "planned_qty": so["good"] + so["defect"] + so["scrap"],
                "good_qty": so["good"],
                "scrap_qty": so["scrap"],
                "yield_rate": round(so["good"] / max(so["good"] + so["defect"] + so["scrap"], 1), 3),
            }
            for sid, so in station_output.items()
        ],
        "production_orders": production_orders_out,
        "transfers": transfers,
        "blocking_points": blocking_points,
        "outbound_orders": outbound_out,
        # 生产看板附加实时指标
        "realtime": {
            "active_work_orders": active_wo,
            "running_equipment": running_eq,
            "total_equipment": len(equipment),
            "equipment_utilization": round(running_eq / max(len(equipment), 1), 3),
            "today_reports": len([r for r in reports if r.created_at and r.created_at.date() == now.date()]),
            "today_good_output": sum(r.good_qty for r in reports if r.created_at and r.created_at.date() == now.date()),
        },
    }
