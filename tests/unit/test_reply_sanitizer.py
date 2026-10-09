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
    strip_reasoning_markup,
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


# ── 推理区块泄漏（线上 chat_messages 残留样本 2026-08-16 / 2026-10-03） ──
# 旧实现只匹配字面量 "<think>.*?</think>"，于是三类真实样本全部放行给用户：
#   a. 孤立闭标签 </think>（开标签已被前一轮剥掉）
#   b. 变体标签名 <thinking>
#   c. 带属性的开标签 <think type="...">
# 用户 2026-10-03 因此关闭了展示。以下每条都对应一个线上形态。


def test_orphan_close_think_stripped_text_kept():
    raw = "库存 120 件。\n</think>"
    assert strip_tool_call_markup(raw) == "库存 120 件。"
    # strip_reasoning_markup 只删标记、不做 strip（收尾去空白由 _clean_model_reply 负责）
    assert strip_reasoning_markup(raw).strip() == "库存 120 件。"


def test_orphan_close_think_alone_does_not_survive():
    assert strip_tool_call_markup("</think>") == ""
    assert strip_reasoning_markup("</think>") == ""


def test_orphan_close_think_mid_text_keeps_both_sides():
    raw = "结论 120 件。\n</think>\n以上。"
    out = strip_reasoning_markup(raw)
    assert "结论 120 件。" in out
    assert "以上。" in out
    assert "think" not in out.lower()


def test_thinking_variant_stripped():
    assert strip_tool_call_markup("<thinking>内部推理</thinking>\n库存 120 件。") == "库存 120 件。"
    assert strip_reasoning_markup("<thinking>内部推理</thinking>\n库存 120 件。").strip() == "库存 120 件。"


def test_think_with_attributes_stripped():
    raw = '<think type="reasoning">内部推理</think>\n库存 120 件。'
    assert strip_tool_call_markup(raw) == "库存 120 件。"
    assert strip_reasoning_markup(raw).strip() == "库存 120 件。"


def test_reasoning_markup_escapes_tool_call_gate():
    """孤立闭标签与变体标签名都逃得过 looks_like_tool_call_leak 的预判。

    所以推理区块必须有一条**无条件**通道（strip_reasoning_markup）；
    只靠 _strip_tool_call_leak 的预判会整段放行给用户。
    """
    for raw in ("</think>", "<thinking>x</thinking>", '<think type="a">x</think>'):
        assert looks_like_tool_call_leak(raw) is False, raw
        assert strip_reasoning_markup(raw) == "", raw


def test_orphan_close_tool_tag_stripped():
    raw = "库存 120 件。\n</tool_call>"
    assert strip_tool_call_markup(raw) == "库存 120 件。"
    assert looks_like_tool_call_leak(raw) is True


def test_stream_sanitizer_drops_orphan_close_think():
    s = StreamSanitizer()
    out = s.feed("库存 120 件。\n</think>") + s.flush()
    assert "think" not in out.lower()
    assert "库存 120 件。" in out


def test_stream_sanitizer_drops_thinking_variant():
    s = StreamSanitizer()
    out = s.feed("<thinking>内部推理</thinking>库存 120 件。") + s.flush()
    assert "thinking" not in out.lower()
    assert "库存 120 件。" in out


def test_reasoning_cleanup_keeps_legit_prose_and_json():
    """不变量：清推理标记不得吃掉正文里的合法尖括号或合法 JSON。"""
    keep = "当 a<b 时成立"
    assert strip_reasoning_markup(keep) == keep
    assert strip_tool_call_markup(keep) == keep
    legit = '接口返回示例：{"code": 200, "data": []} 请参考。'
    assert strip_tool_call_markup(legit) == legit
    assert strip_reasoning_markup(legit) == legit


# ── 线上 2026-08-15 两条残留（此前只在流式路径漏出） ──
# cadee6e4（4714 字符）：连续几百个 <tool_call> 开标签、零闭标签。旧 feed()
#   只从「最后一个 <」暂扣，前面几百个开标签当场外发给用户。
# 9ce9c3bb（104 字符）：<invoke name="…"> **开标签**无人覆盖，只删孤立
#   </invoke> 会把开标签留给用户。

BARE_TOOL_CALL_OPENERS = "结论如下。\n\n" + "<tool_call>\n" * 40
INVOKE_ORPHANS = (
    '我来查一下。\n\n</invoke>\n'
    '<invoke name="query_pmc_work_matrix">\n\n</invoke>\n\n</invoke>'
)


def test_stream_bare_tool_call_openers_do_not_leak():
    """多个未闭合 <tool_call> 开标签：流式路径不得外发任何一个。"""
    s = StreamSanitizer()
    out = s.feed(BARE_TOOL_CALL_OPENERS) + s.flush()
    assert "<tool_call" not in out
    assert "结论如下。" in out


def test_nonstream_bare_tool_call_openers_do_not_leak():
    out = strip_tool_call_markup(BARE_TOOL_CALL_OPENERS)
    assert "<tool_call" not in out
    assert "结论如下。" in out


def test_invoke_opener_stripped_both_paths():
    """<invoke name="…"> 开标签：此前只删 </invoke>，开标签会漏给用户。"""
    ns = strip_tool_call_markup(INVOKE_ORPHANS)
    assert "invoke" not in ns.lower()
    assert "我来查一下。" in ns
    s = StreamSanitizer()
    streamed = s.feed(INVOKE_ORPHANS) + s.flush()
    assert "invoke" not in streamed.lower()
    assert "我来查一下。" in streamed


def test_invoke_opener_opens_the_gate():
    assert looks_like_tool_call_leak('<invoke name="x">') is True


def test_truncated_protocol_tag_at_tail_stripped():
    """流末尾断在半截开标签上：只删半截标签，不吃正文。"""
    for raw in ("<tool_call", "<tool_use", "<invoke", "<think", "<tool"):
        assert strip_tool_call_markup(raw) == "", raw
    s = StreamSanitizer()
    assert (s.feed("结论。<tool") + s.flush()) == "结论。"


def test_truncated_tag_rule_keeps_legit_angle_brackets():
    """半截标签规则只认协议标签前缀（>=3 字符），正文里的 <b / <y 一律保留。"""
    for raw in ("当 a<b", "x<y", "5 < 10"):
        assert strip_tool_call_markup(raw) == raw, raw


# ── numeric_claims：什么算正文引用了一个数据读数（对话核实与 L4 同一口径）──

def test_numeric_claims_keeps_real_readings():
    from core.kernel.reply_sanitizer import numeric_claims

    assert numeric_claims('共处理 371 项、575 项') == ['371', '575']
    assert numeric_claims('人工成本 $52,380 美元') == ['52,380']
    assert numeric_claims('延后 12.5 天，共 1,234 台') == ['1,234']
    # 阈值是「3 位起」：12.5 这种两位小数不算数据引用（口径写在 numeric_claims 里）
    assert numeric_claims('承诺 10,131 台 vs 5 天延误') == ['10,131']


def test_numeric_claims_ignores_years_ids_and_dates():
    from core.kernel.reply_sanitizer import numeric_claims

    assert numeric_claims('2026 年第 37 周正常') == []
    assert numeric_claims('交期 2026-10-02 已确认') == []
    # UUID / 编码里的一段数字不是数据引用（前后粘着字母或数字）
    assert numeric_claims('工作簿 ID 2edc79f5-e085-4b88-832c-2448a9fa7615') == []
    assert numeric_claims('未排产工单：0 张') == []

def test_disclosure_is_one_phrase_list_for_kernel_and_judge():
    """模型自己标"这是估算/不调用接口"和内核追加的标注，必须被同一份短语表认下来：
    一处认、一处不认，就会出现"判据说已披露、出口又追加第二遍免责声明"的自相矛盾。"""
    from core.kernel.reply_sanitizer import is_disclosed

    assert is_disclosed("这些数没有调用 MES 工具核实")
    assert is_disclosed("按 1200 台设备估算，不调用接口：OEE 约 78%")
    assert is_disclosed("先强调这是经验值，不是实时数据：不良率约 2%")
    assert not is_disclosed("当前在制工单 84 单，待排 68 单")
    assert not is_disclosed("")


def test_numeric_claims_ignores_years_and_short_numbers():
    from core.kernel.reply_sanitizer import is_disclosed, numeric_claims

    assert numeric_claims("2026 年 10 月完成 1,204 件") == ["1,204"]
    assert numeric_claims("没有数字") == []


def test_missing_gap_note_appends_when_the_item_is_not_conveyed():
    """引擎报了算不出、答复里没这句话 → 出口要补一行。"""
    from core.kernel.reply_sanitizer import missing_gap_note

    item = {"name": "change_attribution", "state": "not_computable",
            "reason": "请求没给 compare，算不出「为什么变了」",
            "ask": "问变化就传两组输入"}
    note = missing_gap_note([item], "交期是 2026-11-06，最晚延 8 天。")
    assert note.strip().startswith("〔引擎本轮还有 1 项给不出数〕")
    assert "请求没给 compare" in note, "补的那行要把缺项的整句 reason 交出去，不是半截片段"


def test_missing_gap_note_lists_shared_reason_once_and_is_idempotent():
    """三个杠杆同一句 reason 只列一次；补过一次的答复再过一次不该又追加。"""
    from core.kernel.reply_sanitizer import missing_gap_note

    same = [{"name": n, "reason": "这一维测不出斜率，无法归因"}
            for n in ("absent_line", "absent_share", "expedite_bottleneck_to_days")]
    note = missing_gap_note(same, "完工 2026-11-02，延 10 天。")
    assert note.count("这一维测不出斜率") == 1, "同一句理由不许重复三遍"
    assert "共 3 项" in note
    # 补过一次之后那些说法就在正文里了 → 第二次必须闭嘴
    assert missing_gap_note(same, "完工 2026-11-02。" + note) == ""


def test_missing_gap_note_stays_quiet_when_the_item_was_conveyed():
    """答复已经把那条说法带出来了就不许再补 —— 否则每次都多一行噪声，
    而点名率这一格也会永远满分（因为是我们自己补的字）。"""
    from core.kernel.reply_sanitizer import missing_gap_note

    item = {"name": "expedite_bottleneck_to_days",
            "reason": "这一维测不出斜率，无法归因"}
    reply = "外购提前期这一维测不出斜率，本轮不给斜率。"
    assert missing_gap_note([item], reply) == ""
    assert missing_gap_note([], reply) == ""


def test_generic_words_do_not_count_as_disclosing_a_specific_gap():
    """讲"另几个杠杆未测出有效改善"不等于点名了这条缺项 —— 旧尺就是在这里放行的。"""
    from core.kernel.reply_sanitizer import gap_is_disclosed

    item = {"name": "change_attribution", "reason": "请求没给 compare，算不出「为什么变了」"}
    other = ("到岗比例、单件工时、设备可用率均未测出有效改善效果，"
             "这一项算不出。")
    assert not gap_is_disclosed(item, other)
    assert gap_is_disclosed(item, "变更归因这项算不出：请求没给 compare 两组输入。")


def test_iter_unavailable_walks_list_answers_and_layers():
    """三种形状都要认（少认一层就把"有缺项"读成"没缺项"，等于静默放行）。"""
    from core.kernel.reply_sanitizer import iter_unavailable

    one = {"unavailable": [{"name": "a", "reason": "缺基准档"}]}
    wrapped = {"answers": {"x": {"unavailable": [{"name": "b", "reason": "缺对比档"}]}}}
    layered = {"layers": [{"unavailable": [{"name": "c", "reason": "没有实测温度"}]}]}
    assert [i["name"] for i in iter_unavailable(one)] == ["a"]
    assert [i["name"] for i in iter_unavailable(wrapped)] == ["b"]
    assert [i["name"] for i in iter_unavailable(layered)] == ["c"]
    assert [i["name"] for i in iter_unavailable([one, wrapped, layered])] == ["a", "b", "c"]


def test_item_without_any_phrase_is_noted_but_never_demands_an_internal_key():
    """只写了 name 的缺项：出口要提一句"没写清缺什么"，但绝不要求答复写键名。

    要求答复里出现 `silent_one` 这种内部标识，会被 L4「契约泄漏内部标识数」判成泄漏；
    所以这类条目既不参与"点名率"的判线（见 engine_capability 那条测试），
    也不能被静默忽略 —— 出口这一行就是留给读者知道本轮有几项没交代清楚。
    """
    from core.kernel.reply_sanitizer import gap_phrases, missing_gap_note

    silent = {"name": "silent_one"}
    assert gap_phrases(silent) == [], "没写 reason/ask/missing 就不该有可核说法"
    note = missing_gap_note([silent], "交期 2026-11-06。")
    assert note.startswith("\n\n") and "没写清缺什么" in note
    assert "silent_one" not in note, "不许把内部键名塞进给用户看的答复"


# ── 「数字可回溯」的唯一判据：按读数算，每个数一票 ─────────────────────
def _row(claims, reply, turn="", history="", user=""):
    return {"claims": claims, "reply": reply, "turn": turn, "history": history, "user": user}


def test_number_backing_votes_per_number_not_per_reply():
    from core.kernel.reply_sanitizer import number_backing

    stats = number_backing([_row(["12.5", "300", "9"],
                                 "负荷 12.5 件/时、缺口 300 件、还有 9 个待补",
                                 turn='{"rate": 12.5, "shortage": 300}')])
    assert stats["claims_total"] == 3
    assert stats["claims_same_turn"] == 2
    assert stats["claims_unbacked"] == 1
    assert stats["number_backing_rate"] == round(2 / 3, 3)
    # 按答复算的那一级只报数：这一条"至少有一个数没出处"，所以通篇干净的答复占比是 0
    assert stats["replies_with_unbacked"] == 1
    assert stats["reply_clean_rate"] == 0.0


def test_number_backing_has_no_partial_credit_threshold():
    """旧的 L4 判线给"整条 ≥60% 有出处"放行 —— 那条 0.6 常数没人按业务定过，已废。

    这里钉住两个方向：4 个里中 3 个（0.75）在旧尺下算这条答复过，现在按读数只算 0.75，
    而按答复全中算 0.0。判线看的是 0.75 那个数。
    """
    from core.kernel.reply_sanitizer import number_backing

    stats = number_backing([_row(["1", "2", "3", "4"],
                                 "1 2 3 4", turn="1 2 3")])
    assert stats["number_backing_rate"] == 0.75
    assert stats["reply_clean_rate"] == 0.0
    assert stats["per_reply"][0]["unbacked"] == ["4"]


def test_number_backing_excludes_numbers_the_human_just_gave():
    from core.kernel.reply_sanitizer import number_backing

    stats = number_backing([_row(["1200"], "按你说的 1200 台来算",
                                 turn="{}", user="我们这版排 1200 台")])
    assert stats["claims_total"] == 0
    assert stats["replies_user_only"] == 1
    assert stats["number_backing_rate"] is None
    assert stats["claims_from_user"] == 1


def test_number_backing_counts_disclosed_numbers_as_not_invented():
    from core.kernel.reply_sanitizer import number_backing

    stats = number_backing([_row(["876"], "这是估算值：省 876 小时", turn="{}")])
    assert stats["claims_disclosed"] == 1
    assert stats["claims_unbacked"] == 0
    assert stats["number_backing_rate"] == 1.0
    assert stats["replies_with_unbacked"] == 0


def test_number_backing_accepts_history_corpus_from_earlier_turns():
    from core.kernel.reply_sanitizer import number_backing

    stats = number_backing([_row(["44.7"], "最差区间 44.7", turn="{}",
                                 history="… 44.71 …")])
    # 44.7 在语料里命中前 4 位（44.71）→ 同一件事，判可回溯
    assert stats["claims_from_history"] == 1
    assert stats["number_backing_rate"] == 1.0


def test_gap_note_lists_every_missing_item_without_truncating_the_phrase():
    """出口那一行必须把判据要看的每个说法原样交出去。

    判据要求"每条缺项都被带到"，而旧出口只列前 3 种说法、还把句子截到 60 字：
    ≥4 种不同说法、或一句 reason 长过 60 字时，被漏掉/截断的那条永远判不到。
    10-09 配对实测：当下 6 轮样本里旧写法还没被触发（追加后也 1.0），所以这一版钉的是
    **潜在**失效条件，不是当前读数 0.167 的成因 —— 那 5 轮早于出口修复上线。
    """
    from core.kernel.reply_sanitizer import gap_phrases, missing_gap_note

    items = [{"reason": f"这一维第 {i} 项缺输入，量不出斜率"} for i in range(1, 6)]
    note = missing_gap_note(items, "交期 2026-11-06。")
    assert "共 5 项" in note or "5 项给不出数" in note
    for item in items:
        assert gap_phrases(item)[0] in note, "判据找的那个串必须整条出现在出口那行里"


def test_gap_note_keeps_a_long_reason_whole():
    from core.kernel.reply_sanitizer import gap_phrases, missing_gap_note

    long_reason = "这一维测不出斜率" + "并且缺输入说明" * 12
    item = {"reason": long_reason}
    note = missing_gap_note([item], "交期 2026-11-06。")
    assert gap_phrases(item)[0] in note
