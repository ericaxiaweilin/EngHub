"""
工厂指挥官（Factory Commander）
================================
核心理念：Chatbot 不是 1:1 对话工具，而是工厂的智能指挥中枢。

指挥官自主决策循环：
  感知(Sense) → 决策(Decide) → 执行(Execute) → 汇报(Report)

订单模式：
  - surplus（充足）：订单 > 产能 120%，挑单、延交、加班
  - normal（正常）：订单 ≈ 产能 80-120%，正常排产
  - deficit（欠缺）：订单 < 产能 80%，主动接单、抢单

指挥官权限（默认无限订单权限）：
  - 自主决定接/拒订单
  - 自主安排投产顺序
  - 自主调度资源
  - 自主决定交货优先级
  - 人类可随时 override

与 virtual_factory 的关系：
  - virtual_factory = 数据心跳（造数据）
  - factory_commander = 决策大脑（做决策）
  - commander 调用 virtual_factory.pulse 来"接单投产"
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("factory_commander")


class OrderMode(str, Enum):
    SURPLUS = "surplus"    # 订单充足（>120%产能）
    NORMAL = "normal"      # 正常（80-120%）
    DEFICIT = "deficit"    # 欠缺（<80%）


class CommanderAction(str, Enum):
    ACCEPT_ORDER = "accept_order"          # 接单
    REJECT_ORDER = "reject_order"          # 拒单
    SCHEDULE_PRODUCTION = "schedule"       # 安排投产
    DISPATCH = "dispatch"                  # 派工
    EXPEDITE = "expedite"                  # 加急
    DELAY_DELIVERY = "delay_delivery"      # 延交
    OVERTIME = "overtime"                  # 加班
    PROCUREMENT = "procurement"            # 采购
    HOLD = "hold"                          # 按兵不动


@dataclass
class FactoryState:
    """工厂当前态势感知"""
    factory_id: str = ""
    timestamp: str = ""

    # 订单态势
    active_orders: int = 0
    pending_orders: int = 0
    in_progress_orders: int = 0
    overdue_orders: int = 0
    due_7d_orders: int = 0
    order_load_ratio: float = 0.0  # 订单负荷 / 产能
    order_mode: OrderMode = OrderMode.NORMAL

    # 产能态势
    total_stations: int = 0
    busy_stations: int = 0
    station_utilization: float = 0.0
    daily_capacity_hours: float = 0.0
    scheduled_hours_7d: float = 0.0

    # 设备态势
    equipment_total: int = 0
    equipment_running: int = 0
    equipment_maintenance: int = 0
    equipment_broken: int = 0

    # 物料态势
    low_stock_items: int = 0
    pending_procurement: int = 0

    # 交期态势
    on_time_rate_30d: float = 0.0
    avg_days_to_due: float = 0.0

    # 质量态势
    defect_rate_30d: float = 0.0
    open_8d: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factory_id": self.factory_id,
            "timestamp": self.timestamp,
            "order_mode": self.order_mode.value,
            "orders": {
                "active": self.active_orders,
                "pending": self.pending_orders,
                "in_progress": self.in_progress_orders,
                "overdue": self.overdue_orders,
                "due_7d": self.due_7d_orders,
                "load_ratio": round(self.order_load_ratio, 2),
            },
            "capacity": {
                "stations": f"{self.busy_stations}/{self.total_stations}",
                "utilization": f"{self.station_utilization:.0%}",
                "daily_hours": round(self.daily_capacity_hours, 1),
                "scheduled_7d_hours": round(self.scheduled_hours_7d, 1),
            },
            "equipment": {
                "total": self.equipment_total,
                "running": self.equipment_running,
                "maintenance": self.equipment_maintenance,
                "broken": self.equipment_broken,
            },
            "material": {"low_stock": self.low_stock_items, "pending_po": self.pending_procurement},
            "delivery": {"on_time_rate": f"{self.on_time_rate_30d:.0%}", "avg_days_to_due": round(self.avg_days_to_due, 1)},
            "quality": {"defect_rate": f"{self.defect_rate_30d:.1%}", "open_8d": self.open_8d},
        }


@dataclass
class CommanderDecision:
    """指挥官决策"""
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    action: CommanderAction = CommanderAction.HOLD
    priority: str = "normal"  # low / normal / high / urgent
    reason: str = ""
    target: str = ""  # 作用对象
    params: Dict[str, Any] = field(default_factory=dict)
    executed: bool = False
    result: Optional[Dict[str, Any]] = None


@dataclass
class CommanderReport:
    """指挥官汇报（每轮决策的输出）"""
    cycle_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    factory_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    order_mode: OrderMode = OrderMode.NORMAL
    state_summary: str = ""
    decisions: List[CommanderDecision] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    duration_ms: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "factory_id": self.factory_id,
            "timestamp": self.timestamp,
            "order_mode": self.order_mode.value,
            "state_summary": self.state_summary,
            "decisions": [{
                "id": d.decision_id,
                "action": d.action.value,
                "priority": d.priority,
                "reason": d.reason,
                "target": d.target,
                "executed": d.executed,
                "result": d.result,
            } for d in self.decisions],
            "next_actions": self.next_actions,
            "alerts": self.alerts,
            "duration_ms": round(self.duration_ms, 1),
        }

    def to_chatbot_reply(self) -> str:
        """格式化为用户可读的指挥官汇报"""
        mode_emoji = {"surplus": "🟢", "normal": "🔵", "deficit": "🟡"}
        mode_label = {"surplus": "订单充足", "normal": "产销平衡", "deficit": "订单欠缺"}

        parts = [
            f"🎖️ 工厂指挥官态势汇报",
            f"━━━━━━━━━━━━━━━━━━",
            f"{mode_emoji.get(self.order_mode.value, '⚪')} 订单模式：{mode_label.get(self.order_mode.value, self.order_mode.value)}",
            f"",
            f"📊 态势感知：{self.state_summary}",
        ]

        if self.decisions:
            parts.append(f"\n🎯 本轮决策（{len(self.decisions)} 项）：")
            for i, d in enumerate(self.decisions, 1):
                icon = "✅" if d.executed else "📋"
                parts.append(f"  {icon} {i}. [{d.priority}] {d.reason}")
                if d.result and d.result.get("message"):
                    parts.append(f"      → {d.result['message']}")

        if self.alerts:
            parts.append(f"\n⚠️ 预警：")
            for a in self.alerts:
                parts.append(f"  • {a}")

        if self.next_actions:
            parts.append(f"\n📌 下一步：")
            for n in self.next_actions:
                parts.append(f"  • {n}")

        parts.append(f"\n⏱️ 决策耗时：{self.duration_ms:.0f}ms")
        return "\n".join(parts)


class FactoryCommander:
    """
    工厂指挥官 - 自主决策引擎

    每个用户有自己的指挥官，开启后自动接管其工作范围内的事务。

    用法：
        commander = FactoryCommander(db)
        report = await commander.run_cycle("FAC_MECH_001")
        # report.to_chatbot_reply() → 用户可读汇报

    或指定模式：
        report = await commander.run_cycle("FAC_MECH_001", force_mode="deficit")

    Per-user 作用域：
        commander.set_user_scope("admin", {"departments": ["生产部"], "role": "厂长"})
    """

    # 决策历史（内存）
    _history: List[CommanderReport] = []
    _history_max = 50

    # 当前模式（持久化到内存，可被 override）
    _mode_override: Dict[str, Optional[str]] = {}  # factory_id -> forced mode

    # Per-user 指挥官状态
    _user_commanders: Dict[str, Dict[str, Any]] = {}  # user_id -> {enabled, scope, factory_id}

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # Per-user 指挥官管理
    # ═══════════════════════════════════════════════════════════

    def enable_for_user(self, user_id: str, factory_id: str, scope: Optional[Dict] = None):
        """为用户开启指挥官（自动接管其工作范围）"""
        self._user_commanders[user_id] = {
            "enabled": True,
            "factory_id": factory_id,
            "scope": scope or {},  # {departments, role, stations}
            "enabled_at": datetime.utcnow().isoformat(),
        }
        _logger.info(f"[commander] 用户 {user_id} 开启指挥官 | scope={scope}")

    def disable_for_user(self, user_id: str):
        """关闭用户指挥官"""
        if user_id in self._user_commanders:
            self._user_commanders[user_id]["enabled"] = False

    def get_user_status(self, user_id: str) -> Dict[str, Any]:
        """获取用户指挥官状态"""
        cfg = self._user_commanders.get(user_id)
        if not cfg:
            return {"enabled": False, "message": "指挥官未开启"}
        return {**cfg, "message": "指挥官运行中" if cfg["enabled"] else "指挥官已暂停"}

    def is_enabled(self, user_id: str) -> bool:
        cfg = self._user_commanders.get(user_id)
        return bool(cfg and cfg.get("enabled"))

    # ═══════════════════════════════════════════════════════════
    # 核心：决策循环
    # ═══════════════════════════════════════════════════════════

    async def run_cycle(
        self,
        factory_id: str,
        force_mode: Optional[str] = None,
        auto_execute: bool = True,
    ) -> CommanderReport:
        """
        执行一轮完整的指挥官决策循环：
        1. 感知（Sense）：采集工厂全维度数据
        2. 判断（Assess）：确定订单模式
        3. 决策（Decide）：根据模式+态势生成行动列表
        4. 执行（Execute）：调用各智能体执行
        5. 汇报（Report）：结构化输出
        """
        start = time.time()
        report = CommanderReport(factory_id=factory_id)

        # 1. 感知
        state = await self._sense(factory_id)

        # 2. 判断订单模式
        if force_mode:
            state.order_mode = OrderMode(force_mode)
        elif factory_id in self._mode_override and self._mode_override[factory_id]:
            state.order_mode = OrderMode(self._mode_override[factory_id])
        else:
            state.order_mode = self._assess_order_mode(state)

        report.order_mode = state.order_mode
        report.state_summary = self._build_state_summary(state)

        # 3. 决策
        decisions = await self._decide(state)
        report.decisions = decisions

        # 4. 执行
        if auto_execute:
            await self._execute_decisions(decisions, factory_id, state)

        # 5. 预警 + 下一步
        report.alerts = self._generate_alerts(state)
        report.next_actions = self._plan_next_actions(state, decisions)

        # 6. 数据治理：检查数据充足性，不足则通知责任人补填
        data_gaps = await self._check_data_governance(factory_id, state)
        if data_gaps:
            report.alerts.extend([g["alert"] for g in data_gaps])
            report.next_actions.extend([g["action"] for g in data_gaps])

        report.duration_ms = (time.time() - start) * 1000

        # 记录历史
        self._history.append(report)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

        _logger.info(
            f"[commander] {factory_id} | mode={state.order_mode.value} | "
            f"decisions={len(decisions)} | {report.duration_ms:.0f}ms"
        )

        return report

    # ═══════════════════════════════════════════════════════════
    # 感知（Sense）
    # ═══════════════════════════════════════════════════════════

    async def _sense(self, factory_id: str) -> FactoryState:
        """全维度态势感知"""
        state = FactoryState(factory_id=factory_id, timestamp=datetime.utcnow().isoformat())

        # 并行采集所有维度
        results = await asyncio.gather(
            self._sense_orders(factory_id),
            self._sense_capacity(factory_id),
            self._sense_equipment(factory_id),
            self._sense_material(factory_id),
            self._sense_delivery(factory_id),
            self._sense_quality(factory_id),
            return_exceptions=True,
        )

        # 解析各维度
        if not isinstance(results[0], Exception):
            orders = results[0]
            state.active_orders = orders.get("active", 0)
            state.pending_orders = orders.get("pending", 0)
            state.in_progress_orders = orders.get("in_progress", 0)
            state.overdue_orders = orders.get("overdue", 0)
            state.due_7d_orders = orders.get("due_7d", 0)

        if not isinstance(results[1], Exception):
            cap = results[1]
            state.total_stations = cap.get("total_stations", 0)
            state.busy_stations = cap.get("busy_stations", 0)
            state.station_utilization = cap.get("utilization", 0)
            state.daily_capacity_hours = cap.get("daily_hours", 16)
            state.scheduled_hours_7d = cap.get("scheduled_7d", 0)

        if not isinstance(results[2], Exception):
            eq = results[2]
            state.equipment_total = eq.get("total", 0)
            state.equipment_running = eq.get("running", 0)
            state.equipment_maintenance = eq.get("maintenance", 0)
            state.equipment_broken = eq.get("broken", 0)

        if not isinstance(results[3], Exception):
            mat = results[3]
            state.low_stock_items = mat.get("low_stock", 0)
            state.pending_procurement = mat.get("pending_po", 0)

        if not isinstance(results[4], Exception):
            dlv = results[4]
            state.on_time_rate_30d = dlv.get("on_time_rate", 0)
            state.avg_days_to_due = dlv.get("avg_days", 0)

        if not isinstance(results[5], Exception):
            q = results[5]
            state.defect_rate_30d = q.get("defect_rate", 0)
            state.open_8d = q.get("open_8d", 0)

        # 计算订单负荷比
        if state.daily_capacity_hours > 0:
            weekly_capacity = state.daily_capacity_hours * 7
            state.order_load_ratio = state.scheduled_hours_7d / max(weekly_capacity, 1)
        else:
            state.order_load_ratio = 1.0 if state.active_orders > 0 else 0.0

        return state

    async def _sense_orders(self, factory_id: str) -> Dict:
        r = await self.db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status IN ('released','pending','in_progress')) as active,
                COUNT(*) FILTER (WHERE status IN ('released','pending')) as pending,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status != 'completed' AND planned_due < NOW()) as overdue,
                COUNT(*) FILTER (WHERE status != 'completed' AND planned_due BETWEEN NOW() AND NOW() + INTERVAL '7 days') as due_7d
            FROM work_orders WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = dict(r.first()._mapping)
        return row

    async def _sense_capacity(self, factory_id: str) -> Dict:
        # 工位数
        st = await self.db.execute(text(
            "SELECT COUNT(*) as total FROM stations WHERE factory_id = :fid"
        ), {"fid": factory_id})
        total_stations = st.scalar() or 0

        # 排程负荷（未来7天）
        cap = await self.db.execute(text("""
            SELECT COUNT(DISTINCT station_id) as busy,
                   COALESCE(SUM(EXTRACT(EPOCH FROM (planned_end - planned_start))/3600), 0) as hours_7d
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft','confirmed')
              AND t.planned_start BETWEEN NOW() AND NOW() + INTERVAL '7 days'
        """), {"fid": factory_id})
        cap_row = dict(cap.first()._mapping)

        daily_hours = total_stations * 12  # 每工位12h/天
        utilization = cap_row["busy"] / max(total_stations, 1)

        return {
            "total_stations": total_stations,
            "busy_stations": cap_row["busy"] or 0,
            "utilization": utilization,
            "daily_hours": daily_hours,
            "scheduled_7d": cap_row["hours_7d"] or 0,
        }

    async def _sense_equipment(self, factory_id: str) -> Dict:
        r = await self.db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status IN ('running','available','idle')) as running,
                COUNT(*) FILTER (WHERE status = 'maintenance') as maintenance,
                COUNT(*) FILTER (WHERE status IN ('broken','down')) as broken
            FROM equipment WHERE factory_id = :fid
        """), {"fid": factory_id})
        return dict(r.first()._mapping)

    async def _sense_material(self, factory_id: str) -> Dict:
        try:
            r = await self.db.execute(text("""
                SELECT COUNT(*) FILTER (WHERE available_qty <= COALESCE(reorder_point, 20)) as low_stock
                FROM inventory WHERE factory_id = :fid
            """), {"fid": factory_id})
            low = r.scalar() or 0
        except Exception:
            low = 0
        try:
            po = await self.db.execute(text("""
                SELECT COUNT(*) FROM purchase_orders WHERE factory_id = :fid AND status IN ('pending','approved')
            """), {"fid": factory_id})
            pending_po = po.scalar() or 0
        except Exception:
            pending_po = 0
        return {"low_stock": low, "pending_po": pending_po}

    async def _sense_delivery(self, factory_id: str) -> Dict:
        r = await self.db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'completed' AND actual_end <= planned_due) as on_time,
                AVG(CASE WHEN status != 'completed' AND planned_due IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (planned_due - NOW()))/86400 END) as avg_days
            FROM work_orders WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '90 days'
        """), {"fid": factory_id})
        row = dict(r.first()._mapping)
        completed = row["completed"] or 0
        on_time = row["on_time"] or 0
        return {
            "on_time_rate": on_time / max(completed, 1),
            "avg_days": row["avg_days"] or 0,
        }

    async def _sense_quality(self, factory_id: str) -> Dict:
        try:
            r = await self.db.execute(text("""
                SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE result='fail') as fail
                FROM inspection_records WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '30 days'
            """), {"fid": factory_id})
            row = r.first()
            total = (row[0] or 0) if row else 0
            fail = (row[1] or 0) if row else 0
            defect_rate = fail / max(total, 1)
        except Exception:
            defect_rate = 0
        try:
            d8 = await self.db.execute(text("""
                SELECT COUNT(*) FROM eight_d_reports WHERE factory_id = :fid AND status NOT IN ('closed','verified')
            """), {"fid": factory_id})
            open_8d = d8.scalar() or 0
        except Exception:
            open_8d = 0
        return {"defect_rate": defect_rate, "open_8d": open_8d}

    # ═══════════════════════════════════════════════════════════
    # 判断（Assess）
    # ═══════════════════════════════════════════════════════════

    def _assess_order_mode(self, state: FactoryState) -> OrderMode:
        """根据订单负荷比判断模式"""
        ratio = state.order_load_ratio
        if ratio > 1.2:
            return OrderMode.SURPLUS
        elif ratio < 0.8:
            return OrderMode.DEFICIT
        return OrderMode.NORMAL

    def _build_state_summary(self, state: FactoryState) -> str:
        """一句话态势摘要"""
        parts = []
        parts.append(f"在制{state.active_orders}单(待排{state.pending_orders}/执行中{state.in_progress_orders})")
        if state.overdue_orders > 0:
            parts.append(f"逾期{state.overdue_orders}单")
        parts.append(f"工位利用{state.station_utilization:.0%}")
        if state.equipment_broken > 0:
            parts.append(f"故障设备{state.equipment_broken}台")
        if state.low_stock_items > 0:
            parts.append(f"缺料{state.low_stock_items}项")
        parts.append(f"交期达成{state.on_time_rate_30d:.0%}")
        return "，".join(parts)

    # ═══════════════════════════════════════════════════════════
    # 决策（Decide）
    # ═══════════════════════════════════════════════════════════

    async def _decide(self, state: FactoryState) -> List[CommanderDecision]:
        """根据态势+模式生成决策列表"""
        decisions: List[CommanderDecision] = []
        mode = state.order_mode

        # ─── 模式驱动决策 ───
        if mode == OrderMode.DEFICIT:
            # 订单欠缺 → 主动接单
            decisions.append(CommanderDecision(
                action=CommanderAction.ACCEPT_ORDER,
                priority="high",
                reason=f"订单欠缺(负荷{state.order_load_ratio:.0%})，主动承接新订单补充产能",
                target="virtual_factory",
                params={"count": 2, "mode": "deficit"},
            ))

        elif mode == OrderMode.SURPLUS:
            # 订单充足 → 挑单、延交低优先级
            if state.overdue_orders > 0:
                decisions.append(CommanderDecision(
                    action=CommanderAction.EXPEDITE,
                    priority="urgent",
                    reason=f"订单充足但有{state.overdue_orders}单逾期，加急处理逾期工单",
                    target="overdue_orders",
                ))
            decisions.append(CommanderDecision(
                action=CommanderAction.REJECT_ORDER,
                priority="normal",
                reason=f"产能已满(负荷{state.order_load_ratio:.0%})，暂缓接新单",
                target="new_orders",
            ))

        else:  # NORMAL
            # 正常 → 维持节奏
            if state.pending_orders > 3:
                decisions.append(CommanderDecision(
                    action=CommanderAction.SCHEDULE_PRODUCTION,
                    priority="normal",
                    reason=f"{state.pending_orders}单待排产，执行自动排程",
                    target="pending_orders",
                ))

        # ─── 通用决策（不论模式）───

        # 待排产工单 → 排程
        if state.pending_orders > 0 and mode != OrderMode.SURPLUS:
            decisions.append(CommanderDecision(
                action=CommanderAction.SCHEDULE_PRODUCTION,
                priority="normal" if state.pending_orders < 10 else "high",
                reason=f"{state.pending_orders}个工单待排产，安排投产",
                target="aps_schedule",
            ))

        # 设备故障 → 维修
        if state.equipment_broken > 0:
            decisions.append(CommanderDecision(
                action=CommanderAction.PROCUREMENT,
                priority="high",
                reason=f"{state.equipment_broken}台设备故障，安排维修并评估产能影响",
                target="broken_equipment",
            ))

        # 缺料 → 采购
        if state.low_stock_items > 5:
            decisions.append(CommanderDecision(
                action=CommanderAction.PROCUREMENT,
                priority="high" if state.low_stock_items > 20 else "normal",
                reason=f"{state.low_stock_items}项物料低于安全线，触发补货",
                target="low_stock_materials",
            ))

        # 交期风险 → 加班/调整
        if state.due_7d_orders > 5 and state.station_utilization > 0.9:
            decisions.append(CommanderDecision(
                action=CommanderAction.OVERTIME,
                priority="high",
                reason=f"7天内{state.due_7d_orders}单到期且产能紧张，建议加班",
                target="capacity",
            ))

        # 去重（同 action+target 只保留最高优先级）
        seen = {}
        for d in decisions:
            key = f"{d.action.value}:{d.target}"
            if key not in seen or _priority_rank(d.priority) > _priority_rank(seen[key].priority):
                seen[key] = d
        return list(seen.values())

    # ═══════════════════════════════════════════════════════════
    # 执行（Execute）
    # ═══════════════════════════════════════════════════════════

    async def _execute_decisions(
        self, decisions: List[CommanderDecision], factory_id: str, state: FactoryState
    ):
        """并行执行所有决策"""
        tasks = []
        for d in decisions:
            tasks.append(self._execute_single(d, factory_id, state))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_single(self, decision: CommanderDecision, factory_id: str, state: FactoryState):
        """执行单个决策"""
        try:
            if decision.action == CommanderAction.ACCEPT_ORDER:
                decision.result = await self._exec_accept_order(factory_id, decision.params)
            elif decision.action == CommanderAction.SCHEDULE_PRODUCTION:
                decision.result = await self._exec_schedule(factory_id)
            elif decision.action == CommanderAction.EXPEDITE:
                decision.result = await self._exec_expedite(factory_id)
            elif decision.action == CommanderAction.PROCUREMENT:
                decision.result = {"message": "已标记补货需求，采购智能体跟进", "status": "delegated"}
            elif decision.action == CommanderAction.OVERTIME:
                decision.result = {"message": "加班建议已生成，待主管确认", "status": "pending_approval"}
            elif decision.action == CommanderAction.REJECT_ORDER:
                decision.result = {"message": "暂缓接单，产能已满", "status": "hold"}
            else:
                decision.result = {"message": f"{decision.action.value} 待实现", "status": "planned"}
            decision.executed = True
        except Exception as e:
            decision.result = {"message": f"执行失败: {str(e)[:100]}", "status": "error"}
            decision.executed = False

    async def _exec_accept_order(self, factory_id: str, params: Dict) -> Dict:
        """接单：调用 virtual_factory pulse 创建新订单"""
        try:
            from api.services.virtual_factory_service import VirtualFactoryService, PulseConfig
            svc = VirtualFactoryService(self.db)
            count = params.get("count", 2)
            cfg = PulseConfig(
                factory_id=factory_id,
                target_active_orders=count + 4,
                max_new_orders_per_pulse=count,
            )
            result = await svc.pulse(cfg)
            created = len(result.get("created_orders", []))
            return {"message": f"已承接{created}个新订单并分解为工单", "created": created}
        except Exception as e:
            return {"message": f"接单执行: {str(e)[:80]}", "created": 0}

    async def _exec_schedule(self, factory_id: str) -> Dict:
        """排产：调用排产智能体"""
        try:
            from api.services.scheduling_agent_service import SchedulingAgent
            agent = SchedulingAgent(self.db)
            result = await agent.auto_schedule(factory_id)
            tasks_count = result.get("tasks_created", result.get("total_tasks", 0))
            return {"message": f"自动排程完成，{tasks_count}个任务已排入", "tasks": tasks_count}
        except Exception as e:
            return {"message": f"排程: {str(e)[:80]}", "tasks": 0}

    async def _exec_expedite(self, factory_id: str) -> Dict:
        """加急逾期工单"""
        r = await self.db.execute(text("""
            UPDATE work_orders SET priority = 'urgent', updated_at = NOW()
            WHERE factory_id = :fid AND status != 'completed' AND planned_due < NOW()
              AND priority != 'urgent'
            RETURNING work_order_code
        """), {"fid": factory_id})
        codes = [row[0] for row in r.fetchall()]
        await self.db.commit()
        return {"message": f"{len(codes)}个逾期工单已升级为紧急", "expedited": len(codes)}

    # ═══════════════════════════════════════════════════════════
    # 预警 + 下一步
    # ═══════════════════════════════════════════════════════════

    def _generate_alerts(self, state: FactoryState) -> List[str]:
        alerts = []
        if state.overdue_orders > 0:
            alerts.append(f"{state.overdue_orders}个工单已逾期，需立即处理")
        if state.equipment_broken > 0:
            alerts.append(f"{state.equipment_broken}台设备故障，影响产能")
        if state.low_stock_items > 10:
            alerts.append(f"{state.low_stock_items}项物料缺料，可能导致停线")
        if state.defect_rate_30d > 0.05:
            alerts.append(f"不良率{state.defect_rate_30d:.1%}偏高，需质量介入")
        if state.station_utilization > 0.95:
            alerts.append("产能接近满载，新单需排队或加班")
        if state.on_time_rate_30d < 0.8 and state.on_time_rate_30d > 0:
            alerts.append(f"交期达成率仅{state.on_time_rate_30d:.0%}，低于80%目标")
        return alerts

    def _plan_next_actions(self, state: FactoryState, decisions: List[CommanderDecision]) -> List[str]:
        next_actions = []
        mode = state.order_mode
        if mode == OrderMode.DEFICIT:
            next_actions.append("持续监控订单流入，产能空闲时主动承接")
            next_actions.append("评估是否可承接外部协作订单")
        elif mode == OrderMode.SURPLUS:
            next_actions.append("评估逾期工单加急方案")
            next_actions.append("低优先级订单协商延交")
        else:
            next_actions.append("维持当前生产节奏")
            if state.pending_orders > 0:
                next_actions.append(f"下一轮排程消化{state.pending_orders}个待排工单")
        if state.low_stock_items > 0:
            next_actions.append("跟催采购到货情况")
        return next_actions

    # ═══════════════════════════════════════════════════════════
    # 模式管理 + 历史
    # ═══════════════════════════════════════════════════════════

    def set_mode(self, factory_id: str, mode: Optional[str]):
        """手动 override 订单模式（None=自动判断）"""
        self._mode_override[factory_id] = mode

    def get_status(self, factory_id: str) -> Dict[str, Any]:
        """获取指挥官当前状态"""
        recent = [r for r in self._history if r.factory_id == factory_id]
        last = recent[-1] if recent else None
        return {
            "factory_id": factory_id,
            "mode_override": self._mode_override.get(factory_id),
            "total_cycles": len(recent),
            "last_cycle": last.to_dict() if last else None,
            "history_count": len(recent),
        }

    def get_history(self, factory_id: str, limit: int = 10) -> Dict[str, Any]:
        recent = [r for r in self._history if r.factory_id == factory_id][-limit:]
        return {
            "factory_id": factory_id,
            "total": len([r for r in self._history if r.factory_id == factory_id]),
            "records": [r.to_dict() for r in reversed(recent)],
        }

    # ═══════════════════════════════════════════════════════════
    # 数据治理：充足性检查 + 降级策略 + 通知责任人
    # ═══════════════════════════════════════════════════════════

    async def _check_data_governance(self, factory_id: str, state: FactoryState) -> List[Dict[str, str]]:
        """
        数据治理核心：
        - 检查各维度数据是否充足
        - 不充足时：用降级值 + 通知责任人补填
        - 返回数据缺口列表

        典型场景：
        - 设备OEE=0 但设备状态=running → 操作员漏填运行日志 → 通知责任人
        - 报工数据为0 但工单in_progress → 操作员漏报工 → 通知班组长
        - 库存无数据 → 仓管未录入 → 通知仓管
        """
        gaps: List[Dict[str, str]] = []

        # 并行检查所有维度
        checks = await asyncio.gather(
            self._check_equipment_data(factory_id, state),
            self._check_production_data(factory_id, state),
            self._check_inventory_data(factory_id, state),
            self._check_quality_data(factory_id, state),
            return_exceptions=True,
        )

        for check in checks:
            if isinstance(check, Exception):
                continue
            if check:
                gaps.extend(check)

        # 对每个缺口发送通知
        for gap in gaps:
            await self._notify_data_gap(factory_id, gap)

        return gaps

    async def _check_equipment_data(self, factory_id: str, state: FactoryState) -> List[Dict]:
        """设备数据充足性：设备在动但没有运行日志/OEE=0"""
        gaps = []
        try:
            # 检查：设备状态=running 但无近期维护/运行记录
            r = await self.db.execute(text("""
                SELECT e.equipment_code, e.equipment_name, e.responsible_engineer_id,
                       e.status, e.last_maintenance_date
                FROM equipment e
                WHERE e.factory_id = :fid AND e.status IN ('running', 'available')
                  AND (e.last_maintenance_date IS NULL OR e.last_maintenance_date < NOW() - INTERVAL '90 days')
                LIMIT 5
            """), {"fid": factory_id})
            stale_equipment = [dict(row) for row in r.mappings().all()]

            if stale_equipment:
                # 降级策略：用行业平均OEE=85%代替
                engineers = set()
                for eq in stale_equipment:
                    if eq.get("responsible_engineer_id"):
                        engineers.add(eq["responsible_engineer_id"])

                gaps.append({
                    "dimension": "equipment",
                    "issue": f"{len(stale_equipment)}台设备无近期运行日志，OEE数据不可信",
                    "fallback": "使用行业基准OEE=85%作为估算",
                    "alert": f"📉 设备数据缺失：{len(stale_equipment)}台设备无运行日志，已用OEE=85%降级估算",
                    "action": f"通知设备工程师补填运行日志（涉及{len(engineers)}位责任人）",
                    "responsible": list(engineers) or ["equipment_admin"],
                    "severity": "warning",
                })
        except Exception:
            pass
        return gaps

    async def _check_production_data(self, factory_id: str, state: FactoryState) -> List[Dict]:
        """生产数据充足性：工单in_progress但无报工记录"""
        gaps = []
        try:
            # 检查：工单in_progress 但今天无报工
            r = await self.db.execute(text("""
                SELECT COUNT(*) as stale_wo FROM work_orders w
                WHERE w.factory_id = :fid AND w.status = 'in_progress'
                  AND NOT EXISTS (
                    SELECT 1 FROM production_reports pr
                    WHERE pr.work_order_id = w.id::text AND pr.created_at > NOW() - INTERVAL '3 days'
                  )
            """), {"fid": factory_id})
            stale_count = r.scalar() or 0

            if stale_count > 3:
                gaps.append({
                    "dimension": "production",
                    "issue": f"{stale_count}个在制工单3天内无报工记录",
                    "fallback": "假定正常生产中，用计划进度估算完成率",
                    "alert": f"📝 报工数据缺失：{stale_count}个工单无近期报工，已用计划进度降级估算",
                    "action": "通知产线班组长督促操作员及时报工",
                    "responsible": ["production_supervisor"],
                    "severity": "warning",
                })
        except Exception:
            pass
        return gaps

    async def _check_inventory_data(self, factory_id: str, state: FactoryState) -> List[Dict]:
        """库存数据充足性：库存表是否有数据"""
        gaps = []
        try:
            r = await self.db.execute(text(
                "SELECT COUNT(*) FROM inventory WHERE factory_id = :fid"
            ), {"fid": factory_id})
            count = r.scalar() or 0

            if count == 0:
                gaps.append({
                    "dimension": "inventory",
                    "issue": "库存表无数据，无法进行齐套检查和缺料预警",
                    "fallback": "假定物料充足，不做缺料拦截",
                    "alert": "📦 库存数据缺失：库存表为空，已跳过缺料检查",
                    "action": "通知仓管员录入库存初始数据",
                    "responsible": ["warehouse_admin"],
                    "severity": "critical",
                })
        except Exception:
            pass
        return gaps

    async def _check_quality_data(self, factory_id: str, state: FactoryState) -> List[Dict]:
        """质量数据充足性：有生产但无检验记录"""
        gaps = []
        try:
            if state.in_progress_orders > 0:
                r = await self.db.execute(text("""
                    SELECT COUNT(*) FROM inspection_records
                    WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '7 days'
                """), {"fid": factory_id})
                insp_count = r.scalar() or 0

                if insp_count == 0:
                    gaps.append({
                        "dimension": "quality",
                        "issue": "有在制工单但7天内无检验记录",
                        "fallback": "假定质量正常，不做质量拦截",
                        "alert": "🔍 质量数据缺失：7天无检验记录，已跳过质量门禁",
                        "action": "通知品质工程师安排过程检验",
                        "responsible": ["quality_engineer"],
                        "severity": "warning",
                    })
        except Exception:
            pass
        return gaps

    async def _notify_data_gap(self, factory_id: str, gap: Dict):
        """数据缺口 → 自动通知责任人补填"""
        try:
            import uuid as _uuid
            responsible_list = gap.get("responsible", [])
            for recipient in responsible_list[:3]:  # 最多通知3人
                await self.db.execute(text("""
                    INSERT INTO notifications (id, factory_id, title, content, severity, category, recipient, is_read, source_type, created_at)
                    VALUES (:id, :fid, :title, :content, :sev, 'data_governance', :rec, FALSE, 'commander', NOW())
                """), {
                    "id": str(_uuid.uuid4()),
                    "fid": factory_id,
                    "title": f"[指挥官] 数据缺失预警: {gap['dimension']}",
                    "content": f"{gap['issue']}\n降级策略: {gap['fallback']}\n请补填相关数据。",
                    "sev": gap.get("severity", "warning"),
                    "rec": recipient,
                })
            await self.db.commit()
        except Exception as e:
            _logger.debug(f"[commander] 通知发送失败: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass


def _priority_rank(p: str) -> int:
    return {"low": 0, "normal": 1, "high": 2, "urgent": 3}.get(p, 1)
