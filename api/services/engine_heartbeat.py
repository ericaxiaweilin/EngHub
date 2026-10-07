"""引擎后台循环的心跳台账。

"无人任务中心"要能被证明是无人也在跑，而不是靠人信。所以每一个循环的每一轮都
往 `engine_loop_state` 落一行：谁（host/pid）、跑没跑完、多久一轮、最近一次
成功/失败、失败原因。读一次就能判断"活着 / 卡住 / 死了"，不用去翻日志。

表结构见 database/migrations/097_engine_heartbeats.sql。
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

TABLE = "engine_loop_state"

# 循环名 -> 期望间隔（秒），心跳超过 2 个间隔没更新就算掉线。
# 循环自己上报 interval_seconds 时以数据库里的值为准，这里只是兜底。
LOOP_INTERVAL_SECONDS: Dict[str, int] = {
    # 30 是循环自己的 sleep 间隔，一轮真实耗时会叠加在上面（实测 50 秒一跳），
    # 判死阈值取 2 倍会误报，所以这里给心脏循环留更宽的容差。
    "periodic-scheduler": 120,
    # 这三个循环现在每轮都自己报心跳（10-04 补的），不再是"只证明起了没崩"
    "model-warmup": 600,
    "skill-seed": 300,
    "followup-scanner": 120,
    "commander-watch": 300,
    # 路线回填循环自己逐轮报心跳（含看了几个产品、回填几张工单）
    "routing-backfill": 900,
}


def window_hours() -> int:
    """崩溃率的滚动窗口长度（小时）。默认 24：够攒上百跳，又短到当天就能暴露回归。

    累计口径的问题不是数字假，是它把插桩之前查不到成因的失败永久压在分子上 ——
    无法归因的数不能当判据，所以判线看窗口，累计只当诊断留档。"""
    try:
        return max(1, int(os.getenv("ENGINE_WINDOW_HOURS", "24")))
    except ValueError:
        return 24


def crash_window_rate(window_ticks: Any, window_failures: Any) -> Optional[float]:
    """窗口崩溃率；没有窗口数据返回 None（算不出，不是 0）。"""
    try:
        ticks = int(window_ticks or 0)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return round(int(window_failures or 0) / ticks, 5)


def expected_interval(loop_name: str) -> int:
    return LOOP_INTERVAL_SECONDS.get(loop_name, 300)


def is_alive(last_tick_at: Optional[datetime], now: Optional[datetime] = None,
             interval: int = 300) -> bool:
    """心跳新鲜度判据：超过 2 个预期间隔没跳就视为没在跑。

    数据库列是 timestamp without time zone（存的是 UTC 墙钟），
    naive 值必须补上 tzinfo 再比较，否则会把未来/过去算错 8 小时。
    """
    if last_tick_at is None:
        return False
    moment = now or datetime.now(timezone.utc)
    stamp = last_tick_at if last_tick_at.tzinfo else last_tick_at.replace(tzinfo=timezone.utc)
    return stamp > moment - timedelta(seconds=max(interval, 1) * 2)


async def record(loop_name: str, status: str = "tick", detail: Optional[Dict[str, Any]] = None,
                 error: Optional[str] = None, interval_seconds: Optional[int] = None) -> None:
    """落一行心跳。心跳本身失败不该把业务循环带崩，所以只记日志。"""
    from database.db_config import db_config

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        async with db_config.session_factory() as db:
            await db.execute(text(f"""
                INSERT INTO {TABLE}
                    (loop_name, host, pid, interval_seconds, started_at,
                     last_tick_at, ticks, failures, last_status, last_error, last_detail,
                     recent_errors, updated_at,
                     window_started_at, window_ticks, window_failures)
                VALUES (:loop, :host, :pid, :interval, :now, :now, 1,
                        CASE WHEN :status = 'failed' THEN 1 ELSE 0 END,
                        :status, :error, CAST(:detail AS jsonb),
                        CASE WHEN :status = 'failed'
                             THEN jsonb_build_array(jsonb_build_object('at', CAST(:now_text AS text), 'error', CAST(:error AS text)))
                             ELSE '[]'::jsonb END,
                        :now, :now, 1,
                        CASE WHEN :status = 'failed' THEN 1 ELSE 0 END)
                ON CONFLICT (loop_name) DO UPDATE SET
                    host = EXCLUDED.host,
                    pid = EXCLUDED.pid,
                    interval_seconds = EXCLUDED.interval_seconds,
                    last_tick_at = EXCLUDED.last_tick_at,
                    ticks = {TABLE}.ticks + 1,
                    failures = {TABLE}.failures + CASE WHEN EXCLUDED.last_status = 'failed' THEN 1 ELSE 0 END,
                    last_status = EXCLUDED.last_status,
                    last_error = CASE WHEN EXCLUDED.last_status = 'failed'
                                      THEN EXCLUDED.last_error ELSE {TABLE}.last_error END,
                    -- 成功心跳不再抹掉错误原文；失败时把这条错误推进最近 5 条的小环
                    recent_errors = CASE WHEN EXCLUDED.last_status = 'failed'
                        THEN (SELECT jsonb_path_query_array(
                                  (EXCLUDED.recent_errors
                                   || CASE WHEN jsonb_typeof({TABLE}.recent_errors) = 'array'
                                           THEN {TABLE}.recent_errors ELSE '[]'::jsonb END),
                                  '$[0 to 4]'))
                        ELSE {TABLE}.recent_errors END,
                    last_detail = EXCLUDED.last_detail,
                    updated_at = EXCLUDED.updated_at,
                    -- 滚动窗口：跨过 ENGINE_WINDOW_HOURS 就重新起算（累计值单独留着当诊断）
                    window_started_at = CASE WHEN {TABLE}.window_started_at IS NULL
                        OR EXCLUDED.last_tick_at - {TABLE}.window_started_at
                           > make_interval(hours => CAST(:window_hours AS int))
                        THEN EXCLUDED.last_tick_at ELSE {TABLE}.window_started_at END,
                    window_ticks = CASE WHEN {TABLE}.window_started_at IS NULL
                        OR EXCLUDED.last_tick_at - {TABLE}.window_started_at
                           > make_interval(hours => CAST(:window_hours AS int))
                        THEN 1 ELSE {TABLE}.window_ticks + 1 END,
                    window_failures = CASE WHEN {TABLE}.window_started_at IS NULL
                        OR EXCLUDED.last_tick_at - {TABLE}.window_started_at
                           > make_interval(hours => CAST(:window_hours AS int))
                        THEN CASE WHEN EXCLUDED.last_status = 'failed' THEN 1 ELSE 0 END
                        ELSE {TABLE}.window_failures
                             + CASE WHEN EXCLUDED.last_status = 'failed' THEN 1 ELSE 0 END END
            """), {
                "loop": loop_name,
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "interval": interval_seconds or expected_interval(loop_name),
                "now": now,
                "now_text": now.isoformat(timespec="seconds"),
                "status": status,
                "error": (error or "")[:500] or None,
                "detail": json_dumps(detail),
                "window_hours": window_hours(),
            })
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[engine-heartbeat] 心跳写入失败 %s: %s", loop_name, exc)


def json_dumps(detail: Optional[Dict[str, Any]]) -> str:
    return json.dumps(detail or {}, ensure_ascii=False, default=str)


async def read_states() -> list:
    """读所有循环的最近心跳，并给出 alive/stale_seconds —— 健康检查与界面共用。"""
    from database.db_config import db_config

    async with db_config.session_factory() as db:
        rows = (await db.execute(text(f"""
            SELECT loop_name, host, pid, interval_seconds, started_at, last_tick_at,
                   ticks, failures, last_status, last_error, last_detail, recent_errors,
                   window_started_at, window_ticks, window_failures
            FROM {TABLE} ORDER BY loop_name
        """))).mappings().all()

    now = datetime.now(timezone.utc)
    out = []
    for row in rows:
        interval = int(row["interval_seconds"] or expected_interval(row["loop_name"]))
        stale = None
        if row["last_tick_at"]:
            stamp = row["last_tick_at"]
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            stale = (now - stamp).total_seconds()
        status = row["last_status"]
        # 只有逐轮报心跳的循环能声称"活着"；一次性任务（skill-seed）跑完就退出，
        # 说它 alive 是假话；崩溃/退出必须显式标出来。
        alive = status == "tick" and is_alive(row["last_tick_at"], now, interval)
        out.append({
            "loop": row["loop_name"],
            "host": row["host"],
            "pid": row["pid"],
            "interval_seconds": interval,
            "alive": alive,
            "state": {
                "tick": "ticking",
                "spawned": "spawned-unverified",
                "exited": "exited",
                "failed": "failed",
            }.get(status, status or "unknown"),
            "stale_seconds": round(stale, 1) if stale is not None else None,
            "ticks": row["ticks"],
            "failures": row["failures"],
            "last_status": status,
            "last_error": row["last_error"],
            # 催办要说"断在几点"，只有 stale_seconds 就得每次现算，还会跟着扫描时刻漂
            "last_tick_at": str(row["last_tick_at"]) if row["last_tick_at"] else None,
            "started_at": str(row["started_at"]) if row["started_at"] else None,
            "recent_errors": row["recent_errors"],
            "window_started_at": str(row["window_started_at"]) if row["window_started_at"] else None,
            "window_ticks": int(row["window_ticks"] or 0),
            "window_failures": int(row["window_failures"] or 0),
            "window_crash_rate": crash_window_rate(row["window_ticks"], row["window_failures"]),
        })
    return out
