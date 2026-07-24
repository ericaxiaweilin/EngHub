"""
预警情报审查引擎（017）

核心职责：
- review_alert: 接收预警上下文，调 LLM 做初步审查，存储结构化结果
- batch_review_pending: 批量审查待处理预警（定时巡检用）
- acknowledge_review: 人工确认/驳回审查建议
- get_pending_alerts_summary: 汇总当前待处理预警（供 chatbot 主动汇报）
- patrol: 主动巡检（工单超时/安灯未响应）→ 生成预警 → 触发审查
- validate_alert_data: 预警数据边界校验（防低级失误）

设计原则：
- AI 审查+建议，不自动执行写操作
- 异步执行，不阻塞预警创建主流程
- 审查结果结构化存储，可追溯、可展示
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AlertIntelligenceReview, DefectRecord,
    Equipment, WorkOrder,
)
from core.andon.models import AndonTicket

# LLM 配置（复用 chat_routes 的环境变量）
GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://host.docker.internal:14040").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))

# 预警来源标签
SOURCE_LABELS = {
    "andon": "安灯工单",
    "defect": "质量缺陷",
    "equipment": "设备故障",
    "wo_timeout": "工单超时",
    "inventory": "库存预警",
}

# AI 审查 Prompt 模板
REVIEW_PROMPT_TEMPLATE = """你是 EngHub MES 制造执行系统的智能预警审查员。以下是一条被动预警，请做初步审查。

【预警来源】{source_label}
【预警内容】
{context}

请严格按以下 JSON 格式输出（不要输出其他内容）：
{{
  "severity": "critical 或 high 或 medium 或 low",
  "root_causes": ["根因假设1", "根因假设2"],
  "actions": ["建议处置措施1", "建议处置措施2", "建议处置措施3"],
  "dispatch_to": "推荐分派对象（工序组/角色/岗位）"
}}

审查原则：
- severity 判定：影响产线停线=critical，影响品质/交期=high，局部影响=medium，信息性=low
- root_causes：基于预警内容做合理推断，1-3条
- actions：具体可执行的处置建议（如"通知XX工序组检查"、"暂停相关工单"等）
- dispatch_to：推荐由谁处理（如"设备维修组"、"品质经理"、"慢走丝工序组"等）
"""


# ==================== 边界校验（防低级失误） ====================

VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
VALID_SEVERITIES = {"critical", "major", "minor"}
VALID_EQUIPMENT_TRANSITIONS = {
    "running": {"idle", "fault", "maintenance"},
    "available": {"running", "maintenance", "idle"},
    "idle": {"running", "available", "maintenance", "fault"},
    "fault": {"maintenance", "available"},
    "maintenance": {"available", "idle"},
}


def validate_andon_data(
    timeout_no_response: int = 15,
    timeout_resolve: int = 30,
    priority: Optional[str] = None,
) -> Optional[str]:
    """校验 Andon 工单数据边界，返回错误信息或 None（通过）"""
    if timeout_no_response < 5 or timeout_no_response > 60:
        return f"无响应超时须在 5-60 分钟之间，当前值 {timeout_no_response}"
    if timeout_resolve < 10 or timeout_resolve > 120:
        return f"解决超时须在 10-120 分钟之间，当前值 {timeout_resolve}"
    if timeout_resolve <= timeout_no_response:
        return f"解决超时({timeout_resolve}min)须大于无响应超时({timeout_no_response}min)"
    if priority and priority not in VALID_PRIORITIES:
        return f"优先级 '{priority}' 不合法，可选值：{sorted(VALID_PRIORITIES)}"
    return None


def validate_defect_data(quantity: int = 1, severity: str = "minor") -> Optional[str]:
    """校验缺陷记录数据边界"""
    if quantity <= 0:
        return f"缺陷数量须大于 0，当前值 {quantity}"
    if quantity > 10000:
        return f"缺陷数量异常偏大（{quantity}），请确认是否输入错误"
    if severity not in VALID_SEVERITIES:
        return f"严重等级 '{severity}' 不合法，可选值：{sorted(VALID_SEVERITIES)}"
    return None


def validate_work_order_data(planned_qty: int = 1, planned_due: Optional[str] = None) -> Optional[str]:
    """校验工单数据边界"""
    if planned_qty <= 0:
        return f"计划数量须大于 0，当前值 {planned_qty}"
    if planned_qty > 100000:
        return f"计划数量异常偏大（{planned_qty}），请确认"
    if planned_due:
        try:
            due = datetime.strptime(planned_due, "%Y-%m-%d")
            if due < datetime.now() - timedelta(days=1):
                return f"计划完成日期 {planned_due} 已过期，不能创建过去交期的工单"
        except ValueError:
            return f"日期格式错误：{planned_due}，应为 YYYY-MM-DD"
    return None


def validate_equipment_transition(current_status: str, new_status: str) -> Optional[str]:
    """校验设备状态转换合法性"""
    allowed = VALID_EQUIPMENT_TRANSITIONS.get(current_status)
    if allowed is None:
        return f"未知当前状态 '{current_status}'"
    if new_status not in allowed:
        return f"设备状态不能从 '{current_status}' 直接转为 '{new_status}'，允许转为：{sorted(allowed)}"
    return None


# ==================== AI 审查引擎 ====================

async def _call_llm_for_review(context: str, source: str) -> Dict[str, Any]:
    """调用 LLM 做预警审查，返回结构化结果。LLM 不可用时返回规则兜底。"""
    source_label = SOURCE_LABELS.get(source, source)
    prompt = REVIEW_PROMPT_TEMPLATE.format(source_label=source_label, context=context)

    try:
        headers = {"Content-Type": "application/json"}
        if API_KEY:
            headers["Authorization"] = f"Bearer {API_KEY}"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                headers=headers,
            )
        if resp.status_code < 400:
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            # 尝试解析 JSON
            parsed = _extract_json(content)
            if parsed:
                parsed["_raw"] = content
                return parsed
    except Exception:
        pass

    # LLM 不可用时的规则兜底
    return _rule_based_review(context, source)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 回复中提取 JSON 对象"""
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # 尝试提取 ```json ... ``` 块
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, TypeError):
                pass
    # 尝试找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _rule_based_review(context: str, source: str) -> Dict[str, Any]:
    """规则兜底审查（LLM 不可用时）"""
    context_lower = context.lower()
    # 简单规则判定严重度
    if any(kw in context_lower for kw in ["停线", "critical", "紧急", "安全"]):
        severity = "critical"
    elif any(kw in context_lower for kw in ["quality_issue", "故障", "fault", "major"]):
        severity = "high"
    elif any(kw in context_lower for kw in ["超时", "timeout", "延迟"]):
        severity = "medium"
    else:
        severity = "low"

    dispatch_map = {
        "andon": "相关工序组",
        "defect": "品质经理",
        "equipment": "设备维修组",
        "wo_timeout": "生产经理",
        "inventory": "仓储物流组",
    }
    return {
        "severity": severity,
        "root_causes": ["待人工分析（AI 服务暂不可用，已按规则初步分级）"],
        "actions": ["请相关责任人尽快确认并处理", "如影响产线请立即上报"],
        "dispatch_to": dispatch_map.get(source, "生产经理"),
        "_raw": f"[规则兜底] source={source}, severity={severity}",
    }


async def review_alert(
    db: AsyncSession,
    factory_id: str,
    source: str,
    ref_id: str,
    ref_code: str,
    context: str,
) -> AlertIntelligenceReview:
    """核心入口：接收预警上下文 → 调 AI 审查 → 存储结果"""
    ai_result = await _call_llm_for_review(context, source)

    review = AlertIntelligenceReview(
        id=str(uuid.uuid4()),
        factory_id=factory_id,
        alert_source=source,
        alert_ref_id=ref_id,
        alert_ref_code=ref_code,
        alert_summary=context[:2000],  # 截断防溢出
        severity_assessment=ai_result.get("severity", "medium"),
        root_cause_hypothesis=json.dumps(ai_result.get("root_causes", []), ensure_ascii=False),
        recommended_actions=json.dumps(ai_result.get("actions", []), ensure_ascii=False),
        dispatch_recommendation=ai_result.get("dispatch_to", ""),
        raw_ai_response=ai_result.get("_raw", ""),
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


# ==================== 巡检（Patrol） ====================

async def patrol(
    db: AsyncSession,
    factory_id: str,
) -> Dict[str, Any]:
    """主动巡检：扫描工单超时 + 安灯未响应 → 生成预警 → 触发审查"""
    now = datetime.utcnow()
    alerts_found = 0
    reviews_created = 0

    # 1. 工单超时检测：in_progress 且 planned_due 已过期或 < 24h
    deadline_threshold = now + timedelta(hours=24)
    stmt = select(WorkOrder).where(
        WorkOrder.factory_id == factory_id,
        WorkOrder.status.in_(["in_progress", "released"]),
        WorkOrder.wo_type == "operation",
        WorkOrder.planned_due.isnot(None),
        WorkOrder.planned_due <= deadline_threshold,
    )
    overdue_wos = (await db.execute(stmt)).scalars().all()

    for wo in overdue_wos:
        # 检查是否已有未处理的同源审查（去重）
        existing = await db.execute(
            select(AlertIntelligenceReview).where(
                AlertIntelligenceReview.alert_source == "wo_timeout",
                AlertIntelligenceReview.alert_ref_id == wo.id,
                AlertIntelligenceReview.status == "pending",
            )
        )
        if existing.scalar_one_or_none():
            continue

        is_overdue = wo.planned_due < now if wo.planned_due else False
        hours_left = (wo.planned_due - now).total_seconds() / 3600 if wo.planned_due else 0
        context = (
            f"工单超时预警：\n"
            f"- 工单号：{wo.work_order_code}\n"
            f"- 工序：{wo.process_code or '未知'}（工序组：{wo.work_center or '未知'}）\n"
            f"- 状态：{'已超期' if is_overdue else f'距交期仅剩 {hours_left:.1f} 小时'}\n"
            f"- 计划交期：{wo.planned_due.strftime('%Y-%m-%d %H:%M') if wo.planned_due else '未设置'}\n"
            f"- 计划数量：{wo.planned_qty}，已完成：{wo.completed_qty or 0}\n"
            f"- 优先级：{wo.priority}"
        )
        await review_alert(db, factory_id, "wo_timeout", wo.id, wo.work_order_code, context)
        alerts_found += 1
        reviews_created += 1

    # 2. 安灯工单超 30min 未响应
    threshold_30m = now - timedelta(minutes=30)
    stmt = select(AndonTicket).where(
        AndonTicket.factory_id == factory_id,
        AndonTicket.status == "open",
        AndonTicket.created_at <= threshold_30m,
    )
    stale_tickets = (await db.execute(stmt)).scalars().all()

    for ticket in stale_tickets:
        existing = await db.execute(
            select(AlertIntelligenceReview).where(
                AlertIntelligenceReview.alert_source == "andon",
                AlertIntelligenceReview.alert_ref_id == ticket.id,
                AlertIntelligenceReview.status == "pending",
            )
        )
        if existing.scalar_one_or_none():
            continue

        minutes_open = (now - ticket.created_at).total_seconds() / 60
        context = (
            f"安灯工单超时未响应预警：\n"
            f"- 工单号：{ticket.ticket_code}\n"
            f"- 类别：{ticket.category_code}\n"
            f"- 标题：{ticket.title}\n"
            f"- 已开放 {minutes_open:.0f} 分钟无人响应\n"
            f"- 优先级：{ticket.priority}\n"
            f"- 描述：{(ticket.description or '无')[:200]}"
        )
        await review_alert(db, factory_id, "andon", ticket.id, ticket.ticket_code, context)
        alerts_found += 1
        reviews_created += 1

    return {
        "patrol_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "alerts_found": alerts_found,
        "reviews_created": reviews_created,
        "overdue_work_orders": len(overdue_wos),
        "stale_andon_tickets": len(stale_tickets),
    }


# ==================== 查询 / 确认 ====================

async def get_pending_alerts_summary(
    db: AsyncSession,
    factory_id: str,
) -> Dict[str, Any]:
    """汇总当前待处理预警（供 chatbot 主动汇报）"""
    stmt = select(
        AlertIntelligenceReview.alert_source,
        AlertIntelligenceReview.severity_assessment,
        func.count().label("cnt"),
    ).where(
        AlertIntelligenceReview.factory_id == factory_id,
        AlertIntelligenceReview.status == "pending",
    ).group_by(
        AlertIntelligenceReview.alert_source,
        AlertIntelligenceReview.severity_assessment,
    )
    rows = (await db.execute(stmt)).all()

    by_source: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    total = 0
    for source, severity, cnt in rows:
        by_source[source] = by_source.get(source, 0) + cnt
        by_severity[severity or "unknown"] = by_severity.get(severity or "unknown", 0) + cnt
        total += cnt

    # 最紧急的 5 条（按创建时间倒序）
    top_stmt = select(AlertIntelligenceReview).where(
        AlertIntelligenceReview.factory_id == factory_id,
        AlertIntelligenceReview.status == "pending",
    ).order_by(AlertIntelligenceReview.created_at.desc()).limit(5)

    top_reviews = (await db.execute(top_stmt)).scalars().all()

    return {
        "total_pending": total,
        "by_source": {SOURCE_LABELS.get(k, k): v for k, v in by_source.items()},
        "by_severity": by_severity,
        "top_alerts": [_review_to_dict(r) for r in top_reviews],
    }


async def list_reviews(
    db: AsyncSession,
    factory_id: str,
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """查询审查记录列表"""
    stmt = select(AlertIntelligenceReview).where(
        AlertIntelligenceReview.factory_id == factory_id,
    )
    if source:
        stmt = stmt.where(AlertIntelligenceReview.alert_source == source)
    if status:
        stmt = stmt.where(AlertIntelligenceReview.status == status)
    stmt = stmt.order_by(AlertIntelligenceReview.created_at.desc()).limit(min(limit, 50))
    rows = (await db.execute(stmt)).scalars().all()
    return [_review_to_dict(r) for r in rows]


async def acknowledge_review(
    db: AsyncSession,
    review_id: str,
    action: str,  # acknowledged / dismissed
    user: str,
) -> Optional[Dict[str, Any]]:
    """确认/驳回审查建议"""
    review = (await db.execute(
        select(AlertIntelligenceReview).where(AlertIntelligenceReview.id == review_id)
    )).scalar_one_or_none()
    if not review:
        return None
    if review.status != "pending":
        return {"error": f"该审查已处理（状态：{review.status}），不可重复操作"}

    review.status = action
    review.acknowledged_by = user
    review.acknowledged_at = datetime.utcnow()
    await db.commit()
    await db.refresh(review)
    return _review_to_dict(review)


# ==================== 工具函数 ====================

def _review_to_dict(r: AlertIntelligenceReview) -> Dict[str, Any]:
    """序列化审查记录"""
    actions = []
    if r.recommended_actions:
        try:
            actions = json.loads(r.recommended_actions)
        except (json.JSONDecodeError, TypeError):
            actions = [r.recommended_actions]
    root_causes = []
    if r.root_cause_hypothesis:
        try:
            root_causes = json.loads(r.root_cause_hypothesis)
        except (json.JSONDecodeError, TypeError):
            root_causes = [r.root_cause_hypothesis]

    return {
        "id": r.id,
        "factory_id": r.factory_id,
        "alert_source": r.alert_source,
        "source_label": SOURCE_LABELS.get(r.alert_source, r.alert_source),
        "alert_ref_id": r.alert_ref_id,
        "alert_ref_code": r.alert_ref_code,
        "alert_summary": r.alert_summary,
        "severity_assessment": r.severity_assessment,
        "root_cause_hypothesis": root_causes,
        "recommended_actions": actions,
        "dispatch_recommendation": r.dispatch_recommendation,
        "status": r.status,
        "acknowledged_by": r.acknowledged_by,
        "acknowledged_at": r.acknowledged_at.strftime("%Y-%m-%d %H:%M") if r.acknowledged_at else None,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
    }


__all__ = [
    "review_alert", "patrol", "get_pending_alerts_summary",
    "list_reviews", "acknowledge_review",
    "validate_andon_data", "validate_defect_data",
    "validate_work_order_data", "validate_equipment_transition",
    "SOURCE_LABELS",
]
