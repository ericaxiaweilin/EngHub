"""确认承接 + tool_use 泄漏剥离回归（线上 2026-10-04 对话事故）。"""

import pytest

pytestmark = [pytest.mark.unit]

from core.kernel.confirmation import confirmation_grounding
from core.kernel.context_window import compact_messages
from core.kernel.agent_loop import AgentLoop
from core.kernel.reply_sanitizer import (
    StreamSanitizer,
    extract_tool_json_spans,
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
    assert "答复" in strip_tool_call_markup(raw)
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
    note = confirmation_grounding(h)
    assert "严禁重复提问" in note


def test_confirm_with_instruction_kept():
    h = _hist(
        ("assistant", "产品 ID 是否就是 cf72？"),
        ("user", "是 确认 你自己安排"),
    )
    note = confirmation_grounding(h)
    assert "严禁重复提问" in note
    assert "你自己安排" in note


def test_paraphrase_confirm_grounded():
    h = _hist(
        ("assistant", "用这条路线排 500 台可以吗？"),
        ("user", "那就这样"),
    )
    assert "严禁重复提问" in confirmation_grounding(h)


def test_question_shaped_confirm_not_grounded():
    h = _hist(
        ("assistant", "路线是哪条？"),
        ("user", "是不是要先建BOM?"),
    )
    assert confirmation_grounding(h) == ""


def test_new_request_starting_with_can_not_grounded():
    h = _hist(
        ("assistant", "还有别的问题吗？"),
        ("user", "可以帮我查一下设备状态"),
    )
    assert confirmation_grounding(h) == ""


def test_no_assistant_before_not_grounded():
    assert confirmation_grounding(_hist(("user", "确认"))) == ""


def test_statement_answer_not_grounded():
    h = _hist(
        ("assistant", "已生成排产建议。"),
        ("user", "确认收到"),
    )
    assert confirmation_grounding(h) == ""


def test_grounding_survives_compaction():
    filler = []
    for i in range(20):
        filler.append(("user", f"第{i}轮用户问题内容填充 " + "x" * 200))
        filler.append(("assistant", f"第{i}轮回答内容填充 " + "y" * 200))
    h = _hist(*filler)
    h.append({"role": "assistant", "content": "产品 ID 是否就是 cf72？"})
    h.append({"role": "user", "content": "确认"})
    compacted = compact_messages(h, max_messages=24, max_chars=24000).messages
    assert "严禁重复提问" in confirmation_grounding(compacted)

def test_stream_sanitizer_splits_tag_across_chunks():
    s = StreamSanitizer()
    assert s.feed("先给结论") == "先给结论"
    assert s.feed("，查到 3 条。<tool_use>{") == "，查到 3 条。"
    assert s.feed('"name": "q"}') == ""
    assert s.feed("</tool_use>后续正文") == "后续正文"
    assert s.flush() == ""


def test_stream_sanitizer_keeps_bare_angle_bracket():
    s = StreamSanitizer()
    assert s.feed("当 a<") == "当 a"
    assert s.feed("b 时成立") == ""
    assert s.flush() == "<b 时成立"


def test_stream_sanitizer_drops_think_block():
    s = StreamSanitizer()
    assert s.feed("答复<think>内部推理") == "答复"
    assert s.feed("继续推理</think>正文") == "正文"
    assert s.flush() == ""


def test_stream_sanitizer_flush_emits_held_tail():
    s = StreamSanitizer()
    assert s.feed("尾巴<") == "尾巴"
    assert s.flush() == "<"

LEAKED_SAMPLE = (
    '{"tool":"query_wip_work_orders",'
    '"arguments":{"status":"in_progress","page":1,"page_size":200}}'
)


def test_bare_tool_json_stripped_from_prose():
    raw = "我来查一下在制工单。" + LEAKED_SAMPLE + "稍等。"
    cleaned = strip_tool_call_markup(raw)
    assert "query_wip_work_orders" not in cleaned
    assert "我来查一下在制工单" in cleaned
    assert looks_like_tool_call_leak(raw) is True


def test_bare_tool_json_whole_reply_stripped():
    assert strip_tool_call_markup(LEAKED_SAMPLE) == ""


def test_legit_json_untouched():
    raw = '接口返回示例：{"code": 200, "data": []} 请参考。'
    assert strip_tool_call_markup(raw) == raw
    assert looks_like_tool_call_leak(raw) is False


def test_extract_tool_json_spans_parses_stringified_args():
    spans = extract_tool_json_spans(LEAKED_SAMPLE)
    assert len(spans) == 1
    _s, _e, name, args = spans[0]
    assert name == "query_wip_work_orders"
    assert args == {"status": "in_progress", "page": 1, "page_size": 200}


def test_stream_holds_partial_tool_json():
    s = StreamSanitizer()
    assert s.feed("正在查询") == "正在查询"
    assert s.feed('{"tool":"query_wip') == ""
    assert s.feed('_work_orders","arguments":{}}后续') == "后续"
    assert s.flush() == ""


def _loop_with(write=(), sim=()):
    loop = AgentLoop.__new__(AgentLoop)
    loop._write_tools = frozenset(write)
    loop._sim_tools = frozenset(sim)
    return loop


def test_recover_readonly_call():
    calls = _loop_with()._recover_readonly_calls(LEAKED_SAMPLE, 0)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "query_wip_work_orders"
    assert calls[0]["id"].startswith("recovered-")


def test_recover_never_takes_write_tools():
    calls = _loop_with(write=("create_work_order",))._recover_readonly_calls(
        '{"tool":"create_work_order","arguments":{"a":1}}', 1,
    )
    assert calls == []

