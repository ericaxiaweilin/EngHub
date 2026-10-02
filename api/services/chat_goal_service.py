"""Durable thread-level Goal service.

Goal is deliberately separate from follow-up tasks: it is the objective that
keeps a chat focused across turns, while follow-up tasks are business actions
that may be created as a consequence of the conversation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ChatGoal, ChatGoalMetric, ChatSession, generate_uuid


GOAL_STATUSES = {"active", "paused", "completed", "blocked"}
MAX_OBJECTIVE_CHARS = 4000

# These are the stable business facts exposed by the PMC control tower.  A
# Goal can observe any of them, and a user may later add a target through the
# metrics endpoint without coupling the Goal model to a particular KPI.
GOAL_METRIC_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "orders": {"label": "排程订单数", "field": "scheduled_order_count", "unit": "单", "default_comparator": "gte"},
    "materials": {"label": "受控物料数", "field": "controlled_material_count", "unit": "种", "default_comparator": "gte"},
    "shortage": {"label": "Shortage缺口", "field": "total_shortage_qty", "unit": "件", "default_comparator": "lte"},
    "inventory": {"label": "呆滞库存SKU", "field": "stagnant_count", "unit": "SKU", "default_comparator": "lte"},
    "otd": {"label": "OTD", "field": "otd_pct", "unit": "%", "default_comparator": "gte"},
    "capacity": {"label": "产能瓶颈工位", "field": "bottleneck_count", "unit": "个", "default_comparator": "lte"},
    "rush": {"label": "已执行插单", "field": "executed_count", "unit": "单", "default_comparator": "gte"},
    "engineering_change": {"label": "EC/BOM变更", "field": "ecn_count", "unit": "单", "default_comparator": "gte"},
    "supplier_delay": {"label": "供应商逾期PO", "field": "overdue_count", "unit": "单", "default_comparator": "lte"},
}
GOAL_METRIC_CODES = tuple(GOAL_METRIC_DEFINITIONS)
_ALL_PMC_KEYWORDS = ("pmc", "数字员工", "订单评审", "订单、物料", "生产控制塔")
_METRIC_KEYWORDS = {
    "orders": ("订单", "排程", "交期"),
    "materials": ("物料", "bom", "齐套"),
    "shortage": ("shortage", "缺料", "缺口"),
    "inventory": ("库存", "呆滞"),
    "otd": ("otd", "交付", "准时"),
    "capacity": ("产能", "瓶颈", "平衡"),
    "rush": ("插单", "急单", "紧急"),
    "engineering_change": ("ec", "ecn", "bom change", "工程变更", "变更"),
    "supplier_delay": ("supplier", "供应商", "延期", "延迟"),
}


class ChatGoalAccessError(PermissionError):
    """Goal does not exist or is outside the current thread scope."""


def normalize_objective(objective: str) -> str:
    value = str(objective or "").strip()
    if not value:
        raise ValueError("目标不能为空")
    if len(value) > MAX_OBJECTIVE_CHARS:
        raise ValueError(f"目标不能超过 {MAX_OBJECTIVE_CHARS} 个字符")
    return value


def normalize_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    value = str(status).strip().lower()
    value = {"complete": "completed", "done": "completed", "resume": "active"}.get(value, value)
    if value not in GOAL_STATUSES:
        raise ValueError(f"不支持的 Goal 状态：{status}")
    return value


def _user_id(user: Any) -> str:
    return str(getattr(user, "id", "")) or getattr(user, "username", "") or "anonymous"


def goal_to_dict(goal: Optional[ChatGoal]) -> Optional[Dict[str, Any]]:
    if goal is None:
        return None
    payload = {
        "goal_id": goal.id,
        "thread_id": goal.session_id,
        "session_id": goal.session_id,
        "factory_id": goal.factory_id,
        "user_id": goal.user_id,
        "objective": goal.objective,
        "status": goal.status,
        "token_budget": goal.token_budget,
        "tokens_used": goal.tokens_used or 0,
        "time_used_seconds": goal.time_used_seconds or 0,
        "progress_pct": goal.progress_pct or 0,
        "summary": goal.summary,
        "blocked_reason": goal.blocked_reason,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
        "cleared_at": goal.cleared_at.isoformat() if goal.cleared_at else None,
    }
    # Keep the existing EngHub snake_case contract while accepting the
    # official App Server camelCase vocabulary from Codex clients.
    payload.update({
        "goalId": goal.id,
        "threadId": goal.session_id,
        "tokenBudget": goal.token_budget,
        "tokensUsed": goal.tokens_used or 0,
        "timeUsedSeconds": goal.time_used_seconds or 0,
        "progressPct": goal.progress_pct or 0,
        "blockedReason": goal.blocked_reason,
    })
    return payload


def metric_to_dict(metric: ChatGoalMetric) -> Dict[str, Any]:
    """Serialize a Goal metric without leaking Decimal values to JSON."""
    def number(value: Any) -> Optional[float]:
        if value is None:
            return None
        return float(value) if isinstance(value, (Decimal, int, float)) else float(value)

    return {
        "metric_id": metric.id,
        "goal_id": metric.goal_id,
        "metric_code": metric.metric_code,
        "label": metric.label,
        "comparator": metric.comparator,
        "target_value": number(metric.target_value),
        "unit": metric.unit,
        "current_value": number(metric.current_value),
        "status": metric.status,
        "source_tool": metric.source_tool,
        "evidence": metric.evidence or {},
        "last_checked_at": metric.last_checked_at.isoformat() if metric.last_checked_at else None,
        "created_at": metric.created_at.isoformat() if metric.created_at else None,
        "updated_at": metric.updated_at.isoformat() if metric.updated_at else None,
    }


async def get_goal_metrics(db: AsyncSession, goal_id: str) -> List[ChatGoalMetric]:
    result = await db.execute(
        select(ChatGoalMetric)
        .where(ChatGoalMetric.goal_id == goal_id)
        .order_by(ChatGoalMetric.metric_code.asc())
    )
    return list(result.scalars().all())


def infer_metric_codes(objective: str) -> List[str]:
    """Map a human Goal to existing PMC facts, preserving definition order."""
    text = str(objective or "").strip().lower()
    if any(keyword in text for keyword in _ALL_PMC_KEYWORDS):
        return list(GOAL_METRIC_CODES)
    return [
        code for code in GOAL_METRIC_CODES
        if any(keyword in text for keyword in _METRIC_KEYWORDS[code])
    ]


def _metric_config(code: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if code not in GOAL_METRIC_DEFINITIONS:
        raise ValueError(f"不支持的 Goal 指标：{code}")
    definition = GOAL_METRIC_DEFINITIONS[code]
    config = config or {}
    comparator = str(config.get("comparator") or definition["default_comparator"]).lower()
    if comparator not in {"gte", "lte", "eq"}:
        raise ValueError(f"不支持的指标比较方式：{comparator}")
    target = config.get("target_value")
    if target is not None:
        try:
            target = float(target)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"指标目标值必须是数字：{code}") from exc
    return {
        "metric_code": code,
        "label": str(config.get("label") or definition["label"]),
        "comparator": comparator,
        "target_value": target,
        "unit": str(config.get("unit") or definition["unit"]),
    }


async def ensure_goal_metrics(
    db: AsyncSession,
    goal: ChatGoal,
    metric_codes: Iterable[str],
) -> List[ChatGoalMetric]:
    """Create inferred metrics while preserving user-configured targets."""
    codes = list(dict.fromkeys(str(code).strip() for code in metric_codes if str(code).strip()))
    for code in codes:
        config = _metric_config(code)
        result = await db.execute(
            select(ChatGoalMetric).where(
                ChatGoalMetric.goal_id == goal.id,
                ChatGoalMetric.metric_code == code,
            )
        )
        metric = result.scalar_one_or_none()
        if metric is None:
            metric = ChatGoalMetric(id=generate_uuid(), goal_id=goal.id, **config)
            db.add(metric)
        else:
            metric.label = config["label"]
            metric.unit = config["unit"]
            metric.updated_at = datetime.utcnow()
    await db.flush()
    return await get_goal_metrics(db, goal.id)


async def configure_goal_metrics(
    db: AsyncSession,
    goal: ChatGoal,
    configs: Iterable[Any],
    *,
    replace: bool = False,
) -> List[ChatGoalMetric]:
    """Upsert metric definitions and optionally remove omitted ones."""
    normalized: Dict[str, Dict[str, Any]] = {}
    for item in configs:
        if isinstance(item, str):
            code, payload = item, {}
        else:
            payload = dict(item or {})
            code = str(payload.get("metric_code") or payload.get("code") or "")
        code = code.strip()
        if not code:
            continue
        normalized[code] = _metric_config(code, payload)

    if replace:
        existing = await get_goal_metrics(db, goal.id)
        for metric in existing:
            if metric.metric_code not in normalized:
                await db.delete(metric)

    for code, config in normalized.items():
        result = await db.execute(
            select(ChatGoalMetric).where(
                ChatGoalMetric.goal_id == goal.id,
                ChatGoalMetric.metric_code == code,
            )
        )
        metric = result.scalar_one_or_none()
        if metric is None:
            metric = ChatGoalMetric(id=generate_uuid(), goal_id=goal.id, **config)
            db.add(metric)
        else:
            for key, value in config.items():
                setattr(metric, key, value)
            metric.updated_at = datetime.utcnow()
    await db.flush()
    return await get_goal_metrics(db, goal.id)


def _metric_value(metric_code: str, fact: Dict[str, Any]) -> Optional[float]:
    if metric_code == "capacity":
        return float(sum(
            1 for item in (fact.get("bottlenecks") or [])
            if str(item.get("status") or "").lower() == "overloaded"
        ))
    definition = GOAL_METRIC_DEFINITIONS[metric_code]
    value = fact.get(definition["field"])
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_metric(current: Optional[float], target: Optional[float], comparator: str) -> Optional[float]:
    if current is None or target is None:
        return None
    if comparator == "gte":
        return 100.0 if target <= 0 and current >= target else max(0.0, min(100.0, current / target * 100))
    if comparator == "lte":
        if target == 0:
            return 100.0 if current == 0 else 0.0
        return 100.0 if current <= target else max(0.0, min(100.0, target / current * 100))
    return 100.0 if current == target else 0.0


async def refresh_goal_metrics(db: AsyncSession, goal: ChatGoal) -> List[ChatGoalMetric]:
    """Refresh a Goal from the canonical, read-only PMC control tower."""
    metrics = await get_goal_metrics(db, goal.id)
    if not metrics:
        return []
    from api.services.pmc_control_tower_service import PmcControlTowerService

    collected = await PmcControlTowerService(db).collect(goal.factory_id, scope="all")
    facts = collected.get("facts") or {}
    quality = {
        item.get("key"): item for item in (collected.get("data_quality") or [])
        if item.get("key")
    }
    scores: List[float] = []
    blocked: List[str] = []
    checked_at = datetime.utcnow()
    for metric in metrics:
        fact = facts.get(metric.metric_code) or {}
        current = _metric_value(metric.metric_code, fact)
        score = score_metric(current, float(metric.target_value) if metric.target_value is not None else None, metric.comparator)
        data_status = fact.get("data_status") or quality.get(metric.metric_code, {}).get("status") or "unknown"
        if data_status == "missing" or current is None:
            status = "unknown"
        elif score is None:
            status = "observed"
        elif score >= 100:
            status = "achieved"
            scores.append(score)
        elif score >= 80:
            status = "on_track"
            scores.append(score)
        else:
            status = "blocked"
            scores.append(score)
            blocked.append(metric.label)
        metric.current_value = current
        metric.status = status
        metric.source_tool = "query_pmc_control_tower"
        metric.evidence = {
            "data_status": data_status,
            "source": fact.get("source"),
            "missing_sources": fact.get("missing_sources") or quality.get(metric.metric_code, {}).get("missing_sources", []),
            "data_note": fact.get("data_note") or quality.get(metric.metric_code, {}).get("note", ""),
            "value_field": GOAL_METRIC_DEFINITIONS[metric.metric_code]["field"],
            "current_value": current,
            "score_pct": score,
            "actions": [action for action in (collected.get("actions") or []) if metric.metric_code in action.lower()],
        }
        metric.last_checked_at = checked_at
        metric.updated_at = checked_at

    if scores:
        goal.progress_pct = max(0, min(100, int(round(sum(scores) / len(scores)))))
    if blocked and goal.status == "active":
        goal.status = "blocked"
        goal.blocked_reason = "；".join(blocked[:3])
    goal.summary = f"已检查 {len(metrics)} 项PMC业务指标" + (f"，{len(blocked)} 项未达标" if blocked else "，当前无已配置目标未达标项")
    goal.updated_at = checked_at
    await db.flush()
    return await get_goal_metrics(db, goal.id)


async def get_goal_for_user(
    db: AsyncSession,
    session_id: str,
    *,
    user: Any,
    factory_id: str,
) -> Optional[ChatGoal]:
    result = await db.execute(
        select(ChatGoal).where(
            ChatGoal.session_id == session_id,
            ChatGoal.user_id == _user_id(user),
            ChatGoal.factory_id == factory_id,
        )
    )
    return result.scalar_one_or_none()


async def require_goal_for_user(
    db: AsyncSession,
    session_id: str,
    *,
    user: Any,
    factory_id: str,
) -> ChatGoal:
    goal = await get_goal_for_user(db, session_id, user=user, factory_id=factory_id)
    if goal is None:
        raise ChatGoalAccessError("该线程没有可访问的 Goal")
    return goal


async def set_goal(
    db: AsyncSession,
    session: ChatSession,
    *,
    user: Any,
    factory_id: str,
    objective: Optional[str] = None,
    status: Optional[str] = None,
    token_budget: Optional[int] = None,
) -> ChatGoal:
    """Create or update the single current Goal owned by a thread."""
    if session.user_id != _user_id(user) or session.factory_id != factory_id:
        raise ChatGoalAccessError("无权访问该线程")
    normalized_status = normalize_status(status)
    goal = await get_goal_for_user(db, session.id, user=user, factory_id=factory_id)
    if goal is None:
        if objective is None:
            raise ValueError("首次设置 Goal 必须提供目标")
        if token_budget is not None and token_budget < 0:
            raise ValueError("token_budget 不能为负数")
        goal = ChatGoal(
            id=generate_uuid(),
            session_id=session.id,
            factory_id=factory_id,
            user_id=_user_id(user),
            objective=normalize_objective(objective),
            status=normalized_status or "active",
            token_budget=token_budget,
            progress_pct=100 if normalized_status == "completed" else 0,
        )
        db.add(goal)
    else:
        if objective is not None:
            new_objective = normalize_objective(objective)
            if new_objective != goal.objective:
                goal.objective = new_objective
                goal.tokens_used = 0
                goal.time_used_seconds = 0
                goal.progress_pct = 0
                goal.summary = None
                goal.blocked_reason = None
        if normalized_status is not None:
            goal.status = normalized_status
        if token_budget is not None:
            if token_budget < 0:
                raise ValueError("token_budget 不能为负数")
            goal.token_budget = token_budget
        goal.cleared_at = None
        goal.updated_at = datetime.utcnow()
    await db.flush()
    return goal


async def update_goal(
    db: AsyncSession,
    goal: ChatGoal,
    *,
    status: Optional[str] = None,
    token_budget: Optional[int] = None,
    progress_pct: Optional[int] = None,
    summary: Optional[str] = None,
    blocked_reason: Optional[str] = None,
) -> ChatGoal:
    normalized_status = normalize_status(status)
    if normalized_status is not None:
        goal.status = normalized_status
    if token_budget is not None:
        if token_budget < 0:
            raise ValueError("token_budget 不能为负数")
        goal.token_budget = token_budget
    if progress_pct is not None:
        goal.progress_pct = max(0, min(100, int(progress_pct)))
    if summary is not None:
        goal.summary = str(summary).strip() or None
    if blocked_reason is not None:
        goal.blocked_reason = str(blocked_reason).strip() or None
    if goal.status == "completed":
        goal.progress_pct = 100
        goal.blocked_reason = None
    goal.updated_at = datetime.utcnow()
    await db.flush()
    return goal


async def record_goal_usage(
    db: AsyncSession,
    goal: ChatGoal,
    *,
    tokens: int = 0,
    elapsed_seconds: int = 0,
) -> ChatGoal:
    """Accumulate per-turn usage for Codex-compatible Goal accounting."""
    goal.tokens_used = max(0, int(goal.tokens_used or 0) + max(0, int(tokens or 0)))
    goal.time_used_seconds = max(
        0, int(goal.time_used_seconds or 0) + max(0, int(elapsed_seconds or 0)),
    )
    goal.updated_at = datetime.utcnow()
    await db.flush()
    return goal


async def clear_goal(db: AsyncSession, goal: ChatGoal) -> None:
    await db.delete(goal)
    await db.flush()
