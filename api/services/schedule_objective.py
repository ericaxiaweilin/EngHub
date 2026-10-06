"""排产目标函数：objective 必须真的改变"谁先占产能"，不能只改说明文字。

为什么要单独建这个模块：`optimize_for` 以前只决定排程器内部的 5 个写死分支和
一句 rule_explanation 文案，cost_model 的四种目标（人力/交期/总成本/均衡）传进来
会被当成未知值走 delivery 分支 —— 换个目标，账面数字一模一样。目标不同答案就不同，
这是用户给的口径，不是我们的偏好。

规则只有三条，全部可核对：
① **缺料的单一律靠后**：料不齐在物理上就开不了工，让它占着工位时隙，
   能开工的单反而排不进去（这是"账面排满、车间开不了工"的根因）；
② 权重只取 `cost_model.OBJECTIVES` 里已有的 labor / delivery 两项 —— 设备和物料
   是"线/批"层面的成本，按单排不出来，硬编一个每单设备成本就是造假；
③ 归一化用当轮订单集合的极值，所以 rank 只有**可比性**、没有绝对含义，
   排名解释里必须写清这一点。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.services.cost_model import DEFAULT_OBJECTIVE, OBJECTIVES

# 目标名归一：排程 API 历史上的几个别名指同一类取向，不另立第二套词汇。
_ALIASES = {
    "delivery": "delivery_first",
    "critical_ratio": "delivery_first",
    "priority": "delivery_first",
    "efficiency": "labor_first",
    "cost": "total_cost",
}

# 缺料单整体后移的偏移量：combined 的取值区间是 [-2, 2]，+1000 保证任何目标下
# 能开工的单都排在开不了工的单前面，同时缺料单之间仍按同一目标比。
BLOCKED_OFFSET = 1000.0

HORIZON_HOURS = 24.0 * 30  # 松弛度归一化用的窗口，与排程默认 horizon 一致


def normalize_objective(value: Optional[str]) -> str:
    key = str(value or "").strip()
    key = _ALIASES.get(key, key)
    return key if key in OBJECTIVES else DEFAULT_OBJECTIVE


def _urgency(work_hours: float, hours_to_due: float, horizon_hours: float) -> float:
    """交期紧迫度：松弛 = 距交期小时 − 做完要的小时，越紧越接近 1。"""
    slack = float(hours_to_due or 0) - float(work_hours or 0)
    if slack <= 0:
        return 1.0
    return max(0.0, 1.0 - slack / max(float(horizon_hours), 1.0))


def order_rank(
    orders: List[Dict[str, Any]],
    objective: Optional[str] = None,
    *,
    horizon_hours: float = HORIZON_HOURS,
) -> Dict[str, Any]:
    """给每张单一个排序值（越小越先占产能），并说明这次是按什么排的。

    orders 每项：order_id、blocked、person_hours、work_hours、hours_to_due。
    """
    name = normalize_objective(objective)
    weights = OBJECTIVES[name]
    if not orders:
        return {
            "objective": name,
            "objective_label": weights["label"],
            "weights": {"labor": weights["labor"], "delivery": weights["delivery"]},
            "rank": {},
            "blocked_last": 0,
            "orders_with_person_hours": 0,
        }

    labor_max = max(0.0, *[float(o.get("person_hours") or 0) for o in orders])
    ranked: Dict[str, float] = {}
    for o in orders:
        person_hours = float(o.get("person_hours") or 0)
        work_hours = float(o.get("work_hours") or 0)
        labor = person_hours / labor_max if labor_max else 0.0
        delivery = _urgency(work_hours, float(o.get("hours_to_due") or 0), horizon_hours)
        combined = weights["labor"] * labor + weights["delivery"] * delivery
        rank = -combined
        if o.get("blocked"):
            rank += BLOCKED_OFFSET
        ranked[str(o["order_id"])] = round(rank, 6)

    return {
        "objective": name,
        "objective_label": weights["label"],
        "weights": {"labor": weights["labor"], "delivery": weights["delivery"]},
        "rank": ranked,
        "blocked_last": sum(1 for o in orders if o.get("blocked")),
        "orders_with_person_hours": sum(
            1 for o in orders if float(o.get("person_hours") or 0) > 0
        ),
        "labor_max_person_hours": round(labor_max, 2),
        "note": (
            "排序值只有可比性、没有绝对含义：人力项按本轮订单的最大人·时归一，"
            "交期项按 30 天窗口归一；缺料单一律后移，因为料不齐物理上开不了工。"
        ),
    }
