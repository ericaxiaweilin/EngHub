"""闲置产能台账的口径：闲置按方案跨度算、人数按 HR 原始行加一次、匹配不到就说匹配不到。

第一版这里错得很难看：窗口取了"今天"，而方案排在另外 31 天里，于是每个工位都算成
`available=8、scheduled=0、全天空转` —— 那是把口径 bug 报成经营结论。所以现在断言打在窗口上。
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import idle_capacity as ic


def _hr(station, position, people):
    return {"station": station, "position": position, "people": people}


def test_headcount_matches_both_ways_of_naming_without_double_counting():
    """stations 写"焊接车间"、HR 写"焊接"：两边都要认，但同一个人只能加一次。"""
    rows = [_hr("焊接", "操作员", 120), _hr("焊接", "组长", 6), _hr("涂装", "操作员", 77)]
    index = ic._headcount_index(rows)
    people = ic._station_people("焊接车间", "ST-HJ-01", rows, index)
    assert people == {"操作员": 120, "组长": 6}
    assert sum(people.values()) == 126


def test_station_without_hr_match_reports_zero_not_a_guess():
    rows = [_hr("焊接", "操作员", 120)]
    index = ic._headcount_index(rows)
    assert ic._station_people("CNC加工中心", "CNC-CENT-01", rows, index) == {}


def test_window_comes_from_the_plan_not_from_today():
    """SQL 里的窗口必须取自方案自身的 planned 跨度；写死"今天"会让整版方案算成 0 工时。"""
    sql = str(ic.STATION_HOURS_SQL)
    assert "MIN(t.planned_start)" in sql and "MAX(t.planned_end)" in sql
    assert "date_trunc('day'" in sql
    assert "CAST(:as_of AS date) AS d0" not in sql


@pytest.mark.asyncio
async def test_report_sums_idle_person_hours_across_stations():
    """只读：一张 UPDATE/INSERT 都不许发，且闲置按"工时 × 该工位人数"落到人·小时。"""
    station_rows = [
        {"station_id": "s1", "station_code": "ST-HJ-01", "station_name": "焊接车间",
         "workshop_id": None, "window_days": 3, "available_hours": 24.0,
         "efficiency_rate": 1, "setup_time_minutes": 0,
         "capacity_known": True, "capacity_hours_per_day": 8.0, "required_skills": None,
         "scheduled_hours": 4.0, "blocked_hours": 2.0, "scheduled_orders": 5},
    ]
    fill_rows = [{"id": "o1", "work_order_code": "WO-1", "planned_qty": 10,
                  "routing_id": "rt-1", "routing_template_id": None}]

    async def execute(statement, params=None):
        r = MagicMock()
        sql = str(statement)
        if "FROM aps_schedule_tasks t" in sql and "win AS" in sql:
            r.mappings.return_value.all.return_value = station_rows
        elif "FROM work_orders wo" in sql:
            r.mappings.return_value.all.return_value = fill_rows
        elif "hr_employees" in sql:
            r.mappings.return_value.all.return_value = [_hr("焊接", "操作员", 10)]
        elif "step_seq" in sql:
            r.mappings.return_value.first.return_value = {
                "step_seq": 1, "station_code": "ST-HJ-01", "standard_hours": 0.5,
                "is_parallel": False}
        elif "hours_per_unit" in sql:
            r.mappings.return_value.first.return_value = {"hours_per_unit": 0.5, "steps": 4}
        else:
            r.mappings.return_value.first.return_value = None
            r.mappings.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await ic.idle_capacity_report(db, "FAC_MECH_001", as_of=date(2026, 11, 2))

    line = out["top_idle"][0]
    assert out["plan_window_days"] == 3
    assert line["runnable_hours"] == 2.0          # 4 排定 - 2 开不了工
    assert line["idle_hours"] == 22.0             # 24 可用 - 2 真能干
    assert line["labor_hours_available_estimated"] == 240.0     # 10 人 × 8h × 3 天
    assert line["idle_ratio"] == round(22.0 / 24.0, 4)
    assert line["idle_person_hours_estimated"] == round(240.0 * line["idle_ratio"], 1)
    # 一致性守卫：估算的闲置人时永远不能超过可用工时的 100%
    assert line["idle_person_hours_estimated"] <= line["labor_hours_available_estimated"]
    assert line["fillable_kitted_orders"] == 1
    assert line["fillable_need_hours"] == 5.0     # 0.5 工时/件 × 10 件
    # 闲置量一旦算出来，钱就跟着出来（用内置标定，来源标 default_calibration）
    assert out["cost_totals"]["labor_idle_cost_window"] > 0
    assert out["cost_basis"]["labor_person_day"]["basis"] == "default_calibration"
