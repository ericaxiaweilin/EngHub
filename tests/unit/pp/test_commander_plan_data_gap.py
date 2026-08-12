"""
工厂指挥官：计划主数据缺口巡检测试（审计 MPS 断链根因修复）

覆盖：
- _sense_orders 解析销售订单未纳入 MPS 计划数 / 缺路由产品数 / 缺 BOM 产品数
- _decide 在缺口>0 时生成 DATA_GAP 决策
- _generate_alerts / _plan_next_actions 输出缺口提醒
- _check_plan_master_data 返回可通知的责任人缺口清单

注：异步服务方法通过 asyncio.run() 包装为同步调用，规避
pytest-asyncio 1.3.0 + Python 3.14 的循环作用域不兼容。
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

from api.services.factory_commander import (
    FactoryCommander,
    FactoryState,
    CommanderAction,
    CommanderDecision,
)


def _run(coro):
    return asyncio.run(coro)


def _mock_sense_result(so_unplanned=0, no_routing=0, no_bom=0, active=0):
    """构造 _sense_orders 返回的行（dict），并 mock db.execute 按 SQL 关键字区分。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=lambda *a, **k: _result_for_orders_sql(str(a[0]), so_unplanned, no_routing, no_bom, active))
    return db


def _result_for_orders_sql(sql, so_unplanned, no_routing, no_bom, active):
    res = MagicMock()
    if "FROM work_orders" in sql:
        row = MagicMock()
        row._mapping = {
            "active": active, "pending": active, "in_progress": 0,
            "overdue": 0, "due_7d": 0,
            "so_unplanned": so_unplanned,
            "products_no_routing": no_routing,
            "products_no_bom": no_bom,
        }
        res.first.return_value = row
    elif "FROM sales_orders" in sql:
        res.scalar.return_value = so_unplanned
    elif "FROM products" in sql:
        row = MagicMock()
        row._mapping = {"no_routing": no_routing, "no_bom": no_bom}
        res.first.return_value = row
    return res


# ─────────────── 感知：plan_data_gaps 解析 ───────────────

def test_sense_parses_unplanned_and_master_data_gaps():
    async def scenario():
        db = MagicMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: _result_for_orders_sql(
            str(a[0]), so_unplanned=57, no_routing=574, no_bom=475, active=80
        ))
        svc = FactoryCommander(db)
        state = await svc._sense("FAC_MECH_001")
        return state

    state = _run(scenario())
    assert state.so_unplanned == 57
    assert state.products_no_routing == 574
    assert state.products_no_bom == 475
    d = state.to_dict()
    assert d["plan_data_gaps"]["so_unplanned"] == 57


def test_sense_zero_gaps_when_covered():
    async def scenario():
        db = MagicMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: _result_for_orders_sql(
            str(a[0]), so_unplanned=0, no_routing=0, no_bom=0, active=5
        ))
        svc = FactoryCommander(db)
        state = await svc._sense("FAC_MECH_001")
        return state

    state = _run(scenario())
    assert state.so_unplanned == 0
    assert state.products_no_routing == 0
    assert state.products_no_bom == 0


# ─────────────── 决策：DATA_GAP 生成 ───────────────

def test_decide_emits_data_gap_for_unplanned_orders():
    state = FactoryState(factory_id="FAC_MECH_001")
    state.so_unplanned = 57
    state.products_no_routing = 574
    state.products_no_bom = 475
    state.order_mode = "normal"
    decisions = _run(FactoryCommander(MagicMock())._decide(state))
    actions = {(d.action, d.target) for d in decisions}
    assert (CommanderAction.DATA_GAP, "so_unplanned") in actions
    assert (CommanderAction.DATA_GAP, "products_no_routing") in actions
    assert (CommanderAction.DATA_GAP, "products_no_bom") in actions


def test_decide_no_data_gap_when_covered():
    state = FactoryState(factory_id="FAC_MECH_001")
    state.order_mode = "normal"
    decisions = _run(FactoryCommander(MagicMock())._decide(state))
    assert all(d.action != CommanderAction.DATA_GAP for d in decisions)


# ─────────────── 提醒文案 ───────────────

def test_generate_alerts_mentions_gaps():
    state = FactoryState(factory_id="FAC_MECH_001")
    state.so_unplanned = 10
    state.products_no_routing = 99
    state.products_no_bom = 50
    alerts = FactoryCommander(MagicMock())._generate_alerts(state)
    joined = " ".join(alerts)
    assert "未纳入 MPS 计划" in joined
    assert "缺工艺路线" in joined
    assert "缺已生效 BOM" in joined


def test_plan_next_actions_mentions_pmc_tasks():
    state = FactoryState(factory_id="FAC_MECH_001")
    state.so_unplanned = 3
    actions = FactoryCommander(MagicMock())._plan_next_actions(state, [])
    assert any("纳入 MPS 计划" in a for a in actions)


# ─────────────── 数据治理缺口清单 ───────────────

def test_check_plan_master_data_returns_notifiable_gaps():
    state = FactoryState(factory_id="FAC_MECH_001")
    state.so_unplanned = 8
    state.products_no_routing = 100
    state.products_no_bom = 60

    async def scenario():
        svc = FactoryCommander(MagicMock())
        return await svc._check_plan_master_data("FAC_MECH_001", state)

    gaps = _run(scenario())
    assert len(gaps) == 3
    dims = {g["dimension"] for g in gaps}
    assert dims == {"plan_master_data"}
    texts = " | ".join(g["issue"] for g in gaps)
    assert "未纳入 MPS 计划" in texts
    assert "缺工艺路线" in texts
    assert "缺已生效 BOM" in texts
    # 责任人含计划员
    assert any("planner" in (g.get("responsible") or []) for g in gaps)


# ─────────────── 通知：广播修复 ───────────────

def test_notify_data_gap_writes_broadcast_notification():
    """缺口通知应为广播（recipient=NULL），确保通知中心所有用户可见。"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()

    async def scenario():
        svc = FactoryCommander(db)
        await svc._notify_data_gap("FAC_MECH_001", {
            "dimension": "plan_master_data",
            "issue": "57张销售订单未纳入 MPS 计划",
            "action": "计划员为未计划订单建 MPS 计划",
            "fallback": "订单未建计划，视为待计划需求",
            "responsible": ["planner", "production_manager"],
            "severity": "high",
        })

    _run(scenario())
    assert db.execute.await_count >= 1
    stmt = str(db.execute.await_args.args[0])
    params = db.execute.await_args.args[1] if len(db.execute.await_args.args) > 1 else {}
    # 广播语义：不再按角色字符串定向（无 :rec 占位符），recipient 走 NULL
    assert ":rec" not in stmt
    assert "recipient" in stmt
    # 责任角色保留在内容中供 PMC 认领
    assert "planner" in params.get("content", "")
    assert "生产_manager" not in params.get("content", "")
