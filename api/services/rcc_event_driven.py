"""RCC 事件驱动数据层 — 统一事件总线接线

数据层严格性设计（单一事实源 + 事件驱动）：
1. 事实源（真实DB）：hr_employees/equipment/work_orders/inventory
2. 事件总线（agent_events）：状态变化 → 事件（缺勤/设备故障/订单加急/缺料）
3. RCC 感知（reconcile）：轮询事件 → 重算基线 → 决策
4. 决策执行：更新基线/生成任务/通知人员/创建RCC调度

核心：任何影响资源的状态变化都必须产生事件 → RCC 才能感知并规划。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import text

_logger = logging.getLogger("rcc_event_driven")


async def emit_event(db, factory_id: str, event_type: str, agent_key: str,
                     data: Dict, task_id: Optional[str] = None) -> str:
    """写入事件总线（agent_events）。"""
    event_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO agent_events (event_id, event_type, agent_key, factory_id, task_id, data, created_at)
        VALUES (:eid, :etype, :ak, :fid, :tid, :data, NOW())
    """), {"eid": event_id, "etype": event_type, "ak": agent_key,
           "fid": factory_id, "tid": task_id,
           "data": json.dumps(data, ensure_ascii=False, default=str)})
    return event_id


async def detect_changes(db, factory_id: str) -> Dict:
    """轮询事实源变化 → 产生事件（缺勤/设备故障/订单加急/缺料）。"""
    events = []

    # 1) 员工缺勤变化：hr_employees status='leave'（对比最近基线）
    leave_rows = (await db.execute(text("""
        SELECT station, COUNT(*) AS leave_count,
               (SELECT COUNT(*) FROM hr_employees WHERE factory_id=:f AND station=hr.station) AS total
        FROM hr_employees hr
        WHERE factory_id=:f AND status='leave'
        GROUP BY station
        HAVING COUNT(*)::float / (SELECT COUNT(*) FROM hr_employees WHERE factory_id=:f AND station=hr.station) >= 0.05
    """), {"f": factory_id})).mappings().all()
    for r in leave_rows:
        events.append({
            "event_type": "staff_leave",
            "agent_key": "hr_agent",
            "data": {"station": r["station"], "leave_count": r["leave_count"],
                     "total": r["total"],
                     "leave_rate": round(r["leave_count"] / r["total"] * 100, 1)},
        })

    # 2) 设备故障：equipment status broken/fault/maintenance
    eq_rows = (await db.execute(text("""
        SELECT equipment_code, equipment_name, status FROM equipment
        WHERE factory_id=:f AND status IN ('broken','fault','maintenance')
    """), {"f": factory_id})).mappings().all()
    for r in eq_rows:
        events.append({
            "event_type": "equipment_fault",
            "agent_key": "equipment_agent",
            "data": {"equipment_code": r["equipment_code"], "equipment_name": r["equipment_name"], "status": r["status"]},
        })

    # 3) 订单加急：work_orders priority=urgent
    wo_rows = (await db.execute(text("""
        SELECT work_order_code, product_id, planned_qty, planned_due, priority
        FROM work_orders
        WHERE factory_id=:f AND status IN ('pending','in_progress') AND priority='urgent'
        LIMIT 5
    """), {"f": factory_id})).mappings().all()
    for r in wo_rows:
        events.append({
            "event_type": "order_rush",
            "agent_key": "scheduling_agent",
            "data": {"work_order_code": r["work_order_code"], "product_id": r["product_id"],
                     "qty": r["planned_qty"], "due": str(r["planned_due"])[:10]},
        })

    # 4) 缺料：库存 < 在制/待排工单需求（真缺料，MRP 口径）
    mat_rows = (await db.execute(text("""
        SELECT wom.material_code,
               COALESCE((SELECT SUM(inv2.available_qty) FROM inventory inv2
                         WHERE inv2.material_code=wom.material_code AND inv2.factory_id=:f), 0) AS avail,
               SUM(wom.required_qty - wom.received_qty) AS need,
               COUNT(DISTINCT wom.work_order_id) AS affected_wos
        FROM work_order_materials wom
        JOIN work_orders wo ON wo.id=wom.work_order_id
        WHERE wo.factory_id=:f AND wo.status IN ('released','in_progress','pending')
          AND wom.required_qty > wom.received_qty
        GROUP BY wom.material_code
        HAVING SUM(wom.required_qty - wom.received_qty) > COALESCE(
            (SELECT SUM(inv2.available_qty) FROM inventory inv2
             WHERE inv2.material_code=wom.material_code AND inv2.factory_id=:f), 0)
        LIMIT 8
    """), {"f": factory_id})).mappings().all()
    for r in mat_rows:
        events.append({
            "event_type": "material_shortage",
            "agent_key": "warehouse_agent",
            "data": {"material_code": r["material_code"],
                     "avail": float(r["avail"] or 0), "need": float(r["need"] or 0),
                     "gap": round(float(r["need"] or 0) - float(r["avail"] or 0), 1),
                     "affected_wos": r["affected_wos"]},
        })

    # 写入总线（幂等：同事件类型+同主体 1 小时内不重复）
    written = []
    for ev in events:
        dedup = (await db.execute(text("""
            SELECT 1 FROM agent_events
            WHERE event_type=:t AND data->>:k = :v AND created_at > NOW() - interval '1 hour'
            LIMIT 1
        """), {"t": ev["event_type"],
               "k": list(ev["data"].keys())[0],
               "v": str(list(ev["data"].values())[0])})).scalar_one_or_none()
        if not dedup:
            eid = await emit_event(db, factory_id, ev["event_type"], ev["agent_key"], ev["data"])
            written.append({**ev, "event_id": eid})
    await db.commit()
    return {"detected": len(events), "written": written}


async def reconcile(db, factory_id: str) -> Dict:
    """事件 → RCC 感知 → 决策 → 更新基线 + 通知 + 调度任务。

    每个事件类型对应 RCC 决策：
    - staff_leave → 人力调度建议（people-assignment）+ 通知 PMC/产线
    - equipment_fault → 产能更新（equipment-baseline）+ 通知 PMC/产线管理者
    - order_rush → 关联人员/资源计算 + 通知 PMC
    - material_shortage → 采购动作链 + RCC 调度
    """
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from api.services.followup_task_service import create_task
    from api.services.chat_tools_service import execute_tool

    result = {"events": [], "decisions": [], "notified": [], "tasks": []}

    # 取最近 1 小时未处理事件
    evs = (await db.execute(text("""
        SELECT event_id, event_type, agent_key, data FROM agent_events
        WHERE factory_id=:f AND created_at > NOW() - interval '1 hour'
        ORDER BY created_at ASC
    """), {"f": factory_id})).mappings().all()

    for ev in evs:
        data = ev["data"] or {}
        decision = {"event": ev["event_type"], "summary": ""}

        if ev["event_type"] == "staff_leave":
            station = data.get("station")
            rate = data.get("leave_rate")
            decision["summary"] = f"员工缺勤 {station} 缺勤率 {rate}%"
            # 调用 RCC 人力决策（自动生成 manpower 调度任务）
            engine = RCCResourceDecisionEngine(db)
            r = await engine.recommend_worker_assignment(factory_id)
            decision["detail"] = f"RCC 人力决策: 借调方案 {len(r.get('suggested_transfers', []))} 条"
            # 通知 PMC + 产线管理者
            await _notify(db, factory_id, "vf_mec_pmc_01",
                          f"【缺勤预警】{station} 缺勤率 {rate}%，需人员调配",
                          f"RCC 已生成借调方案 {len(r.get('suggested_transfers', []))} 条，请确认", "warning")

        elif ev["event_type"] == "equipment_fault":
            code = data.get("equipment_code")
            decision["summary"] = f"设备故障 {code}"
            # 产能更新：重新同步基线（设备产能变化 → PMC/产线知道）
            from core.rcc.calculator import RCCResourceCalculator
            calc = RCCResourceCalculator(db)
            try:
                await calc.full_baseline_sync(factory_id)
                decision["detail"] = "RCC 已重算基线（设备产能更新）"
            except Exception as e:
                decision["detail"] = f"基线更新: {str(e)[:60]}"
            # 通知 PMC + 产线管理者
            await _notify(db, factory_id, "vf_mec_pmc_01",
                          f"【设备故障】{code} 已停，产能基线已更新",
                          f"请产线管理者重新安排该设备工单，RCC 可协助重新排产", "critical")

        elif ev["event_type"] == "order_rush":
            wocode = data.get("work_order_code")
            decision["summary"] = f"订单加急 {wocode}"
            # 关联人员计算：工单涉及的核心岗位（操作员/计划员/质检）按工厂产线匹配
            people = (await db.execute(text("""
                SELECT DISTINCT e.name, e.position, e.station
                FROM hr_employees e
                WHERE e.factory_id = :f
                  AND e.position IN ('操作员','计划员','质检员','组长')
                  AND e.status = 'active'
                ORDER BY e.position LIMIT 8
            """), {"f": factory_id})).mappings().all()
            decision["detail"] = f"关联核心岗位 {len(people)} 人: {[p['position'] for p in people[:4]]}"
            await _notify(db, factory_id, "vf_mec_pmc_01",
                          f"【订单加急】{wocode} 需提前交付",
                          f"RCC 已计算关联核心岗位 {len(people)} 人，请确认产能与排程", "warning")

        elif ev["event_type"] == "material_shortage":
            mcode = data.get("material_code")
            gap = data.get("gap")
            decision["summary"] = f"缺料 {mcode}（缺口 {gap}）"
            await _notify(db, factory_id, "procurement",
                          f"【缺料】{mcode} 缺口 {gap}，请采购处理",
                          f"影响 {data.get('affected_wos')} 个在制工单，RCC 已升级并建任务", "critical")
            # ── 自动建缺料任务（智能体接管：AI 引擎会验证→闭环/转采购）──
            dup = (await db.execute(text("""
                SELECT 1 FROM followup_tasks
                WHERE factory_id=:f AND title LIKE :like AND status IN ('open','blocked') LIMIT 1
            """), {"f": factory_id, "like": f"%{mcode}%"})).scalar_one_or_none()
            if not dup:
                await db.execute(text("""
                    INSERT INTO followup_tasks (id, factory_id, created_by, title, description, status,
                        agent_key, follow_interval_minutes, next_follow_at, max_follows, assigned_to, created_at, updated_at)
                    VALUES (gen_random_uuid()::text, :f, 'rcc_events', :title, :desc, 'blocked',
                        'procurement_agent', 30, NOW(), 10, 'procurement', NOW(), NOW())
                """), {"f": factory_id,
                       "title": f"缺料：{mcode} 可用 {data.get('avail')} < 在制需求 {data.get('need')}",
                       "desc": f"RCC 检测到缺料，缺口 {gap}，影响 {data.get('affected_wos')} 个在制工单。AI 引擎将自动验证库存并处理。"})

        result["decisions"].append(decision)
        result["notified"].append(decision["summary"])
        # 标记事件已处理
        await db.execute(text("UPDATE agent_events SET data = data || CAST(:flag AS jsonb) WHERE event_id=:eid"),
                         {"flag": json.dumps({"processed": True}), "eid": ev["event_id"]})

    await db.commit()
    return result


async def _notify(db, factory_id: str, recipient: str, title: str, content: str, severity: str = "info"):
    """站内通知（写 notifications 表）。"""
    await db.execute(text("""
        INSERT INTO notifications (id, factory_id, recipient, category, title, content, severity, is_read, created_at)
        VALUES (gen_random_uuid()::text, :f, :r, 'rcc_event', :t, :c, :sev, false, NOW())
    """), {"f": factory_id, "r": recipient, "t": title[:200], "c": content[:500], "sev": severity})
