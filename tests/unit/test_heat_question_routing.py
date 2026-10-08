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
