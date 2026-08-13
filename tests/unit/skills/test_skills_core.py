"""Tests for core/skills — EngFlow Skills 层（Phase 2）。

覆盖：注册表路由、自动发现、工具定义聚合、legacy 回退哨兵、
work_order/inventory 执行、Kernel 接入（skill 优先 + legacy 回退）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.skills.base import BaseSkill
from core.skills.registry import (
    SkillRegistry, LEGACY_FALLBACK, is_legacy_fallback,
)
from core.skills.work_order.skill import WorkOrderSkill
from core.skills.inventory.skill import InventorySkill


@pytest.fixture(scope="session")
def event_loop():
    """Python 3.14 兼容的 event_loop（覆盖 tests/unit/conftest 的旧实现）。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def clean_registry():
    SkillRegistry.reset()
    yield
    SkillRegistry.reset()


# ──────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────

def test_register_and_route_tools():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    reg.register(InventorySkill())

    assert reg.has_skill("work_order")
    assert reg.has_skill("inventory")
    assert reg.has_tool("query_work_orders")
    assert reg.has_tool("query_inventory")

    skill = reg.get_skill_for_tool("create_work_order")
    assert skill is not None
    assert skill.name == "work_order"


def test_all_tool_definitions_aggregate():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    reg.register(InventorySkill())

    defs = reg.all_tool_definitions()
    names = {d["function"]["name"] for d in defs}
    assert "query_work_orders" in names
    assert "create_work_order" in names
    assert "query_inventory" in names
    assert "query_stagnant" in names
    # 每个定义符合 OpenAI function-calling 结构
    for d in defs:
        assert d["type"] == "function"
        assert d["function"]["parameters"]["type"] == "object"


def test_unknown_tool_error():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    assert not reg.has_tool("no_such_tool")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    result = await reg.execute("no_such_tool", {})
    assert "error" in result


def test_register_rejects_non_skill():
    reg = SkillRegistry()
    with pytest.raises(TypeError):
        reg.register(object())


def test_autodiscover_finds_skills():
    reg = SkillRegistry()
    n = reg.autodiscover()
    assert n >= 2
    names = {s.name for s in reg.get_all()}
    assert "work_order" in names
    assert "inventory" in names


# ──────────────────────────────────────────────
# BaseSkill
# ──────────────────────────────────────────────

def test_skill_tool_names_and_has_tool():
    skill = WorkOrderSkill()
    names = skill.tool_names()
    assert "query_work_orders" in names
    assert skill.has_tool("create_work_order")
    assert not skill.has_tool("query_inventory")


# ──────────────────────────────────────────────
# Legacy fallback 哨兵
# ──────────────────────────────────────────────

def test_legacy_fallback_sentinel():
    assert is_legacy_fallback(LEGACY_FALLBACK)
    assert not is_legacy_fallback({"ok": True})
    assert not is_legacy_fallback({"error": "boom"})


@pytest.mark.asyncio
async def test_inventory_unmigrated_tool_returns_fallback():
    reg = SkillRegistry()
    reg.register(InventorySkill())
    result = await reg.execute(
        "query_stagnant", {"days": 180},
        db=MagicMock(),
    )
    assert is_legacy_fallback(result)


@pytest.mark.asyncio
async def test_inventory_with_exec_impl_calls_legacy():
    calls = []

    async def fake_legacy(db, tool_name, args, operator="", factory_id=None):
        calls.append((tool_name, args))
        return {"items": []}

    reg = SkillRegistry()
    reg.register(InventorySkill(exec_impl=fake_legacy))
    result = await reg.execute(
        "query_stagnant", {"days": 90},
        db=MagicMock(), operator="eric", factory_id="F01",
    )
    assert calls == [("query_stagnant", {"days": 90})]
    assert "items" in result


# ──────────────────────────────────────────────
# WorkOrder Skill 执行（mock db）
# ──────────────────────────────────────────────

class FakeScalar:
    def __init__(self, val):
        self._val = val

    def scalar_one_or_none(self):
        return self._val


@pytest.mark.asyncio
async def test_work_order_query_list_with_mock_db():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())

    db = AsyncMock()
    wo = SimpleNamespace(
        id="wo1", work_order_code="WO-001", factory_id="F01",
        product_id="P1", planned_qty=10, completed_qty=2,
        status="in_progress", priority="high", planned_due="2026-08-20",
    )
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: [wo]))
    )

    result = await reg.execute(
        "query_work_orders", {"status": "in_progress"},
        db=db, factory_id="F01",
    )
    assert result["count"] == 1
    assert result["items"][0]["work_order_code"] == "WO-001"


@pytest.mark.asyncio
async def test_work_order_create_with_mock_db():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())

    db = AsyncMock()

    async def fake_commit():
        pass

    async def fake_refresh(obj):
        obj.id = "new-wo"

    db.commit = AsyncMock(side_effect=fake_commit)
    db.refresh = AsyncMock(side_effect=fake_refresh)

    result = await reg.execute(
        "create_work_order",
        {"factory_id": "F01", "product_id": "P1", "quantity": 5, "priority": "high"},
        db=db, operator="eric",
    )
    assert result["success"] is True
    assert result["work_order"]["factory_id"] == "F01"


@pytest.mark.asyncio
async def test_work_order_create_missing_args():
    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    result = await reg.execute("create_work_order", {}, db=MagicMock())
    assert "error" in result


@pytest.mark.asyncio
async def test_inventory_query_with_mock_db():
    reg = SkillRegistry()
    reg.register(InventorySkill())

    db = AsyncMock()
    inv = SimpleNamespace(
        material_id="mid1", material_code="MAT-001",
        warehouse_id="WH-1", batch_code="B1", total_qty=120,
        available_qty=100, reserved_qty=20, status="available",
    )
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: [inv]))
    )

    result = await reg.execute(
        "query_inventory", {"material_keyword": "钢"},
        db=db, factory_id="F01",
    )
    assert result["count"] == 1
    assert result["inventory"][0]["material_code"] == "MAT-001"
    assert result["inventory"][0]["available_qty"] == 100


# ──────────────────────────────────────────────
# Kernel 接入：skill 优先 + legacy 回退
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kernel_skill_priority_and_legacy_fallback():
    from core.kernel import HarnessKernel
    from core.kernel.context import KernelContext

    reg = SkillRegistry()
    reg.register(WorkOrderSkill())
    reg.register(InventorySkill())

    calls = []

    async def fake_legacy(tool_name, arguments):
        calls.append(("legacy", tool_name))
        return {"legacy": True, "tool": tool_name}

    async def responder(payload):
        # 第二轮（工具已执行）返回最终回复
        if any(m.get("role") == "tool" for m in payload["messages"]):
            return MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "完成"}}]},
            )
        import json
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "query_stagnant",  # 未迁移 → legacy
                        "arguments": json.dumps({"days": 90}),
                    },
                }],
            }}]},
        )

    kernel = HarnessKernel(
        db=MagicMock(),
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=fake_legacy,
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: f"TOOL: {r}",
        verify_reply=None,
        make_tool_action=lambda tool, label, args, result, is_w, is_s, ok: {
            "tool": tool, "success": ok,
        },
        write_tools=frozenset(),
        sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys",
        final_grounding_prompt="ground",
        max_tool_rounds=3,
        skill_registry=reg,
        legacy_execute_tool=fake_legacy,
    )

    ctx = KernelContext(
        request_id="req-skill", factory_id="F01",
        user=SimpleNamespace(username="eric"),
        messages=[{"role": "user", "content": "查滞呆料"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        operator="eric",
    )
    result = await kernel.handle(ctx)
    # query_stagnant 未迁移 → legacy 被调用
    assert ("legacy", "query_stagnant") in calls
    assert result.reply == "完成"


@pytest.mark.asyncio
async def test_kernel_uses_skill_for_migrated_tool():
    from core.kernel import HarnessKernel
    from core.kernel.context import KernelContext

    reg = SkillRegistry()
    reg.register(WorkOrderSkill())

    legacy_calls = []

    async def fake_legacy(tool_name, arguments):
        legacy_calls.append(tool_name)
        return {"legacy": True}

    async def responder(payload):
        # 第二轮（工具已执行）返回最终回复
        if any(m.get("role") == "tool" for m in payload["messages"]):
            return MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "已查"}}]},
            )
        import json
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "query_work_orders",  # 已迁移 → skill
                        "arguments": json.dumps({"status": "in_progress"}),
                    },
                }],
            }}]},
        )

    db = AsyncMock()
    wo = SimpleNamespace(
        id="wo1", work_order_code="WO-001", factory_id="F01",
        product_id="P1", planned_qty=10, completed_qty=0,
        status="in_progress", priority="medium", planned_due=None,
    )
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: [wo]))
    )

    kernel = HarnessKernel(
        db=db,
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=fake_legacy,
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: f"TOOL: {r}",
        verify_reply=None,
        make_tool_action=lambda tool, label, args, result, is_w, is_s, ok: {
            "tool": tool, "success": ok,
        },
        write_tools=frozenset(),
        sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys",
        final_grounding_prompt="ground",
        max_tool_rounds=3,
        skill_registry=reg,
        legacy_execute_tool=fake_legacy,
    )

    ctx = KernelContext(
        request_id="req-skill2", factory_id="F01",
        user=SimpleNamespace(username="eric"),
        messages=[{"role": "user", "content": "查工单"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        operator="eric",
    )
    result = await kernel.handle(ctx)
    # query_work_orders 已迁移 → legacy 不被调用
    assert "query_work_orders" not in legacy_calls
    assert result.reply == "已查"