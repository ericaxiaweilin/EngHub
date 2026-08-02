
"""
Andon 2.0 API Routes
智能小工单系统 — CRUD + 派单/抢单/升级/提醒/超时处理
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/andon", tags=["andon - 智能工单"])


# ==================== Request Models ====================

class AndonTicketCreate(BaseModel):
    factory_id: str
    category_code: str  # equipment_repair/material_call/quality_issue/tech_support/admin_matter
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    location_id: Optional[str] = None
    equipment_id: Optional[str] = None
    work_order_id: Optional[str] = None
    priority: Optional[str] = None
    reminder_interval_minutes: int = Field(default=5, ge=1, le=30)
    timeout_minutes_no_response: int = Field(default=15, ge=5, le=60)
    timeout_minutes_resolve: int = Field(default=30, ge=10, le=120)
    metadata_: dict = Field(default_factory=dict)


class AndonTicketAssign(BaseModel):
    target_user_id: str
    reason: Optional[str] = None


class AndonTicketClaim(BaseModel):
    user_id: str


class AndonTicketResolve(BaseModel):
    resolution: str
    resolved_by: Optional[str] = None


class AndonTicketEscalate(BaseModel):
    level: int = Field(..., ge=1, le=3)
    note: Optional[str] = None


class AndonTicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


# ==================== Route Definitions ====================

@router.post("/tickets", status_code=201, summary="创建安灯工单")
async def create_ticket(payload: AndonTicketCreate, background_tasks: BackgroundTasks):
    """创建安灯小工单，自动校验类别，支持扫码派单和抢单。创建后异步触发 AI 审查。"""
    from api.services.andon_service import AndonService
    from api.services.alert_intelligence_service import validate_andon_data, review_alert
    from database.db_config import db_config

    # 边界校验（防低级失误）
    validation_err = validate_andon_data(
        timeout_no_response=payload.timeout_minutes_no_response,
        timeout_resolve=payload.timeout_minutes_resolve,
        priority=payload.priority,
    )
    if validation_err:
        raise HTTPException(status_code=422, detail=validation_err)

    async with db_config.session_factory() as db:
        service = AndonService(db)
        try:
            ticket = await service.create_ticket(
                factory_id=payload.factory_id,
                category_code=payload.category_code,
                title=payload.title,
                description=payload.description,
                location_id=payload.location_id,
                equipment_id=payload.equipment_id,
                work_order_id=payload.work_order_id,
                priority=payload.priority,
                metadata_=payload.metadata_,
            )

            # 异步触发 AI 审查（不阻塞主流程）
            context = (
                f"安灯工单创建：\n"
                f"- 工单号：{ticket.ticket_code}\n"
                f"- 类别：{payload.category_code}\n"
                f"- 标题：{payload.title}\n"
                f"- 优先级：{ticket.priority}\n"
                f"- 描述：{(payload.description or '无')[:300]}"
            )
            background_tasks.add_task(
                _async_review_alert, payload.factory_id, "andon", ticket.id, ticket.ticket_code, context
            )

            await db.commit()
            return {"success": True, "data": {
                "id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "status": ticket.status,
                "priority": ticket.priority,
                "category_code": ticket.category_code,
            }}
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _async_review_alert(factory_id: str, source: str, ref_id: str, ref_code: str, context: str):
    """Background task 包装器：独立 session 执行 AI 审查"""
    from database.db_config import db_config
    from api.services.alert_intelligence_service import review_alert
    try:
        async with db_config.session_factory() as db:
            await review_alert(db, factory_id, source, ref_id, ref_code, context)
    except Exception:
        pass  # 审查失败不影响主流程


@router.get("/tickets", summary="安灯工单列表")
async def list_tickets(
    factory_id: str = Query(...),
    status: Optional[str] = None,
    category_code: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查询安灯工单列表"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    tickets = await service.list_tickets(factory_id=factory_id, status=status, category_code=category_code, page=page, page_size=page_size)
    return {"items": [
        {
            "id": t.id, "ticket_code": t.ticket_code, "factory_id": t.factory_id,
            "category_code": t.category_code, "title": t.title,
            "status": t.status, "priority": t.priority,
            "assigned_to": t.assigned_to, "escalation_level": t.escalation_level,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in tickets
    ], "total": len(tickets)}


@router.get("/tickets/{ticket_id}", summary="安灯工单详情")
async def get_ticket(ticket_id: str):
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.get_ticket(ticket_id)
        return {"data": {
            "id": ticket.id, "ticket_code": ticket.ticket_code, "factory_id": ticket.factory_id,
            "category_code": ticket.category_code, "title": ticket.title,
            "description": ticket.description, "location_id": ticket.location_id,
            "equipment_id": ticket.equipment_id, "work_order_id": ticket.work_order_id,
            "status": ticket.status, "priority": ticket.priority,
            "assigned_to": ticket.assigned_to, "assigned_by": ticket.assigned_by,
            "claimed_at": ticket.claimed_at.isoformat() if ticket.claimed_at else None,
            "escalation_level": ticket.escalation_level, "escalated_to": ticket.escalated_to,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "metadata_": ticket.metadata_,
            "created_at": ticket.created_at.isoformat(), "updated_at": ticket.updated_at.isoformat(),
        }}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/tickets/{ticket_id}", summary="更新安灯工单")
async def update_ticket(ticket_id: str, payload: AndonTicketUpdate):
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.get_ticket(ticket_id)
        if payload.title is not None:
            ticket.title = payload.title
        if payload.description is not None:
            ticket.description = payload.description
        if payload.priority is not None:
            ticket.priority = payload.priority
        if payload.status is not None:
            ticket.status = payload.status
        await db.commit()
        await db.refresh(ticket)
        return {"success": True, "data": {"id": ticket.id, "ticket_code": ticket.ticket_code}}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/assign", summary="指定派单")
async def assign_ticket(ticket_id: str, payload: AndonTicketAssign):
    """一键指派给特定人员（支持扫码自动识别）"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.assign_ticket(ticket_id, payload.target_user_id, payload.reason)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status, "assigned_to": ticket.assigned_to}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/claim", summary="抢单认领")
async def claim_ticket(ticket_id: str, payload: AndonTicketClaim):
    """公共池抢单模式"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.claim_ticket(ticket_id, payload.user_id)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status, "claimed_at": ticket.claimed_at.isoformat()}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/resolve", summary="解决工单")
async def resolve_ticket(ticket_id: str, payload: AndonTicketResolve):
    """标记工单为已解决"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.resolve_ticket(ticket_id, payload.resolution, payload.resolved_by)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status, "resolved_at": ticket.resolved_at.isoformat()}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/escalate", summary="手动升级")
async def escalate_ticket(ticket_id: str, payload: AndonTicketEscalate):
    """手动升级至班组长/厂长"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.escalate_ticket(ticket_id, payload.level, payload.note)
        return {"success": True, "data": {"id": ticket.id, "escalation_level": ticket.escalation_level, "escalated_to": ticket.escalated_to}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/cancel", summary="取消工单")
async def cancel_ticket(ticket_id: str):
    """取消安灯工单"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        ticket = await service.get_ticket(ticket_id)
        ticket.status = "cancelled"
        await db.commit()
        await db.refresh(ticket)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/admin/process-timeouts", summary="处理超时升级")
async def process_timeouts():
    """定时任务接口：处理超时未响应/未解决的升级通知"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        actions = await service.process_timeout_escalations()
        return {"success": True, "actions": actions}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/admin/process-reminders", summary="发送定时提醒")
async def process_reminders():
    """定时任务接口：发送定时提醒推送"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config

    db = db_config.session_factory()
    service = AndonService(db)
    try:
        reminders = await service.process_timed_reminders()
        return {"success": True, "reminders": reminders}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/categories", summary="工单类别列表")
async def list_categories():
    """返回预设的5大类安灯工单"""
    return {
        "categories": [
            {"code": k, **v} for k, v in AndonService.CATEGORIES.items()
        ]
    }


@router.get("/kpi", summary="安灯 KPI 统计（MTTR/响应率/解决率）")
async def andon_kpi(
    factory_id: str = Query(...),
    days: int = Query(7, ge=1, le=90, description="统计近 N 天"),
):
    """安灯协调员 KPI 闭环：平均响应时间、平均解决时间(MTTR)、解决率、各类别分布。"""
    from api.services.andon_service import AndonService
    from database.db_config import db_config
    from datetime import datetime, timedelta
    from sqlalchemy import select, func
    from core.andon.models import AndonTicket

    async with db_config.session_factory() as db:
        since = datetime.utcnow() - timedelta(days=days)
        base = select(AndonTicket).where(
            AndonTicket.factory_id == factory_id,
            AndonTicket.created_at >= since,
        )
        tickets = list((await db.execute(base)).scalars().all())

    total = len(tickets)
    if total == 0:
        return {"period_days": days, "total": 0, "message": "无工单数据"}

    resolved = [t for t in tickets if t.status == "resolved"]
    open_tickets = [t for t in tickets if t.status in ("open", "assigned", "claimed", "upgrading")]

    # MTTR：平均解决时间（分钟）
    mttr_list = []
    for t in resolved:
        if t.resolved_at and t.created_at:
            mttr_list.append((t.resolved_at - t.created_at).total_seconds() / 60)
    mttr_avg = round(sum(mttr_list) / len(mttr_list), 1) if mttr_list else None

    # 平均响应时间（抢单/派单时间 - 创建时间）
    response_list = []
    for t in tickets:
        if t.claimed_at and t.created_at:
            response_list.append((t.claimed_at - t.created_at).total_seconds() / 60)
    response_avg = round(sum(response_list) / len(response_list), 1) if response_list else None

    # 解决率
    resolution_rate = round(len(resolved) / total * 100, 1)

    # 升级率
    escalated = [t for t in tickets if (t.escalation_level or 0) > 0]
    escalation_rate = round(len(escalated) / total * 100, 1)

    # 按类别统计
    by_category = {}
    for t in tickets:
        cat = t.category_code or "unknown"
        if cat not in by_category:
            by_category[cat] = {"total": 0, "resolved": 0, "open": 0}
        by_category[cat]["total"] += 1
        if t.status == "resolved":
            by_category[cat]["resolved"] += 1
        elif t.status in ("open", "assigned", "claimed", "upgrading"):
            by_category[cat]["open"] += 1

    # 超时率（触发过升级的 / 总数）
    return {
        "period_days": days,
        "total": total,
        "resolved": len(resolved),
        "open": len(open_tickets),
        "mttr_minutes": mttr_avg,
        "avg_response_minutes": response_avg,
        "resolution_rate_pct": resolution_rate,
        "escalation_rate_pct": escalation_rate,
        "by_category": by_category,
    }


__all__ = ["router"]
