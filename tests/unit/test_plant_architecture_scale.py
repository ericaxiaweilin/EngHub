"""规模架构模型的缩放层：哪些能量、哪些必须拒绝外推。

台账里两厂的结构比例差 1.9~9.1 倍，所以"千人厂该有几个工位"没有通用系数 ——
这个模块只允许以一座参照厂等比放大，并把不可等的层（线数、产品族）明确挡掉。
"""
from core.mes.plant_architecture import (MIN_SPREAD_TO_REFUSE_TRANSFER, _spread,
                                         scale_shape)

SHAPE = {"people_per_day": 1044, "ledger_days": 9, "sections_observed": 12,
         "stations": 28, "equipment": 81, "products": 764, "routes_active": 197, "lines": 3,
         "sections": [{"section": "组立", "people": 330, "share": 0.32},
                      {"section": "焊接", "people": 218, "share": 0.21},
                      {"section": "涂装", "people": 91, "share": 0.088}],
         "ratios": {"people_per_station": 37.29}}


def test_headcount_is_turned_into_a_factor_against_the_measured_base():
    out = scale_shape(SHAPE, headcount=5220)
    assert out["ok"] and out["factor"] == 5.0
    assert out["target_people"] == 5220 and out["target_stations"] == 140
    assert [s["people"] for s in out["sections"]] == [1650, 1090, 455]


def test_products_and_lines_are_never_scaled_like_people():
    out = scale_shape(SHAPE, factor=0.1)
    assert out["target_products_kept"] == 764, "SKU 数不随人头缩放"
    assert out["target_lines_scaled"] == 0.3
    assert any("线不是可等比层" in w for w in out["warnings"])
    assert any("lines" in x for x in out["not_scaled"])


def test_small_scale_says_section_baselines_stop_having_samples():
    out = scale_shape(SHAPE, headcount=100)
    assert any("台账可观测下限" in w for w in out["warnings"])
    assert out["target_stations"] == 3


def test_no_reference_people_or_no_target_is_a_refusal_not_a_guess():
    assert scale_shape(dict(SHAPE, people_per_day=0), headcount=1000)["ok"] is False
    assert scale_shape(SHAPE)["ok"] is False
    assert scale_shape(SHAPE, factor=0)["ok"] is False


def test_sampling_only_station_master_is_flagged_as_not_physical():
    """机械厂 1044 人 / 28 工位 = 37.3 人/工位：工位表显然只是抽样登记。"""
    out = scale_shape(SHAPE, headcount=1000)
    assert any("抽样登记" in w for w in out["warnings"])


def test_spread_rule_is_what_blocks_cross_factory_transfer():
    assert _spread([37.29, 70.6]) == 1.89
    assert _spread([32.09, 32.09]) == 1.0
    assert _spread([1.0]) is None
    assert _spread([]) is None
    assert MIN_SPREAD_TO_REFUSE_TRANSFER == 1.5


def test_scale_words_become_numbers_not_a_default_plant():
    from api.services.chat_tools_service import (_architecture_intent_args,
                                                 _resolve_intent_keyword)

    assert _architecture_intent_args("给我一个五千人的厂，40度90%湿度") == {"headcount": 5000}
    assert _architecture_intent_args("千人工厂长什么样") == {"headcount": 1000}
    assert _architecture_intent_args("百人工厂呢") == {"headcount": 100}
    assert _architecture_intent_args("按 3000 人规模放大") == {"headcount": 3000}
    assert _architecture_intent_args("工厂架构模型") == {}     # 没说规模 → 不猜
    hit = _resolve_intent_keyword("千人工厂的架构模型")
    assert hit["tool"] == "generate_plant_architecture" and hit["args"]["headcount"] == 1000
    assert _resolve_intent_keyword("工厂架构模型") is None        # 规模缺失交回模型追问


def test_scale_question_keeps_the_working_condition_with_it():
    """"五千人的厂 40度90%" 不能只抽规模：工况那一半丢了，每段少来多少人就没数了。"""
    from api.services.chat_tools_service import _resolve_intent_keyword

    hit = _resolve_intent_keyword("千人工厂的架构模型，车间40度、湿度90%，装配岗")
    assert hit["args"]["headcount"] == 1000
    assert hit["args"]["temperature_c"] == 40.0 and hit["args"]["humidity_percent"] == 90.0
    assert hit["args"]["task_type"] == "assembly"


def test_cross_check_reading_does_not_print_a_fake_range():
    from core.mes.plant_architecture import _cross_check_reading

    same = _cross_check_reading({"min": 9.09, "max": 9.09, "compared": 11,
                                 "worst_line": "LINE-BIKE-01", "worst_model": "HTM1481-00",
                                 "worst_station": "加工车间"})
    assert "差 9.09 倍" in same and "~" not in same.split("组")[1]
    span = _cross_check_reading({"min": 6.82, "max": 9.09, "compared": 11,
                                 "worst_line": "L", "worst_model": "M", "worst_station": "S"})
    assert "6.82~9.09 倍" in span
    # 没有可比组时必须说"没对上过"，不能被读成"对上了"
    none_ = _cross_check_reading(None)
    assert "没有可比组" in none_ and "这不是『对上了』" in none_
    assert "没有可比组" in _cross_check_reading({"compared": 0})


def test_architecture_model_carries_the_cross_check_and_the_open_question():
    import inspect

    from core.mes.plant_architecture import architecture_model, capacity_cross_check

    src = inspect.getsource(architecture_model)
    assert "capacity_cross_check" in src, "架构模型必须带线↔工位对撞，不然只是自说自话的缩放"
    assert "cross_check" in src
    sig = inspect.signature(capacity_cross_check)
    assert list(sig.parameters) == ["db", "factory_id", "max_models"]


def test_run_target_reports_line_vs_station_without_choosing_a_side():
    from api.services.virtual_run import _line_station_conflict

    clash = _line_station_conflict({"units_per_day": 400.0},
                                   {"units_per_day": 40.0, "bottleneck_station": "ST-JG-01"})
    assert clash["agrees"] is False and clash["ratio_line_over_station"] == 10.0
    assert "不自己取小" in clash["note"] and "ST-JG-01" in clash["note"]
    # 线声明数不会因为工位侧更小而被偷偷替换
    assert clash["line_declared_units_per_day"] == 400.0
    ok = _line_station_conflict({"units_per_day": 300.0}, {"units_per_day": 260.0})
    assert ok["agrees"] is True and "note" not in ok
    assert _line_station_conflict({"units_per_day": 300.0}, None) is None
    assert _line_station_conflict({"units_per_day": 0}, {"units_per_day": 40.0}) is None


def test_run_target_still_computes_station_bound_when_a_line_exists():
    """以前 line 存在时 station_cap 被置 None —— 于是两个数从没同时出现过。"""
    import inspect

    from api.services.virtual_run import run_target

    src = inspect.getsource(run_target)
    assert "station_cap = station_route_capacity(route, census[\"stations\"], station_hours)" in src
    # 分支前的初始化可以留，但"有线就不算工位侧"那条置空不许回来
    assert src.count("station_cap = None") == 1
    assert '"line_vs_station": _line_station_conflict' in src


def test_home_line_wins_over_any_other_line_that_can_make_it():
    """家线必须排第一：A-50-04-F 的家是 LINE-TREAD-01（11h/300 台/300 人）。

    以前 capable_lines 只按 line_profiles 的行序返回，bike 线先入表 → 跑步机被派到 bike 线，
    日产能 400、班组 150，到岗曲线乘的人力与加班上限全跟着错一条线。
    """
    from api.services.virtual_run import capable_lines, pick_line

    lines = [
        {"line_code": "LINE-BIKE-01", "line_group": "G-B", "hours_per_day": 11, "units_per_day": 400,
         "group_units_per_day": 700, "crew_size": 150, "can_models": ["A-50-04-F", "HTM1481-00"],
         "cannot_models": [], "default_model": "HTM1481-00"},
        {"line_code": "LINE-TREAD-01", "line_group": "G-T", "hours_per_day": 11, "units_per_day": 300,
         "group_units_per_day": 300, "crew_size": 300, "can_models": ["A-50-04-F"],
         "cannot_models": ["HTM1481-00"], "default_model": "A-50-04-F"},
    ]
    order = [(l["line_code"], b) for l, b in capable_lines("A-50-04-F", lines)]
    assert order[0] == ("LINE-TREAD-01", "line_declared_home")
    line, basis = pick_line("A-50-04-F", lines)
    assert line["line_code"] == "LINE-TREAD-01" and basis == "line_declared_home"
    # 而 bike 机种的家线仍是 bike 线：家线优先不是"永远选 tread"
    line2, basis2 = pick_line("HTM1481-00", lines)
    assert line2["line_code"] == "LINE-BIKE-01" and basis2 == "line_declared_home"
    # 负向声明仍然优先于任何正向声明
    assert all(l["line_code"] != "LINE-TREAD-01" for l, _ in capable_lines("HTM1481-00", lines))


def test_scale_question_with_an_order_also_carries_the_delivery_target():
    """「千人的厂做 8000 台 A-50-04-F，交期 25 天」——规模之外那半句也要抽出来。

    只回台/天的模型答不了"几天交"；天数得由缩放后的线进沙箱算，所以机种/数量/交期得跟
    规模一起进工具。反过来，没给数量的问法不许被塞一个数量（那等于替厂里下了一张单）。
    """
    from api.services.chat_tools_service import _architecture_intent_args, _resolve_intent_keyword

    assert _architecture_intent_args("千人工厂做 8000 台 A-50-04-F，交期 25 天来得及吗") == {
        "headcount": 1000, "delivery_model": "A-50-04-F", "delivery_units": 8000.0,
        "delivery_due_days": 25}
    hit = _resolve_intent_keyword("千人工厂做 8000 台 A-50-04-F")
    assert hit["tool"] == "generate_plant_architecture"
    assert hit["args"]["delivery_model"] == "A-50-04-F" and hit["args"]["delivery_units"] == 8000.0
    assert "delivery_units" not in _architecture_intent_args("千人工厂每天最多能做多少台")
    assert "delivery_model" not in _architecture_intent_args("百人工厂的结构什么样")


def test_delivery_refuses_days_without_naming_both_model_and_quantity():
    import asyncio

    from core.mes.plant_architecture import attach_delivery

    base = {"reference_factory_id": "FAC_MECH_001", "scaled": {"target_people": 1000}}
    no_model = asyncio.run(attach_delivery(None, dict(base), {"delivery_units": 8000}))
    assert no_model["delivery"]["status"] == "no_target_order"
    assert "机种" in no_model["delivery"]["why"] and "8000 台 A-50-04-F" in no_model["delivery"]["hint"]
    no_units = asyncio.run(attach_delivery(None, dict(base), {"delivery_model": "A-50-04-F"}))
    assert "数量" in no_units["delivery"]["why"] and "机种" not in no_units["delivery"]["why"]
    # factor 路径没落成人头时也不许硬凑一个规模
    no_base = asyncio.run(attach_delivery(None, {"reference_factory_id": "F", "scaled": {}},
                                         {"delivery_model": "A-50-04-F", "delivery_units": 8000}))
    assert no_base["delivery"]["status"] == "no_scale_basis"


def test_chat_answer_prints_the_scaled_timeline_and_that_nothing_was_written():
    from api.routes.chat_routes import _format_architecture_reply

    result = {"status": "ok", "reference_factory_id": "FAC_MECH_001",
              "readings": ["参照厂 FAC_MECH_001：实测每天 1044 人"], "scaled": {"warnings": []},
              "delivery": {"status": "simulated", "factor": 0.9579,
                           "scaled_line": {"from_line": "LINE-TREAD-01",
                                           "line_basis": "line_declared_home",
                                           "units_per_day": 287.36, "crew": 287.4},
                           "due": {"days": 25, "note": "交期天数由提问给出"},
                           "min_scale": {"status": "found", "min_headcount": 2280,
                                         "reading": "赶上 25 天交期至少要 2280 人（参照厂实测 1044 人的 "
                                                    "2.18 倍；载体 LINE-TREAD-01 声明 300 台/天、班组 300 人 "
                                                    "→ 等效 8 个这样的班组），届时完工 25 天；试了 13 个规模"},
                           "reading": "1000 人规模（载体 LINE-TREAD-01 声明 300 台/天 → 287.36 台/天）："
                                      "8000 台 A-50-04-F 预计 57 天完工，比交期晚 32 天；用工 9626.8 人日"}}
    text = _format_architecture_reply(result)
    assert "预计 57 天完工" in text and "9626.8 人日" in text
    assert "LINE-TREAD-01" in text and "line_declared_home" in text
    assert "line_profiles 未改动" in text, "缩放线只活在内存里，界面必须这么说"
    assert "赶得上这个交期至少要：赶上 25 天交期至少要 2280 人" in text, "延了就要顺手给出要多少人"
    # 缺数量那条出口也要在答复里出现，不能整个 delivery 段静默消失
    refused = _format_architecture_reply({
        "status": "ok", "reference_factory_id": "F", "readings": [], "scaled": {"warnings": []},
        "delivery": {"status": "no_target_order", "why": "只给了目标规模，没给数量（多少台/件） → 不出交期天数",
                     "hint": "补一句规模+机种+数量"}})
    assert "规模交期：没算" in refused and "没给数量" in refused


def test_both_entries_share_one_delivery_computation():
    """/chat 工具与 /plant-architecture 必须走同一个 attach_delivery。

    两条入口各写一遍缩放口径，迟早给 PMC 两个天数 —— 与"唯一路径唯一基线"冲突。
    """
    import inspect

    from api.routes.pmc_routes import get_plant_architecture
    from api.services.chat_tools_service import _tool_generate_plant_architecture

    assert "attach_delivery" in inspect.getsource(get_plant_architecture)
    assert "attach_delivery" in inspect.getsource(_tool_generate_plant_architecture)
    assert "scaled_delivery_run" not in inspect.getsource(_tool_generate_plant_architecture)


def test_scaled_line_does_not_carry_a_decimal_into_the_chat_payload():
    """line_profiles.hours_per_day 是 numeric：原样带出来就落不进 chat_messages 的 jsonb。

    实测过：答复文本已经生成好，落库时 `Object of type Decimal is not JSON serializable`
    把整条 /chat 打成 500 —— 生成侧成功不等于交付成功，所以这里钉住显式转换。
    按模块源码判：缩放读数在 _run_at_scale 里组装，函数拆了也不该让这条约束跟着漏。
    """
    import inspect

    import core.mes.plant_architecture as pa

    src = inspect.getsource(pa)
    assert 'float(base_line["hours_per_day"])' in src
    assert '"hours_per_day": scaled_line.get("hours_per_day")' not in src


def test_min_scale_finds_the_smallest_headcount_that_meets_the_due_date():
    """搜索本身要能单测：探针给一个单调的完工天数函数，看它收敛到几个人。

    finish(hc)=⌈57000/hc⌉：1000 人 57 天（与真实沙箱同一形状），25 天交期→最少 2280 人。
    """
    import asyncio
    from math import ceil

    from core.mes.plant_architecture import min_scale_for_delivery

    def finish(hc: float) -> float:
        return ceil(57000.0 / hc)

    async def probe(hc: float):
        return {"finish_day": finish(hc), "wait_days_for_material": 10, "person_days": hc * finish(hc)}

    out = asyncio.run(min_scale_for_delivery(probe, reference_headcount=1044, units=8000, due_days=25))
    assert out["status"] == "found" and out["min_headcount"] == 2280
    assert finish(out["min_headcount"]) <= 25 and finish(out["min_headcount"] - 1) > 25
    # 报出去的那个人数自己就得赶得上，完工天数也必须挂在它身上（不是挂在 2280.7 人身上）
    assert out["finish_day"] == 25 and out["infeasible_one_person_less"] == 26
    assert out["search_tolerance_headcount"] == 1 and out["probes"] < 20


def test_min_scale_says_when_adding_people_stops_helping():
    """完工天数有地板（等料/提前期）时不许回"再加人就快了"。"""
    import asyncio

    from core.mes.plant_architecture import min_scale_for_delivery

    async def probe(hc: float):
        return {"finish_day": max(40.0, 57000.0 / hc), "wait_days_for_material": 40}

    out = asyncio.run(min_scale_for_delivery(probe, reference_headcount=1044, units=8000, due_days=25))
    assert out["status"] == "lead_time_bound"
    assert out["finish_day_at_max"] == 40 and out["finish_day_at_max_div_8"] == 40
    assert "卡的是等料" in out["note"] and "200000" in out["why"]


def test_min_scale_reports_a_ceiling_instead_of_a_number_when_people_still_bind():
    import asyncio

    from core.mes.plant_architecture import min_scale_for_delivery

    async def probe(hc: float):
        return {"finish_day": 6_000_000.0 / hc, "wait_days_for_material": 10}

    out = asyncio.run(min_scale_for_delivery(probe, reference_headcount=1044, units=8000, due_days=25))
    assert out["status"] == "beyond_ceiling" and out["finish_day_at_max"] == 30
    assert out["finish_day_at_max_div_8"] == 240     # 规模差 8 倍天数还在动 → 人仍是瓶颈
    assert "并行多条线" in out["note"]


def test_min_scale_is_computed_only_when_that_scale_misses_the_date(monkeypatch):
    """赶上了就不必再花十几轮沙箱；赶不上就必须把"要多少人"一起给出，不等追问。"""
    import asyncio

    import core.mes.plant_architecture as pa

    calls = []

    async def late_run(db, ref, **kw):
        return {"status": "simulated", "finish_day": 57, "days_late": 32, "due": {"days": 25}}

    async def on_time_run(db, ref, **kw):
        return {"status": "ok", "finish_day": 20, "days_late": -5, "due": {"days": 25}}

    async def fake_min(db, ref, **kw):
        calls.append(kw)
        return {"status": "found", "min_headcount": 2280}

    args = {"delivery_model": "A-50-04-F", "delivery_units": 8000, "delivery_due_days": 25}
    base = {"reference_factory_id": "FAC_MECH_001", "scaled": {"target_people": 1000}}
    monkeypatch.setattr(pa, "scaled_delivery_run", late_run)
    monkeypatch.setattr(pa, "min_headcount_for_delivery", fake_min)
    out = asyncio.run(pa.attach_delivery(None, dict(base), dict(args)))
    assert out["delivery"]["min_scale"]["min_headcount"] == 2280
    assert calls[0]["model"] == "A-50-04-F" and calls[0]["due_in_days"] == 25

    calls.clear()
    monkeypatch.setattr(pa, "scaled_delivery_run", on_time_run)
    out2 = asyncio.run(pa.attach_delivery(None, dict(base), dict(args)))
    assert not calls and "min_scale" not in out2["delivery"]
