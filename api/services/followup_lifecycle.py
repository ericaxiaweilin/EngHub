"""缺料催办的生命周期：齐套了自己关，催不动了就升级 —— 判定按台账证据，不按模型的说法。

跟进循环原来把任务交给 LLM"核实"，关闭与进度都由它的一句话决定。于是两种错都能发生：
库里缺口早就补平了（收货已过账），任务还每 4 小时催一次人；反过来模型说"已解决"而
台账仍写着缺口时，它也会被标成完成。两种都是拿说法当事实。

三条规则，全部要求"证据存在"（空集合不等于通过）：

① **齐套关闭**：`work_order_materials` 对该单有行、且缺口行数=0 → 关闭，
   结论里写清几行、合计可领多少件，依据是台账而不是某人的判断。
② **没有快照行 = 不判齐套**：0 行既可能是"都齐了"也可能是"根本没算过"，
   分不清就继续催，并把"没有齐套依据"写进结论（这类单在就绪门里叫 no_kit_evidence）。
③ **催不动升级**：连续 N 轮缺口没有变小（对比创建时记下的 shortage_total）→
   挂一条升级待办，把"改期/调线/外购/停机"四个选项摆给有裁量权的人；
   原催办转 blocked 并写明"已升级"。同一张工单只挂一条升级待办。

进度也改成按证据算：缺口从 47 件降到 20 件就是 57.4%，不再是模型填的整数。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 催几轮缺口没动就升级（240 分钟一轮 → 默认约 3 天）
STALL_ROUNDS = max(1, int(os.getenv("FOLLOWUP_ESCALATE_AFTER_STALL_ROUNDS", "3")))

CATEGORY = "material_shortage"
ESCALATION_CATEGORY = "material_shortage_escalation"

KIT_STATE_SQL = text("""
    SELECT count(*) AS evidence_lines,
           count(*) FILTER (WHERE GREATEST(COALESCE(m.shortage_qty, 0), 0) > 0) AS shortage_lines,
           ROUND(GREATEST(COALESCE(SUM(GREATEST(COALESCE(m.shortage_qty, 0), 0)), 0), 0)::numeric, 3)
               AS shortage_qty,
           count(*) FILTER (WHERE m.item_type = 'buy') AS buy_lines,
           count(*) FILTER (WHERE m.item_type = 'make') AS make_lines
    FROM work_order_materials m
    JOIN work_orders w ON w.id = m.work_order_id
    WHERE w.id = CAST(:wo_id AS text) AND w.factory_id = :fid
""")

# 升级给"比当前责任人高一级"的岗位。岗位字典按 hr_employees 里真实存在的值写，
# 库里现在最高只到 线长/组长 —— 没有主管、经理、厂长这些行，所以升级多半会落到
# "映射不到"这一支，那是主数据缺口，要如实报出去而不是随便抓个名字填上。
POSITION_RANK = ["操作员", "技术员", "设备工程师", "采购员", "采购专员", "物控员",
                 "组长", "线长", "主管", "经理", "部长", "厂长"]
_SENIOR_OR = ("'组长', '线长', '主管', '经理', '部长', '厂长'")
_ESCALATION_OWNER_SQL = text(f"""
    SELECT name, position, department, station
    FROM hr_employees
    WHERE factory_id = :fid AND status = 'active'
      AND position IN ({_SENIOR_OR})
      AND (
            (:role = 'purchase' AND department = '采购部')
         OR (:role = 'make' AND (station = :station_name OR station = :station_alias))
          )
    ORDER BY CASE position
               WHEN '线长' THEN 0 WHEN '主管' THEN 1 WHEN '经理' THEN 2
               WHEN '部长' THEN 3 WHEN '厂长' THEN 4 WHEN '组长' THEN 5
               ELSE 6 END,
             name
    LIMIT 1
""")

# 四个裁量选项：机器不替人决定，但要把人需要比较的东西一次摆齐
ESCALATION_OPTIONS = (
    "① 改期（顺延交期并重排这张单）② 调线（同型制另一条线做）"
    "③ 外购/代料（走采购或替代料审批）④ 停线待料（接受闲置并通知下游）"
)


def rank_of(position: Optional[str]) -> int:
    try:
        return POSITION_RANK.index(str(position or ""))
    except ValueError:
        return -1


def evidence_progress_pct(recorded: Optional[float], current: Optional[float]) -> Optional[float]:
    """按缺口下降算进度百分比；没有基线（recorded<=0）就不给百分比，不编一个 0%。"""
    if not recorded or recorded <= 0:
        return None
    base = float(recorded or 0)
    now = float(current or 0)
    if now >= base:
        return 0.0
    return round(100.0 * (base - now) / base, 1)


def is_stalled(recorded: Optional[float], current: Optional[float],
               follow_count: int, *, rounds: int = STALL_ROUNDS) -> bool:
    """催了 rounds 轮以上、缺口一点没变小 —— 判定为催不动。"""
    base = float(recorded or 0)
    if base <= 0 or int(follow_count or 0) < rounds:
        return False
    return float(current or 0) >= base


OPEN_TASKS_SQL = text("""
    SELECT id, factory_id, created_by, title, description, agent_key, status,
           block_reason, follow_count, max_follows, progress_pct, assigned_to, payload
    FROM followup_tasks
    WHERE factory_id = :fid AND status IN ('open', 'blocked')
      AND payload->>'category' = :cat
    ORDER BY last_follow_at NULLS FIRST, created_at DESC
    LIMIT :lim
""")


async def open_shortage_tasks(db: AsyncSession, factory_id: str,
                              *, limit: int = 50) -> list:
    """本厂还没关的缺料催办（含已 blocked 的：blocked 更要复判，缺口可能早就补平了）。"""
    rows = (await db.execute(OPEN_TASKS_SQL,
                             {"fid": factory_id, "cat": CATEGORY, "lim": limit})).mappings().all()
    return [dict(r) for r in rows]


def veto_model_closure(new_status: str, conclusion: Dict[str, Any],
                       lifecycle: Dict[str, Any]) -> str:
    """缺料催办不许凭模型的一句话关闭：台账还写着缺口就退回 open，并把两边说法都留下。

    实测有过两条写着"缺口已补齐 / 缺料已完全解决"的已完成任务，齐套台账里仍挂着
    5 件和 544 件缺口。规则放在这里而不是跟进循环里，是为了能被单测钉住。
    """
    if new_status != "done":
        return new_status
    kit = (lifecycle or {}).get("kit") or {}
    if kit.get("state") != "short":
        return new_status
    conclusion["state"] = "open"
    conclusion["progress_pct"] = int((lifecycle or {}).get("evidence_progress_pct") or 0)
    conclusion["note"] = (f"{conclusion.get('note', '')}｜未关闭：模型判定已完成，但齐套台账仍有 "
                          f"{kit['shortage_lines']}/{kit['evidence_lines']} 行缺口、合计 "
                          f"{kit['shortage_qty']:g} 件（{kit['basis']}）—— 以台账为准继续催。")
    return "open"


async def kit_state(db: AsyncSession, factory_id: str, work_order_id: str) -> Dict[str, Any]:
    """这一单的齐套台账现状：有几行依据、几行还缺、合计缺多少。"""
    row = (await db.execute(KIT_STATE_SQL,
                            {"wo_id": str(work_order_id), "fid": str(factory_id)})).mappings().first()
    lines = int((row or {}).get("evidence_lines") or 0)
    short_lines = int((row or {}).get("shortage_lines") or 0)
    short_qty = float((row or {}).get("shortage_qty") or 0)
    if lines == 0:
        state = "no_evidence"
        note = "齐套快照里没有这一单的任何物料行 → 无法判定齐套，不能当齐套关闭"
    elif short_lines == 0:
        state = "complete"
        note = f"齐套快照 {lines} 行缺口全部归零 → 可投产"
    else:
        state = "short"
        note = f"齐套快照 {lines} 行中仍有 {short_lines} 行缺口，合计 {short_qty:g} 件"
    return {
        "state": state,
        "evidence_lines": lines,
        "shortage_lines": short_lines,
        "shortage_qty": short_qty,
        "buy_lines": int((row or {}).get("buy_lines") or 0),
        "make_lines": int((row or {}).get("make_lines") or 0),
        "note": note,
        "basis": "work_order_materials（齐套快照，按当前库存台账刷新）",
    }


async def escalation_owner(db: AsyncSession, factory_id: str, role: str,
                           station_name: Optional[str]) -> Dict[str, Any]:
    """找比责任人高一级的岗位；找不到就把缺口写明白，不编名字。"""
    alias = (station_name or "").replace("车间", "").replace("工位", "")
    row = (await db.execute(_ESCALATION_OWNER_SQL, {
        "fid": factory_id, "role": role,
        "station_name": station_name or "", "station_alias": alias,
    })).mappings().first()
    if not row:
        return {
            "assigned_to": None, "position": None,
            "gap": (f"HR 岗位台账里找不到可承接升级的岗位（本厂 active 人员岗位只到 "
                    f"组长/线长一级，采购部只有采购员；无 主管/经理/厂长 行）"
                    f"—— 升级单挂任务中心等人工认领，请人事补管理岗岗位行"),
        }
    return {"assigned_to": str(row["name"]), "position": str(row["position"]),
            "gap": None,
            "basis": f"{row['department']}·{row['position']}（station={row['station'] or '-'}）"}


CLOSED_TASKS_SQL = text("""
    SELECT id, factory_id, created_by, title, description, agent_key, status,
           block_reason, follow_count, max_follows, progress_pct, assigned_to,
           payload, closed_at, result_summary, follow_interval_minutes
    FROM followup_tasks
    WHERE factory_id = :fid AND status = 'done'
      AND payload->>'category' = :cat
      AND closed_at >= NOW() - make_interval(days => :days)
    ORDER BY closed_at DESC
    LIMIT :lim
""")


async def audit_false_closures(db: AsyncSession, factory_id: str, *, days: int = 7,
                               limit: int = 50, apply: bool = False) -> Dict[str, Any]:
    """复核"已关闭"的缺料催办：台账还写着缺口的就是误关闭，重新打开并写明证据。

    为什么必须有这一段：关闭原来只由模型一句话决定，实测就有两条写着"缺口已补齐 /
    缺料已完全解决"，而齐套台账里还挂着 5 件和 544 件缺口。缺口没补平就关掉催办，
    等于机器自己把阻塞从视图里擦掉 —— 下游看到的是"没人催了"，不是"料到了"。
    """
    rows = (await db.execute(CLOSED_TASKS_SQL, {
        "fid": factory_id, "cat": CATEGORY, "days": int(days), "lim": int(limit),
    })).mappings().all()

    findings = []
    reopened = 0
    for row in rows:
        task = dict(row)
        payload = task.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
        payload = payload or {}
        wo_id = str(payload.get("work_order_id") or "")
        if not wo_id:
            continue
        kit = await kit_state(db, factory_id, wo_id)
        if kit["state"] != "short":
            continue          # complete=关得对；no_evidence=判不了，不冤枉它
        note = (f"误关闭复核：这条已被判定完成，但齐套台账仍显示 "
                f"{kit['shortage_lines']}/{kit['evidence_lines']} 行缺口、合计 "
                f"{kit['shortage_qty']:g} 件（依据 {kit['basis']}）。"
                f"原结论：{str(task.get('result_summary') or '')[:160]}")
        findings.append({"task_id": str(task["id"]),
                         "work_order_code": payload.get("work_order_code"),
                         "closed_at": str(task.get("closed_at") or ""),
                         "kit": kit, "note": note})
        if apply:
            interval = int(task.get("follow_interval_minutes") or 240)
            await db.execute(text("""
                UPDATE followup_tasks
                SET status = 'open', progress_pct = LEAST(progress_pct, 99.0),
                    last_follow_note = :note, result_summary = NULL, closed_at = NULL,
                    next_follow_at = NOW() + make_interval(mins => :mins),
                    block_reason = :reason, updated_at = NOW()
                WHERE id = :id
            """), {"note": note, "mins": interval, "id": str(task["id"]),
                   "reason": f"复核后重开：台账仍缺 {kit['shortage_qty']:g} 件"})
            await _log(db, str(task["id"]), factory_id, "false_closure_reopened",
                       note, "open", float(task.get("progress_pct") or 0))
            await _notify_owner(db, task, "缺料催办复核后重开", note, "warning")
            await db.commit()
            reopened += 1

    return {
        "factory_id": factory_id, "apply": apply, "days": int(days),
        "closed_examined": len(rows), "false_closures": len(findings),
        "reopened": reopened, "items": findings,
        "rule": "关闭是否成立只看齐套台账的缺口数；快照没有行的已完成任务不判误关闭（分不清就没冤枉）。",
    }


async def _escalation_exists(db: AsyncSession, factory_id: str, work_order_id: str) -> bool:
    found = (await db.execute(text("""
        SELECT 1 FROM followup_tasks
        WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
          AND payload->>'category' = :cat
          AND payload->>'work_order_id' = :wo_id
        LIMIT 1
    """), {"fid": factory_id, "cat": ESCALATION_CATEGORY, "wo_id": str(work_order_id)})).first()
    return found is not None


async def sync_shortage_task(db: AsyncSession, task: Dict[str, Any],
                             *, apply: bool = False) -> Dict[str, Any]:
    """按台账证据推进一条缺料催办：关闭 / 升级 / 继续，并回报依据。

    apply=False 只出判定不动库（默认，界面和巡检先看判定准不准）；
    apply=True 才真的关闭与挂升级单。
    """
    payload = task.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
    payload = payload or {}
    work_order_id = str(payload.get("work_order_id") or "")
    if str(payload.get("category") or "") != CATEGORY or not work_order_id:
        return {"action": "not_applicable", "reason": "不是缺料催办（没有 material_shortage 类别或工单号）"}

    kit = await kit_state(db, str(task.get("factory_id") or ""), work_order_id)
    recorded = payload.get("shortage_total")
    follow_count = int(task.get("follow_count") or 0)
    progress = evidence_progress_pct(recorded, kit["shortage_qty"])
    outcome: Dict[str, Any] = {
        "task_id": str(task.get("id") or ""),
        "work_order_code": payload.get("work_order_code"),
        "kit": kit,
        "recorded_shortage": recorded,
        "follow_count": follow_count,
        "evidence_progress_pct": progress,
        "apply": apply,
    }

    if kit["state"] == "no_evidence":
        outcome["action"] = "keep_open_no_evidence"
        outcome["note"] = kit["note"]
        return outcome

    if kit["state"] == "complete":
        outcome["action"] = "close_kit_complete"
        outcome["note"] = (f"自动关闭：{kit['note']}。催办创建时缺口 "
                           f"{recorded if recorded is not None else '-'} 件 → 现在 0 件，"
                           f"依据 {kit['basis']}，跟进 {follow_count} 轮。")
        if apply:
            await db.execute(text("""
                UPDATE followup_tasks
                SET status = 'done', progress_pct = 100.0, last_follow_at = NOW(),
                    last_follow_note = :note, result_summary = :note, closed_at = NOW(),
                    next_follow_at = NULL, updated_at = NOW()
                WHERE id = :id AND status <> 'done'
            """), {"note": outcome["note"], "id": outcome["task_id"]})
            await _log(db, outcome["task_id"], str(task.get("factory_id") or ""),
                       "kit_auto_close", outcome["note"], "done", 100.0)
            await _notify_owner(db, task, "缺料催办已自动关闭", outcome["note"], "info")
            await db.commit()
        return outcome

    stalled = is_stalled(recorded, kit["shortage_qty"], follow_count)
    if not stalled:
        outcome["action"] = "continue"
        outcome["note"] = kit["note"]
        if apply and progress is not None:
            # 进度按缺口下降算，覆盖掉模型填的猜测值
            await db.execute(text("""
                UPDATE followup_tasks SET progress_pct = :pct, updated_at = NOW()
                WHERE id = :id
            """), {"pct": progress, "id": outcome["task_id"]})
            await db.commit()
        return outcome

    role = "purchase" if kit["buy_lines"] >= kit["make_lines"] else "make"
    already = await _escalation_exists(db, str(task.get("factory_id") or ""), work_order_id)
    if already:
        outcome["action"] = "escalation_already_open"
        outcome["note"] = (f"升级单已在任务中心等待裁决，这条催办不再重复追人（催 {follow_count} 轮，"
                           f"仍缺 {kit['shortage_qty']:g} 件）")
        if apply:
            await db.execute(text("""
                UPDATE followup_tasks
                SET status = 'blocked', block_reason = :reason, last_follow_at = NOW(),
                    last_follow_note = :note, next_follow_at = NULL, updated_at = NOW()
                WHERE id = :id AND status <> 'blocked'
            """), {"reason": "已升级，等人工裁决", "note": outcome["note"], "id": outcome["task_id"]})
            await db.commit()
        return outcome

    outcome["action"] = "escalated"
    outcome["note"] = (f"催不动升级：已跟进 {follow_count} 轮，缺口 "
                       f"{kit['shortage_qty']:g} 件 ≥ 创建时的 {recorded:g} 件，一轮没少。"
                       f"需要人来裁：{ESCALATION_OPTIONS}")
    if not apply:
        return outcome

    # 责任人所在工位要从路线首道工序反查（沿用缺料催办的同一口径，不在这里另算一份）
    station_name = await _station_for_order(db, str(task.get("factory_id") or ""), work_order_id)
    target = await escalation_owner(db, str(task.get("factory_id") or ""), role, station_name)
    from api.services.followup_task_service import create_task

    title = (f"升级｜{payload.get('work_order_code')} 催 {follow_count} 轮缺口未动"
             f"（仍缺 {kit['shortage_qty']:g} 件）→ 需裁决")[:200]
    description = (
        f"{outcome['note']}\n"
        f"受阻工单：{payload.get('work_order_code')}（机种 {payload.get('model_code') or '-'}，"
        f"计划 {payload.get('planned_qty')} 件）\n"
        f"还缺 {kit['shortage_lines']} 行：外购 {kit['buy_lines']} 行、自制 {kit['make_lines']} 行\n"
        f"原催办责任人：{task.get('assigned_to') or '（未指派）'}"
        f"{'；升级承接人：' + str(target['assigned_to']) if target['assigned_to'] else ''}"
        f"{'。' + target['gap'] if target['gap'] else ''}\n"
        f"证据来源：{kit['basis']}"
    )
    created = await create_task(
        db, str(task.get("factory_id") or ""), str(task.get("created_by") or "virtual_factory"),
        title, description=description,
        agent_key="procurement_agent" if role == "purchase" else "pmc_agent",
        item_type="assigned" if target["assigned_to"] else "followup",
        assigned_to=target["assigned_to"],
        block_reason=target["gap"] or f"缺口 {kit['shortage_qty']:g} 件催 {follow_count} 轮未动，需人工裁决",
        source="virtual_factory",
        conversation_hint="四个选项选一个并说明代价；不选就等于默认停线待料。",
        payload=json.dumps({
            "category": ESCALATION_CATEGORY,
            "work_order_id": work_order_id,
            "work_order_code": payload.get("work_order_code"),
            "model_code": payload.get("model_code"),
            "planned_qty": payload.get("planned_qty"),
            "shortage_qty": kit["shortage_qty"],
            "shortage_lines": kit["shortage_lines"],
            "escalated_from": outcome["task_id"],
            "options": ESCALATION_OPTIONS,
            "basis": kit["basis"],
        }, ensure_ascii=False),
        follow_interval_minutes=24 * 60,
    )
    outcome["escalation_task_id"] = created.get("task_id")
    outcome["escalation_assigned_to"] = target["assigned_to"]
    outcome["escalation_gap"] = target["gap"]
    outcome["escalation_station"] = station_name

    # 收件箱按"下次跟进"排序且只渲染前 10 行：按 24 小时节奏挂出来的升级单会沉到第 2 页之后，
    # 界面上等于没挂过。第一次跟进提前到 5 分钟后，之后照 24 小时走。
    if created.get("task_id"):
        await db.execute(text("""
            UPDATE followup_tasks SET next_follow_at = NOW() + INTERVAL '5 minutes'
            WHERE id = :id
        """), {"id": str(created["task_id"])})

    # 原催办停下，避免同一个人继续被每 4 小时催一次
    await db.execute(text("""
        UPDATE followup_tasks
        SET status = 'blocked', block_reason = :reason, last_follow_at = NOW(),
            last_follow_note = :note, next_follow_at = NULL, updated_at = NOW()
        WHERE id = :id
    """), {"reason": f"已升级待人工裁决（催 {follow_count} 轮缺口未动）",
           "note": outcome["note"], "id": outcome["task_id"]})
    await _log(db, outcome["task_id"], str(task.get("factory_id") or ""),
               "escalated", outcome["note"], "blocked", progress or 0.0)
    await _notify_owner(db, task, "缺料催办升级：需要人来裁", outcome["note"], "warning")
    await db.commit()
    return outcome


async def _station_for_order(db: AsyncSession, factory_id: str,
                             work_order_id: str) -> Optional[str]:
    """这张单首道工序落在哪个工位（HR 的 station 存中文工位名，升级要按它找人）。

    路线→工位、工位→中文名 两步都复用缺料催办那份 SQL，不在这里另起一套口径。
    """
    from api.services.material_followup import STATION_NAME_SQL, _primary_stations

    code = (await _primary_stations(db, factory_id, [work_order_id])).get(work_order_id)
    if not code:
        return None
    return (await db.execute(STATION_NAME_SQL, {"fid": factory_id, "code": code})).scalar()


async def _log(db: AsyncSession, task_id: str, factory_id: str, trigger: str,
               note: str, status: str, progress_pct: float) -> None:
    from api.services.followup_task_service import _append_log

    await _append_log(db, task_id, factory_id, trigger, note, status, progress_pct, "system")


async def _notify_owner(db: AsyncSession, task: Dict[str, Any], title: str,
                        content: str, severity: str) -> None:
    from api.services.followup_task_service import _notify

    for recipient in {str(task.get("assigned_to") or "").strip(),
                      str(task.get("created_by") or "").strip()} - {""}:
        await _notify(db, str(task.get("factory_id") or ""), recipient, title, content, severity)
