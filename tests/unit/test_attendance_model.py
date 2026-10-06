"""天气折算出勤的断言：三档率是用户给的数、定档可复现、拿不到依据就不折算。

用户 10-06：好天 97%、雨 92%、暴雨 70%，并要"按北宁历史雨量推"。
这里既钉换算率，也钉两件更容易错的事：**同一天的定档必须可复现**（不然重排一次交期就变一套），
以及**没有天气依据时不许拿 97% 兜底**。
"""

from datetime import date

import pytest

pytestmark = [pytest.mark.unit]

from api.services.attendance_model import (
    RATE_DRY,
    RATE_RAIN,
    RATE_STORM,
    STORM_MM,
    attendance_rate,
    band_shares,
    draw_band,
    expected_headcount,
    weather_condition,
)


def test_three_bands_use_the_users_own_numbers():
    assert (RATE_DRY, RATE_RAIN, RATE_STORM) == (0.97, 0.92, 0.70)
    assert weather_condition(0.0) == "dry"
    assert weather_condition(6.5) == "rain"
    assert weather_condition(80.0) == "storm"


def test_storm_threshold_sits_above_the_rain_threshold():
    """暴雨阈值一旦低于雨阈值，小雨就被折成 70% 出勤。"""
    assert STORM_MM > 1.0
    assert weather_condition(STORM_MM - 0.1) == "rain"
    assert weather_condition(STORM_MM) == "storm"


def test_thunderstorm_counts_as_storm_even_when_daily_mm_looks_mild():
    """21.7mm 配 WMO 95（雷暴）：累计雨量只是"雨"，现场是暴雨天 —— 取更严重那一档。"""
    assert weather_condition(21.7, 95) == "storm"
    assert weather_condition(21.7, 61) == "rain"
    assert weather_condition(0.0, 0) == "dry"


def test_unknown_weather_gives_no_rate_rather_than_the_dry_default():
    assert weather_condition(None, None) == "unknown"
    assert attendance_rate("unknown") is None
    assert expected_headcount(1005, "unknown") is None


def test_headcount_rounds_and_refuses_to_invent_people():
    assert expected_headcount(1005, "dry") == round(1005 * RATE_DRY)
    assert expected_headcount(1005, "storm") == round(1005 * RATE_STORM)
    assert expected_headcount(0, "dry") is None, "没有在册人就不该凭空出现到岗数"


def test_band_shares_only_count_days_it_actually_saw():
    series = [
        (date(2025, 6, 1), 0.0),      # dry
        (date(2025, 6, 2), 12.0),     # rain
        (date(2025, 6, 3), 120.0),    # storm
        (date(2025, 7, 1), None),     # 缺测：不进任何一档
    ]
    out = band_shares(series)
    assert out["observed_days"] == 3
    assert out["missing_days"] == 1, "缺测要单独报出来，不然会被读成晴天"
    june = out["months"]["6"]
    assert june["days"] == 3
    assert june["dry"] == pytest.approx(1 / 3, abs=1e-4)
    assert june["storm"] == pytest.approx(1 / 3, abs=1e-4)
    assert june["average_rate"] == pytest.approx((RATE_DRY + RATE_RAIN + RATE_STORM) / 3, abs=1e-4)
    assert "7" not in out["months"], "整月缺测不该产出一个看起来能用的分布"


def test_draw_band_is_reproducible_and_follows_the_distribution():
    shares = {"dry": 0.8, "rain": 0.15, "storm": 0.05}
    key = "21.186,106.046,2026-11-15"
    assert draw_band(shares, key) == draw_band(shares, key), "同一天必须同一档，否则重排一次交期就对不上"
    drawn = [draw_band(shares, f"k{i}") for i in range(4000)]
    counts = {b: drawn.count(b) / len(drawn) for b in ("dry", "rain", "storm")}
    assert counts["dry"] > counts["rain"] > counts["storm"], "抽样得偏向好天，不能三档均匀"
    assert abs(counts["dry"] - 0.8) < 0.05
    assert draw_band({}, key) is None, "没有当月分布就别假装抽得出天气"


def test_north_and_south_are_kept_as_separate_regions():
    """南部是工业重地，不能拿北部的天气盖它。"""
    from api.services.attendance_model import REGIONS, region_coords

    assert {"bacninh", "hochiminh"} <= set(REGIONS)
    north, south = region_coords("bacninh"), region_coords("hochiminh")
    assert abs(north[0] - south[0]) > 5, "两个区域得真的隔着一段纬度，不然分它做什么"


def test_unknown_region_falls_back_to_default_instead_of_crashing():
    from api.services.attendance_model import DEFAULT_REGION, region_meta

    assert region_meta("mars")["label"] == region_meta(DEFAULT_REGION)["label"]
