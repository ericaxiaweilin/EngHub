"""旧排产草案的 keep-last-N 回收：只清系统自己生成的历史版本，一条业务事实都不留。

为什么会堆：排程是逐版存的（PMC 要比对版本），而引擎在扩张期每轮输入都真的变了
（新建子工单、齐套刷新改了缺口）→ 每轮一份 ~1,000 行的新方案。实测 10-05：
FAC_MECH_001 攒了 295 份 draft、`aps_schedule_tasks` 22,075 行 / 9.5MB，
其中 18,361 行属于"保留最近 3 版"之外的旧草案 —— 全是没被确认过的中间产物。

这不是原始数据：工单、物料、BOM、台账过账一条都不碰；删掉的每一行都能由
"当前输入 + 排程算法"重新算出来。**但有三条东西不能跟着一起掉**，所以判据是白名单式的：

1. 只删 `status='draft'` 且 `is_current=false` 的方案 —— 确认过的、下达过的、
   归档过的（那是"当时下了什么计划"的记录）一律不动；
2. 每个厂区按 (is_current desc, created_at desc, version desc) 保留最近 N 版；
3. **仍会影响排程的锁定工序所在草案不删**：`load_pinned_tasks` 是按
   (工单, 工序序号) 取最新版本再看是否 locked，删掉那一行等于抹掉计划员的决定。
   口径与排程一致：`planned_end < now` 的历史锁已经不参与排程，可以随草案一起回收。

删除动作只走一条 SQL 路径，并且 WHERE 里重复一遍守卫（防止 select 与 delete 之间
恰好有人确认了这份方案）；`aps_schedule_tasks` 先删（它是唯一有外键指向方案表的表），
方案表后删；每次回收写一条 `drafts_pruned` 事件，把删掉的 schedule id 列进 payload ——
行可以再生，"删过什么"必须留痕。

默认只预演（`APS_DRAFT_PRUNE_ENABLED`），保留版数走 `APS_DRAFT_KEEP_VERSIONS`。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SELECTION_SQL = text("""
    WITH ranked AS (
        SELECT s.id, s.factory_id, s.schedule_code, s.version_number, s.created_at,
               ROW_NUMBER() OVER (PARTITION BY s.factory_id
                   ORDER BY s.is_current DESC, s.created_at DESC, s.version_number DESC) AS rn
        FROM aps_schedules s
        WHERE s.status = 'draft' AND COALESCE(s.is_current, FALSE) = FALSE
          AND (:fid = '' OR s.factory_id = :fid)
    ),
    live_lock AS (
        SELECT DISTINCT ON (t.work_order_id, t.operation_seq) t.schedule_id
        FROM aps_schedule_tasks t
        JOIN aps_schedules s ON s.id = t.schedule_id
        WHERE COALESCE(t.is_locked, FALSE) = TRUE
          AND COALESCE(t.status, '') NOT IN ('completed', 'cancelled')
          AND t.planned_end >= :now
          AND s.status = 'draft'
        ORDER BY t.work_order_id, t.operation_seq, s.version_number DESC, t.created_at DESC
    )
    SELECT r.id, r.factory_id, r.schedule_code, r.version_number, r.created_at, r.rn,
           (SELECT count(*) FROM aps_schedule_tasks t WHERE t.schedule_id = r.id) AS task_rows,
           EXISTS (SELECT 1 FROM live_lock l WHERE l.schedule_id = r.id) AS holds_live_lock
    FROM ranked r
    WHERE r.rn > :keep
    ORDER BY r.created_at
""")

PROTECTED_SQL = text("""
    SELECT count(*) FILTER (WHERE status = 'draft' AND COALESCE(is_current, FALSE)) AS draft_marked_current,
           count(*) FILTER (WHERE status IN ('confirmed', 'released')) AS confirmed_or_released,
           count(*) FILTER (WHERE status = 'archived') AS archived,
           count(*) FILTER (WHERE status = 'draft' AND COALESCE(is_current, FALSE) = FALSE) AS drafts
    FROM aps_schedules WHERE (:fid = '' OR factory_id = :fid)
""")

DELETE_TASKS_SQL = text("""
    DELETE FROM aps_schedule_tasks
    WHERE schedule_id = ANY(CAST(:ids AS text[]))
      AND schedule_id IN (
          SELECT id FROM aps_schedules
          WHERE status = 'draft' AND COALESCE(is_current, FALSE) = FALSE
      )
""")

DELETE_SCHEDULES_SQL = text("""
    DELETE FROM aps_schedules
    WHERE id = ANY(CAST(:ids AS text[]))
      AND status = 'draft' AND COALESCE(is_current, FALSE) = FALSE
""")

SIZE_SQL = text("SELECT pg_total_relation_size('aps_schedule_tasks') AS tasks_bytes, "
                "pg_total_relation_size('aps_schedules') AS schedules_bytes")

AUDIT_CAP = 100


async def plan_prune(db: AsyncSession, *, factory_id: str = "", keep: int = 3) -> Dict[str, Any]:
    """只读预演：哪些草案在回收窗口外、各带多少行、哪几份因为还压着锁定工序必须留下。"""
    now = datetime.utcnow()
    rows = (await db.execute(SELECTION_SQL, {"fid": factory_id, "now": now, "keep": keep})).mappings().all()
    prunable = [r for r in rows if not r["holds_live_lock"]]
    held = [r for r in rows if r["holds_live_lock"]]
    protected = (await db.execute(PROTECTED_SQL, {"fid": factory_id})).mappings().first()
    sizes = (await db.execute(SIZE_SQL)).mappings().first()
    return {
        "factory_id": factory_id or "全部厂区",
        "keep_versions": keep,
        "candidates": len(rows),
        "prunable": len(prunable),
        "prunable_task_rows": sum(int(r["task_rows"] or 0) for r in prunable),
        "held_by_live_lock": len(held),
        "held_by_live_lock_task_rows": sum(int(r["task_rows"] or 0) for r in held),
        "held_examples": [
            {"schedule_code": r["schedule_code"], "task_rows": int(r["task_rows"] or 0)}
            for r in held[:5]
        ],
        "examples": [
            {"schedule_code": r["schedule_code"], "version_number": r["version_number"],
             "task_rows": int(r["task_rows"] or 0),
             "created_at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in prunable[:5]
        ],
        "protected_untouched": {
            "draft_marked_current": int((protected["draft_marked_current"] or 0)),
            "confirmed_or_released": int(protected["confirmed_or_released"] or 0),
            "archived": int(protected["archived"] or 0),
            "drafts_total": int(protected["drafts"] or 0),
        },
        "sizes_before": {"aps_schedule_tasks": int(sizes["tasks_bytes"]),
                         "aps_schedules": int(sizes["schedules_bytes"])},
        "ids": [str(r["id"]) for r in prunable],
        "rule": (f"仅动 status='draft' 且非 is_current 的方案；每厂区保留最近 {keep} 版；"
                 "仍会影响排程的锁定工序所在草案跳过；确认/下达/归档的一律不碰"),
    }


async def prune_superseded_drafts(
    db: AsyncSession, *, factory_id: str = "", keep: int = 3,
    apply: bool = False, actor: str = "aps-draft-prune",
) -> Dict[str, Any]:
    """执行回收。apply=False 时一行都不删（心跳与预演端点走的就是这条路）。"""
    plan = await plan_prune(db, factory_id=factory_id, keep=keep)
    receipt = {k: v for k, v in plan.items() if k != "ids"}
    receipt["dry_run"] = not apply
    ids: List[str] = plan["ids"]
    if not ids:
        receipt["status"] = "nothing_to_prune"
        receipt["message"] = (f"没有超出保留窗口（最近 {keep} 版）的可回收草案；"
                             f"因锁定工序被保住的 {plan['held_by_live_lock']} 份仍原样留着")
        return receipt
    if not apply:
        receipt["status"] = "dry_run"
        receipt["message"] = (
            f"预演：可回收 {plan['prunable']} 份草案 / {plan['prunable_task_rows']} 行任务明细；"
            f"另有 {plan['held_by_live_lock']} 份压着仍算数的锁定工序，不动"
        )
        return receipt

    deleted_tasks = (await db.execute(DELETE_TASKS_SQL, {"ids": ids})).rowcount
    deleted_schedules = (await db.execute(DELETE_SCHEDULES_SQL, {"ids": ids})).rowcount
    sizes_after = (await db.execute(SIZE_SQL)).mappings().first()
    db.add(_prune_event(factory_id, actor, ids, int(deleted_tasks or 0),
                        int(deleted_schedules or 0), keep))
    await db.commit()
    receipt.update({
        "status": "ok",
        "deleted_task_rows": int(deleted_tasks or 0),
        "deleted_schedules": int(deleted_schedules or 0),
        "sizes_after": {"aps_schedule_tasks": int(sizes_after["tasks_bytes"]),
                        "aps_schedules": int(sizes_after["schedules_bytes"])},
        "reclaimed_bytes": plan["sizes_before"]["aps_schedule_tasks"]
        + plan["sizes_before"]["aps_schedules"]
        - int(sizes_after["tasks_bytes"]) - int(sizes_after["schedules_bytes"]),
        "message": (
            f"已回收 {deleted_schedules} 份旧草案与 {deleted_tasks} 行任务明细"
            f"（保留最近 {keep} 版；确认/下达/归档的一条没动；"
            f"压着锁定工序的 {plan['held_by_live_lock']} 份跳过）"
        ),
    })
    return receipt


def _prune_event(factory_id: str, actor: str, ids: List[str], task_rows: int,
                 schedules: int, keep: int):
    from database.models import ApsPlanEvent

    return ApsPlanEvent(
        id=str(uuid.uuid4()),
        factory_id=factory_id or "ALL",
        event_type="drafts_pruned",
        actor=actor,
        schedule_id=None,
        reason=f"keep-last-{keep} 回收旧草案：{schedules} 份 / {task_rows} 行任务明细",
        payload={"pruned_schedule_ids": ids[:AUDIT_CAP], "pruned_total": len(ids),
                 "pruned_task_rows": task_rows, "keep_versions": keep,
                 "audit_truncated_at": AUDIT_CAP},
    )


KEEP_VERSIONS = max(1, int(os.getenv("APS_DRAFT_KEEP_VERSIONS", "3")))
APPLY_ENABLED = os.getenv("APS_DRAFT_PRUNE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
