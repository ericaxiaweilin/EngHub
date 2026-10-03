
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from core.kernel.confirmation import confirmation_grounding
from core.kernel.context import KernelContext
from core.kernel.kernel import HarnessKernel


def _make_kernel() -> HarnessKernel:
    async def _noop(*args, **kwargs):
        return None

    return HarnessKernel(
        db=MagicMock(),
        call_llm=_noop,
        resolve_model_route=_noop,
        execute_tool=_noop,
        clean_reply=lambda c: c or "",
        ground_tool_result=lambda r: "",
        system_prompt="SYS",
    )


def _ctx(messages) -> KernelContext:
    return KernelContext(
        request_id="r-confirm",
        factory_id="F1",
        user=None,
        messages=[{"role": r, "content": c} for r, c in messages],
        model_route={"gateway_model": "m", "provider": "p", "task_id": "t"},
    )


def test_build_payload_appends_confirmation_grounding():
    kernel = _make_kernel()
    payload = kernel._build_payload(_ctx([
        ("user", "系统有什么工艺路线"),
        ("assistant", "只有 1 条。产品 ID 是否就是 cf72？"),
        ("user", "确认"),
    ]))
    assert payload["messages"][-1]["role"] == "system"
    assert "严禁重复提问" in payload["messages"][-1]["content"]


def test_build_payload_no_grounding_without_question():
    kernel = _make_kernel()
    payload = kernel._build_payload(_ctx([
        ("assistant", "已生成排产建议。"),
        ("user", "确认收到"),
    ]))
    assert all(m["role"] != "system" or "用户已确认" not in m["content"] for m in payload["messages"][1:])


def test_confirmation_grounding_pure_function_still_ok():
    assert "严禁重复提问" in confirmation_grounding([
        {"role": "assistant", "content": "继续吗？"},
        {"role": "user", "content": "好"},
    ])
