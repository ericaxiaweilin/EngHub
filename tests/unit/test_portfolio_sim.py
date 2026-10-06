"""组合推演的算法口径：算不出货期就给 0 分而不是编一个日期，工作日要跳休班日。

这个模块的分数会被用来排资源，所以断言打在两件事上：
① 没有依据时不许出日期（no_time_basis → delivery=0）；
② 需求/人力/评分的数学可复核（不依赖库）。
"""

import pytest
from datetime import date

pytestmark = [pytest.mark.unit]

from api.services import portfolio_sim as ps


def test_working_days_are_needed_days_not_calendar_days():
    assert ps.working_days_needed(300, 300) == 1.0
    assert ps.working_days_needed(80, 300) == 0.27
    assert ps.working_days_needed(80, 0) == 0.0      # 没有线产能就不算天数，不除零蒙一个


def test_add_working_days_skips_non_shift_days():
    """周五之后是周六周日：只按排班的日子往后数，休班日不消耗产能。"""
    start = date(2026, 10, 9)                    # 周五
    assert ps.add_working_days(start, 1, {1, 2, 3, 4, 5}) == date(2026, 10, 12)   # 跳过周末
    assert ps.add_working_days(start, 0.5, {1, 2, 3, 4, 5}) == date(2026, 10, 12)  # 半天也算到下一个班次日
    assert ps.add_working_days(start, 0, {1, 2, 3, 4, 5, 6}) == start


def test_late_orders_lose_delivery_points_and_no_basis_is_zero():
    assert ps.score_delivery(0, has_basis=True) == 100.0
    assert ps.score_delivery(3, has_basis=True) == 82.0
    assert ps.score_delivery(30, has_basis=True) == 0.0
    assert ps.score_delivery(0, has_basis=False) == 0.0     # 算不出来不是"准点"


def test_labor_score_penalizes_both_idle_and_overload():
    assert ps.score_labor(0.88) == 100.0        # 健康区间
    assert ps.score_labor(0.20) < 40.0          # 线班组八成时间在等活
    assert ps.score_labor(1.4) < 40.0           # 长期超载
    assert ps.score_labor(None) == 0.0          # 没有依据不给分


def test_kit_shortage_with_no_arrival_evidence_is_hard_blocked():
    assert ps.score_kit(0, 16, blocked_forever=False) == 100.0
    assert ps.score_kit(15, 16, blocked_forever=True) == 5.0    # 缺料且没有任何到货期依据
    assert ps.score_kit(0, 0, blocked_forever=False) == 0.0     # 没有物料行 = 无从判断


def test_kit_requirement_multiplies_bom_by_units():
    bom = [{"material_code": "A", "qty_per_unit": 2}, {"material_code": "B", "qty_per_unit": 0.5}]
    assert ps.kit_requirement(bom, 300) == {"A": 600.0, "B": 150.0}


def test_levers_rank_the_binding_constraint_by_possible_lift():
    results = [
        {"binding_constraint": "算不出货期", "score": 8.8, "model_code": "M-A"},
        {"binding_constraint": "算不出货期", "score": 9.2, "model_code": "M-B"},
        {"binding_constraint": "缺料", "score": 55.0, "model_code": "M-C"},
    ]
    out = ps.levers(results)
    assert out[0]["constraint"] == "算不出货期"           # 数据缺口比单张缺料的单更值得先补
    assert out[0]["orders"] == 2 and out[0]["potential_lift"] > out[1]["potential_lift"]


class _Res:
    def __init__(self, first=None, all_rows=None):
        self._first, self._all = first, all_rows

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all or []

    def scalar(self):
        return 100


class _FakeDB:
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM bom_items b" in sql and "GROUP BY b.product_id" in sql:
            return _Res(all_rows=[{"model_code": "M-1", "bom_lines": 16, "materials": 16,
                                   "bom_levels": 1, "lines_with_qty": 16}])
        if "MAX(planned_qty)" in sql:
            return _Res(first={"q": 80})
        if "FROM bom_items WHERE" in sql:
            return _Res(all_rows=[{"material_code": f"P{i}", "qty_per_unit": 1, "unit": "pcs",
                                   "level": 1} for i in range(16)])
        if "FROM inventory i" in sql:
            return _Res(all_rows=[])
        if "FROM materials m" in sql:
            return _Res(all_rows=[{"code": f"P{i}", "lead_time_days": "10",
                                   "default_supplier": None} for i in range(16)])
        if "FROM line_profiles" in sql:
            return _Res(all_rows=[{"line_code": "LINE-1", "line_group": "G1", "hours_per_day": 11.0,
                                   "units_per_day": 300.0, "group_units_per_day": 300.0,
                                   "crew_size": 300, "parallel_lines": 1,
                                   "can_models": "['M-1']", "default_model": "M-1"}])
        if "FROM aps_work_calendars" in sql:
            return _Res(all_rows=[{"weekday": wd, "start_time": "08:00", "end_time": "20:00"}
                                   for wd in range(0, 6)])   # 周一~周六排班，周日休
        if "FROM equipment" in sql:
            return _Res(all_rows=[{"station_id": "s", "running": 4, "down": 1, "total": 5}])
        if "FROM hr_employees" in sql:
            return _Res(first={"people": 1000})
        return _Res(all_rows=[])


@pytest.mark.asyncio
async def test_simulate_uses_line_capacity_and_attendance(monkeypatch):
    async def fake_route(db, fid, model):
        return [{"operation_name": "装配", "work_center": "ST-1", "standard_hours": 0}]

    monkeypatch.setattr(ps, "route_ops_for_product", fake_route)
    out = await ps.simulate(_FakeDB(), "FAC_MECH_001", n=1, units_default=300,
                            demand_date=date(2026, 10, 6), attendance_factor=0.7)
    order = out["orders"][0]
    assert out["portfolio_score"] > 0
    assert order["units"] == 80                      # 批量取历史最大工单量，不是默认值
    assert order["line"] == "LINE-1"
    assert order["time_basis"] == "line_profiles"
    assert order["crew_present_after_attendance"] == 210.0   # 300 × 0.7：人到不齐就不按满编算
    assert order["estimated_finish"] is not None
    assert order["score_parts"]["delivery"] == 100.0


@pytest.mark.asyncio
async def test_simulate_refuses_a_date_without_any_basis(monkeypatch):
    """路线没有工时、也没有可做的线：不许出一个日期，交付分就是 0。"""
    async def fake_route(db, fid, model):
        return [{"operation_name": "装配", "work_center": "ST-1", "standard_hours": 0}]

    monkeypatch.setattr(ps, "route_ops_for_product", fake_route)
    out = await ps.simulate(_FakeDB(), "FAC_MECH_001", n=1, units_default=300,
                            demand_date=date(2026, 10, 6),
                            models=[{"model_code": "NO-LINE-MODEL", "units": 100,
                                     "due_date": date(2026, 11, 1)}])
    order = out["orders"][0]
    assert order["time_basis"] == "no_time_basis"
    assert order["estimated_finish"] is None
    assert order["score_parts"]["delivery"] == 0.0
    assert "算不出货期" in order["binding_constraint"]


@pytest.mark.asyncio
async def test_ie_hours_assumption_unlocks_a_date_and_is_labeled(monkeypatch):
    """补进来的工时要标成 assumed_ie_hours，不能伪装成路线声明的工时。"""
    async def fake_route(db, fid, model):
        return [{"operation_name": "装配", "work_center": "ST-1", "standard_hours": 0}]

    monkeypatch.setattr(ps, "route_ops_for_product", fake_route)
    out = await ps.simulate(_FakeDB(), "FAC_MECH_001", n=1, units_default=300,
                            demand_date=date(2026, 10, 6),
                            models=[{"model_code": "NO-LINE-MODEL", "units": 100,
                                     "due_date": date(2026, 11, 1)}],
                            ie_hours_per_unit=0.037)
    order = out["orders"][0]
    assert order["time_basis"] == "assumed_ie_hours"
    assert order["assumed_hours_per_step"] == 0.037
    assert order["estimated_finish"] is not None
