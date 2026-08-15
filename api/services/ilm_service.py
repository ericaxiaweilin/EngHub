"""信息生命周期管理（ILM）服务 — enghub 消息存储治理

策略（按表生命周期）：
- followup_task_logs: >30天 → 聚合归档（log_agg），>90天 → 删除
- notifications: 已读+>30天 → 聚合归档，>60天 → 删除
- followup_tasks: done/cancelled+关闭>7天 → 归档 task，>90天 → 删除
- rcc_tasks: completed/failed+>30天 → 归档，>90天 → 删除
- commander_cycles: >30天 → 保留最新50条，其余归档
- im_messages: >90天 → 删除

返回清理报告（归档数/删除数/释放估算）
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import text

_logger = logging.getLogger("ilm_service")

# 保留策略（天）
RETENTION = {
    "log_agg_after_days": 30,     # 日志聚合阈值
    "log_delete_after_days": 90,  # 日志删除阈值
    "notif_agg_after_days": 30,
    "notif_delete_after_days": 60,
    "task_archive_after_days": 7, # done/cancelled 关闭后归档
    "task_delete_after_days": 90,
    "rcc_archive_after_days": 30,
    "rcc_delete_after_days": 90,
    "cycle_keep_max": 50,         # commander_cycles 保留最新数
    "im_delete_after_days": 90,
}


async def run_ilm(db) -> Dict[str, int]:
    """执行一轮 ILM，返回清理报告。"""
    now = datetime.utcnow()
    report = {"archived_tasks": 0, "archived_notifs": 0, "archived_logs": 0,
              "deleted_logs": 0, "deleted_notifs": 0, "deleted_tasks": 0,
              "deleted_rcc": 0, "deleted_im": 0, "archived_cycles": 0}

    # ── 1) 任务归档：done/cancelled + 关闭 > N 天 ──
    r = await db.execute(text("""
        INSERT INTO archive_records (id, factory_id, record_type, source_id, title, summary, status, owner, meta, archived_at)
        SELECT gen_random_uuid()::text, factory_id, 'task', id, title,
               LEFT(COALESCE(last_follow_note, result_summary, ''), 500), status, created_by,
               jsonb_build_object('agent', agent_key, 'progress', progress_pct,
                                  'follow_count', follow_count, 'closed_at', closed_at),
               :now
        FROM followup_tasks
        WHERE status IN ('done','cancelled') AND closed_at IS NOT NULL
          AND closed_at < :cutoff
          AND id NOT IN (SELECT source_id FROM archive_records WHERE record_type='task')
    """), {"now": now, "cutoff": now - timedelta(days=RETENTION["task_archive_after_days"])})
    report["archived_tasks"] = r.rowcount or 0

    # ── 2) 任务删除：归档后 >90 天 ──
    r = await db.execute(text("""
        DELETE FROM followup_tasks WHERE id IN (
            SELECT source_id FROM archive_records
            WHERE record_type='task' AND archived_at < :cutoff
        )
    """), {"cutoff": now - timedelta(days=RETENTION["task_delete_after_days"] - RETENTION["task_archive_after_days"])})
    report["deleted_tasks"] = r.rowcount or 0

    # ── 3) 日志聚合：>30 天 → log_agg ──
    r = await db.execute(text("""
        INSERT INTO archive_records (id, factory_id, record_type, source_id, title, summary, status, owner, meta, archived_at)
        SELECT gen_random_uuid()::text, MAX(factory_id), 'log_agg', task_id,
               '跟进日志聚合', LEFT(MAX(note), 300), MAX(status_after), NULL,
               jsonb_build_object('count', COUNT(*), 'day', date_trunc('day', created_at)),
               :now
        FROM followup_task_logs
        WHERE created_at < :cutoff
          AND task_id NOT IN (SELECT source_id FROM archive_records WHERE record_type='log_agg')
        GROUP BY task_id, date_trunc('day', created_at)
    """), {"now": now, "cutoff": now - timedelta(days=RETENTION["log_agg_after_days"])})
    report["archived_logs"] = r.rowcount or 0

    # ── 4) 日志删除：>90 天 ──
    r = await db.execute(text("""
        DELETE FROM followup_task_logs WHERE created_at < :cutoff
    """), {"cutoff": now - timedelta(days=RETENTION["log_delete_after_days"])})
    report["deleted_logs"] = r.rowcount or 0

    # ── 5) 通知聚合：已读 + >30 天 ──
    r = await db.execute(text("""
        INSERT INTO archive_records (id, factory_id, record_type, source_id, title, summary, status, owner, meta, archived_at)
        SELECT gen_random_uuid()::text, factory_id, 'notification', NULL,
               '通知聚合', '已读通知汇总', 'archived', NULL,
               jsonb_build_object('count', COUNT(*), 'from', MIN(created_at), 'to', MAX(created_at)),
               :now
        FROM notifications
        WHERE is_read = true AND created_at < :cutoff
        GROUP BY factory_id
    """), {"now": now, "cutoff": now - timedelta(days=RETENTION["notif_agg_after_days"])})
    report["archived_notifs"] = r.rowcount or 0

    # ── 6) 通知删除：已读 + >60 天 ──
    r = await db.execute(text("""
        DELETE FROM notifications WHERE is_read = true AND created_at < :cutoff
    """), {"cutoff": now - timedelta(days=RETENTION["notif_delete_after_days"])})
    report["deleted_notifs"] = r.rowcount or 0

    # ── 7) RCC 任务归档/删除 ──
    r = await db.execute(text("""
        INSERT INTO archive_records (id, factory_id, record_type, source_id, title, summary, status, owner, meta, archived_at)
        SELECT gen_random_uuid()::text, COALESCE((SELECT factory_id FROM org_units ou WHERE ou.id = rcc.org_unit_id), 'FAC_MECH_001'),
               'rcc_task', id, title, LEFT(COALESCE(description, ''), 500), status, requested_by,
               jsonb_build_object('task_type', task_type, 'approved_by', approved_by), :now
        FROM rcc_tasks rcc
        WHERE status IN ('completed','failed','rejected') AND updated_at < :cutoff
          AND id NOT IN (SELECT source_id FROM archive_records WHERE record_type='rcc_task')
    """), {"now": now, "cutoff": now - timedelta(days=RETENTION["rcc_archive_after_days"])})
    r = await db.execute(text("""
        DELETE FROM rcc_tasks WHERE id IN (
            SELECT source_id FROM archive_records
            WHERE record_type='rcc_task' AND archived_at < :cutoff
        )
    """), {"cutoff": now - timedelta(days=RETENTION["rcc_delete_after_days"] - RETENTION["rcc_archive_after_days"])})
    report["deleted_rcc"] = r.rowcount or 0

    # ── 8) commander_cycles 保留最新 50 ──
    r = await db.execute(text("""
        DELETE FROM commander_cycles WHERE id NOT IN (
            SELECT id FROM commander_cycles ORDER BY created_at DESC LIMIT :keep
        ) AND created_at < :cutoff
    """), {"keep": RETENTION["cycle_keep_max"], "cutoff": now - timedelta(days=RETENTION["log_agg_after_days"])})
    report["archived_cycles"] = r.rowcount or 0

    # ── 9) im_messages 删除 >90 天 ──
    r = await db.execute(text("""
        DELETE FROM im_messages WHERE created_at < :cutoff
    """), {"cutoff": now - timedelta(days=RETENTION["im_delete_after_days"])})
    report["deleted_im"] = r.rowcount or 0

    await db.commit()
    return report


def format_report(report: Dict[str, int]) -> str:
    lines = ["━━ ILM 清理报告 ━━"]
    labels = {
        "archived_tasks": "归档任务", "archived_notifs": "归档通知聚合", "archived_logs": "归档日志聚合",
        "deleted_logs": "删除日志", "deleted_notifs": "删除通知", "deleted_tasks": "删除任务",
        "deleted_rcc": "删除RCC任务", "deleted_im": "删除IM消息", "archived_cycles": "清理指挥官快照",
    }
    for k, v in report.items():
        if v:
            lines.append(f"  {labels.get(k, k)}: {v}")
    total = sum(report.values())
    lines.append(f"  合计: {total} 条记录已治理")
    return "\n".join(lines)
