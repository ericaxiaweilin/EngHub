"""Tests for Phase 4 — PermissionGate（Chat V2 工具权限门控）。

覆盖：读/写工具映射、无权限拒绝、作用域校验、operator 一致性、
Kernel 接入后拒绝执行（skill/legacy 均不调用）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kernel.permission import PermissionGate
from core.kernel.context import KernelContext


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _ctx(operator="eric", factory_id="F01", username="eric"):
    return KernelContext(
        request_id="r", factory_id=factory_id,
        user=SimpleNamespace(username=username),
        messages=[], model_route={}, operator=operator,
    )


DEV_VIEW = [{"module": "work_order", "actions": ["view"]}]
ADMIN = [
    {"module": m, "actions": ["view", "create", "edit", "delete", "approve",
                              "release", "start", "complete", "cancel",
                              "confirm_report", "modify_report", "export", "manage"]}
    for m in ["work_order", "production_report", "station", "routing", "equipment",
              "wms", "qms", "pp", "cost", "hr", "simulation", "tms", "ai", "system"]
]


# ──────────────────────────────────────────────
# 映射
# ──────────────────────────────────────────────

def test_module_for_tool():
    g = PermissionGate()
    assert g.module_for_tool("query_work_orders") == "work_order"
    assert g.module_for_tool("create_work_order") == "work_order"
    assert g.module_for_tool("query_inventory") == "wms"
    assert g.module_for_tool("no_such") is None


def test_write_tools_require_actions():
    g = PermissionGate()
    ctx = _ctx()
    assert g.check(tool_name="create_work_order", ctx=ctx,
                   user_permissions=DEV_VIEW, operator="eric",
                   factory_id="F01") is not None
    assert g.check(tool_name="release_work_order", ctx=ctx,
                   user_permissions=DEV_VIEW, operator="eric",
                   factory_id="F01") is not None


# ──────────────────────────────────────────────
# 权限判定
# ──────────────────────────────────────────────

def test_read_allowed_with_view():
    g = PermissionGate()
    ctx = _ctx()
    assert g.check(tool_name="query_work_orders", ctx=ctx,
                   user_permissions=DEV_VIEW, operator="eric",
                   factory_id="F01") is None


def test_no_permissions_denied():
    g = PermissionGate()
    ctx = _ctx()
    err = g.check(tool_name="query_work_orders", ctx=ctx,
                  user_permissions=[], operator="eric", factory_id="F01")
    assert err is not None and "无权限" in err


def test_write_denied_without_action():
    g = PermissionGate()
    ctx = _ctx()
    err = g.check(tool_name="create_work_order", ctx=ctx,
                  user_permissions=DEV_VIEW, operator="eric",
                  factory_id="F01")
    assert err is not None and "create" in err


def test_admin_all_access():
    g = PermissionGate()
    ctx = _ctx()
    for tool in ("query_work_orders", "create_work_order", "query_inventory"):
        assert g.check(tool_name=tool, ctx=ctx,
                       user_permissions=ADMIN, operator="eric",
                       factory_id="F01") is None


def test_operator_mismatch_on_write():
    g = PermissionGate()
    ctx = _ctx(operator="eric")
    err = g.check(tool_name="create_work_order", ctx=ctx,
                  user_permissions=ADMIN, operator="eric",
                  factory_id="F01")
    # operator 与 ctx.user.username 一致 → 不拦截
    assert err is None


def test_operator_mismatch_detected():
    g = PermissionGate()
    ctx = _ctx(operator="eric")
    err = g.check(tool_name="create_work_order", ctx=ctx,
                  user_permissions=ADMIN, operator="spoof",
                  factory_id="F01")
    assert err is not None and "身份不匹配" in err


def test_scope_own_requires_factory():
    g = PermissionGate()
    ctx = _ctx(factory_id="")
    perms = DEV_VIEW + [{"module": "wms", "actions": ["view"]}]
    err = g.check(tool_name="query_inventory", ctx=ctx,
                  user_permissions=perms, operator="eric", factory_id="")
    assert err is not None and "factory_id" in err


# ──────────────────────────────────────────────
# Kernel 接入：拒绝时不执行工具
# ──────────────────────────────────────────────

async def _run_kernel(user_perms, first_tool, factory_id="F01",
                      operator="eric", username="eric"):
    from core.kernel import HarnessKernel
    from core.kernel import permission as perm_mod
    from core.kernel.context import KernelContext

    executed = []
    db = MagicMock()

    async def responder(payload):
        if any(m.get("role") == "tool" for m in payload["messages"]):
            return MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "结果"}}]},
            )
        import json
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": first_tool, "arguments": json.dumps({"x": 1})},
                }],
            }}]},
        )

    async def fake_legacy(tool, args):
        executed.append(tool)
        return {"ok": True}

    user = SimpleNamespace(username=username)

    gate = PermissionGate()

    kernel = HarnessKernel(
        db=db,
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=fake_legacy,
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: "grounded",
        verify_reply=None,
        make_tool_action=lambda *a, **k: SimpleNamespace(tool=a[0]),
        write_tools=frozenset({"create_work_order"}),
        sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys", final_grounding_prompt="ground",
        max_tool_rounds=3,
        skill_registry=None,
        legacy_execute_tool=fake_legacy,
        permission_gate=gate,
    )
    # 强制注入权限集（绕开 roles 解析不可控性）
    ctx = KernelContext(
        request_id="req-perm", factory_id=factory_id,
        user=user, messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        operator=operator, permissions=set(),
    )
    result = await kernel.handle(ctx)
    return result, executed


@pytest.mark.asyncio
async def test_kernel_denied_tool_not_executed():
    from unittest.mock import patch
    from core.auth import roles as roles_mod

    def fake_perms(user):
        return DEV_VIEW

    with patch.object(roles_mod, "get_user_permissions", side_effect=fake_perms):
        result, executed = await _run_kernel(DEV_VIEW, "create_work_order")
    assert executed == []  # create 需要 create 权限 → 被拒，不执行
    assert result.reply


@pytest.mark.asyncio
async def test_kernel_allowed_tool_executed():
    def fake_perms(user):
        return ADMIN

    from unittest.mock import patch
    from core.auth import roles as roles_mod

    with patch.object(roles_mod, "get_user_permissions", side_effect=fake_perms):
        result, executed = await _run_kernel(ADMIN, "create_work_order")
    assert executed == ["create_work_order"]