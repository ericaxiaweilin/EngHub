"""能力三格画像：推演 / 分析 / 总结 的判据是算出来的，不是文案。

只测纯函数（_surface / headline_items / summary_score / analysis_score / forecast_score / _verdict），
动库那两条（_load_replies、capability_profile 里的契约调用）在预演接口里看得到。
"""
from api.services.engine_capability import (
    GAP_WORDS,
    HEADLINE_TOOLS,
    MIN_SUMMARY_REPLIES,
    THRESHOLDS,
    _surface,
    _verdict,
    analysis_score,
    forecast_score,
    headline_items,
    summary_score,
)


# ── 要点名要取中文面：拿字段名比中文正文，覆盖率永远 0（那是尺错不是答复错）──
def test_surface_prefers_chinese_label_over_field_name():
    assert _surface({"name": "expedite_bottleneck_to_days",
                     "label": "瓶颈件到货日"}) == "瓶颈件到货日"
    assert _surface({"name": "change_attribution",
                     "ask": "问变化就传两组输入"}) == "问变化就传两组输入"
    # 没有中文面时退回字段名：这条会照数进分母，是真没带到
    assert _surface({"name": "purchase_lead_time"}) == "purchase_lead_time"


def test_headline_items_reads_metrics_and_unavailable_from_layers():
    result = {"layers": [
        {"metrics": [{"metric": "同输入可复现率", "value": 1.0}],
         "unavailable": [{"metric": "回测 MAPE", "state": "not_computable"}]},
    ]}
    assert set(headline_items(result)) == {"回测 MAPE", "同输入可复现率"}


def test_headline_items_accepts_list_of_tool_results():
    # 一条回复可能调多个工具；库里存的是 [{tool,result}, ...] 的数组
    assert set(headline_items([{"unavailable": [{"name": "x", "ask": "缺 A"}]},
                                {"metrics": [{"metric": "命中率"}]}])) == {"缺 A", "命中率"}


# ── 总结格 ──────────────────────────────────────────────────────────
def _reply(content, tools=None, session_tools="", session_user="", sid="s1"):
    return {"session_id": sid, "content": content, "tool_json": tools or [],
            "session_tools": session_tools, "session_user": session_user}


def test_summary_counts_a_number_found_in_session_tool_corpus():
    row = _reply("瓶颈件还差 3,299 件", session_tools='{"shortage_qty": 3299}')
    s = summary_score([row])
    assert s["numbers_backed"] == 1 and s["numbers_unbacked"] == 0
    assert s["number_backing_rate"] == 1.0


def test_summary_number_only_user_supplied_is_not_engine_backing():
    # 人自己报的数单列，不算引擎有出处、也不算引擎编的（不能进判线分母）
    s = summary_score([_reply("按你说的 1200 台来算", session_user="我们这版排 1200 台")])
    assert s["numbers_from_user"] == 1
    assert s["replies_with_claims"] == 0 and s["number_backing_rate"] is None


def test_summary_unbacked_number_without_disclosure_is_counted_against_it():
    s = summary_score([_reply("预计还能省 876 小时", session_tools="{}")])
    assert s["numbers_unbacked"] == 1 and s["number_backing_rate"] == 0.0
    assert s["unbacked_samples"][0]["numbers"] == ["876"]


def test_summary_disclosed_unbacked_counts_as_backed():
    # 引擎的规矩是"没核实的数要写在脸上"：写了就不算编
    s = summary_score([_reply("这是估算值：省 876 小时", session_tools="{}")])
    assert s["numbers_disclosed"] == 1 and s["number_backing_rate"] == 1.0


def test_summary_gap_rate_only_judges_replies_that_had_engine_gaps():
    """点名 = 把**那一条**缺项自己的说法交出去；只说"算不出"不说哪一项不算。

    两个方向都要钉住（只验"会拦"就等于拦住所有人，只验"会放"就等于放过所有人）：
    旧尺拿固定词表判，实测 3db81365 那条答复讲的是另外几个杠杆"未测出有效改善效果"，
    并没有把 change_attribution 这条缺项交给用户，却被判成"点名了"—— 那是假阳性。
    """
    gap_tool = [{"tool": "query_engine_attribution",
                 "result": {"unavailable": [{"name": "change_attribution",
                                             "ask": "问变化就传两组输入"}]}}]
    silent = summary_score([_reply("交期是 2026-11-06", gap_tool,
                                   session_tools="2026-11-06")])
    assert silent["engine_gap_items"] == 1
    assert silent["replies_with_engine_gaps"] == 1
    assert silent["gap_named_replies"] == 0 and silent["gap_disclosure_rate"] == 0.0

    # 只带一个通用记号、没说是哪一项 → 仍算丢（旧尺会在这里误判成点名）
    vague = summary_score([_reply("交期 2026-11-06；这一项算不出", gap_tool,
                                 session_tools="2026-11-06")])
    assert vague["gap_named_replies"] == 0, "通用词不能替那条缺项说话，否则点名率永远虚高"

    named = summary_score([_reply("交期 2026-11-06；问变化就传两组输入，"
                                 "这轮没给两组输入所以给不出变更归因", gap_tool,
                                 session_tools="2026-11-06")])
    assert named["gap_named_replies"] == 1 and named["gap_disclosure_rate"] == 1.0


def test_item_without_a_phrase_is_excluded_from_the_disclosure_ruler():
    """没写"缺什么"的条目不参与点名率：判不了的东西既不扣分也不给过（今天推翻的旧语义）。

    旧写法是"退回通用词表"，等于只要答复里出现过『没有依据』就算这条被点名了 ——
    那正是通用词表的假阳性；而按 name 去要求正文写 `silent_one`，又会撞上
    L4 的契约泄漏判线。两头都不成立，所以这一格对它不判，交给
    「契约信封违规数」（说算不出却没点名缺什么）去罚 —— 那才是这条问题的正确落点。
    """
    only_name = [{"tool": "query_engine_attribution",
                  "result": {"unavailable": [{"name": "silent_one"}]}}]
    s = summary_score([_reply("交期 2026-11-06，这一项算不出", only_name,
                              session_tools="2026-11-06")])
    assert s["engine_gap_items"] == 0, "无可核说法的条目不进分母"
    assert s["replies_with_engine_gaps"] == 0
    assert s["gap_disclosure_rate"] is None, "没有可判的缺项就不许出一个比率"


def test_disclosure_counts_items_not_replies_and_needs_all_conveyed():
    """一轮里有两条缺项、只带到一条 → 这一轮仍算丢（另一条用户根本没看见）。"""
    two = [{"tool": "query_engine_attribution",
            "result": {"unavailable": [
                {"name": "a", "reason": "档位曲线里缺基准档"},
                {"name": "b", "reason": "请求没给 compare 两组输入"}]}}]
    half = summary_score([_reply("本轮档位曲线里缺基准档，所以给不出斜率。", two,
                                 session_tools="x")])
    assert half["engine_gap_items"] == 2
    assert half["gap_named_replies"] == 0 and half["gap_disclosure_rate"] == 0.0
    full = summary_score([_reply("档位曲线里缺基准档；请求没给 compare 两组输入。", two,
                                 session_tools="x")])
    assert full["gap_named_replies"] == 1 and full["gap_disclosure_rate"] == 1.0


def test_gap_words_are_the_only_surface_the_ruler_reads():
    # 判"有没有点名缺口"只认这张字面表，加词要显式改常量（别在函数里硬编第二套）
    assert "算不出" in GAP_WORDS and "not_computable" in GAP_WORDS
    assert all(isinstance(w, str) and w for w in GAP_WORDS)


# ── 分析格 ──────────────────────────────────────────────────────────
def _attr(relief, per_order):
    return {"answers": {"relief_attribution": relief,
                        "constraint_attribution": {"per_order": per_order}}}


def test_analysis_treats_measured_no_effect_as_trustworthy_but_not_as_advice():
    a = analysis_score(_attr(
        [{"state": "measured", "relieves": ["waiting_for_material"], "do_this": "催购 X"},
         {"state": "no_effect_measured", "relieves": [], "do_this": None},
         {"state": "suspicious_direction", "relieves": [], "do_this": None}],
        [{"constrained_by": [{"code": "waiting_for_material"}]}]))
    assert a["trustworthy_rate"] == round(2 / 3, 3)   # 测出 0 效果也是测出来的
    assert a["actionable_rate"] == round(1 / 3, 3)    # 但只有 1 条能当动作建议
    assert a["refuses_noise_advice"] is True
    assert a["orders_with_an_actionable_lever"] == 1


def test_analysis_flags_advice_built_on_unmeasured_state():
    a = analysis_score(_attr([{"state": "unknown_expectation", "do_this": "加开一条线"}], []))
    assert a["refuses_noise_advice"] is False          # 没测出效果却写成动作 = 推计划员做没用的事
    assert a["trustworthy_rate"] == 0.0


def test_analysis_explainable_rate_needs_named_constraint():
    a = analysis_score(_attr([], [{"constrained_by": [{"code": "queued_behind_orders"}]},
                                  {"constrained_by": []}]))
    assert (a["orders_explained"], a["orders_total"]) == (1, 2)
    assert a["explainable_rate"] == 0.5


# ── 推演格：只引用分层验收的同名实测值 ──────────────────────────────
def test_forecast_score_pulls_named_metrics_and_gate():
    layers = {"layers": [{"metrics": [
        {"metric": "同输入可复现率", "value": 1.0},
        {"metric": "方向命中率", "value": 1.0},
        {"metric": "瓶颈件一致率（提前期口径）", "value": 0.033},
        {"metric": "推荐相对基线的再跑差值（暴雨档）", "value": 5},
    ]}], "gate": {"first_unmet_layer": "L2B", "reportable_through": ["L1", "L2A"]}}
    f = forecast_score(layers)
    assert f["同输入可复现率"] == 1.0 and f["瓶颈件一致率（提前期口径）"] == 0.033
    assert f["闸门"] == "L2B" and f["可引用层"] == ["L1", "L2A"]


def test_forecast_score_keeps_missing_metric_as_none_not_zero():
    f = forecast_score({"layers": [], "gate": {}})
    assert f["同输入可复现率"] is None                 # 没跑过 ≠ 0 分
    assert f["闸门"] is None


def test_forecast_score_error_propagates():
    assert forecast_score({"error": "TimeoutError: x"})["error"] == "TimeoutError: x"


# ── 判定：三态必须分得开 ────────────────────────────────────────────
def test_verdict_pass_fail_and_missing_value():
    ok = _verdict({"x": 1.0}, [("x", "forecast_reproducible")])
    assert ok["state"] == "pass" and ok["failed"] == []
    bad = _verdict({"x": 0.5}, [("x", "forecast_reproducible")])
    assert bad["state"] == "fail" and "低于判线" in bad["failed"][0]
    miss = _verdict({"x": None}, [("x", "forecast_reproducible")])
    assert miss["state"] == "fail" and "算不出" in miss["failed"][0]


def test_verdict_not_computable_on_crash_and_on_small_sample():
    assert _verdict({"error": "Boom"}, [("x", "forecast_reproducible")])["state"] \
        == "not_computable"
    thin = _verdict({"replies_with_claims": MIN_SUMMARY_REPLIES - 1,
                     "number_backing_rate": 0.0},
                    [("number_backing_rate", "summary_number_backing")],
                    min_n=("replies_with_claims", MIN_SUMMARY_REPLIES))
    assert thin["state"] == "not_computable" and "样本不足" in thin["missing"]


def test_thresholds_are_named_per_grid_and_judgable():
    # 判线必须存在这张表里（散在文案里的线，下一个人就没法复算）
    for key in ("forecast_reproducible", "forecast_direction_hit", "forecast_agreement",
                "analysis_relief_trustworthy", "analysis_explainable_orders",
                "summary_number_backing", "summary_gap_disclosure"):
        assert isinstance(THRESHOLDS[key], float) or THRESHOLDS[key] == 1.0


def test_headline_tools_are_all_registered_chat_tools():
    """名单里每个名字都必须是 chat 真注册的工具：写错一个，那类答复就永远进不了分母。

    10-08 实测就是这么发现的 —— 名单里的 `virtual_factory_simulate` 从来没存在过，
    60 天窗口只攒到 6 条样本，看着像"用得少"，实际是名字对不上。
    """
    from api.services.chat_tools_service import TOOL_DEFINITIONS

    registered = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    unknown = sorted(set(HEADLINE_TOOLS) - registered)
    assert unknown == [], f"这些引擎工具名不存在：{unknown}"
    assert len(HEADLINE_TOOLS) >= 8, "只剩三五个名字通常意味着名单错拼，不是引擎面变少了"


def test_unbacked_kind_separates_engine_side_derivation_from_invention():
    """分类是为了追对人：差值/百分数缺的是引擎返回，不是模型编数。

    196.6 就是被上一版报成"编的"那条实测：正文写 7053.1 → 6856.5 人日（少 196.6），
    两端都在工具返回里、减法不在 —— 引擎后来直接返回 extra_person_days 才算齐。
    """
    from api.services.engine_capability import unbacked_kind

    reply = "用工 7053.1 → 6856.5 人日（少 196.6 人日）"
    corpus = ('{"normal": {"person_days_total": 7053.1}, '
              '"under": {"person_days_total": 6856.5}}')
    assert unbacked_kind("196.6", reply, corpus) == "两数之差"
    assert unbacked_kind("100", "产能占用比例：100%", '{"capacity_share": 1.0}') == "百分数写法"
    # 两端不在工具返回里就不许认差值：否则模型造两个数相减也算"有出处"
    assert unbacked_kind("196.6", "用工 7053.1 → 6856.5（少 196.6 人日）", "{}") == "找不到来源"


def test_unbacked_kind_recognises_a_backed_sum_as_derivation():
    """$17,460 + $153,000 = $170,460：分量都在工具里、合计是模型加的 —— 归派生，不归编造。

    只认**紧邻的前两个数**：允许全池两两组合去凑，等于模型随便加两个数都算有出处。
    """
    from api.services.engine_capability import unbacked_kind

    reply = "- 额外成本：人工费增加 $17,460，开线成本增加 $153,000，合计 $170,460。"
    corpus = '{"labor_delta_usd": 17460.0, "activation_delta_usd": 153000.0}'
    assert unbacked_kind("170460", reply, corpus) == "两数之和"
    # 分量没在工具返回里就不许认合计
    assert unbacked_kind("170460", reply, "{}") == "找不到来源"


def test_unbacked_kind_uses_comma_form_of_the_same_number():
    """170,460 与 170460 是同一个数：排版差不该被算成"编的"。"""
    from api.services.engine_capability import unbacked_kind

    assert unbacked_kind("170460", "缺口 170,460 件",
                         '{"shortage_qty": 170460.0}') == "千分位写法"
