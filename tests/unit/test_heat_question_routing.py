"""高温问题的参数抽取与路由：用户说出口的数必须进引擎，没说的要看得见是默认的。

实测踩过两类事故：一是"一小时走12000步、背10公斤"被抽成默认 3000 步/0kg（等于替用户改题），
二是问"这批单延几天"却只答合规（把缺勤扣人头这条后果藏起来）。这两条都锁在这里。
"""

from __future__ import annotations

from api.services.chat_tools_service import asks_delivery_impact, extract_heat_scenario


def test_gait_load_and_terrain_words_reach_the_engine():
    args = extract_heat_scenario("机械厂车间33度、湿度70%，装配岗一小时走12000步，还要背10公斤，能干吗")
    assert args["temperature_c"] == 33.0 and args["humidity_percent"] == 70.0
    assert args["step_count"] == 12000
    assert args["load_weight_kg"] == 10.0
    assert args["continuous_work_minutes"] == 60      # "一小时"是中文数字，也要认
    assert args["factory_id"] == "机械厂"


def test_stoop_degrees_are_not_read_as_room_temperature():
    args = extract_heat_scenario("弯腰70度、机加工车间30度，能连续干2小时吗")
    assert args["temperature_c"] == 30.0
    assert args["posture_angle_deg"] == 70.0
    assert args["continuous_work_minutes"] == 120
    assert args["task_type"] == "machining"


def test_stairs_and_wan_steps_are_parsed():
    args = extract_heat_scenario("检验岗在车间26度、湿度55%，爬楼梯巡检一小时6000步")
    assert args["terrain"] == "stairs"
    assert args["step_count"] == 6000 and args["task_type"] == "inspect"


def test_no_temperature_means_no_deterministic_simulation():
    """没温度就整条不跑：只有关键词的过程量不足以构成一个工况场景，默认 30℃ 会答非所问。"""
    assert extract_heat_scenario("装配岗今天干得怎么样") == {}
    assert extract_heat_scenario("湿度90%能干吗") == {}


def test_delivery_questions_pull_in_the_capacity_run():
    assert asks_delivery_impact("手上这批单会比平时多延几天交付？") is True
    assert asks_delivery_impact("闷热天到岗会掉多少") is True
    # 只问能不能干时不该多跑一遍沙箱（成本翻倍，答案也没问交期）
    assert asks_delivery_impact("车间38度、湿度70%，装配岗连续干3小时合规吗") is False


def test_section_word_is_carried_to_the_engine():
    """"涂装段"要带走：段级缺勤率与全厂平均差好几倍，按全厂回答等于把风险摊平。"""
    # 抓到的可能是带前缀的短语（"厂涂装"），段名由工具拿台账反查，这里只保证"X段"被带走
    assert "涂装" in extract_heat_scenario("机械厂涂装段车间38度、湿度70%，还开得起吗")["section"]
    # 但"连续干3小时"里的"小时"不是段
    assert "section" not in extract_heat_scenario("车间38度、装配岗连续干3小时合规吗")


def test_temperature_question_beats_a_work_order_keyword():
    """点了车间温度又问"还能干吗/延几天"的问题必须由引擎答。

    实测事故：「40度、湿度90%，涂装段还能干吗？这批单会延几天？」里"会延几"先命中插单关键词，
    插单工具又因为没给数量返回 None，于是整条确定性路径让位给模型 —— 模型编出一套
    "涂装节拍下降 30~50%、延 1.5~3 天"，一个数都不是台账来的。
    """
    from api.services.chat_tools_service import _resolve_intent_keyword

    hit = _resolve_intent_keyword("40度、湿度90%，涂装段还能干吗？这批单会延几天？")
    assert hit["tool"] == "run_compliance_simulation"
    assert hit["args"]["temperature_c"] == 40.0 and hit["args"]["humidity_percent"] == 90.0
    assert "涂装" in str(hit["args"].get("section"))


def test_complete_rush_question_still_goes_to_the_rush_tool():
    """给了数量与机种的插单问题不被温度抢走（它自己就是产能题，且参数齐）。"""
    from api.services.chat_tools_service import _resolve_intent_keyword

    hit = _resolve_intent_keyword("插单 500 台 A-50-04-F 会延几天")
    assert hit["tool"] == "query_pmc_rush_impact"
    assert hit["args"]["quantity"] == 500 and hit["args"]["product_id"] == "A-50-04-F"


def test_temperature_without_a_condition_question_is_not_forced_into_the_engine():
    """只有温度、没问工况后果（能干吗/要不要休/延几天）就不抢模型的活。"""
    from api.services.chat_tools_service import _asks_working_condition, _resolve_intent_keyword

    assert _asks_working_condition("烘干炉设定 40 度是多少") is False
    assert _resolve_intent_keyword("烘干炉设定 40 度是多少") is None


def test_work_matrix_question_keeps_its_own_route():
    """工段锤/矩阵那种"看这张单的证据"的问题不因句中出现温度就被改成合规仿真。"""
    from api.services.chat_tools_service import _HEAT_PREEMPT_EXEMPT

    assert "query_pmc_work_matrix" in _HEAT_PREEMPT_EXEMPT
