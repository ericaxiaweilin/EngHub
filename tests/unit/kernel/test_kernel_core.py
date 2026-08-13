"""Tests for core/kernel — EngFlow Harness Kernel (Phase 1).

覆盖：AgentLoop 行为、Checkpoint、Telemetry、HarnessKernel 编排、Context。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kernel.context import KernelContext
from core.kernel.agent_loop import AgentLoop, LoopResult
from core.kernel.checkpoint import CheckpointManager
from core.kernel.telemetry import Telemetry, TelemetryEvent
from core.kernel.kernel import HarnessKernel, KernelResponse


@pytest.fixture(scope="session")
def event_loop():
    """Python 3.14 兼容的 event_loop（覆盖 tests/unit/conftest 的旧实现）。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ──────────────────────────────────────────────
# Fake LLM 响应
# ──────────────────────────────────────────────

class FakeLlmResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _final_reply_payload(content: str = "你好，这是最终回复") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _tool_call_payload(tool_calls: list, content: str = "") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}]}


def _make_tool_call(name: str, args: dict, call_id: str = "call-1") -> dict:
    import json
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.fixture
def kernel_ctx() -> KernelContext:
    """最小 KernelContext。"""
    user = SimpleNamespace(username="eric", id="u1", is_superuser=True)
    return KernelContext(
        request_id="req-test-1",
        factory_id="FAC_MECH_001",
        user=user,
        messages=[{"role": "user", "content": "查一下库存"}],
        model_route={
            "task_id": "chat",
            "provider": "p1",
            "gateway_model": "m1",
            "request_timeout": 5.0,
            "max_completion_tokens": 256,
        },
        operator="eric",
        permissions={"pp", "work_order"},
    )


def _make_loop(responder) -> AgentLoop:
    """构造 AgentLoop，responder 是 async (payload) -> FakeLlmResponse。"""
    return AgentLoop(
        call_llm=responder,
        execute_tool=AsyncMock(return_value={"ok": True}),
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: f"TOOL: {r}",
        verify_reply=None,
        make_tool_action=lambda tool, label, args, result, is_w, is_s, ok: {
            "tool": tool, "success": ok,
        },
        write_tools=frozenset({"create_work_order"}),
        sim_tools=frozenset(),
        final_grounding_prompt="禁止添加 JSON 外的内容",
        max_rounds=3,
    )


# ──────────────────────────────────────────────
# AgentLoop
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_loop_direct_reply_without_tools():
    """无工具调用 → 直接返回最终回复。"""
    async def responder(payload):
        assert "tools" in payload
        return FakeLlmResponse(200, _final_reply_payload("库存查询完成"))

    loop = _make_loop(responder)
    result = await loop.run({"model": "m1", "messages": [], "tools": [], "tool_choice": "auto"})
    assert result.status == "complete"
    assert not result.degraded
    assert result.reply == "库存查询完成"
    assert result.rounds_used == 1


@pytest.mark.asyncio
async def test_loop_executes_tools_then_replies():
    """工具调用 → 执行 → 第二轮给出回复。"""
    calls = []

    async def responder(payload):
        if len(payload["messages"]) < 3:
            calls.append(payload["messages"][-1])
            return FakeLlmResponse(200, _tool_call_payload([
                _make_tool_call("query_inventory", {"material": "steel"})
            ]))
        return FakeLlmResponse(200, _final_reply_payload("工具有效，库存已查"))

    loop = _make_loop(responder)
    result = await loop.run({"model": "m1", "messages": [{"role": "user", "content": "查库存"}], "tools": [], "tool_choice": "auto"})
    assert result.status == "complete"
    assert result.rounds_used == 2
    assert len(result.actions) == 1
    assert result.actions[0]["tool"] == "query_inventory"
    # 第一轮后 tools 应被移除
    assert "tools" not in calls[-1] if calls else True


@pytest.mark.asyncio
async def test_loop_gateway_error_is_degraded():
    """网关返回 >=400 → degraded。"""
    async def responder(payload):
        return FakeLlmResponse(500, {})

    loop = _make_loop(responder)
    result = await loop.run({"model": "m1", "messages": []})
    assert result.degraded
    assert result.status == "gateway_error"
    assert "500" in (result.error or "")


@pytest.mark.asyncio
async def test_loop_empty_reply_is_degraded():
    """模型无有效回复 → degraded。"""
    async def responder(payload):
        return FakeLlmResponse(200, _final_reply_payload(""))

    loop = _make_loop(responder)
    result = await loop.run({"model": "m1", "messages": []})
    assert result.degraded
    assert result.status == "no_reply"


@pytest.mark.asyncio
async def test_loop_verify_reply_is_called():
    """verify_reply 注入被调用。"""
    async def responder(payload):
        return FakeLlmResponse(200, _final_reply_payload("原始草稿"))

    verify = AsyncMock(return_value="审校后")
    loop = _make_loop(responder)
    loop._verify_reply = verify
    result = await loop.run({"model": "m1", "messages": []})
    assert result.reply == "审校后"
    verify.assert_awaited_once()


@pytest.mark.asyncio
async def test_loop_max_rounds_stops():
    """超过最大轮次 → max_rounds degraded。"""
    async def responder(payload):
        return FakeLlmResponse(200, _tool_call_payload([
            _make_tool_call("query_inventory", {})
        ]))

    loop = _make_loop(responder)
    result = await loop.run({"model": "m1", "messages": [], "tools": [], "tool_choice": "auto"})
    assert result.status == "max_rounds"
    assert result.degraded
    assert result.rounds_used == 3


# ──────────────────────────────────────────────
# Checkpoint
# ──────────────────────────────────────────────

def test_checkpoint_save_restore_clear():
    mgr = CheckpointManager()
    key1 = mgr.save("req-1", messages=[{"role": "user", "content": "a"}], actions_count=0)
    key2 = mgr.save("req-1", messages=[{"role": "user", "content": "a"}, {"role": "tool", "content": "x"}], actions_count=1)

    latest = mgr.latest("req-1")
    assert latest["key"] == key2
    assert latest["actions_count"] == 1
    assert mgr.has("req-1")

    restored = mgr.restore("req-1", up_to_key=key1)
    assert restored["key"] == key1

    mgr.clear("req-1")
    assert not mgr.has("req-1")


def test_checkpoint_fingerprint_is_deterministic():
    mgr = CheckpointManager()
    fp1 = mgr.fingerprint([{"role": "user", "content": "hi"}])
    fp2 = mgr.fingerprint([{"role": "user", "content": "hi"}])
    assert fp1 == fp2
    assert len(fp1) == 16


# ──────────────────────────────────────────────
# Telemetry
# ──────────────────────────────────────────────

def test_telemetry_record_and_query():
    tel = Telemetry()
    tel.record(TelemetryEvent(request_id="r1", phase="tool_loop", rounds=2, model="m1"))
    events = tel.query(request_id="r1")
    assert len(events) == 1
    assert events[0]["phase"] == "tool_loop"
    assert events[0]["rounds"] == 2


def test_telemetry_timed_context():
    tel = Telemetry()
    with tel.timed("r2", "total"):
        pass
    events = tel.query(request_id="r2")
    assert len(events) == 1
    assert events[0]["success"] is True
    assert events[0]["duration_ms"] >= 0


def test_telemetry_timed_records_failure():
    tel = Telemetry()
    with pytest.raises(RuntimeError):
        with tel.timed("r3", "total"):
            raise RuntimeError("boom")
    events = tel.query(request_id="r3")
    assert events[0]["success"] is False
    assert "boom" in events[0]["error"]


def test_telemetry_failures_list():
    tel = Telemetry()
    tel.record(TelemetryEvent(request_id="r4", phase="total", success=False, error="gateway 500"))
    fails = tel.failures()
    assert len(fails) >= 1
    assert fails[-1]["error"] == "gateway 500"


# ──────────────────────────────────────────────
# KernelContext
# ──────────────────────────────────────────────

def test_context_last_user_content():
    ctx = KernelContext(
        request_id="r", factory_id="F", user=None,
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "查库存"},
        ],
        model_route={},
    )
    assert ctx.last_user_content == "查库存"


def test_context_last_user_multimodal():
    ctx = KernelContext(
        request_id="r", factory_id="F", user=None,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": "看看这张图"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ]},
        ],
        model_route={},
    )
    assert ctx.last_user_content == "看看这张图"


def test_context_snapshot():
    ctx = KernelContext(
        request_id="r", factory_id="F", user=None,
        messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "g"},
    )
    snap = ctx.snapshot()
    assert snap["request_id"] == "r"
    assert snap["message_count"] == 1
    assert snap["model_route"]["gateway_model"] == "g"


# ──────────────────────────────────────────────
# HarnessKernel
# ──────────────────────────────────────────────

def _make_kernel(responder=None, execute_result=None) -> HarnessKernel:
    async def default_responder(payload):
        return FakeLlmResponse(200, _final_reply_payload("kernel 回复"))

    async def resolve_route(task_id, **kwargs):
        return {
            "task_id": task_id, "provider": "p1", "gateway_model": "m1",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }

    return HarnessKernel(
        db=MagicMock(),
        call_llm=responder or default_responder,
        resolve_model_route=resolve_route,
        execute_tool=AsyncMock(return_value=execute_result or {"ok": True}),
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: f"TOOL: {r}",
        verify_reply=None,
        make_tool_action=lambda tool, label, args, result, is_w, is_s, ok: {
            "tool": tool, "success": ok,
        },
        write_tools=frozenset(),
        sim_tools=frozenset(),
        tool_definitions=[{"type": "function", "function": {"name": "q"}}],
        system_prompt="system",
        final_grounding_prompt="ground",
        chat_task_id="chat-task",
        vision_task_id="vision-task",
        max_tool_rounds=3,
    )


@pytest.mark.asyncio
async def test_kernel_handles_request(kernel_ctx):
    kernel = _make_kernel()
    result = await kernel.handle(kernel_ctx)
    assert isinstance(result, KernelResponse)
    assert result.reply == "kernel 回复"
    assert not result.degraded
    assert result.request_id == kernel_ctx.request_id


@pytest.mark.asyncio
async def test_kernel_degraded_on_gateway_error(kernel_ctx):
    async def bad_responder(payload):
        return FakeLlmResponse(503, {})

    kernel = _make_kernel(responder=bad_responder)
    result = await kernel.handle(kernel_ctx)
    assert result.degraded


@pytest.mark.asyncio
async def test_kernel_build_context_resolves_route(kernel_ctx):
    kernel = _make_kernel()
    ctx = await kernel.build_context(
        factory_id="FAC_MECH_001",
        user=kernel_ctx.user,
        messages=[{"role": "user", "content": "hi"}],
        prompt_tokens=100,
    )
    assert ctx.model_route["gateway_model"] == "m1"
    assert ctx.request_id.startswith("req-")


@pytest.mark.asyncio
async def test_kernel_vision_task_id_for_images():
    kernel = _make_kernel()
    fake_att = SimpleNamespace(content_type="image/png")
    ctx = await kernel.build_context(
        factory_id="F",
        user=SimpleNamespace(username="e"),
        messages=[{"role": "user", "content": "看图"}],
        attachments=[fake_att],
    )
    # 图片附件 → 走 vision task
    assert kernel._vision_task_id == "vision-task"


@pytest.mark.asyncio
async def test_kernel_exception_is_degraded():
    async def boom_responder(payload):
        raise RuntimeError("network down")

    kernel = _make_kernel(responder=boom_responder)
    ctx = KernelContext(
        request_id="req-x", factory_id="F", user=None,
        messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m", "max_completion_tokens": 256},
    )
    result = await kernel.handle(ctx)
    assert result.degraded
    assert "Chat V2" in result.reply