"""
工厂指挥官：决策轨迹（Decision Trail）测试

钉住 commander_decision_log 的落盘与回放契约：

- _snapshot_state 保留【原始数值】而非展示态 to_dict()（后者是 "0%" / "3/5"，
  且 load_ratio 被 round(…, 2)），并把 Decimal 归一成 float。
  Decimal 不归一 → json.dumps 抛 "Object of type Decimal is not JSON serializable"，
  这个 bug **只在真实 run_cycle 路径上暴露**（合成状态手写 float 测不出来），
  所以必须由测试钉死，不能只靠一次性脚本。
- _mode_reason：策略判定记判别量；人工 forced/override 只记来源
  —— 否则重放会把人工决定算成策略效果。
- 回放等价：快照 → 重建 FactoryState → _assess_order_mode / _decide 复现同一决策。
  契约是【决策等价】，不是浮点逐位相等（Decimal("0.93") != 0.93）。
- 阈值参数化：SURPLUS/DEFICIT 阈值常量真的在驱动判定（防止退回硬编码）。
- primary 模式不得覆盖 PMC 四类确定性映射（报告 §9.3 的真实劫持）。

注：异步服务方法用 asyncio.run() 包装，同 test_commander_plan_data_gap.py。
"""

import asyncio
import json
from dataclasses import asdict
from decimal import Decimal

import pytest

from api.services import factory_commander as fc
from api.services.factory_commander import (
    FactoryCommander,
    FactoryState,
    OrderMode,
)

pytestmark = [pytest.mark.unit]


def _run(coro):
    return asyncio.run(coro)


def _commander():
    """快照 / 判定 / 决策方法都不依赖 db，传 None 即可。"""
    return FactoryCommander(None)


def _sig(decisions):
    return [(d.action.value, d.priority, d.target) for d in decisions]


# ═══════════════ 快照：原始数值 + Decimal 归一 ═══════════════

def test_snapshot_keeps_raw_values_not_display_form():
    """快照必须是原始数值，不能是 to_dict() 的展示态。"""
    cmd = _commander()
    st = FactoryState(
        factory_id="FAC_X", total_stations=5, busy_stations=3,
        station_utilization=0.0, order_load_ratio=16.819541474001678,
    )
    snap = cmd._snapshot_state(st)
    display = st.to_dict()

    # 展示态把数值格式化成字符串
    assert display["capacity"]["utilization"] == "0%"
    assert display["capacity"]["stations"] == "3/5"
    # 快照必须是数字，否则无法无损重建
    assert snap["station_utilization"] == 0.0
    assert snap["busy_stations"] == 3
    assert snap["total_stations"] == 5
    assert isinstance(snap["order_load_ratio"], float)
    # 展示态四舍五入丢精度，快照保留全精度 —— 这是不用 to_dict() 的核心理由
    assert display["orders"]["load_ratio"] == 16.82
    assert snap["order_load_ratio"] == 16.819541474001678
    # order_mode 以字符串落盘，才能 JSONB 化
    assert snap["order_mode"] == "normal"


def test_snapshot_normalises_decimal_to_float():
    """asyncpg 的 COUNT/AVG/SUM 返回 Decimal；不归一，落盘整条失败。"""
    cmd = _commander()
    st = FactoryState(
        factory_id="FAC_X",
        order_load_ratio=Decimal("16.819541474001678"),
        station_utilization=Decimal("0.25"),
    )
    snap = cmd._snapshot_state(st)

    assert isinstance(snap["order_load_ratio"], float)
    assert isinstance(snap["station_utilization"], float)
    # 归一之后必须能 JSON 序列化 —— 正是线上报错的那一步
    payload = json.dumps(snap, ensure_ascii=False)
    assert "16.819541474001678" in payload


def test_raw_asdict_with_decimal_would_break_json():
    """钉住坑本身：未归一的 Decimal 会让 json.dumps 抛 TypeError。

    这是"只在真实路径暴露"的那个 bug 的最小复现，防止有人删掉归一逻辑。
    """
    st = FactoryState(factory_id="FAC_X", order_load_ratio=Decimal("1.5"))
    with pytest.raises(TypeError):
        json.dumps(asdict(st))
    # 归一后同样的数据可以序列化
    assert json.dumps(_commander()._snapshot_state(st)) is not None


# ═══════════════ _mode_reason ═══════════════

def test_mode_reason_policy_records_discriminant():
    cmd = _commander()
    st = FactoryState(factory_id="FAC_X", order_load_ratio=1.5,
                      order_mode=OrderMode.SURPLUS)
    assert cmd._mode_reason(st, "policy") == "load_ratio=1.50"


def test_mode_reason_blocked_lists_blockers():
    cmd = _commander()
    st = FactoryState(
        factory_id="FAC_X", order_mode=OrderMode.BLOCKED,
        pending_orders=22, overdue_orders=12, so_unplanned=6,
        products_no_routing=1, products_no_bom=1,
    )
    reason = cmd._mode_reason(st, "policy")
    assert reason.startswith("blockers: ")
    for frag in ("pending=22", "overdue=12", "so_unplanned=6",
                 "no_routing=1", "no_bom=1"):
        assert frag in reason


def test_mode_reason_forced_records_source_not_discriminant():
    """人工干预只记来源，否则重放会把人工决定算成策略效果。"""
    cmd = _commander()
    st = FactoryState(factory_id="FAC_X", order_load_ratio=1.5,
                      order_mode=OrderMode.DEFICIT)
    assert cmd._mode_reason(st, "forced") == "forced=deficit"
    assert cmd._mode_reason(st, "override") == "override=deficit"


# ═══════════════ 回放等价 ═══════════════

def test_replay_reproduces_decisions_from_snapshot():
    """快照 → 重建 FactoryState → 重跑策略，模式与决策三元组必须一致。"""
    cmd = _commander()
    original = FactoryState(
        factory_id="FAC_MECH_001",
        active_orders=85, pending_orders=69, in_progress_orders=16,
        overdue_orders=63,
        order_load_ratio=16.819541474001678,
        so_unplanned=53, products_no_routing=575, products_no_bom=473,
        low_stock_items=371,
    )
    original.order_mode = cmd._assess_order_mode(original)
    first = _run(cmd._decide(original))
    assert first, "该状态应产出决策，否则这个用例没意义"

    # 走一遍落盘/读回的序列化边界
    snap = json.loads(json.dumps(cmd._snapshot_state(original), default=fc._json_default))
    snap["order_mode"] = OrderMode(snap["order_mode"])
    rebuilt = FactoryState(**snap)

    assert cmd._assess_order_mode(rebuilt) == original.order_mode
    assert _sig(_run(cmd._decide(rebuilt))) == _sig(first)


# ═══════════════ 阈值参数化 & 闸门语义 ═══════════════

def test_threshold_constants_drive_mode_assessment():
    """阈值必须由常量驱动（防止退回硬编码 1.2 / 0.8）。"""
    cmd = _commander()
    st = FactoryState(factory_id="FAC_X", order_load_ratio=1.5, overdue_orders=5)

    assert fc.SURPLUS_RATIO_THRESHOLD == 1.2
    assert fc.DEFICIT_RATIO_THRESHOLD == 0.8
    assert cmd._assess_order_mode(st) == OrderMode.SURPLUS

    original = fc.SURPLUS_RATIO_THRESHOLD
    try:
        fc.SURPLUS_RATIO_THRESHOLD = 2.0   # 抬到负荷之上 → 有阻塞 ⇒ BLOCKED
        assert cmd._assess_order_mode(st) == OrderMode.BLOCKED
    finally:
        fc.SURPLUS_RATIO_THRESHOLD = original
    assert cmd._assess_order_mode(st) == OrderMode.SURPLUS


def test_deficit_and_normal_bands():
    cmd = _commander()
    # 无阻塞时按负荷率分档
    assert cmd._assess_order_mode(
        FactoryState(factory_id="FAC_X", order_load_ratio=0.5)
    ) == OrderMode.DEFICIT
    assert cmd._assess_order_mode(
        FactoryState(factory_id="FAC_X", order_load_ratio=1.0)
    ) == OrderMode.NORMAL


def test_blocked_gate_only_applies_below_surplus_threshold():
    """记录当前闸门语义（已知不对称，见报告 §10.4）。

    阻塞闸门挂在负荷率条件之后，所以【阻塞指标更重】的高负荷厂反而拿到更宽松的
    surplus，而轻症低负荷厂进 BLOCKED。这是有意的记录：若将来决定改语义，这条会红。
    """
    cmd = _commander()
    heavy = FactoryState(factory_id="FAC_HEAVY", order_load_ratio=16.82,
                         overdue_orders=63, pending_orders=69)
    light = FactoryState(factory_id="FAC_LIGHT", order_load_ratio=0.0,
                         overdue_orders=12, pending_orders=22)
    assert cmd._assess_order_mode(heavy) == OrderMode.SURPLUS
    assert cmd._assess_order_mode(light) == OrderMode.BLOCKED


# ═══════════════ 意图路由：async 包装 + 确定性契约 ═══════════════

def test_resolve_intent_async_matches_sync(monkeypatch):
    """async 包装必须与同步实现同结果（不碰网络）。"""
    from api.services import laya_intent_service as laya
    from api.services.chat_tools_service import resolve_intent, resolve_intent_async

    monkeypatch.setattr(laya, "mode", lambda: "off")
    for msg in ["在制工单有多少", "查一下库存", "库存怎么降", "今天天气怎么样"]:
        assert _run(resolve_intent_async(msg)) == resolve_intent(msg)


def test_primary_mode_never_overrides_deterministic_pmc_tools(monkeypatch):
    """primary 模式下 Laya 不得覆盖 PMC 四类（报告 §9.3 的真实劫持）。

    真实事故：Laya 把「库存怎么降」「控过多少物料」判成查库存，而 query_inventory
    不在确定性执行白名单里，这两条 PMC 问题因此丢掉全部确定性答复。
    """
    from api.services import laya_intent_service as laya
    from api.services.chat_tools_service import (
        DETERMINISTIC_INTENT_TOOLS,
        _resolve_intent_keyword,
        resolve_intent,
    )

    monkeypatch.setattr(laya, "is_enabled", lambda: True)
    monkeypatch.setattr(laya, "mode", lambda: "primary")
    # 模拟 Laya 的粗粒度误判：凡是涉及库存/物料就路由到 query_inventory
    # （真实事故里「控过多少物料」正是这样被判成"查库存"的）
    monkeypatch.setattr(
        laya, "resolve_tool",
        lambda m: {"tool": "query_inventory", "args": {}}
        if ("库存" in m or "物料" in m or "欠料" in m) else None,
    )

    for q in ["库存怎么降", "控过多少物料"]:
        kw = _resolve_intent_keyword(q)
        assert kw and kw["tool"] in DETERMINISTIC_INTENT_TOOLS, f"{q} 应命中确定性白名单"
        assert resolve_intent(q)["tool"] == kw["tool"], f"{q} 被 Laya 覆盖了"

    # 非确定性工具仍允许 Laya 补位（否则就是把 Laya 整个关掉）
    assert _resolve_intent_keyword("有没有欠料的") is None
    assert resolve_intent("有没有欠料的")["tool"] == "query_inventory"
