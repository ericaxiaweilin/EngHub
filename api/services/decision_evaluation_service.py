"""
RCC 决策效果回评估引擎（Decision Effect Evaluation）
====================================================
设计原则：上游部门的决策一定会影响下游部门。
每个 RCC 决策执行后不再是黑盒，而是进入「追踪 → 度量 → 定论 → 通报」闭环：

1. 执行时刻（T0）：注册评估记录，锁定预期效果 + 关键指标基线快照，
   并立即向受影响的下游部门发出「决策影响预警」通知；
2. 追踪期：按动作类型的间隔周期复测同一组指标（工单进度/交期、
   PO 到货、库存、全厂逾期压力等），量化决策的实际效果与下游波及；
3. 定论：满足终态条件（目标达成/失败/超窗）后给出 achieved/partial/failed
   结论，并向下游部门 + 审批人发出「决策效果报告」通知，形成组织记忆。

对外提供列表/汇总/强制评估接口，供 RCC 决策中枢页面展示决策质量看板。
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

_logger = logging.getLogger(__name__)

EVAL_LOOP_INTERVAL_SECONDS = int(os.getenv("DECISION_EVAL_INTERVAL_SECONDS", "3600"))
EVAL_FIRST_DELAY_SECONDS = int(os.getenv("DECISION_EVAL_FIRST_DELAY_SECONDS", "90"))
EVAL_BATCH_LIMIT = 50

# ──────────────────────────────────────────────────────────────
# 动作元数据：评估间隔 / 最大评估次数 / 受影响的下游部门 / 预期描述
# ──────────────────────────────────────────────────────────────
ACTION_META: Dict[str, Dict[str, Any]] = {
    "expedite": {
        "interval_hours": 12, "max_evaluations": 10,
        "downstream": ["procurement", "production", "warehouse"],
        "expectation": "目标工单提速：进度持续推进并在交期内完成；下游采购需保障物料、产线让渡产能",
    },
    "rush_insert": {
        "interval_hours": 12, "max_evaluations": 10,
        "downstream": ["procurement", "production", "warehouse"],
        "expectation": "插单成功释放产线：工单 urgent 投产、进度推进；下游需承接额外负荷与物料需求",
    },
    "change_priority": {
        "interval_hours": 12, "max_evaluations": 10,
        "downstream": ["procurement", "production"],
        "expectation": "优先级调整被产线执行并推动进度；被降序工单的交期风险由下游承接",
    },
    "reschedule": {
        "interval_hours": 24, "max_evaluations": 8,
        "downstream": ["procurement", "warehouse", "production"],
        "expectation": "新交期被采纳并保持；物料到货节奏需与新交期匹配（采购/仓储承接）",
    },
    "place_order": {
        "interval_hours": 24, "max_evaluations": 10,
        "downstream": ["warehouse", "quality", "production"],
        "expectation": "PO 在预期交付日内到货入库；仓储承接收货、IQC 承接检验、产线等待齐料",
    },
    "cancel_order": {
        "interval_hours": 24, "max_evaluations": 4,
        "downstream": ["procurement", "warehouse", "production"],
        "expectation": "单据取消释放资源；下游需确认无关联工单因此断料/断单",
    },
    "reject_order": {
        "interval_hours": 24, "max_evaluations": 6,
        "downstream": ["procurement", "production"],
        "expectation": "PR 重新指派供应商并生成替代 PO；采购周期延长风险由计划侧承接",
    },
}

WO_TERMINAL = ("completed", "cancelled", "closed")


# ══════════════════════════════════════════════════════════════
# 度量原语（基线与复测共用同一组函数，保证口径一致）
# ══════════════════════════════════════════════════════════════
async def _wo_snapshot(db, target: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text(
        "SELECT work_order_code, status, priority, planned_due, planned_qty, completed_qty "
        "FROM work_orders WHERE id=:t OR work_order_code=:t LIMIT 1"
    ), {"t": target})).mappings().first()
    if not row:
        return None
    planned = float(row["planned_qty"] or 0)
    done = float(row["completed_qty"] or 0)
    return {
        "code": row["work_order_code"], "status": row["status"], "priority": row["priority"],
        "planned_due": str(row["planned_due"])[:10] if row["planned_due"] else None,
        "progress_pct": round(done / planned * 100, 1) if planned > 0 else 0.0,
    }


async def _factory_pressure(db, factory_id: str) -> Dict[str, Any]:
    row = (await db.execute(text(
        "SELECT COUNT(*)::int AS active, "
        "COUNT(*) FILTER (WHERE planned_due IS NOT NULL AND planned_due < NOW() "
        "AND status NOT IN ('completed','cancelled','closed'))::int AS overdue "
        "FROM work_orders WHERE factory_id=:f"
    ), {"f": factory_id})).mappings().first()
    return {"active_orders": row["active"], "overdue_orders": row["overdue"]}


async def _po_snapshot(db, target: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text(
        "SELECT po_code, status, material_code, qty, expected_date, actual_date "
        "FROM purchase_orders WHERE id=:t OR po_code=:t LIMIT 1"
    ), {"t": target})).mappings().first()
    if not row:
        return None
    today = datetime.utcnow().date()
    exp = row["expected_date"]
    return {
        "code": row["po_code"], "status": row["status"], "material_code": row["material_code"],
        "expected_date": str(exp) if exp else None,
        "actual_date": str(row["actual_date"]) if row["actual_date"] else None,
        "overdue_days": max(0, (today - exp).days) if exp and str(row["status"]) not in ("received", "arrived", "completed", "cancelled") else 0,
    }


async def _material_stock(db, factory_id: str, material_code: Optional[str]) -> Optional[float]:
    if not material_code:
        return None
    v = (await db.execute(text(
        "SELECT COALESCE(SUM(COALESCE(available_qty,0)), 0) FROM inventory "
        "WHERE factory_id=:f AND material_code=:m"
    ), {"f": factory_id, "m": material_code})).scalar_one()
    return float(v)


async def _pr_snapshot(db, target: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text(
        "SELECT pr_code, status, material_code, qty, supplier_id "
        "FROM purchase_requisitions WHERE id=:t OR pr_code=:t LIMIT 1"
    ), {"t": target})).mappings().first()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════
# 注册：决策执行成功后调用，锁定预期 + 基线，并预警下游
# ══════════════════════════════════════════════════════════════
async def register_decision(db, task) -> Optional[str]:
    """task 为 RCCTask ORM 对象（需含 factory_id/affected_params）。失败不抛异常。"""
    try:
        ap = getattr(task, "affected_params", None) or {}
        if isinstance(ap, str):
            ap = json.loads(ap)
        action = ap.get("action", "") if isinstance(ap, dict) else ""
        target = str(ap.get("target", "") or "") if isinstance(ap, dict) else ""
        params = ap.get("params", {}) if isinstance(ap, dict) else {}
        meta = ACTION_META.get(action)
        factory_id = getattr(task, "factory_id", None)
        if not action or not meta or not factory_id:
            return None

        # T0 基线快照（按动作类型采集相关指标）
        baseline: Dict[str, Any] = {}
        expectations: Dict[str, Any] = {"summary": meta["expectation"]}
        if action in ("expedite", "rush_insert", "change_priority", "reschedule", "cancel_order"):
            wo = await _wo_snapshot(db, target)
            if wo:
                baseline["work_order"] = wo
                if action == "change_priority":
                    expectations["target_priority"] = params.get("priority", "urgent")
                if action == "reschedule":
                    expectations["new_due"] = str(params.get("new_due") or params.get("planned_due") or "")[:10]
        if action in ("place_order", "reject_order"):
            pr = await _pr_snapshot(db, target)
            if pr:
                baseline["pr"] = {k: str(v) for k, v in dict(pr).items()}
                baseline["stock"] = await _material_stock(db, factory_id, pr.get("material_code"))
        if action in ("cancel_order", "reject_order"):
            po = await _po_snapshot(db, target)
            if po:
                baseline["po"] = po
                baseline["stock"] = await _material_stock(db, factory_id, po.get("material_code"))
        baseline["factory_pressure"] = await _factory_pressure(db, factory_id)

        eval_id = str(uuid.uuid4())
        await db.execute(text(
            "INSERT INTO rcc_decision_evaluations (id, factory_id, rcc_task_id, task_code, action, target, "
            "status, executed_at, approved_by, expectations, baseline, evaluation_count, max_evaluations, "
            "next_evaluate_at, created_at, updated_at) "
            "VALUES (:id, :f, :tid, :tc, :act, :tgt, 'tracking', NOW(), :by, CAST(:exp AS jsonb), "
            "CAST(:bl AS jsonb), 0, :mx, NOW() + (:iv || ' hours')::interval, NOW(), NOW())"
        ), {"id": eval_id, "f": factory_id, "tid": task.id,
            "tc": getattr(task, "task_code", None), "act": action, "tgt": target,
            "by": getattr(task, "approved_by", None),
            "exp": json.dumps(expectations, ensure_ascii=False),
            "bl": json.dumps(baseline, ensure_ascii=False),
            "mx": meta["max_evaluations"], "iv": str(meta["interval_hours"])})

        # 下游预警：决策已执行，波及范围即刻可见（上游决策 → 下游感知）
        await _notify(db, factory_id, recipients=meta["downstream"],
                      title=f"[决策影响预警] {action} → {target or '未知目标'}",
                      content=f"RCC 已执行决策 {action}（审批人 {getattr(task, 'approved_by', '?')}）。"
                              f"预期：{meta['expectation']}。系统将持续追踪效果并通报波及情况。",
                      severity="info", source_id=eval_id)
        await db.commit()
        return eval_id
    except Exception as e:
        _logger.warning(f"[decision-eval] 注册失败(不阻塞审批): {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return None


# ══════════════════════════════════════════════════════════════
# 评估：复测指标 → 判定 → 终态时通报下游与审批人
# ══════════════════════════════════════════════════════════════
async def evaluate_one(db, rec: Dict[str, Any]) -> Dict[str, Any]:
    action = rec["action"]
    target = rec["target"] or ""
    factory_id = rec["factory_id"]
    baseline = rec["baseline"] if isinstance(rec["baseline"], dict) else {}
    expectations = rec["expectations"] if isinstance(rec["expectations"], dict) else {}
    meta = ACTION_META.get(action, {"downstream": [], "interval_hours": 24})

    measure: Dict[str, Any] = {}
    verdict: Optional[str] = None  # achieved / partial / failed
    notes: List[str] = []

    wo_actions = ("expedite", "rush_insert", "change_priority", "reschedule", "cancel_order")
    if action in wo_actions:
        wo = await _wo_snapshot(db, target)
        if wo:
            measure["work_order"] = wo
        base_wo = baseline.get("work_order") or {}
        if action == "cancel_order":
            if wo and wo["status"] == "cancelled":
                verdict, notes = "achieved", ["单据保持取消状态，资源已释放"]
            elif wo:
                verdict, notes = "failed", [f"单据状态回弹为 {wo['status']}，取消未生效"]
        elif action == "reschedule":
            want = expectations.get("new_due")
            if wo and want:
                if (wo.get("planned_due") or "")[:10] == want[:10]:
                    verdict, notes = "achieved", [f"新交期 {want} 已采纳并保持"]
                else:
                    verdict = "partial"
                    notes.append(f"交期被再次调整为 {wo.get('planned_due')}（原决策目标 {want}）")
        elif action == "change_priority":
            want_prio = expectations.get("target_priority", "urgent")
            if wo and wo["priority"] == want_prio:
                p0, p1 = float(base_wo.get("progress_pct") or 0), wo["progress_pct"]
                if p1 >= p0 + 10 or wo["status"] in WO_TERMINAL:
                    verdict, notes = "achieved", [f"优先级 {want_prio} 已执行，进度 {p0}% → {p1}%"]
                else:
                    verdict, notes = "partial", [f"优先级已生效但进度未推进（{p0}% → {p1}%）"]
            elif wo:
                verdict, notes = "failed", [f"优先级为 {wo['priority']}，决策未被执行"]
        else:  # expedite / rush_insert
            if not wo:
                verdict, notes = "failed", ["目标工单已不存在"]
            elif wo["status"] in ("completed",):
                verdict, notes = "achieved", ["工单已完成，决策目标达成"]
            elif wo["status"] in ("cancelled", "closed"):
                verdict, notes = "failed", [f"工单被 {wo['status']}，决策目标未达成"]
            else:
                p0, p1 = float(base_wo.get("progress_pct") or 0), wo["progress_pct"]
                if p1 >= p0 + 10:
                    verdict, notes = "achieved", [f"进度持续推进 {p0}% → {p1}%，决策生效"]
                elif rec["evaluation_count"] + 1 >= rec["max_evaluations"]:
                    verdict, notes = "partial", [f"追踪窗口结束，进度 {p0}% → {p1}%，推进不明显"]
                else:
                    notes.append(f"进度 {p0}% → {p1}%，继续追踪")

    elif action == "place_order":
        # target 是 PR；找到其转化后的 PO 追踪到货
        po = (await db.execute(text(
            "SELECT po_code, status, material_code, expected_date, actual_date FROM purchase_orders "
            "WHERE pr_id=:t OR pr_id=(SELECT id FROM purchase_requisitions WHERE id=:t OR pr_code=:t LIMIT 1) LIMIT 1"
        ), {"t": target})).mappings().first()
        if po:
            snap = await _po_snapshot(db, po["po_code"])
            measure["po"] = snap
            st = snap["status"]
            if st in ("received", "arrived", "completed"):
                verdict, notes = "achieved", [f"PO {snap['code']} 已到货入库，物料保障达成"]
            elif st == "cancelled":
                verdict, notes = "failed", [f"PO {snap['code']} 被取消，下单决策失效"]
            elif snap["overdue_days"] >= 3:
                verdict, notes = "failed", [f"PO {snap['code']} 逾期 {snap['overdue_days']} 天未到货"]
            else:
                notes.append(f"PO {snap['code']} 状态 {st}，预期到货 {snap['expected_date']}")
            measure["stock_now"] = await _material_stock(db, factory_id, snap.get("material_code"))
        else:
            if rec["evaluation_count"] + 1 >= rec["max_evaluations"]:
                verdict, notes = "failed", ["追踪窗口结束仍未生成 PO"]
            else:
                notes.append("PO 尚未生成，继续追踪")
        if baseline.get("stock") is not None and measure.get("stock_now") is not None:
            measure["stock_delta"] = round(measure["stock_now"] - float(baseline["stock"]), 2)

    elif action == "reject_order":
        pr = await _pr_snapshot(db, target)
        if pr:
            measure["pr"] = {k: str(v) for k, v in dict(pr).items()}
            if str(pr["status"]) == "converted":
                verdict, notes = "achieved", ["PR 已重新转化新 PO，替代供应到位"]
            elif pr["supplier_id"] and str(pr["status"]) == "assigned":
                verdict, notes = "partial", ["PR 已重新指派供应商，待转 PO"]
            elif rec["evaluation_count"] + 1 >= rec["max_evaluations"]:
                verdict, notes = "failed", ["追踪窗口结束 PR 仍未重新指派"]
            else:
                notes.append(f"PR 状态 {pr['status']}，等待重新指派")
        else:
            verdict, notes = "failed", ["目标 PR 已不存在"]

    # 下游波及量化（每次评估都刷新）
    downstream: Dict[str, Any] = {}
    pressure = await _factory_pressure(db, factory_id)
    base_pressure = baseline.get("factory_pressure") or {}
    downstream["production"] = {
        "overdue_orders": pressure["overdue_orders"],
        "overdue_delta": pressure["overdue_orders"] - int(base_pressure.get("overdue_orders") or 0),
    }
    in_po = (await db.execute(text(
        "SELECT COUNT(*)::int FROM purchase_orders WHERE factory_id=:f "
        "AND status IN ('ordered','partial')"
    ), {"f": factory_id})).scalar_one()
    downstream["procurement"] = {"in_flight_po": in_po}
    if measure.get("po") and measure["po"].get("overdue_days", 0) > 0:
        downstream["warehouse"] = {"pending_receipt_overdue": measure["po"]["overdue_days"]}
    measure["factory_pressure"] = pressure

    # 落库
    count = int(rec["evaluation_count"]) + 1
    finalized = verdict is not None
    new_status = verdict if finalized else "tracking"
    next_at = (datetime.utcnow() + timedelta(hours=meta.get("interval_hours", 24))) if not finalized else None
    await db.execute(text(
        "UPDATE rcc_decision_evaluations SET status=:st, latest_measure=CAST(:m AS jsonb), "
        "downstream_impact=CAST(:dw AS jsonb), verdict_note=:note, evaluation_count=:c, "
        "last_evaluated_at=NOW(), next_evaluate_at=:nx, finalized_at=CASE WHEN :fin THEN NOW() ELSE finalized_at END, "
        "updated_at=NOW() WHERE id=:id"
    ), {"st": new_status, "m": json.dumps(measure, ensure_ascii=False, default=str),
        "dw": json.dumps(downstream, ensure_ascii=False, default=str),
        "note": "；".join(notes) if notes else None, "c": count,
        "nx": next_at, "fin": finalized, "id": rec["id"]})

    # 终态通报：下游部门 + 审批人都要看到决策的最终效果（组织记忆）
    if finalized:
        sev = {"achieved": "success", "partial": "warning", "failed": "critical"}[verdict]
        label = {"achieved": "达成", "partial": "部分达成", "failed": "未达成"}[verdict]
        recipients = list(meta.get("downstream", []))
        if rec.get("approved_by"):
            recipients.append(rec["approved_by"])
        await _notify(db, factory_id, recipients=recipients,
                      title=f"[决策效果报告] {action} → {target or '未知目标'}：{label}",
                      content=f"决策效果定论：{'；'.join(notes)}。"
                              f"下游波及：生产逾期 {downstream['production']['overdue_orders']} 单"
                              f"（较决策时 {downstream['production']['overdue_delta']:+d}），"
                              f"在途 PO {downstream['procurement']['in_flight_po']} 张。",
                      severity=sev, source_id=rec["id"])
    await db.commit()
    return {"id": rec["id"], "status": new_status, "verdict": verdict, "notes": notes}


async def evaluate_due(db) -> Dict[str, Any]:
    """评估所有到期的追踪中记录。"""
    rows = (await db.execute(text(
        "SELECT * FROM rcc_decision_evaluations WHERE status='tracking' "
        "AND next_evaluate_at <= NOW() ORDER BY next_evaluate_at LIMIT :n"
    ), {"n": EVAL_BATCH_LIMIT})).mappings().all()
    results = []
    for r in rows:
        try:
            results.append(await evaluate_one(db, dict(r)))
        except Exception as e:
            _logger.warning(f"[decision-eval] 评估 {r['id']} 失败: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
    return {"evaluated": len(results), "results": results}


async def force_evaluate(db, eval_id: str) -> Dict[str, Any]:
    rec = (await db.execute(text(
        "SELECT * FROM rcc_decision_evaluations WHERE id=:id"
    ), {"id": eval_id})).mappings().first()
    if not rec:
        return {"error": "评估记录不存在"}
    return await evaluate_one(db, dict(rec))


# ══════════════════════════════════════════════════════════════
# 查询 / 汇总
# ══════════════════════════════════════════════════════════════
async def list_evaluations(db, factory_id: Optional[str] = None, status: Optional[str] = None,
                           limit: int = 30) -> List[Dict[str, Any]]:
    cond, params = "1=1", {"limit": limit}
    if factory_id:
        cond += " AND factory_id=:f"
        params["f"] = factory_id
    if status:
        cond += " AND status=:st"
        params["st"] = status
    rows = (await db.execute(text(
        f"SELECT * FROM rcc_decision_evaluations WHERE {cond} "
        "ORDER BY COALESCE(finalized_at, last_evaluated_at, created_at) DESC LIMIT :limit"
    ), params)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("expectations", "baseline", "latest_measure", "downstream_impact"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


async def evaluation_summary(db, factory_id: Optional[str] = None) -> Dict[str, Any]:
    cond, params = "1=1", {}
    if factory_id:
        cond = "factory_id=:f"
        params["f"] = factory_id
    rows = (await db.execute(text(
        f"SELECT action, status, COUNT(*)::int AS cnt FROM rcc_decision_evaluations "
        f"WHERE {cond} GROUP BY action, status"
    ), params)).mappings().all()
    by_action: Dict[str, Dict[str, int]] = {}
    totals = {"tracking": 0, "achieved": 0, "partial": 0, "failed": 0}
    for r in rows:
        by_action.setdefault(r["action"], {"tracking": 0, "achieved": 0, "partial": 0, "failed": 0})
        if r["status"] in totals:
            totals[r["status"]] += r["cnt"]
            by_action[r["action"]][r["status"]] += r["cnt"]
    finalized = totals["achieved"] + totals["partial"] + totals["failed"]
    return {
        "totals": totals,
        "finalized": finalized,
        # 达成率：achieved 占已定论决策的比例（决策质量的硬指标）
        "achievement_rate_pct": round(totals["achieved"] / finalized * 100, 1) if finalized else None,
        "by_action": by_action,
    }


# ══════════════════════════════════════════════════════════════
# 通知与后台循环
# ══════════════════════════════════════════════════════════════
async def _notify(db, factory_id: str, recipients: List[str], title: str, content: str,
                  severity: str = "info", source_id: Optional[str] = None):
    for r in recipients:
        await db.execute(text(
            "INSERT INTO notifications (id, factory_id, recipient, category, title, content, "
            "severity, source_type, source_id, is_read, created_at) "
            "VALUES (:id, :f, :r, 'decision_impact', :t, :c, :sv, 'decision_evaluation', :sid, FALSE, NOW())"
        ), {"id": str(uuid.uuid4()), "f": factory_id, "r": r, "t": title, "c": content,
            "sv": severity, "sid": source_id})


async def decision_eval_loop():
    """后台评估循环：启动延迟后每 EVAL_LOOP_INTERVAL_SECONDS 扫一轮到期记录。"""
    await asyncio.sleep(EVAL_FIRST_DELAY_SECONDS)
    from database.db_config import db_config
    while True:
        try:
            async with db_config.session_factory() as db:
                res = await evaluate_due(db)
                if res["evaluated"]:
                    _logger.info(f"[decision-eval] 本轮评估 {res['evaluated']} 条决策记录")
        except Exception as e:
            _logger.warning(f"[decision-eval] 循环异常: {e}")
        await asyncio.sleep(EVAL_LOOP_INTERVAL_SECONDS)
