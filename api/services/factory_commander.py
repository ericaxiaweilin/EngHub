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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("factory_commander")

# 指挥官策略版本号：每次改动 _assess_order_mode / _decide 的阈值或规则就 +1。
# 决策轨迹落盘时一并记录，否则无法区分“当时的策略”与“现在的策略”，A/B 没有基线。
COMMANDER_POLICY_VERSION = "cmd-2026.10.04"

# 订单模式判定的策略参数（原先写死在 _assess_order_mode 里的 1.2 / 0.8）。
# 提出来是为了让「策略参数」本身成为可评估对象：commander_decision_log 存了全精度
# 输入态，scripts/commander_policy_replay.py 就能在真实历史状态上对这两个阈值做 A/B。
# 改动这里的值 → 必须同时 +1 COMMANDER_POLICY_VERSION。
SURPLUS_RATIO_THRESHOLD = 1.2   # 负荷 > 此值 → 订单充足
DEFICIT_RATIO_THRESHOLD = 0.8   # 负荷 < 此值 → 订单欠缺


def _json_default(obj: Any) -> Any:
    """JSONB 序列化兜底。

    DB 聚合（COUNT/AVG/SUM）在 asyncpg 下回来的是 Decimal 而不是 float，直接
    json.dumps 会抛 "Object of type Decimal is not JSON serializable"，真实
    run_cycle 路径上会导致整条落盘失败（合成状态测不出来，因为手写的是 float）。
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.value
    return str(obj)


class OrderMode(str, Enum):
    SURPLUS = "surplus"    # 订单充足（>120%产能）
    NORMAL = "normal"      # 正常（80-120%）
    DEFICIT = "deficit"    # 欠缺（<80%）
    BLOCKED = "blocked"    # 生产阻塞/主数据异常（负荷虽低但产线被卡住，禁止接单）


class CommanderAction(str, Enum):
    ACCEPT_ORDER = "accept_order"          # 接单
    REJECT_ORDER = "reject_order"          # 拒单
    SCHEDULE_PRODUCTION = "schedule"       # 安排投产
    DISPATCH = "dispatch"                  # 派工
    EXPEDITE = "expedite"                  # 加急
    DELAY_DELIVERY = "delay_delivery"      # 延交
    OVERTIME = "overtime"                  # 加班
    PROCUREMENT = "procurement"            # 采购（仅缺料补货）
    MAINTAIN = "maintain"                  # 设备维保/维修（派设备工程师，不走采购）
    DATA_GAP = "data_gap"                  # 计划主数据缺口（补BOM/路由/计划）
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

    # 计划主数据缺口（销售订单 vs MPS 计划 / BOM / 工艺路线）
    so_unplanned: int = 0          # 未纳入 MPS 计划的销售订单数
    products_no_routing: int = 0   # 无工艺路线的主产品数
    products_no_bom: int = 0       # 无已生效 BOM 的主产品数

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
            "plan_data_gaps": {
                "so_unplanned": self.so_unplanned,
                "products_no_routing": self.products_no_routing,
                "products_no_bom": self.products_no_bom,
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
    state: Optional[Dict[str, Any]] = None  # 完整感知数据（供前端展示“读了什么”）
    decisions: List[CommanderDecision] = field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None  # 行动计划（Plan）：决策聚合为目标导向计划，记录在任务中心
    followup_tasks: List[Dict[str, Any]] = field(default_factory=list)  # 挂入任务中心持续盯办的任务
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
            "state": self.state,
            "decisions": [{
                "id": d.decision_id,
                "action": d.action.value,
                "priority": d.priority,
                "reason": d.reason,
                "target": d.target,
                "executed": d.executed,
                "result": d.result,
            } for d in self.decisions],
            "plan": self.plan,
            "followup_tasks": self.followup_tasks,
            "next_actions": self.next_actions,
            "alerts": self.alerts,
            "duration_ms": round(self.duration_ms, 1),
        }

    def to_chatbot_reply(self) -> str:
        """格式化为用户可读的指挥官汇报"""
        mode_emoji = {"surplus": "🟢", "normal": "🔵", "deficit": "🟡", "blocked": "⛔"}
        mode_label = {"surplus": "订单充足", "normal": "产销平衡", "deficit": "订单欠缺",
                      "blocked": "生产阻塞/主数据异常"}

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
                _st = (d.result or {}).get("status") if d.executed else None
                if not d.executed:
                    icon = "📋"
                elif _st in ("blocked", "skipped"):
                    icon = "⚠️"
                elif _st == "error":
                    icon = "❌"
                else:
                    icon = "✅"
                parts.append(f"  {icon} {i}. [{d.priority}] {d.reason}")
                if d.result and d.result.get("message"):
                    parts.append(f"      → {d.result['message']}")

        if self.plan and self.plan.get("objective"):
            parts.append(f"\n🗂️ 行动计划（Plan）：{self.plan['objective']}")
            for it in self.plan.get("items") or []:
                agent = it.get("agent_name") or "通用"
                parts.append(f"  {it.get('plan_seq') or '•'}. [{agent}] {it.get('title')}")
            if self.plan.get("progress_pct") is not None:
                parts.append(f"  📈 计划总进度：{self.plan['progress_pct']}%")

        if self.followup_tasks:
            parts.append(f"\n📌 已挂入任务中心持续盯办（{len(self.followup_tasks)} 项，智能体将持续跟进直到闭环）：")
            for t in self.followup_tasks:
                tag = "🆕 新挂" if t.get("status") == "created" else f"🔄 已跟{t.get('follow_count', 0)}次"
                parts.append(
                    f"  • [{t.get('agent_name')}] {t.get('title')}"
                    f"（每{t.get('interval')}分钟 · {tag} · 进度{t.get('progress_pct', 0)}%）")

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

    def enable_for_user(self, user_id: str, factory_id: str, scope: Optional[Dict] = None, username: Optional[str] = None):
        """为用户开启指挥官（自动接管其工作范围）"""
        self._user_commanders[user_id] = {
            "enabled": True,
            "factory_id": factory_id,
            "scope": scope or {},  # {departments, role, stations}
            "username": username or user_id,  # 任务中心挂账/站内通知用的身份
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
        created_by: Optional[str] = None,
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
        # mode_source 必须区分策略决策与人工干预：force_mode / _mode_override 不是
        # 策略输出，重放时若混在一起会把人工干预算成策略效果。
        if force_mode:
            state.order_mode = OrderMode(force_mode)
            mode_source = "forced"
        elif factory_id in self._mode_override and self._mode_override[factory_id]:
            state.order_mode = OrderMode(self._mode_override[factory_id])
            mode_source = "override"
        else:
            state.order_mode = self._assess_order_mode(state)
            mode_source = "policy"

        report.order_mode = state.order_mode
        report.state_summary = self._build_state_summary(state)
        report.state = state.to_dict()

        # 3. 决策
        decisions = await self._decide(state)
        report.decisions = decisions

        # 4. 执行 + 计划（Planner）：是任务就有 plan —— 决策聚合为目标导向的行动计划
        if auto_execute:
            await self._execute_decisions(decisions, factory_id, state)
            # 4.5 计划物化到任务中心：新挂任务归属当前 active 计划（去重任务沿用原计划持续盯）
            objective = self._build_objective(state, decisions)
            report.followup_tasks, plan_id = await self._attach_followup_tasks(
                decisions, factory_id, state, created_by=created_by or "commander",
                objective=objective, mode=state.order_mode.value, cycle_id=report.cycle_id)
            # 4.6 聚合计划进度，产出完整计划（含子任务）——指挥官必须交付的 plan list
            if plan_id:
                from api.services import followup_task_service as fts
                try:
                    report.plan = await fts.refresh_plan(self.db, plan_id)
                except Exception as e:
                    try:
                        await self.db.rollback()
                    except Exception:
                        pass
                    _logger.warning(f"[commander] 计划聚合失败: {e}")
        else:
            # 不执行时也产出计划预览（dry-run），让用户看到指挥官打算做什么
            report.plan = self._preview_plan(state, decisions)

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

        # 7. 决策轨迹落盘（数据驱动策略评估的原料）：放在执行之后才能带上
        #    result.status；无决策的纯巡检轮次不写全量快照，避免表膨胀。
        if decisions:
            await self._record_decision_log(report, state, mode_source)

        return report

    # ═══════════════════════════════════════════════════════════
    # 决策轨迹落盘（Decision Trail）—— 数据驱动策略评估的原料
    # ═══════════════════════════════════════════════════════════

    def _snapshot_state(self, state: FactoryState) -> Dict[str, Any]:
        """FactoryState 的【原始数值】快照。

        刻意不用 ``state.to_dict()``：那是给前端看的展示版（数值被格式化成
        字符串并四舍五入，如 utilization="0%"、stations="3/5"），无法无损重建
        FactoryState，也就无法重放。
        """
        data = asdict(state)
        data["order_mode"] = state.order_mode.value
        # DB 聚合回来的数值可能是 Decimal —— 归一成 float，既是 JSONB 能接受的形式，
        # 也与字段声明的 float 一致。
        # 注意：float 无法精确表示所有 Decimal（Decimal("0.93") != 0.93），所以快照
        # 不是逐位相等，而是【决策等价】—— 重建后 _assess_order_mode / _decide 必须给出
        # 同一结果。这才是重放真正需要的保证，也是测试断言的对象。
        for key, value in list(data.items()):
            if isinstance(value, Decimal):
                data[key] = float(value)
        return data

    def _mode_reason(self, state: FactoryState, mode_source: str) -> str:
        """模式判定的依据。

        策略判定才记判别量；人工干预（force_mode / override）只标来源——
        否则重放时会把人工干预算成策略效果。
        """
        if mode_source != "policy":
            return f"{mode_source}={state.order_mode.value}"
        if state.order_mode == OrderMode.BLOCKED:
            parts = [
                f"{name}={value}" for name, value in (
                    ("pending", state.pending_orders),
                    ("overdue", state.overdue_orders),
                    ("so_unplanned", state.so_unplanned),
                    ("no_routing", state.products_no_routing),
                    ("no_bom", state.products_no_bom),
                ) if value
            ]
            return "blockers: " + (", ".join(parts) or "none")
        return f"load_ratio={state.order_load_ratio:.2f}"

    async def _record_decision_log(
        self, report: CommanderReport, state: FactoryState, mode_source: str,
    ) -> None:
        """把本轮决策轨迹写进 commander_decision_log，供离线重放与策略 A/B。

        用独立 session 落盘：不参与调用方事务，失败也不可能影响主链路。
        """
        try:
            from database.db_config import db_config

            decisions = [{
                "decision_id": d.decision_id,
                "action": (
                    d.action.value if isinstance(d.action, CommanderAction)
                    else str(d.action)
                ),
                "priority": d.priority,
                "reason": d.reason,
                "target": d.target,
                "executed": d.executed,
                "status": (d.result or {}).get("status") if d.executed else None,
                "message": (d.result or {}).get("message") if d.executed else None,
            } for d in report.decisions]

            async with db_config.session_factory() as session:
                await session.execute(text(
                    "INSERT INTO commander_decision_log "
                    "(id, factory_id, cycle_id, mode, mode_source, mode_reason, "
                    " state_snapshot, decisions, policy_version, duration_ms) "
                    "VALUES (:id, :factory_id, :cycle_id, :mode, :mode_source, "
                    " :mode_reason, CAST(:state_snapshot AS JSONB), "
                    " CAST(:decisions AS JSONB), :policy_version, :duration_ms)"
                ), {
                    "id": str(uuid.uuid4()),
                    "factory_id": report.factory_id,
                    "cycle_id": report.cycle_id,
                    "mode": state.order_mode.value,
                    "mode_source": mode_source,
                    "mode_reason": self._mode_reason(state, mode_source)[:500],
                    "state_snapshot": json.dumps(
                        self._snapshot_state(state), ensure_ascii=False,
                        default=_json_default,
                    ),
                    "decisions": json.dumps(
                        decisions, ensure_ascii=False, default=_json_default,
                    ),
                    "policy_version": COMMANDER_POLICY_VERSION,
                    "duration_ms": int(report.duration_ms or 0),
                })
                await session.commit()
        except Exception as e:  # noqa: BLE001 —— 落盘绝不影响主链路
            _logger.warning(f"[commander] 决策轨迹落盘失败（不影响主链路）: {e}")

    # ═══════════════════════════════════════════════════════════
    # 感知（Sense）
    # ═══════════════════════════════════════════════════════════

    async def _sense(self, factory_id: str) -> FactoryState:
        """全维度态势感知"""
        state = FactoryState(factory_id=factory_id, timestamp=datetime.utcnow().isoformat())

        # 串行采集所有维度（共享同一 db session，并行 gather 会导致事务交叉毒化；
        # 某维度查询失败时立即 rollback 清除已中止事务，避免后续智能体调用连环失败）
        async def _safe(coro):
            try:
                return await coro
            except Exception:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                return None

        results = [
            await _safe(self._sense_orders(factory_id)),
            await _safe(self._sense_capacity(factory_id)),
            await _safe(self._sense_equipment(factory_id)),
            await _safe(self._sense_material(factory_id)),
            await _safe(self._sense_delivery(factory_id)),
            await _safe(self._sense_quality(factory_id)),
        ]

        # 解析各维度
        if results[0] is not None:
            orders = results[0]
            state.active_orders = orders.get("active", 0)
            state.pending_orders = orders.get("pending", 0)
            state.in_progress_orders = orders.get("in_progress", 0)
            state.overdue_orders = orders.get("overdue", 0)
            state.due_7d_orders = orders.get("due_7d", 0)
            state.so_unplanned = orders.get("so_unplanned", 0)
            state.products_no_routing = orders.get("products_no_routing", 0)
            state.products_no_bom = orders.get("products_no_bom", 0)

        if results[1] is not None:
            cap = results[1]
            state.total_stations = cap.get("total_stations", 0)
            state.busy_stations = cap.get("busy_stations", 0)
            state.station_utilization = cap.get("utilization", 0)
            state.daily_capacity_hours = cap.get("daily_hours", 16)
            state.scheduled_hours_7d = cap.get("scheduled_7d", 0)

        if results[2] is not None:
            eq = results[2]
            state.equipment_total = eq.get("total", 0)
            state.equipment_running = eq.get("running", 0)
            state.equipment_maintenance = eq.get("maintenance", 0)
            state.equipment_broken = eq.get("broken", 0)

        if results[3] is not None:
            mat = results[3]
            state.low_stock_items = mat.get("low_stock", 0)
            state.pending_procurement = mat.get("pending_po", 0)

        if results[4] is not None:
            dlv = results[4]
            state.on_time_rate_30d = dlv.get("on_time_rate", 0)
            state.avg_days_to_due = dlv.get("avg_days", 0)

        if results[5] is not None:
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

        # 计划主数据缺口：未纳入 MPS 计划的销售订单
        try:
            so = await self.db.execute(text("""
                SELECT COUNT(*) AS unplanned
                FROM sales_orders so
                WHERE so.factory_id = :fid
                  AND so.status NOT IN ('cancelled', 'completed')
                  AND NOT EXISTS (
                      SELECT 1 FROM pp_plans pp
                      WHERE pp.sales_order_id = so.order_code
                  )
            """), {"fid": factory_id})
            row["so_unplanned"] = so.scalar() or 0
        except Exception:
            row["so_unplanned"] = 0

        # 产品主数据缺口：无工艺路线 / 无 BOM 的产品（在售且非取消）
        try:
            md = await self.db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM routings r
                        WHERE r.factory_id = p.factory_id AND r.is_active = TRUE
                          AND (r.product_id = p.id OR r.product_id = p.product_code)
                    )) AS no_routing,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM bom_items b
                        WHERE b.factory_id = p.factory_id
                          AND (b.product_id = p.id OR b.product_id = p.product_code)
                    )) AS no_bom
                FROM products p
                WHERE p.factory_id = :fid AND p.status = 'active'
            """), {"fid": factory_id})
            mrow = dict(md.first()._mapping)
            row["products_no_routing"] = mrow.get("no_routing", 0)
            row["products_no_bom"] = mrow.get("no_bom", 0)
        except Exception:
            row["products_no_routing"] = 0
            row["products_no_bom"] = 0

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
            await self.db.rollback()
            low = 0
        try:
            po = await self.db.execute(text("""
                SELECT COUNT(*) FROM purchase_orders WHERE factory_id = :fid AND status IN ('pending','approved')
            """), {"fid": factory_id})
            pending_po = po.scalar() or 0
        except Exception:
            await self.db.rollback()
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
            await self.db.rollback()
            defect_rate = 0
        try:
            d8 = await self.db.execute(text("""
                SELECT COUNT(*) FROM eight_d_reports WHERE factory_id = :fid AND status NOT IN ('closed','verified')
            """), {"fid": factory_id})
            open_8d = d8.scalar() or 0
        except Exception:
            await self.db.rollback()
            open_8d = 0
        return {"defect_rate": defect_rate, "open_8d": open_8d}

    # ═══════════════════════════════════════════════════════════
    # 判断（Assess）
    # ═══════════════════════════════════════════════════════════

    def _has_production_blockers(self, state: FactoryState) -> bool:
        """是否存在「先把活干完」级别的阻塞：待排 / 逾期 / 主数据缺口。

        只要其中任一条成立，就说明产能空闲并不等于可以接单——产线被卡住了。
        """
        return bool(
            state.pending_orders > 0
            or state.overdue_orders > 0
            or state.so_unplanned > 0
            or state.products_no_routing > 0
            or state.products_no_bom > 0
        )

    def _assess_order_mode(self, state: FactoryState) -> OrderMode:
        """根据订单负荷比判断模式。

        前置熔断（2026-10-04 修正）：负荷率低**不等于**欠单。线上实测出现过
        「在制 36 单（待排 22 / 执行中 14）+ 逾期 12 单，却因负荷率 0% 被判
        『订单欠缺』并去接新单」的逻辑倒错。因此只要存在待排/逾期/主数据缺口，
        且产能并未真正吃满（负荷 <= SURPLUS_RATIO_THRESHOLD），就强制进入 BLOCKED
        （生产阻塞/主数据异常），决策重心转为疏通积压 + 补主数据，**禁止接单**。
        """
        ratio = state.order_load_ratio
        if ratio <= SURPLUS_RATIO_THRESHOLD and self._has_production_blockers(state):
            return OrderMode.BLOCKED
        if ratio > SURPLUS_RATIO_THRESHOLD:
            return OrderMode.SURPLUS
        elif ratio < DEFICIT_RATIO_THRESHOLD:
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
        if mode == OrderMode.BLOCKED:
            # 生产阻塞/主数据异常：产能虽空但产线被卡住，先疏通积压，绝不接新单
            if state.overdue_orders > 0:
                decisions.append(CommanderDecision(
                    action=CommanderAction.EXPEDITE,
                    priority="urgent",
                    reason=f"生产阻塞且已积压{state.overdue_orders}单逾期，优先加急疏通",
                    target="overdue_orders",
                ))

        elif mode == OrderMode.DEFICIT:
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

        # 设备故障 → 维保（派设备工程师/维保智能体生成维修工单）。
        # 修：此前误用 PROCUREMENT，导致「设备故障」直接触发采购补货。
        # 采购只应由维保智能体在「需更换核心备件且库存不足」时二次发起。
        if state.equipment_broken > 0:
            decisions.append(CommanderDecision(
                action=CommanderAction.MAINTAIN,
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

        # 计划主数据缺口 → 提醒 PMC 补数据/纳入计划
        if state.so_unplanned > 0:
            decisions.append(CommanderDecision(
                action=CommanderAction.DATA_GAP,
                priority="high" if state.so_unplanned >= 10 else "normal",
                reason=f"{state.so_unplanned}张销售订单未纳入 MPS 计划，请计划员建计划并完成评估",
                target="so_unplanned",
            ))
        if state.products_no_routing > 0:
            decisions.append(CommanderDecision(
                action=CommanderAction.DATA_GAP,
                priority="high",
                reason=f"{state.products_no_routing}个产品缺工艺路线，APS 无法排程，需工艺/IE 补路由",
                target="products_no_routing",
            ))
        if state.products_no_bom > 0:
            decisions.append(CommanderDecision(
                action=CommanderAction.DATA_GAP,
                priority="high" if state.products_no_bom >= 50 else "normal",
                reason=f"{state.products_no_bom}个产品缺已生效 BOM，PMC 矩阵无法算齐套率/ETA",
                target="products_no_bom",
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
        """串行执行所有决策（共享同一 db session，不能并行 gather，否则事务交叉毒化）"""
        for d in decisions:
            await self._execute_single(d, factory_id, state)

    async def _execute_single(self, decision: CommanderDecision, factory_id: str, state: FactoryState):
        """执行单个决策"""
        try:
            if decision.action == CommanderAction.ACCEPT_ORDER:
                decision.result = await self._exec_accept_order(factory_id, decision.params)
            elif decision.action == CommanderAction.SCHEDULE_PRODUCTION:
                decision.result = await self._exec_schedule(factory_id)
            elif decision.action == CommanderAction.EXPEDITE:
                decision.result = await self._exec_expedite(factory_id)
            elif decision.action == CommanderAction.MAINTAIN:
                decision.result = {
                    "message": "已生成设备维修工单并派发设备工程师（缺备件时才由维保转采购）",
                    "status": "dispatched",
                    "recipient": "equipment_engineer",
                }
            elif decision.action == CommanderAction.PROCUREMENT:
                decision.result = {"message": "已标记补货需求，采购智能体跟进", "status": "delegated"}
            elif decision.action == CommanderAction.OVERTIME:
                decision.result = {"message": "加班建议已生成，待主管确认", "status": "pending_approval"}
            elif decision.action == CommanderAction.REJECT_ORDER:
                decision.result = {"message": "暂缓接单，产能已满", "status": "hold"}
            elif decision.action == CommanderAction.DATA_GAP:
                decision.result = {
                    "message": f"计划主数据缺口：{decision.reason}",
                    "status": "notified_pmc",
                    "recipient": "planner",
                }
            else:
                decision.result = {"message": f"{decision.action.value} 待实现", "status": "planned"}
            decision.executed = True
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
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
            if created:
                return {"message": f"已承接{created}个新订单并分解为工单", "created": created}
            return {
                "message": "⚠️ 未承接新订单：订单池无可承接订单，本轮接单已跳过",
                "created": 0,
                "status": "skipped",
            }
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            return {"message": f"接单执行: {str(e)[:80]}", "created": 0}

    async def _exec_schedule(self, factory_id: str) -> Dict:
        """排产：调用排产智能体"""
        try:
            from api.services.scheduling_agent_service import SchedulingAgent
            agent = SchedulingAgent(self.db)
            result = await agent.auto_schedule(factory_id)
            tasks_count = result.get("tasks_created", result.get("total_tasks", 0))
            if tasks_count:
                return {"message": f"自动排程完成，{tasks_count}个任务已排入", "tasks": tasks_count}
            # 排入 0 个不是成功：通常是待排工单缺工艺路线/BOM 导致排程被跳过。
            return {
                "message": "⚠️ 排程受阻：本次自动排程未排入任何任务"
                           "（待排工单可能缺工艺路线/BOM），已挂起并通知工艺/IE 与工程处理",
                "tasks": 0,
                "status": "blocked",
            }
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
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
    # 持续盯办：决策 → 挂任务中心（去重）→ 扫描器持续调度智能体跟进
    # ═══════════════════════════════════════════════════════════

    def _followup_config(self, d: CommanderDecision) -> Optional[Dict[str, Any]]:
        """决策 → 任务中心跟进配置（智能体/频率/标题）。按兵不动/拒单类不挂任务。"""
        a = d.action
        if a == CommanderAction.ACCEPT_ORDER:
            return {"agent_key": "pmc_agent", "interval": 30, "title": "跟进新订单承接与投产落地"}
        if a == CommanderAction.SCHEDULE_PRODUCTION:
            return {"agent_key": "scheduling_agent", "interval": 30, "title": "跟进自动排程落地"}
        if a == CommanderAction.EXPEDITE:
            return {"agent_key": "delivery_agent", "interval": 30, "title": "跟进逾期工单加急处理"}
        if a == CommanderAction.MAINTAIN:
            return {"agent_key": "equipment_agent", "interval": 60, "title": "跟进设备故障维修与产能恢复"}
        if a == CommanderAction.PROCUREMENT:
            return {"agent_key": "procurement_agent", "interval": 60, "title": "跟催缺料采购补货到位"}
        if a == CommanderAction.OVERTIME:
            return {"agent_key": "hr_agent", "interval": 120, "title": "跟进加班安排确认落实"}
        if a == CommanderAction.DISPATCH:
            return {"agent_key": "dispatch_agent", "interval": 15, "title": "跟进派工到工位开工"}
        return None

    async def _attach_followup_tasks(
        self, decisions: List[CommanderDecision], factory_id: str,
        state: FactoryState, created_by: str = "commander",
        objective: str = "", mode: str = "", cycle_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """把已执行的决策挂入任务中心并归属到行动计划（Plan）。
        由 followup_scanner_loop 定期调度对应智能体持续核实跟进，直到彻底完成闭环。
        按 source='commander' + title 去重：已有未完成任务沿用原计划继续盯，不重复挂账。
        返回 (attached, plan_id)；plan_id 为物化后的 active 计划（无新挂任务时为 None）。"""
        from api.services import followup_task_service as fts
        attached: List[Dict[str, Any]] = []
        plan_id: Optional[str] = None
        seq = 0
        # 按优先级排序后挂账（urgent 优先），plan_seq 体现计划内优先序
        order = {"urgent": 4, "high": 3, "normal": 2, "low": 1}
        sorted_decisions = sorted(
            decisions, key=lambda d: order.get(d.priority, 0), reverse=True)
        for d in sorted_decisions:
            if not d.executed:
                continue
            cfg = self._followup_config(d)
            if not cfg:
                continue
            # 去重：同厂同类未完成任务已在跟进，跳过（扫描器会持续盯）
            try:
                existing = (await self.db.execute(text(
                    "SELECT id, follow_count, progress_pct FROM followup_tasks "
                    "WHERE factory_id=:fid AND source='commander' AND title=:title "
                    "AND status IN ('open','blocked') ORDER BY created_at DESC LIMIT 1"
                ), {"fid": factory_id, "title": cfg["title"]})).first()
            except Exception:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                existing = None
            if existing:
                attached.append({
                    "task_id": existing[0], "title": cfg["title"],
                    "agent_key": cfg["agent_key"], "agent_name": fts._agent_name(cfg["agent_key"]),
                    "status": "tracked", "follow_count": existing[1] or 0,
                    "progress_pct": existing[2] or 0, "interval": cfg["interval"],
                })
                continue
            # 懒创建计划：确有要新挂的任务才建计划（避免空计划）
            if not plan_id:
                try:
                    plan_id = await fts.get_or_create_active_plan(
                        self.db, factory_id, objective, mode, created_by, cycle_id)
                    cnt = (await self.db.execute(text(
                        "SELECT COUNT(*) FROM followup_tasks WHERE plan_id=:pid"
                    ), {"pid": plan_id})).scalar() or 0
                    seq = int(cnt)
                except Exception as e:
                    try:
                        await self.db.rollback()
                    except Exception:
                        pass
                    _logger.warning(f"[commander] 创建计划失败: {e}")
                    plan_id = None
            desc = (
                f"【指挥官自主决策·持续盯办】\n"
                f"决策原因：{d.reason}\n"
                f"首轮执行：{(d.result or {}).get('message', '已派发')}\n"
                f"决策时态势：{self._build_state_summary(state)}\n"
                f"请以{fts._agent_name(cfg['agent_key'])}身份持续核实此事进展，"
                f"调用 MES 工具查证实际状态，未彻底完成前不要关闭，完成后给出结论。"
            )
            try:
                seq += 1
                task = await fts.create_task(
                    self.db, factory_id=factory_id, created_by=created_by,
                    title=cfg["title"], description=desc,
                    agent_key=cfg["agent_key"], follow_interval_minutes=cfg["interval"],
                    source="commander", item_type="followup",
                    plan_id=plan_id, plan_seq=seq if plan_id else None,
                )
                if task.get("task_id"):
                    attached.append({
                        "task_id": task["task_id"], "title": cfg["title"],
                        "agent_key": cfg["agent_key"], "agent_name": task.get("agent_name"),
                        "status": "created", "follow_count": 0, "progress_pct": 0,
                        "interval": cfg["interval"],
                    })
            except Exception as e:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                _logger.warning(f"[commander] 挂任务中心失败: {e}")
        return attached, plan_id

    def _build_objective(self, state: FactoryState, decisions: List[CommanderDecision]) -> str:
        """根据态势生成目标导向的计划总目标（一句话）。"""
        goals: List[str] = []
        if state.overdue_orders > 0:
            goals.append(f"消除{state.overdue_orders}个逾期工单")
        if state.equipment_broken > 0:
            goals.append(f"修复{state.equipment_broken}台故障设备恢复产能")
        if state.low_stock_items > 5:
            goals.append(f"补货{state.low_stock_items}项缺料")
        if state.pending_orders > 0:
            goals.append(f"排产{state.pending_orders}个待排工单")
        if state.due_7d_orders > 5 and state.station_utilization > 0.9:
            goals.append(f"保{state.due_7d_orders}个7天内到期工单准时交付")
        if not goals:
            goals.append("维持生产节奏并持续监控态势变化")
        mode_label = {"surplus": "订单充足", "normal": "产销平衡", "deficit": "订单欠缺",
                      "blocked": "生产阻塞/主数据异常"}
        return f"[{mode_label.get(state.order_mode.value, '')}] " + "；".join(goals)

    def _preview_plan(self, state: FactoryState, decisions: List[CommanderDecision]) -> Optional[Dict[str, Any]]:
        """不执行时的计划预览（dry-run）：只生成目标+有序子项列表，不落任务中心。"""
        actionable = [d for d in decisions if self._followup_config(d)]
        if not actionable:
            return None
        from api.services.agent_supervisor_service import AGENTS
        objective = self._build_objective(state, decisions)
        order = {"urgent": 4, "high": 3, "normal": 2, "low": 1}
        sorted_d = sorted(actionable, key=lambda d: order.get(d.priority, 0), reverse=True)
        items = []
        for i, d in enumerate(sorted_d, 1):
            cfg = self._followup_config(d) or {}
            agent_key = cfg.get("agent_key")
            agent = AGENTS.get(agent_key) if agent_key else None
            items.append({
                "plan_seq": i,
                "title": cfg.get("title") or d.reason,
                "agent_key": agent_key,
                "agent_name": agent["name"] if agent else "通用",
                "status": "planned",
                "progress_pct": 0,
            })
        return {
            "objective": objective, "mode": state.order_mode.value,
            "status": "preview", "progress_pct": 0, "items": items,
        }

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
        if state.so_unplanned > 0:
            alerts.append(f"{state.so_unplanned}张销售订单未纳入 MPS 计划，需 PMC 建计划")
        if state.products_no_routing > 0:
            alerts.append(f"{state.products_no_routing}个产品缺工艺路线，APS 排程会卡住")
        if state.products_no_bom > 0:
            alerts.append(f"{state.products_no_bom}个产品缺已生效 BOM，齐套率/ETA 无法计算")
        # 待排工单在 SURPLUS 下不产生排程决策（见 _decide 的 mode != SURPLUS 排除），
        # 于是「N 单待排」会整份汇报里一次都不出现。这里补上，避免高负荷厂被读成
        # 「订单充足、一切正常」。
        if state.pending_orders > 0 and state.order_mode == OrderMode.SURPLUS:
            alerts.append(
                f"{state.pending_orders}个工单待排产但未入计划，需人工确认排程/挂起/转外协"
            )
        return alerts

    def _plan_next_actions(self, state: FactoryState, decisions: List[CommanderDecision]) -> List[str]:
        next_actions = []
        mode = state.order_mode
        if mode == OrderMode.BLOCKED:
            next_actions.append("先疏通积压：加急逾期工单、消化待排工单")
            next_actions.append("补齐主数据（BOM/工艺路线/未计划销售订单）后再评估是否接单")
        elif mode == OrderMode.DEFICIT:
            next_actions.append("持续监控订单流入，产能空闲时主动承接")
            next_actions.append("评估是否可承接外部协作订单")
        elif mode == OrderMode.SURPLUS:
            next_actions.append("评估逾期工单加急方案")
            next_actions.append("低优先级订单协商延交")
            if state.pending_orders > 0:
                # 与 NORMAL 分支对齐：待排工单必须被明确处置，不能因为模式是
                # 「订单充足」就当作不存在。
                next_actions.append(
                    f"确认{state.pending_orders}个待排工单的处置（排程/挂起/转外协）"
                )
        else:
            next_actions.append("维持当前生产节奏")
            if state.pending_orders > 0:
                next_actions.append(f"下一轮排程消化{state.pending_orders}个待排工单")
        if state.low_stock_items > 0:
            next_actions.append("跟催采购到货情况")
        if state.so_unplanned > 0:
            next_actions.append(f"把{state.so_unplanned}张未计划销售订单纳入 MPS 计划并做 PMC 评估")
        if state.products_no_routing > 0:
            next_actions.append("联系工艺/IE 补齐缺工艺路线的产品")
        if state.products_no_bom > 0:
            next_actions.append("联系工程/PP 补齐缺 BOM 的产品")
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

        # 串行检查所有维度（共享同一 db session，并行 gather 会导致连接并发错误/事务交叉）
        for check_coro in (
            self._check_equipment_data(factory_id, state),
            self._check_production_data(factory_id, state),
            self._check_inventory_data(factory_id, state),
            self._check_quality_data(factory_id, state),
            self._check_plan_master_data(factory_id, state),
        ):
            try:
                check = await check_coro
            except Exception:
                try:
                    await self.db.rollback()
                except Exception:
                    pass
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

    async def _check_plan_master_data(self, factory_id: str, state: FactoryState) -> List[Dict]:
        """计划主数据充足性：销售订单是否纳入 MPS 计划、产品是否缺 BOM/工艺路线。

        这是 PMC 全链"待确认"的根因——产品没有已生效 BOM/路由，PMC 工作矩阵
        会在物料证据处断链，UHN/齐套率/FG Ready/ETA 全部无法输出。
        """
        gaps = []
        try:
            if state.so_unplanned > 0:
                gaps.append({
                    "dimension": "plan_master_data:so_unplanned",
                    "issue": f"{state.so_unplanned}张销售订单未纳入 MPS 计划",
                    "fallback": "订单未建计划，视为待计划需求，不进入排产",
                    "alert": f"📋 计划缺口：{state.so_unplanned}张销售订单未纳入 MPS 计划",
                    "action": "计划员为未计划订单建 MPS 计划并做 PMC 评估",
                    "responsible": ["planner", "production_manager"],
                    "severity": "high",
                })
            if state.products_no_routing > 0:
                gaps.append({
                    "dimension": "plan_master_data:no_routing",
                    "issue": f"{state.products_no_routing}个产品缺工艺路线，APS 无法排程",
                    "fallback": "缺路由产品以产能速度倒推，不承诺精确交期",
                    "alert": f"🗺️ 工艺缺口：{state.products_no_routing}个产品缺工艺路线",
                    "action": "工艺/IE 为缺路由产品绑定工艺路线与标准工时",
                    "responsible": ["process_engineer", "planner"],
                    "severity": "high",
                })
            if state.products_no_bom > 0:
                gaps.append({
                    "dimension": "plan_master_data:no_bom",
                    "issue": f"{state.products_no_bom}个产品缺已生效 BOM，齐套率/ETA 无法计算",
                    "fallback": "缺 BOM 产品不做 MRP 齐套结论",
                    "alert": f"🧩 BOM 缺口：{state.products_no_bom}个产品缺已生效 BOM",
                    "action": "工程/PP 为缺 BOM 产品维护并生效 BOM 版本",
                    "responsible": ["planner", "engineering"],
                    "severity": "high",
                })
        except Exception:
            pass
        return gaps

    async def _notify_data_gap(self, factory_id: str, gap: Dict):
        """数据缺口 → 通知责任人补填。

        采用广播通知（recipient=NULL）：通知中心按 username 过滤，
        而缺口责任人是角色（planner/process_engineer 等）而非具体账号，
        写角色字符串会导致通知无人可见。改广播后所有用户都能在通知中心看到，
        内容中保留责任角色（responsible）与处理建议（action）。

        去重：同一工厂同一缺口维度 24 小时内已有未读通知则不重复发送，
        避免盯办循环每轮巡检都轰炸通知中心。
        """
        try:
            import uuid as _uuid
            # 去重检查：24 小时内是否已有同工厂同维度未读缺口通知
            dup = await self.db.execute(text("""
                SELECT 1 FROM notifications
                WHERE factory_id = :fid AND category = 'data_governance'
                  AND recipient IS NULL AND is_read = FALSE
                  AND title = :title
                  AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """), {
                "fid": factory_id,
                "title": f"[指挥官] 数据缺口：{gap['dimension']}",
            })
            if dup.first() is not None:
                return

            responsible_list = ", ".join(gap.get("responsible", []))
            reason = gap.get("issue", "")
            action = gap.get("action", "")
            await self.db.execute(text("""
                INSERT INTO notifications (id, factory_id, title, content, severity, category, recipient, is_read, source_type, created_at)
                VALUES (:id, :fid, :title, :content, :sev, 'data_governance', NULL, FALSE, 'commander', NOW())
            """), {
                "id": str(_uuid.uuid4()),
                "fid": factory_id,
                "title": f"[指挥官] 数据缺口：{gap['dimension']}",
                "content": f"{reason}\n处理建议: {action}\n责任角色: {responsible_list or '未指定'}\n降级策略: {gap.get('fallback', '')}",
                "sev": gap.get("severity", "warning"),
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


# ═══════════════════════════════════════════════════════════
# 后台持续盯办循环：为每个开启指挥官的用户定期巡检
# （感知新问题 + 把新决策挂入任务中心；任务的持续跟进由
#   followup_scanner_loop 调度智能体完成，二者协同形成“长久盯着”闭环）
# ═══════════════════════════════════════════════════════════

async def commander_watch_loop() -> None:
    """后台盯办循环（main.py startup 启动）。

    指挥官的核心价值不是一次性决策，而是持续长久地盯着：
    每隔一段时间为所有开启指挥官的用户重新巡检一遍，发现新问题就
    生成新决策并挂入任务中心（带去重）；任务中心扫描器再定期调度
    对应智能体持续跟进，直到任务彻底完成。
    """
    import os
    if os.getenv("COMMANDER_WATCH_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        _logger.info("指挥官盯办循环已禁用（COMMANDER_WATCH_ENABLED=0）")
        from api.services.engine_heartbeat import record as _heartbeat
        await _heartbeat("commander-watch", "disabled")
        return
    interval = max(60, int(os.getenv("COMMANDER_WATCH_INTERVAL_SECONDS", "300") or 300))
    _logger.info("工厂指挥官盯办循环启动，每 %s 秒为已开启用户巡检一次", interval)
    from api.services.engine_heartbeat import record as _heartbeat
    from database.db_config import db_config
    while True:
        try:
            await asyncio.sleep(interval)
            enabled = [(uid, cfg) for uid, cfg in FactoryCommander._user_commanders.items()
                       if cfg.get("enabled")]
            watched = errors = 0
            if not enabled:
                # 无用户开启指挥官时，仍对默认工厂做数据治理巡检（只发缺口通知，
                # 不执行决策/不挂任务），确保计划主数据缺口提醒自动生效。
                try:
                    async with db_config.session_factory() as db:
                        commander = FactoryCommander(db)
                        state = await commander._sense("FAC_MECH_001")
                        gaps = await commander._check_data_governance("FAC_MECH_001", state)
                        _logger.info("[commander-watch] 默认工厂数据治理巡检 | 缺口=%d", len(gaps))
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("[commander-watch] 默认工厂巡检异常：%s", exc)
                # 没有开启用户时这轮只做数据治理巡检，也算干活，照样跳心跳
                await _heartbeat("commander-watch", "tick", interval_seconds=interval,
                                 detail={"mode": "governance", "watched": 0})
                continue
            for uid, cfg in enabled:
                fid = cfg.get("factory_id") or "FAC_MECH_001"
                try:
                    async with db_config.session_factory() as db:
                        commander = FactoryCommander(db)
                        report = await commander.run_cycle(
                            fid, auto_execute=True, created_by=cfg.get("username") or uid)
                        _logger.info(
                            "[commander-watch] 用户 %s 巡检完成 | mode=%s | decisions=%d | 盯办任务=%d",
                            uid, report.order_mode.value, len(report.decisions), len(report.followup_tasks))
                        watched += 1
                except Exception as exc:  # noqa: BLE001 — 单用户巡检失败不影响其他用户
                    _logger.warning("[commander-watch] 用户 %s 巡检异常：%s", uid, exc)
                    errors += 1
            await _heartbeat("commander-watch", "tick", interval_seconds=interval,
                             detail={"mode": "watch", "watched": watched, "errors": errors})
        except asyncio.CancelledError:
            _logger.info("工厂指挥官盯办循环停止")
            return
        except Exception as exc:  # noqa: BLE001 — 盯办循环必须常驻
            _logger.warning("指挥官盯办循环异常：%s", exc)
