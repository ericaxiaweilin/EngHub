"""天气折算出勤的断言：三档要按用户给的率折，算不出时不许拿 97% 兜底。

用户 10-06 给的标定：天气好 97%、雨 92%、暴雨 70%。
关键红线是最后两条 —— 天气取不到就是没有预计值，厂址也不能被猜成"默认晴天"。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.attendance_model import (
    RATE_DRY,
    RATE_RAIN,
    RATE_STORM,
    attendance_rate,
    expected_headcount,
    weather_condition,
)


def test_three_bands_use_the_users_own_numbers():
    assert (RATE_DRY, RATE_RAIN, RATE_STORM) == (0.97, 0.92, 0.70)
    assert weather_condition(0.0) == "dry"
    assert weather_condition(6.5) == "rain"
    assert weather_condition(120.0) == "storm"


def test_storm_band_is_beyond_rain_not_around_it():
    """暴雨阈值一旦低于雨阈值，就会把小雨折成 70% 出勤。"""
    assert weather_condition(49.9) == "rain"
    assert weather_condition(50.0) == "storm"


def test_code_fallback_when_no_precipitation_reading():
    assert weather_condition(None, 95) == "storm"     # 强雷暴
    assert weather_condition(None, 61) == "rain"      # 小雨
    assert weather_condition(None, 0) == "dry"        # 晴
    assert weather_condition(None, None) == "unknown"


def test_thunderstorm_counts_as_storm_even_when_daily_mm_looks_mild():
    """21.7mm 配 WMO 95（雷暴）：按累计雨量只是"雨"，现场是暴雨天 —— 取更严重那一档。"""
    assert weather_condition(21.7, 95) == "storm"
    assert weather_condition(21.7, 61) == "rain"
    assert weather_condition(0.0, 0) == "dry"


def test_unknown_weather_gives_no_rate_rather_than_the_dry_default():
    assert attendance_rate("unknown") is None
    assert expected_headcount(1005, "unknown") is None


def test_headcount_rounds_and_keeps_the_roster_as_denominator():
    assert expected_headcount(1005, "dry") == round(1005 * RATE_DRY)
    assert expected_headcount(1005, "rain") == round(1005 * RATE_RAIN)
    assert expected_headcount(1005, "storm") == round(1005 * RATE_STORM)
    assert expected_headcount(0, "dry") is None, "没有在册人就不该凭空出现到岗数"
