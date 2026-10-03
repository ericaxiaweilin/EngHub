"""确认承接 + tool_use 泄漏剥离回归（线上 2026-10-04 对话事故）。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.routes.chat_routes import _confirmation_grounding
from core.kernel.reply_sanitizer import (
    looks_like_tool_call_leak,
    strip_tool_call_markup,
)


def _hist(*msgs):
    return [{"role": r, "content": c} for r, c in msgs]


def test_tool_use_block_stripped_text_kept():
    raw = '先给结论：查到 3 条。<tool_use>{"name": "query_work_orders", "arguments": "{}"}</tool_use>'
    assert strip_tool_call_markup(raw) == "先给结论：查到 3 条。"
    assert looks_like_tool_call_leak(raw) is True


def test_tool_use_unclosed_stripped():
    raw = '好的<tool_use>{"name": "query_work_orders",'
    assert strip_tool_call_markup(raw) == "好的"


def test_tool_call_still_stripped():
    raw = '答复 <tool_call>{"a": 1}</tool_call> 尾巴'
    assert strip_tool_call_markup(raw) == "答复  尾巴".strip() or "答复" in strip_tool_call_markup(raw)
    assert looks_like_tool_call_leak(raw) is True


def test_plain_text_untouched():
    assert strip_tool_call_markup("今天生产正常") == "今天生产正常"
    assert looks_like_tool_call_leak("今天生产正常") is False


def test_bare_confirm_after_question_grounded():
    h = _hist(
        ("user", "系统有什么产品工艺路线"),
        ("assistant", "只有 1 条路线。产品 ID 是否就是 cf72？"),
        ("user", "确认"),
    )
    note = _confirmation_grounding(h)
    assert "严禁重复提问" in note


def test_confirm_with_instruction_kept():
    h = _hist(
        ("assistant", "产品 ID 是否就是 cf72？"),
        ("user", "是 确认 你自己安排"),
    )
    note = _confirmation_grounding(h)
    assert "严禁重复提问" in note
    assert "你自己安排" in note


def test_new_request_starting_with_can_not_grounded():
    h = _hist(
        ("assistant", "还有别的问题吗？"),
        ("user", "可以帮我查一下设备状态"),
    )
    assert _confirmation_grounding(h) == ""


def test_no_assistant_before_not_grounded():
    assert _confirmation_grounding(_hist(("user", "确认"))) == ""


def test_statement_answer_not_grounded():
    h = _hist(
        ("assistant", "已生成排产建议。"),
        ("user", "确认收到"),
    )
    assert _confirmation_grounding(h) == ""
