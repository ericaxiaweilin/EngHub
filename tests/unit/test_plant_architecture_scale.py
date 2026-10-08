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
                           "reading": "1000 人规模（载体 LINE-TREAD-01 声明 300 台/天 → 287.36 台/天）："
                                      "8000 台 A-50-04-F 预计 57 天完工，比交期晚 32 天；用工 9626.8 人日"}}
    text = _format_architecture_reply(result)
    assert "预计 57 天完工" in text and "9626.8 人日" in text
    assert "LINE-TREAD-01" in text and "line_declared_home" in text
    assert "line_profiles 未改动" in text, "缩放线只活在内存里，界面必须这么说"
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
    """
    import inspect

    from core.mes.plant_architecture import scaled_delivery_run

    src = inspect.getsource(scaled_delivery_run)
    assert 'float(base_line["hours_per_day"])' in src
    assert '"hours_per_day": scaled_line.get("hours_per_day")' not in src
