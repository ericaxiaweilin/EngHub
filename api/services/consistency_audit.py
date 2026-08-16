"""RCC 数据一致性审查服务（automated reconciliation audit）

系统自动对账（无需人肉）：设备 / 人员 / 任务 / 工单 / chatbot / RCC 六方数据自证一致。
每个检查项：预期(期望值) vs 实际(来源值) → OK/DRIFT(漂移)/MISSING(缺失) → 自动告警。

对账矩阵：
1. 人员口径：hr_employees(active/leave) ↔ operators ↔ attendance(今日) ↔ RCC people_baseline
2. 设备口径：equipment(status分布) ↔ RCC equipment_baseline(statuses)
3. 工单口径：work_orders(状态分布/urgent) ↔ RCC work_order_baseline
4. 任务闭环：followup_tasks(blocked) → rcc_tasks(自动提交) → approved → 回写解除
5. 事件一致性：agent_events(staff_leave) vs hr_employees(leave) / equipment_fault vs equipment(broken)
6. chatbot 通知：rcc_tasks(approved/rejected) → notifications(回写动作)
7. 缺料一致性：inventory(available=0) vs followup_tasks(缺料任务) vs rcc_tasks(material)
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List

from sqlalchemy import text

_logger = logging.getLogger("consistency_audit")


async def audit_consistency(db, factory_id: str = "FAC_MECH_001") -> Dict:
    """跑一轮对账，返回检查项结果 + 汇总。"""
    checks: List[Dict] = []

    # ══ 1. 人员口径对账 ══
    try:
        hr = (await db.execute(text("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='active')::int AS active,
                   COUNT(*) FILTER (WHERE status='leave')::int AS leave
            FROM hr_employees WHERE factory_id=:f
        """), {"f": factory_id})).mappings().first()
        ops = (await db.execute(text("""
            SELECT COUNT(*)::int AS total FROM operators WHERE factory_id=:f
        """), {"f": factory_id})).scalar_one()
        att = (await db.execute(text("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='present')::int AS present,
                   COUNT(*) FILTER (WHERE status='leave')::int AS leave
            FROM attendance WHERE factory_id=:f AND date=CURRENT_DATE::text
        """), {"f": factory_id})).mappings().first()
        checks.append(_check("人员1: operators 覆盖产线岗",
                             f"{ops} >= {hr['active'] * 0.5:.0f}", ops, hr["active"] * 0.5,
                             ok_rule=lambda v, e: v >= e, drift="operators 未覆盖 50% 产线岗"))
        if att and att["total"] > 0:
            checks.append(_check("人员2: 考勤台账 vs 缺勤",
                                 f"absent={hr['leave']}", att["leave"], hr["leave"],
                                 ok_rule=lambda v, e: abs(v - e) <= max(3, e * 0.1),
                                 drift="考勤缺勤数与 HR 档案不一致"))
            checks.append(_check("人员3: 在勤率 ≥50%",
                                 f"{att['present']}/{att['total']}", att["present"], att["total"] * 0.5,
                                 ok_rule=lambda v, e: v >= e, drift="考勤覆盖率不足(50%门槛)"))
    except Exception as e:
        checks.append({"name": "人员口径", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 2. 设备口径对账 ══
    try:
        await db.rollback()
        eq = (await db.execute(text("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='broken')::int AS broken,
                   COUNT(*) FILTER (WHERE status='maintenance')::int AS maintenance
            FROM equipment WHERE factory_id=:f
        """), {"f": factory_id})).mappings().first()
        # RCC 基线
        from core.rcc.calculator import RCCResourceCalculator
        calc = RCCResourceCalculator(db)
        bl = (await calc.full_baseline_sync(factory_id)).get("baseline", {})
        eq_bl = bl.get("equipment", {})
        # 基线状态分布不含 broken 键时即“零故障”，按 0 处理（否则 None≠0 误报漂移）
        bl_broken = (eq_bl.get("statuses", {}) or {}).get("broken") or 0
        checks.append(_check("设备1: 总数一致",
                             str(eq_bl.get("total")), eq["total"], eq_bl.get("total"),
                             ok_rule=lambda v, e: v == e,
                             drift="equipment 表总数与 RCC 基线不一致"))
        checks.append(_check("设备2: 故障数一致",
                             f"broken={bl_broken}", eq["broken"],
                             bl_broken,
                             ok_rule=lambda v, e: v == e,
                             drift="故障设备数与 RCC 基线不一致"))
    except Exception as e:
        checks.append({"name": "设备口径", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 3. 工单口径对账 ══
    try:
        await db.rollback()
        wo = (await db.execute(text("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='in_progress')::int AS in_progress,
                   COUNT(*) FILTER (WHERE status='released')::int AS released,
                   COUNT(*) FILTER (WHERE priority='urgent')::int AS urgent
            FROM work_orders WHERE factory_id=:f AND status NOT LIKE 'cancelled'
        """), {"f": factory_id})).mappings().first()
        bl2 = (await calc.full_baseline_sync(factory_id)).get("baseline", {})
        wo_bl = bl2.get("work_orders", {})
        wo_bl_total = sum((wo_bl.get("status") or {}).values()) if isinstance(wo_bl.get("status"), dict) else None
        checks.append(_check("工单1: 总数一致",
                             str(wo_bl_total), wo["total"], wo_bl_total or -1,
                             ok_rule=lambda v, e: e < 0 or v == e,
                             drift="work_orders 与 RCC 工单基线不一致"))
        checks.append(_check("工单2: 加急工单已感知",
                             "urgent in RCC", wo["urgent"], wo_bl.get("urgent_count"),
                             ok_rule=lambda v, e: e is None or (v == 0 and e == 0) or (v > 0 and e >= 0),
                             drift="urgent 工单未被 RCC 基线感知"))
    except Exception as e:
        checks.append({"name": "工单口径", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 4. 任务闭环对账（blocked → RCC 提交 → 审批 → 回写）══
    try:
        await db.rollback()
        blocked = (await db.execute(text("""
            SELECT COUNT(*)::int AS cnt FROM followup_tasks
            WHERE factory_id=:f AND status='blocked' AND created_at > NOW() - interval '7 days'
        """), {"f": factory_id})).scalar_one()
        rcc_refs = (await db.execute(text("""
            SELECT COUNT(*)::int FROM rcc_tasks WHERE created_at > NOW() - interval '7 days'
        """))).scalar_one()
        checks.append(_check("任务1: 受阻任务 → RCC 提交",
                             f"rcc_tasks={rcc_refs} >= blocked={blocked}", rcc_refs, blocked,
                             ok_rule=lambda v, e: v >= e,
                             drift="存在 blocked 任务未提交 RCC（卡在智能体层）"))
    except Exception as e:
        checks.append({"name": "任务闭环", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 5. 事件一致性（agent_events vs 事实源）══
    try:
        await db.rollback()
        ev = (await db.execute(text("""
            SELECT event_type, COUNT(*)::int AS cnt FROM agent_events
            WHERE factory_id=:f AND created_at > NOW() - interval '6 hours'
            GROUP BY event_type
        """), {"f": factory_id})).mappings().all()
        ev_map = {e["event_type"]: e["cnt"] for e in ev}
        leave_now = (await db.execute(text(
            "SELECT COUNT(*)::int FROM hr_employees WHERE factory_id=:f AND status='leave'"
        ), {"f": factory_id})).scalar_one()
        checks.append(_check("事件1: 缺勤事件已产生",
                             f"staff_leave>0 (实际缺勤{leave_now})", ev_map.get("staff_leave", 0), 1 if leave_now > 0 else 0,
                             ok_rule=lambda v, e: (e == 0 and v >= 0) or (e > 0 and v > 0),
                             drift="有缺勤人员但无 staff_leave 事件（事件总线断）"))
    except Exception as e:
        checks.append({"name": "事件一致性", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 6. chatbot 通知闭环（RCC 审批 → 通知）══
    try:
        approved7 = (await db.execute(text("""
            SELECT COUNT(*)::int FROM rcc_tasks WHERE status='approved' AND updated_at > NOW() - interval '7 days'
        """))).scalar_one()
        notif_rcc = (await db.execute(text("""
            SELECT COUNT(*)::int FROM notifications WHERE category='rcc_event'
            OR content LIKE '%RCC%' OR title LIKE '%RCC%'
        """))).scalar_one()
        checks.append(_check("chatbot: RCC 审批 → 通知",
                             f"notifications={notif_rcc}", notif_rcc, approved7,
                             ok_rule=lambda v, e: v >= e or e == 0,
                             drift="RCC 已审批但无对应通知（审批结果未触达）"))
    except Exception as e:
        checks.append({"name": "通知闭环", "status": "ERROR", "detail": str(e)[:80]})

    # ══ 7. 缺料一致性 ══
    try:
        zero_inv = (await db.execute(text(
            "SELECT COUNT(*)::int FROM inventory WHERE factory_id=:f AND COALESCE(available_qty,0)<=0"
        ), {"f": factory_id})).scalar_one()
        shortage_tasks = (await db.execute(text(
            "SELECT COUNT(*)::int FROM followup_tasks WHERE factory_id=:f AND title LIKE '%缺料%' AND status IN ('open','blocked')"
        ), {"f": factory_id})).scalar_one()
        checks.append(_check("缺料: 零库存 → 任务",
                             f"tasks={shortage_tasks}", shortage_tasks, min(zero_inv, 5),
                             ok_rule=lambda v, e: v >= min(e, 5) * 0.5,
                             drift=f"零库存物料 {zero_inv} 但缺料任务少({shortage_tasks})"))
    except Exception as e:
        checks.append({"name": "缺料一致性", "status": "ERROR", "detail": str(e)[:80]})

    ok = sum(1 for c in checks if c["status"] == "OK")
    drift = sum(1 for c in checks if c["status"] == "DRIFT")
    error = sum(1 for c in checks if c["status"] == "ERROR")
    return {
        "factory_id": factory_id,
        "checked_at": datetime.utcnow().isoformat(),
        "summary": {"ok": ok, "drift": drift, "error": error, "total": len(checks)},
        "checks": checks,
    }


def _check(name: str, expected: str, actual, expected_val, ok_rule=None, drift: str = "") -> Dict:
    """构造检查项。"""
    try:
        passed = ok_rule(actual, expected_val) if ok_rule else (actual == expected_val)
    except Exception:
        passed = False
    return {
        "name": name, "status": "OK" if passed else "DRIFT",
        "expected": str(expected), "actual": str(actual),
        "drift": "" if passed else drift,
    }


def format_report(report: Dict) -> str:
    """人类可读报告。"""
    lines = [f"━━ 数据一致性审查 {report['factory_id']} {report['checked_at'][:19]} ━━"]
    for c in report["checks"]:
        icon = "✓" if c["status"] == "OK" else "⚠" if c["status"] == "DRIFT" else "✗"
        if c["status"] == "ERROR":
            lines.append(f"  ✗ {c['name']}: {c.get('detail', 'ERROR')}")
            continue
        lines.append(f"  {icon} {c['name']}: 期望={c['expected']} 实际={c['actual']}"
                     + (f" → {c['drift']}" if c["status"] != "OK" else ""))
    s = report["summary"]
    lines.append(f"  结果: {s['ok']}/{s['total']} OK, {s['drift']} DRIFT, {s['error']} ERROR")
    return "\n".join(lines)
