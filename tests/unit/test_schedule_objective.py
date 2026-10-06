"""目标函数要真的改变谁先占产能 —— 目标不同、答案必须不同。

用户 10-06 的口径：核心是基于订单/物料/人力/工艺多方面推演，不是"缺料就卡住不排产"；
而且"按交期重拍和等料理论上不应该数据一样"。所以这里断言的是：
① 换 objective 会换出不同的顺序；② 缺料单在任何目标下都不占工位时隙；
③ 数不到在岗人数的单，人力项就是 0（不假设每台机器都站着人）。
"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services.schedule_objective import (
    BLOCKED_OFFSET,
    normalize_objective,
    order_rank,
)


def _orders():
    """一张"吃人多但交期松"的单 vs 一张"人少但明天就到期"的单。"""
    return [
        {"order_id": "LABOR_HEAVY", "blocked": False, "person_hours": 900.0,
         "work_hours": 30.0, "hours_to_due": 24 * 25},
        {"order_id": "DUE_TOMORROW", "blocked": False, "person_hours": 30.0,
         "work_hours": 6.0, "hours_to_due": 24},
        {"order_id": "SHORTAGE", "blocked": True, "person_hours": 600.0,
         "work_hours": 20.0, "hours_to_due": 24 * 3},
    ]


def test_objective_aliases_map_onto_one_vocabulary():
    assert normalize_objective("delivery") == "delivery_first"
    assert normalize_objective("efficiency") == "labor_first"
    assert normalize_objective("cost") == "total_cost"
    assert normalize_objective(None) in ("labor_first", "delivery_first", "total_cost", "balanced")
    assert normalize_objective("胡说八道") in ("labor_first", "delivery_first", "total_cost", "balanced")


def test_changing_objective_changes_who_goes_first():
    """这是用户直接要的那件事：两个目标跑出来一模一样就是没接线。"""
    labor = order_rank(_orders(), "labor_first")["rank"]
    delivery = order_rank(_orders(), "delivery_first")["rank"]

    def first(rank):
        return min(rank, key=lambda k: rank[k])

    assert first(labor) == "LABOR_HEAVY"
    assert first(delivery) == "DUE_TOMORROW"


def test_blocked_order_never_beats_a_startable_one_under_any_objective():
    for objective in ("labor_first", "delivery_first", "total_cost", "balanced"):
        rank = order_rank(_orders(), objective)["rank"]
        assert rank["SHORTAGE"] > max(rank["LABOR_HEAVY"], rank["DUE_TOMORROW"])
        assert rank["SHORTAGE"] >= BLOCKED_OFFSET - 2.0


def test_blocked_orders_still_compare_among_themselves():
    orders = _orders() + [
        {"order_id": "SHORTAGE_LATE", "blocked": True, "person_hours": 50.0,
         "work_hours": 4.0, "hours_to_due": 24 * 20},
    ]
    rank = order_rank(orders, "labor_first")["rank"]
    assert rank["SHORTAGE"] < rank["SHORTAGE_LATE"]


def test_no_crew_evidence_does_not_fabricate_labor():
    """工位对不上 HR 在岗人数 → 人·时为 0，人力项整个塌掉，由交期项接管，并且如实报数。"""
    orders = [
        {"order_id": "A", "blocked": False, "person_hours": 0.0, "work_hours": 8.0,
         "hours_to_due": 24 * 10},
        {"order_id": "B", "blocked": False, "person_hours": 0.0, "work_hours": 8.0,
         "hours_to_due": 24},
    ]
    out = order_rank(orders, "labor_first")
    assert out["orders_with_person_hours"] == 0
    assert out["rank"]["B"] < out["rank"]["A"]


def test_empty_input_is_not_an_error_but_gives_no_ranking():
    out = order_rank([], "labor_first")
    assert out["rank"] == {}
    assert out["blocked_last"] == 0


def test_ranking_is_deterministic_for_equal_orders():
    orders = [
        {"order_id": f"WO-{i}", "blocked": False, "person_hours": 100.0,
         "work_hours": 10.0, "hours_to_due": 24 * 5}
        for i in range(5)
    ]
    first = order_rank(orders, "balanced")["rank"]
    second = order_rank(list(reversed(orders)), "balanced")["rank"]
    assert first == second
