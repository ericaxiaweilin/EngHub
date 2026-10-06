"""工时口径的断言：没有出处就不能给出时间，给出时间时要能说清是谁声明的。

背景（线上实测）：routings.steps 的 430 个机械工步里 0 个带工时，
排程落到 `0 秒/件 × 数量 + 300 秒换型` 的兜底，961 条现行任务里 881 条不足 1 小时。
这里断言的是那个兜底不许再回来：宁可 no_time_basis，不要假的 5 分钟。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.time_basis import (
    BASIS_LINE,
    BASIS_NONE,
    BASIS_ROUTE,
    BASIS_STATION,
    TimeBasis,
    capacity_conflicts,
    declared_step_seconds,
    line_models,
    seconds_from_hourly_rate,
)


def test_rate_without_evidence_is_none_not_zero():
    """产能缺失必须返回 None；返回 0 会被调用方当成"有依据但是很快"。"""
    assert seconds_from_hourly_rate(4) == 900.0
    assert seconds_from_hourly_rate(0) is None
    assert seconds_from_hourly_rate(None) is None
    assert seconds_from_hourly_rate(-5) is None


def test_declared_step_hours_take_precedence_and_zero_is_not_a_declaration():
    assert declared_step_seconds({"standard_hours": 0.5}) == 1800.0
    assert declared_step_seconds({"standard_hours": 0, "time_min": 2}) == 120.0
    assert declared_step_seconds({"standard_hours": 0, "standard_time": 45}) == 45.0
    # 三个字段都在但都是 0 —— 那是"没填"，不是"这件产品 0 秒做完"
    assert declared_step_seconds({"standard_hours": 0, "time_min": 0, "standard_time": 0}) is None
    assert declared_step_seconds({}) is None


def _basis():
    return TimeBasis(
        station_rates={"ST-HJ-01": 4.0, "ST-ZL-01": 110.0},
        lines=[
            {"line_code": "LINE-TREAD-01", "line_group": "GROUP-TREAD", "hours_per_day": 11,
             "units_per_day": 300, "crew_size": 300, "group_units_per_day": 300,
             "default_model": "A-50-04-F", "can_make_models": ["A-50-04-F", "HTM1481-00"],
             "cannot_make_models": []},
            {"line_code": "LINE-BIKE-01", "line_group": "GROUP-BIKE", "hours_per_day": 11,
             "units_per_day": 400, "crew_size": 150, "group_units_per_day": 700,
             "default_model": "HTM1481-00", "can_make_models": ["HTM1481-00"],
             "cannot_make_models": []},
        ],
    )


def test_precedence_route_then_line_then_station():
    basis = _basis()
    seconds, used = basis.seconds_per_piece(
        model="A-50-04-F", station="ST-HJ-01", step={"standard_hours": 0.25}
    )
    assert (used, seconds) == (BASIS_ROUTE, 900.0)

    seconds, used = basis.seconds_per_piece(model="A-50-04-F", station="ST-HJ-01", step={})
    takt = 11 * 3600 / 300
    assert (used, round(seconds, 3)) == (BASIS_LINE, round(takt, 3))

    # 机种没有归属线、工步也没 IE 工时 → 工位那列**不再补位**（单位未定义，10-06 定）
    seconds, used = basis.seconds_per_piece(model="A-99-XX", station="ST-HJ-01", step={})
    assert (used, seconds) == (BASIS_NONE, None)
    # 但工位值仍然是对撞报告的证据
    assert basis.bottleneck_rate(["ST-HJ-01", "ST-ZL-01"]) == 4.0


def test_ie_hours_and_line_params_are_the_only_two_sources():
    """两个来源都不成立就是 no_time_basis —— 工位那列未定义单位的数不许补位。"""
    basis = _basis()
    assert basis.seconds_per_piece(model="A-99-XX", station="ST-HJ-01", step={})[1] == BASIS_NONE
    # 归属线仍然给时长（参考级：用户口述）
    assert basis.seconds_per_piece(model="A-50-04-F", station="ST-HJ-01", step={})[1] == BASIS_LINE


def test_home_line_wins_over_a_faster_line_that_could_also_make_it():
    """A-50-04-F 的归属线是跑步机线；bike 线更快也不许拿它来报预计完工。

    把"可能性"当"事实"报，1,180 台会从 4 天变成 1.4 天 —— 车间一看就是假的。
    """
    basis = _basis()
    assert basis.line_by_model["A-50-04-F"]["line_code"] == "LINE-TREAD-01"
    assert basis.line_by_model["A-50-04-F"]["seconds_per_piece"] == pytest.approx(11 * 3600 / 300)


def test_between_two_non_home_lines_the_faster_one_is_used():
    """两条线都不是归属线时，才在能做的里面取快的（bike 是 HTM1481-00 的归属线）。"""
    basis = _basis()
    assert basis.line_by_model["HTM1481-00"]["line_code"] == "LINE-BIKE-01"


def test_cannot_make_is_a_hard_block_not_a_suggestion():
    basis = TimeBasis(
        station_rates={},
        lines=[{"line_code": "L1", "hours_per_day": 10, "units_per_day": 100, "crew_size": 10,
                "default_model": "M1", "can_make_models": ["M1", "M2"],
                "cannot_make_models": ["M2"]}],
    )
    assert line_models(basis.lines[0]) == ["M1"]
    assert "M2" not in basis.line_by_model


def test_flow_order_time_is_line_output_not_steps_times_output():
    """流水线口径：整单 = 数量 ÷ 线产能 + 首件走完前道工序的节拍。

    6 个工步各占 1180×takt 是"每个工位各忙这些"，串行加起来是排程器的批次假设，
    不是产能量 —— 交时必须用这个函数，不能用任务行求和。
    """
    basis = _basis()
    takt = 11 * 3600 / 300
    assert basis.flow_order_seconds(model="A-50-04-F", qty=300, steps=1) == pytest.approx(300 * takt)
    assert basis.flow_order_seconds(model="A-50-04-F", qty=300, steps=6) == pytest.approx(305 * takt)

    # 天数必须按这条线自己声明的班时折算：一天 11 小时做 300 台就是 1 天多，
    # 按 24 小时会报成 0.46 天 —— 交期宽裕一倍是假的。
    estimate = basis.order_flow_estimate(model="A-50-04-F", qty=300, steps=6)
    assert estimate["hours_per_day"] == 11.0
    assert estimate["estimated_days"] == pytest.approx(305 * takt / 3600.0 / 11.0, abs=0.01)
    # 没有归属线的机种不给产能量口径
    assert basis.flow_order_seconds(model="A-99-XX", qty=300, steps=6) is None


def test_line_and_station_capacity_conflict_is_named():
    basis = _basis()
    steps = [
        {"model": "A-50-04-F", "op_name": "车架焊接", "station": "ST-HJ-01", "work_center": None},
        {"model": "A-50-04-F", "op_name": "底架焊接", "station": "ST-HJ-01", "work_center": None},
        {"model": "A-50-04-F", "op_name": "跑步机总装", "station": "ST-ZL-01", "work_center": None},
    ]
    findings = capacity_conflicts(basis, steps, {"A-50-04-F": 1180})
    assert len(findings) == 1
    row = findings[0]
    assert row["model"] == "A-50-04-F"
    assert row["bottleneck_pieces_per_hour"] == pytest.approx(4.0)
    assert row["line_pieces_per_hour"] == pytest.approx(300 / 11, abs=1e-3)
    assert row["ratio"] > 2
    # 两个日期都要摆出来，谁拍板都能看见差多少；口径是同一条线的 11 小时班时
    assert row["hours_per_day"] == 11.0
    assert row["days_by_line"] == pytest.approx(1180 / (300 / 11.0) / 11.0, abs=0.05)
    assert row["days_by_bottleneck"] == pytest.approx(1180 / 4.0 / 11.0, abs=0.05)
    assert row["days_by_line"] < row["days_by_bottleneck"]
    codes = [s["station"] for s in row["bottleneck_stations"]]
    assert len(codes) == len(set(codes)), "同一个工位重复点名不像结论"


def test_agreeing_capacities_are_not_noise():
    basis = TimeBasis(
        station_rates={"ST-ZL-01": 30.0},
        lines=[{"line_code": "L1", "hours_per_day": 11, "units_per_day": 330, "crew_size": 10,
                "default_model": "M1", "can_make_models": ["M1"], "cannot_make_models": []}],
    )
    steps = [{"model": "M1", "op_name": "总装", "station": "ST-ZL-01", "work_center": None}]
    assert capacity_conflicts(basis, steps, {"M1": 500}) == []
