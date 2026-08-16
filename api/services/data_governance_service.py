"""数据治理层：防止追加型表无限膨胀（架构级修复）。

背景（实测教训）：
- warehouse_agent 补货无去重，同物料刷出 8553+ 张重复 PR，ghost 表
  purchase_requests 9 天堆积 27 万行/51MB；
- notifications/production_alerts/agent_events 等追加表只进不出，
  单日通知峰值 1513 条、告警单日峰值 2.8 万条；
- 各写入点去重标准不一，靠逐个修补不可持续。

本服务提供统一的后台治理循环（默认每 6 小时一轮）：
1. 保留策略（retention）：追加型表按「保留天数 + 硬上限」双约束裁剪，
   先到先裁；删除分批执行，避免长事务锁表。
2. 业务去重扫描（dedup sweep）：对已知重复模式做幂等清理
   （如 enghub_bom_items 重复导入）。
3. 治理结果写入日志，可通过 DATA_GOVERNANCE_ENABLED=0 关闭。

写入侧去重仍是第一道防线（见 warehouse_agent_service / factory_commander）；
本层是兜底，保证任何新增的无去重写入点也不会拖垮数据库。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from sqlalchemy import text

_logger = logging.getLogger("data_governance")

# ── 保留策略：(表名, 时间列, 保留天数, 行数硬上限) ──
# 硬上限按当前体量的 2~3 倍设定，超限时从最旧开始裁剪。
RETENTION_RULES: List[Dict[str, Any]] = [
    {"table": "agent_events", "ts": "created_at", "keep_days": 30, "max_rows": 200_000},
    {"table": "notifications", "ts": "created_at", "keep_days": 90, "max_rows": 50_000},
    {"table": "production_alerts", "ts": "created_at", "keep_days": 90, "max_rows": 20_000},
    {"table": "chat_session_events", "ts": "created_at", "keep_days": 30, "max_rows": 100_000},
    {"table": "followup_task_logs", "ts": "created_at", "keep_days": 60, "max_rows": 50_000},
]

# 终态任务归档线：完成/取消的跟进任务超过该天数后清理（保留近期可追溯）
FOLLOWUP_TERMINAL_KEEP_DAYS = 60
FOLLOWUP_TERMINAL_STATUSES = ("done", "completed", "cancelled", "canceled")

DELETE_BATCH = 2_000  # 单批删除行数，避免长事务


async def _table_exists(db, table: str) -> bool:
    r = await db.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name=:t LIMIT 1"
    ), {"t": table})
    return r.scalar_one_or_none() is not None


async def _apply_retention(db, rule: Dict[str, Any]) -> int:
    """对单表执行保留策略，返回删除行数。"""
    table, ts = rule["table"], rule["ts"]
    if not await _table_exists(db, table):
        return 0
    total = 0
    # 1) 时间维度裁剪
    while True:
        r = await db.execute(text(
            f"DELETE FROM {table} WHERE id IN ("
            f"  SELECT id FROM {table} WHERE {ts} < NOW() - INTERVAL '{rule['keep_days']} days'"
            f"  LIMIT {DELETE_BATCH})"
        ))
        n = r.rowcount or 0
        total += n
        await db.commit()
        if n < DELETE_BATCH:
            break
    # 2) 硬上限裁剪（保留最新 max_rows 行）
    while True:
        r = await db.execute(text(
            f"DELETE FROM {table} WHERE id IN ("
            f"  SELECT id FROM {table} ORDER BY {ts} DESC OFFSET {rule['max_rows']}"
            f"  LIMIT {DELETE_BATCH})"
        ))
        n = r.rowcount or 0
        total += n
        await db.commit()
        if n < DELETE_BATCH:
            break
    return total


async def _sweep_bom_duplicates(db) -> int:
    """enghub_bom_items 由外部导入，重复同步会产生同 (型号,料号,层级) 多行。

    保留每组 id 最小的一行（bom_sync_service 全量重建时不受影响）。
    """
    if not await _table_exists(db, "enghub_bom_items"):
        return 0
    total = 0
    while True:
        r = await db.execute(text(f"""
            DELETE FROM enghub_bom_items WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY product_model, part_number, level
                        ORDER BY id) AS rn
                    FROM enghub_bom_items
                ) x WHERE rn > 1 LIMIT {DELETE_BATCH}
            )
        """))
        n = r.rowcount or 0
        total += n
        await db.commit()
        if n < DELETE_BATCH:
            break
    return total


async def _sweep_terminal_followups(db) -> int:
    """清理超龄终态跟进任务（done/cancelled），控制任务中心体量。"""
    if not await _table_exists(db, "followup_tasks"):
        return 0
    statuses = ",".join(f"'{s}'" for s in FOLLOWUP_TERMINAL_STATUSES)
    r = await db.execute(text(
        f"DELETE FROM followup_tasks WHERE status IN ({statuses}) "
        f"AND updated_at < NOW() - INTERVAL '{FOLLOWUP_TERMINAL_KEEP_DAYS} days'"
    ))
    await db.commit()
    return r.rowcount or 0


async def run_governance_cycle(db) -> Dict[str, int]:
    """执行一轮完整治理，返回各项清理行数。"""
    report: Dict[str, int] = {}
    for rule in RETENTION_RULES:
        try:
            report[f"retention:{rule['table']}"] = await _apply_retention(db, rule)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            _logger.warning("保留策略执行失败 %s: %s", rule["table"], exc)
    try:
        report["dedup:enghub_bom_items"] = await _sweep_bom_duplicates(db)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        _logger.warning("BOM 去重扫描失败: %s", exc)
    try:
        report["archive:followup_tasks"] = await _sweep_terminal_followups(db)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        _logger.warning("终态任务清理失败: %s", exc)
    return report


async def data_governance_loop() -> None:
    """后台治理循环（main.py startup 启动）。

    首轮启动后 2 分钟执行（尽快压制存量膨胀），之后每 6 小时一轮。
    DATA_GOVERNANCE_ENABLED=0 可关闭；DATA_GOVERNANCE_INTERVAL_SECONDS 调间隔。
    """
    if os.getenv("DATA_GOVERNANCE_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        _logger.info("数据治理循环已禁用（DATA_GOVERNANCE_ENABLED=0）")
        return
    interval = max(3600, int(os.getenv("DATA_GOVERNANCE_INTERVAL_SECONDS", "21600") or 21600))
    _logger.info("数据治理循环启动，每 %s 秒一轮", interval)
    from database.db_config import db_config
    first = True
    while True:
        await asyncio.sleep(120 if first else interval)
        first = False
        try:
            async with db_config.session_factory() as db:
                report = await run_governance_cycle(db)
            cleaned = {k: v for k, v in report.items() if v}
            if cleaned:
                _logger.info("数据治理完成: %s", cleaned)
            else:
                _logger.debug("数据治理完成：无需清理")
        except Exception as exc:  # noqa: BLE001
            _logger.warning("数据治理循环异常: %s", exc)


__all__ = ["RETENTION_RULES", "run_governance_cycle", "data_governance_loop"]
