"""数据源台账的断言：来源要分得清、考勤过期要说"在册≠出勤"、清账范围要窄到 created_by。

用户口径：IE 数据 + HR 人力数据为准，仿真的真实映射由 出勤·设备·排产·齐套 共同维持；
"没有数据就是骗自己的"。所以这个模块最要命的错不是算错数，而是**把自造数据读成现场事实**。
"""

from datetime import date

import pytest

pytestmark = [pytest.mark.unit]

from api.services.data_authority import (
    SYNTHETIC_IE_SOURCES,
    attendance_freshness,
    classify,
)


def test_seeded_and_engine_written_ie_times_are_not_ie():
    """仓库脚本灌的 + 引擎自己写的，都不算 IE 给的工时。"""
    out = classify([
        {"source": "seed_guard", "rows_in": 12},
        {"source": "virtual_factory", "rows_in": 10},
    ])
    assert out["ie_rows"] == 0
    assert out["synthetic_rows"] == 22
    assert "IE 工时为空" in out["verdict"]


def test_real_ie_rows_become_the_authoritative_source():
    out = classify([
        {"source": "seed_guard", "rows_in": 12},
        {"source": "ie_team", "rows_in": 40},
    ])
    assert out["ie_rows"] == 40
    assert out["synthetic_rows"] == 12
    assert "IE 核定 40 行" in out["verdict"]


def test_empty_source_list_says_ie_dimension_is_missing_not_zero_ok():
    out = classify([])
    assert out["ie_rows"] == 0 and out["synthetic_rows"] == 0
    assert "IE 工时为空" in out["verdict"]


def test_stale_attendance_is_reported_as_roster_not_attendance():
    """考勤停在 8 月、今天 10 月：不能报"今天 1,005 人出勤"。"""
    out = attendance_freshness(date(2026, 8, 22), date(2026, 10, 6))
    assert out["has_data"] is True
    assert out["stale_days"] == 45
    assert "在册" in out["verdict"] and "出勤" in out["verdict"]


def test_today_attendance_is_usable():
    out = attendance_freshness(date(2026, 10, 6), date(2026, 10, 6))
    assert out["stale_days"] == 0
    assert out["verdict"] == "今天有考勤，按出勤人数算"


def test_no_attendance_at_all_admits_it_has_no_value():
    out = attendance_freshness(None, date(2026, 10, 6))
    assert out["has_data"] is False
    assert out["stale_days"] is None
    assert "只能按 HR 在册算" in out["verdict"]


def test_purge_scope_is_limited_to_what_we_wrote_ourselves():
    """清除作用域只认 created_by 白名单 —— 厂里给的行、主档原始值不在其中。"""
    assert set(SYNTHETIC_IE_SOURCES) == {"virtual_factory", "seed_guard"}
    assert "erp_sync" not in SYNTHETIC_IE_SOURCES, \
        "模板声明工时是 IE 该维护的列，来源存疑时走台账标注，不靠删除解决"
