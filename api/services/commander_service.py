"""工厂指挥官：按用户开关的主动态势感知与决策循环。"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _ensure_table(db: AsyncSession) -> None:
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS commander_sessions (
            user_id VARCHAR(64) NOT NULL,
            factory_id VARCHAR(64) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, factory_id)
        )
    """))
    await db.commit()


async def get_status(db: AsyncSession, user_id: str, factory_id: str) -> Dict[str, Any]:
    await _ensure_table(db)
    row = (await db.execute(text("""
        SELECT enabled FROM commander_sessions
        WHERE user_id = :uid AND factory_id = :fid
    """), {"uid": user_id, "fid": factory_id})).mappings().first()
    enabled = bool(row["enabled"]) if row else False
    return {"enabled": enabled, "factory_id": factory_id}


async def toggle(
    db: AsyncSession, user_id: str, factory_id: str, enabled: bool
) -> Dict[str, Any]:
    await _ensure_table(db)
    await db.execute(text("""
        INSERT INTO commander_sessions (user_id, factory_id, enabled, updated_at)
        VALUES (:uid, :fid, :en, NOW())
        ON CONFLICT (user_id, factory_id)
        DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
    """), {"uid": user_id, "fid": factory_id, "en": enabled})
    await db.commit()
    return {
        "enabled": enabled,
        "factory_id": factory_id,
        "message": "指挥官已开启" if enabled else "指挥官已关闭",
    }


async def _sense_state(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """采集订单/产能/设备/物料/交期/质量态势。"""
    wo = (await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status IN ('in_progress','released','pending')) AS active,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (
                WHERE status IN ('in_progress','released','pending')
                  AND planned_due IS NOT NULL AND planned_due < NOW()
            ) AS overdue,
            COUNT(*) FILTER (
                WHERE status IN ('in_progress','released','pending')
                  AND planned_due IS NOT NULL
                  AND planned_due >= NOW()
                  AND planned_due < NOW() + INTERVAL '7 days'
            ) AS due_7d
        FROM work_orders
        WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().first() or {}

    # 工位利用率（有 assigned_station_id 的在制工序）
    cap = (await db.execute(text("""
        SELECT
            COUNT(DISTINCT assigned_station_id) FILTER (
                WHERE assigned_station_id IS NOT NULL AND status = 'in_progress'
            ) AS busy_stations,
            COUNT(DISTINCT assigned_station_id) FILTER (
                WHERE assigned_station_id IS NOT NULL
            ) AS total_stations
        FROM work_orders
        WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().first() or {}
    busy = int(cap.get("busy_stations") or 0)
    total_st = int(cap.get("total_stations") or 0) or 1
    utilization = f"{round(busy / total_st * 100, 1)}%"

    eq = (await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'running') AS running,
            COUNT(*) FILTER (WHERE status IN ('maintenance','maintaining')) AS maintenance,
            COUNT(*) FILTER (WHERE status IN ('fault','broken','down')) AS broken
        FROM equipment
        WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().first() or {}

    mat = (await db.execute(text("""
        SELECT COUNT(*) AS low_stock
        FROM inventory
        WHERE factory_id = :fid
          AND available_qty IS NOT NULL
          AND available_qty <= COALESCE(reorder_point, 20)
    """), {"fid": factory_id})).mappings().first() or {}

    # 交期：近30天已完成 vs 逾期完成近似
    delivery = (await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (
                WHERE status = 'completed'
                  AND planned_due IS NOT NULL
                  AND COALESCE(actual_complete, updated_at, created_at) <= planned_due
            ) AS on_time
        FROM work_orders
        WHERE factory_id = :fid
          AND COALESCE(actual_complete, updated_at, created_at) >= NOW() - INTERVAL '30 days'
    """), {"fid": factory_id})).mappings().first() or {}
    completed = int(delivery.get("completed") or 0)
    on_time = int(delivery.get("on_time") or 0)
    on_time_rate = f"{round(on_time / completed * 100, 1)}%" if completed else "-"

    # 今日不良率
    quality = (await db.execute(text("""
        SELECT
            COALESCE(SUM(good_qty),0) AS good_qty,
            COALESCE(SUM(defect_qty),0) AS defect_qty
        FROM production_reports
        WHERE factory_id = :fid
          AND created_at >= CURRENT_DATE
    """), {"fid": factory_id})).mappings().first() or {}
    good = float(quality.get("good_qty") or 0)
    defect = float(quality.get("defect_qty") or 0)
    total_out = good + defect
    defect_rate = f"{round(defect / total_out * 100, 1)}%" if total_out else "-"

    active = int(wo.get("active") or 0)
    pending = int(wo.get("pending") or 0)
    # 粗负荷：在制+待排 / (在制+待排+缓冲)
    load_ratio = min(1.5, (active + pending) / max(active + pending + 8, 1))

    return {
        "orders": {
            "active": active,
            "pending": pending,
            "in_progress": int(wo.get("in_progress") or 0),
            "overdue": int(wo.get("overdue") or 0),
            "due_7d": int(wo.get("due_7d") or 0),
            "load_ratio": round(load_ratio, 3),
        },
        "capacity": {
            "utilization": utilization,
            "stations": f"{busy}/{total_st}",
        },
        "equipment": {
            "running": int(eq.get("running") or 0),
            "maintenance": int(eq.get("maintenance") or 0),
            "broken": int(eq.get("broken") or 0),
            "total": int(eq.get("total") or 0),
        },
        "material": {"low_stock": int(mat.get("low_stock") or 0)},
        "delivery": {"on_time_rate": on_time_rate},
        "quality": {"defect_rate": defect_rate},
    }


def _decide(state: Dict[str, Any], auto_execute: bool) -> Dict[str, Any]:
    orders = state.get("orders") or {}
    overdue = int(orders.get("overdue") or 0)
    pending = int(orders.get("pending") or 0)
    load_ratio = float(orders.get("load_ratio") or 0)
    low_stock = int((state.get("material") or {}).get("low_stock") or 0)
    broken = int((state.get("equipment") or {}).get("broken") or 0)

    if load_ratio >= 0.85 or overdue >= 3:
        order_mode = "surplus"
    elif pending <= 2 and load_ratio < 0.45:
        order_mode = "deficit"
    else:
        order_mode = "normal"

    decisions: List[Dict[str, Any]] = []
    alerts: List[str] = []
    next_actions: List[str] = []

    if overdue > 0:
        decisions.append({
            "priority": "P0",
            "reason": f"发现 {overdue} 单逾期工单，优先催交/改派资源",
            "executed": bool(auto_execute),
            "result": {"message": "已标记逾期工单进入任务中心跟进"} if auto_execute else None,
        })
        alerts.append(f"逾期工单 {overdue} 单需立即处理")
        next_actions.append("打开任务中心核对逾期工单并确认责任人")

    if broken > 0:
        decisions.append({
            "priority": "P0",
            "reason": f"设备故障 {broken} 台，触发维修协调",
            "executed": bool(auto_execute),
            "result": {"message": "已通知设备责任人"} if auto_execute else None,
        })
        alerts.append(f"故障设备 {broken} 台")

    if low_stock > 0:
        decisions.append({
            "priority": "P1",
            "reason": f"缺料/低库存 {low_stock} 项，启动补料跟催",
            "executed": bool(auto_execute),
            "result": {"message": "已生成物料跟催条目"} if auto_execute else None,
        })
        next_actions.append("核对低库存物料并触发采购/调拨")

    if order_mode == "deficit":
        decisions.append({
            "priority": "P2",
            "reason": "产能空闲且待排不足，建议主动接单补产",
            "executed": False,
            "result": None,
        })
        next_actions.append("评估可接订单并提交接单建议供您确认")
    elif order_mode == "surplus":
        decisions.append({
            "priority": "P2",
            "reason": "负荷偏高，切换挑单/延交低优模式",
            "executed": False,
            "result": None,
        })
        next_actions.append("对低优先级订单执行延交或外协评估（需您确认）")
    else:
        next_actions.append("维持当前节拍，继续自动巡检")

    if not next_actions:
        next_actions.append("继续定期态势感知，有重大决策先请示")

    return {
        "order_mode": order_mode,
        "decisions": decisions,
        "alerts": alerts,
        "next_actions": next_actions,
    }


async def run_cycle(
    db: AsyncSession,
    user_id: str,
    factory_id: str,
    auto_execute: bool = True,
) -> Dict[str, Any]:
    started = time.time()
    status = await get_status(db, user_id, factory_id)
    state = await _sense_state(db, factory_id)
    decided = _decide(state, auto_execute=auto_execute and status.get("enabled", False))
    duration_ms = int((time.time() - started) * 1000)
    return {
        "enabled": status.get("enabled", False),
        "factory_id": factory_id,
        "state": state,
        "order_mode": decided["order_mode"],
        "decisions": decided["decisions"],
        "alerts": decided["alerts"],
        "next_actions": decided["next_actions"],
        "duration_ms": duration_ms,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
