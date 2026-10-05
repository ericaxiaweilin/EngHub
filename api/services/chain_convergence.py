"""链条收敛自检：无人跑的系统必须能自己回答"这一轮它到底有没有把工厂往前推"。

背景是实测到的一个危险状态：10-05 把扩张上限抬到 600、就绪门打开之后，
可下点数从 185 掉到 79、被压住数从 263 涨到 305 —— **链条在发散**，
而引擎心跳每一轮都是 `tick / 0 failures`：从心跳看不出它在一个劲儿地空转。
无人中心最怕的不是报错，是"一直在跳、一直在跳、但工厂没往前走"。

判据只用库里已有的事实，不新设阈值表；每个数字都说明它来自哪：
- `evaluate_commit_gate`（唯一一处下达判据）给出 ready / held / 已下过；
- `work_orders.released_by='plan-commit-gate'` 给出门真的放行了几张；
- `production_reports` 近 24h 给出**执行侧有没有真实输入** —— 没有报工，缺料就不可能自己清零，
  这一条必须出现在原因里，否则"停滞"会被误读成"算法没干活"；
- 缺口总量、子工单数、方案/任务行数给出写量与需求侧的变化。

上一轮的读数不用另建表：直接读心跳自己那一行的 `last_detail->convergence->metrics`，
所以这份自检是"逐轮对撞"而不是"每次从零开始看"。判定规则写在回执里（`verdict_rules`），
谁都能核。停滞连续满 3 轮会把 `alert` 置上 —— 心跳仍然如实是 tick，但任务中心看得见它卡住了。
"""

from __future__ import annotations
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

METRICS_SQL = text("""
    SELECT
        (SELECT count(*) FROM work_orders wo
          WHERE wo.factory_id = :fid AND wo.wo_type IN ('master', 'component')
            AND wo.status IN ('released', 'in_progress', 'pending')) AS open_pool,
        (SELECT count(*) FROM work_orders wo
          WHERE wo.factory_id = :fid AND wo.wo_type = 'component') AS child_orders,
        (SELECT count(*) FROM work_orders wo
          WHERE wo.factory_id = :fid AND wo.status = 'completed') AS completed_orders,
        (SELECT count(*) FROM work_orders wo
          WHERE wo.factory_id = :fid AND wo.released_by = 'plan-commit-gate') AS released_by_gate,
        (SELECT coalesce(sum(greatest(coalesce(m.shortage_qty, 0), 0)), 0)
          FROM work_order_materials m JOIN work_orders wo ON wo.id = m.work_order_id
          WHERE wo.factory_id = :fid AND wo.status IN ('released', 'in_progress', 'pending')) AS shortage_qty,
        (SELECT count(*) FROM production_reports pr
          WHERE pr.factory_id = :fid AND pr.created_at > now() - interval '24 hours') AS reports_24h,
        (SELECT count(*) FROM production_reports pr
          WHERE pr.factory_id = :fid AND pr.created_at > now() - interval '24 hours'
            AND (pr.created_by = 'virtual_factory' OR pr.report_type = 'virtual_pulse')) AS reports_24h_virtual,
        (SELECT count(*) FROM aps_schedules s
          WHERE s.factory_id = :fid AND s.status <> 'archived') AS live_plans,
        (SELECT count(*) FROM aps_schedule_tasks t JOIN aps_schedules s ON s.id = t.schedule_id
          WHERE s.factory_id = :fid) AS plan_task_rows
""")

PREVIOUS_SQL = text("""
    SELECT last_detail FROM engine_loop_state WHERE loop_name = :loop
""")

STALLED_ALERT_AFTER = 3
SHORTAGE_EPSILON = 0.5  # 缺口是数值列，小于半件的变化当没动


async def measure(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    row = (await db.execute(METRICS_SQL, {"fid": factory_id})).mappings().first()
    metrics = {
        "open_pool": int(row["open_pool"] or 0),
        "child_orders": int(row["child_orders"] or 0),
        "completed_orders": int(row["completed_orders"] or 0),
        "released_by_gate": int(row["released_by_gate"] or 0),
        "shortage_qty": float(row["shortage_qty"] or 0),
        "reports_24h": int(row["reports_24h"] or 0),
        "reports_24h_virtual": int(row["reports_24h_virtual"] or 0),
        "live_plans": int(row["live_plans"] or 0),
        "plan_task_rows": int(row["plan_task_rows"] or 0),
    }
    return metrics


async def read_previous(db: AsyncSession, loop_name: str) -> Optional[Dict[str, Any]]:
    """上一轮记在心跳里的同一份读数（没有就当首轮，不猜）。"""
    row = (await db.execute(PREVIOUS_SQL, {"loop": loop_name})).mappings().first()
    detail = row["last_detail"] if row else None
    if isinstance(detail, str):
        import json
        try:
            detail = json.loads(detail)
        except (ValueError, TypeError):
            return None
    if not isinstance(detail, dict):
        return None
    prev = detail.get("convergence") or {}
    metrics = prev.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return {"metrics": metrics, "stalled_ticks": int(prev.get("stalled_ticks") or 0)}


def judge(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """给一个能核对的判定：推进 / 积压变多 / 停滞，并说清是哪几个数支撑的。

    第一版这里犯过值得记住的错：只要本轮放行 >0 就报 advancing，
    于是"放 5 张、同时新进 10 张、缺口还在涨"被报成"工厂在往前走"—— 假绿灯。
    判据改成看**积压有没有在消**：放行必须快过新增、或缺口/完工真的动了，才算推进。
    """
    if previous is None:
        return {"verdict": "baseline", "stalled_ticks": 0, "alert": False,
                "deltas": {}, "reason": "首轮：只记录基线读数，下一轮开始对撞"}

    before = previous["metrics"]
    deltas = {k: round(float(current[k]) - float(before.get(k, 0)), 4)
              for k in ("completed_orders", "released_by_gate", "shortage_qty",
                        "child_orders", "open_pool", "plan_task_rows")}
    released = deltas["released_by_gate"]
    completed = deltas["completed_orders"]
    shortage = deltas["shortage_qty"]
    pool = deltas["open_pool"]

    # 积压在消：缺口下降、有单真的完工，或放行速度盖过新单进入速度
    draining = (shortage < -SHORTAGE_EPSILON or completed > 0
                or (released > 0 and pool <= 0))
    # 积压在长：缺口变大，或新进来的单不少于放行的单
    growing = (shortage > SHORTAGE_EPSILON) or (pool > 0 and pool >= released)
    stalled_ticks = 0 if draining and not growing else int(previous.get("stalled_ticks") or 0) + 1

    if draining and not growing:
        verdict = "advancing"
        reason = (f"积压在消：完工 {completed:+.0f} 张、放行 {released:+.0f} 张、"
                  f"缺口 {shortage:+.0f} 件")
    elif growing:
        verdict = "diverging"
        reason = (f"积压在长：新进入池子 {pool:+.0f} 张而放行只有 {released:+.0f} 张，"
                  f"缺口 {shortage:+.0f} 件 —— 放行速度盖不住需求生成速度")
    else:
        verdict = "stalled"
        reason = "完工、放行、缺口三个数本轮都没动"

    # 执行侧的口径要说清来源，不能再把虚拟工厂的报工说成"没有真实输入"：
    # 任务本来就由虚拟工厂承担，外部接入是另一路（真实工厂目前只做映射输入）。
    external = int(current["reports_24h"]) - int(current.get("reports_24h_virtual") or 0)
    reason += (
        f"；近 24h 报工 {current['reports_24h']} 条（虚拟工厂脉搏 "
        f"{current.get('reports_24h_virtual')} 条 / 外部接入 {external} 条）—— "
        "执行由虚拟工厂承担，缺口要靠领料扣得动与下层完工入库来消"
    )

    return {
        "verdict": verdict,
        "reason": reason,
        "deltas": deltas,
        "stalled_ticks": stalled_ticks,
        "alert": stalled_ticks >= STALLED_ALERT_AFTER,
        "verdict_rules": {
            "advancing": "缺口下降 或 有单完工 或 (有放行 且 池子没变大)",
            "diverging": "缺口上升 或 (新单进入数 >= 放行数 且有新单)",
            "stalled": "以上都不成立",
            "alert_after_stalled_ticks": STALLED_ALERT_AFTER,
            "shortage_epsilon": SHORTAGE_EPSILON,
        },
    }


async def report(db: AsyncSession, factory_id: str, *, loop_name: str = "routing-backfill",
                 gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """一份逐轮可对账的收敛读数：链条数字 + 与上一轮的对撞 + 判定。"""
    current = await measure(db, factory_id)
    previous = await read_previous(db, loop_name)
    verdict = judge(current, previous)
    out = {
        "factory_id": factory_id,
        "metrics": current,
        "previous_metrics": (previous or {}).get("metrics"),
        **verdict,
    }
    if gate:
        # 就绪门的回执是"这版计划能不能开工"的同一处判据产生的，这里只做转述
        out["commit_gate"] = {
            "schedule_code": gate.get("schedule_code"),
            "plan_status": gate.get("plan_status"),
            "ready_count": gate.get("ready_count"),
            "held_count": gate.get("held_count"),
            "already_released_count": gate.get("already_released_count"),
            "hold_reason_counts": gate.get("hold_reason_counts"),
            "released_this_tick": gate.get("released_orders"),
        }
    return out
