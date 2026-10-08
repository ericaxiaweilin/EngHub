"""插单影响的取数口径：数字得来自线台账与路线标准工时，缺依据就拒绝，不许回落到编造的工时。

这些测试锁三件容易回潮的事：
1. `capacity_share` 只拉长急单自己的完工时间 —— 同线被拿走的产出不随它变（这个参数以前解析完就丢了）；
2. 班次日推进要跳过停工日，延迟不能按自然日/墙钟小时摊；
3. 抽不到机种或数量时**不**确定性执行（交回模型追问），以及 `0.5 小时/件 ÷ 0.85` 不许再出现在源码里。
"""
import inspect
from datetime import date

from api.services.chat_tools_service import _extract_model_keyword, _resolve_intent_keyword
from api.services.virtual_run import (_n_pro_days, production_days_between, production_finish_day,
                                      rush_durations, shift_forward)

MON_TO_SAT = {1, 2, 3, 4, 5, 6}   # 台账日历：周日(7)停工


def test_share_only_stretches_rush_own_finish_not_the_displacement():
    full = rush_durations(500, 250, 1.0)
    half = rush_durations(500, 250, 0.5)
    assert full["own_production_days"] == 2.0
    assert full["queue_displacement_days"] == 2.0
    # 只给一半产能：急单自己拖到 4 天，但它从这条线拿走的还是 500 台 = 2 个班次日
    assert half["own_production_days"] == 4.0
    assert half["queue_displacement_days"] == 2.0


def test_no_capacity_basis_gives_zero_days_not_one_unit_per_day():
    assert rush_durations(500, 0)["queue_displacement_days"] == 0.0
    assert rush_durations(0, 250)["own_production_days"] == 0.0


def test_share_is_clamped():
    assert rush_durations(100, 100, 0.01)["own_production_days"] == 20.0   # 下限 5%
    assert rush_durations(100, 100, 5.0)["own_production_days"] == 1.0     # 上限整线
    assert rush_durations(100, 100, 0)["own_production_days"] == 1.0       # 0=没说，按整线，不推到 20 天
    assert rush_durations(100, 100, None)["own_production_days"] == 1.0


def test_finish_day_counts_shift_days_and_skips_sunday():
    # 2026-10-08 是周四
    assert production_finish_day(date(2026, 10, 8), 0, MON_TO_SAT)["end"] == date(2026, 10, 8)
    assert production_finish_day(date(2026, 10, 8), 1, MON_TO_SAT)["end"] == date(2026, 10, 8)
    assert production_finish_day(date(2026, 10, 8), 2, MON_TO_SAT)["end"] == date(2026, 10, 9)
    assert production_finish_day(date(2026, 10, 8), 3, MON_TO_SAT)["end"] == date(2026, 10, 10)
    assert production_finish_day(date(2026, 10, 8), 4, MON_TO_SAT)["end"] == date(2026, 10, 12)  # 跳过周日
    assert production_finish_day(date(2026, 10, 8), 4, MON_TO_SAT)["calendar_days"] == 4


def test_start_on_a_rest_day_moves_to_the_next_shift_day():
    assert production_finish_day(date(2026, 10, 11), 1, MON_TO_SAT)["end"] == date(2026, 10, 12)


def test_partial_day_still_occupies_a_whole_day():
    assert _n_pro_days(0.25) == 1
    assert _n_pro_days(2.0) == 2
    assert production_finish_day(date(2026, 10, 8), 1.49, MON_TO_SAT)["end"] == date(2026, 10, 9)


def test_shift_forward_and_days_between_agree_on_the_calendar():
    assert shift_forward(date(2026, 10, 9), 1, MON_TO_SAT) == date(2026, 10, 10)
    assert shift_forward(date(2026, 10, 9), 2, MON_TO_SAT) == date(2026, 10, 12)   # 周日不占产能
    assert production_days_between(date(2026, 10, 9), date(2026, 10, 12), MON_TO_SAT) == 2
    assert production_days_between(date(2026, 10, 12), date(2026, 10, 9), MON_TO_SAT) == 0


def test_model_keyword_takes_the_code_shape_and_ignores_order_numbers():
    assert _extract_model_keyword("插单 500 台 A-50-04-F 会延几天") == "A-50-04-F"
    assert _extract_model_keyword("急单 HTM1481-00 300台") == "HTM1481-00"
    assert _extract_model_keyword("插 300 台跑步机") == "跑步机"
    assert _extract_model_keyword("WO-2026-0007 这张单能不能插进去") is None
    assert _extract_model_keyword("插单影响有多大") is None


def test_intent_is_not_run_deterministically_without_model_or_quantity():
    hit = _resolve_intent_keyword("插单影响 500 台 A-50-04-F")
    assert hit and hit["tool"] == "query_pmc_rush_impact"
    assert hit["args"]["quantity"] == 500
    assert hit["args"]["product_id"] == "A-50-04-F"
    assert hit["args"]["capacity_share"] == 1.0            # 没点比例就是整线做这单
    assert _resolve_intent_keyword("插单影响有多大") is None      # 没机种 → 让模型去问，不拿默认场景算
    assert _resolve_intent_keyword("插单影响 A-50-04-F") is None  # 没数量 → 同上


def test_explicit_capacity_share_is_carried_through():
    hit = _resolve_intent_keyword("插单 500 台 A-50-04-F，只占用 30% 产能")
    assert hit["args"]["capacity_share"] == 0.3


def test_fabricated_ie_pair_is_gone_from_every_call_site():
    """0.5 小时/件 ÷ 0.85 效率这两个数在三个地方各写过一遍，这里当回归锁。"""
    from api.services import chat_tools_service, pmc_control_tower_service
    from api.services import scheduling_agent_service, virtual_run

    for module in (chat_tools_service, pmc_control_tower_service,
                   scheduling_agent_service, virtual_run):
        src = inspect.getsource(module).replace(" ", "")
        assert "0.5/0.85" not in src, module.__name__
        assert "hours_per_unit=0.5" not in src, module.__name__
        assert "or\"ST-01\"" not in src, module.__name__
