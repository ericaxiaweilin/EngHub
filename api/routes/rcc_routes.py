

"""
v2.6 - RCC API Routes
三位一体调度系统 — RCC任务 + 参数调整 + Chatbot工单 + 逻辑链
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db

router = APIRouter(prefix="/api/v1/rcc", tags=["rcc - 资源控制中心"])


# ==================== RCC 任务 ====================

@router.get("/tasks", summary="查询RCC任务")
async def list_rcc_tasks(
    status: Optional[str] = None,
    org_unit_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询RCC调度任务列表"""
    from core.rcc.services import RCCTaskService

    service = RCCTaskService(db)
    try:
        tasks = await service.list_tasks(status=status, org_unit_id=org_unit_id, page=page, page_size=page_size)
        return {"items": [
            {
                "id": t.id, "task_code": t.task_code, "org_unit_id": t.org_unit_id,
                "task_type": t.task_type, "title": t.title, "description": t.description,
                "affected_params": t.affected_params, "affected_entities": t.affected_entities,
                "expected_impact_summary": t.expected_impact_summary,
                "status": t.status, "requested_by": t.requested_by,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            } for t in tasks
        ], "total": len(tasks)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tasks/create", status_code=201, summary="创建RCC调度任务")
async def create_rcc_task(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """创建RCC调度任务"""
    from core.rcc.services import RCCTaskService

    service = RCCTaskService(db)
    try:
        task = await service.create_task(
            task_type=payload["task_type"],
            title=payload["title"],
            org_unit_id=payload["org_unit_id"],
            affected_params=payload.get("affected_params", []),
            affected_entities=payload.get("affected_entities", []),
            expected_impact_summary=payload.get("expected_impact_summary", ""),
            requested_by=payload.get("requested_by", "system"),
            request_context=payload.get("request_context", {}),
            source_ticket_id=payload.get("source_ticket_id"),
        )
        return {"success": True, "data": {
            "id": task.id, "task_code": task.task_code, "status": task.status,
        }}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tasks/{task_id}/approve", summary="审批通过RCC任务")
async def approve_rcc_task(task_id: str, comment: str = "", db: AsyncSession = Depends(get_db)):
    """审批通过RCC任务"""
    from core.rcc.services import RCCTaskService

    service = RCCTaskService(db)
    try:
        task = await service.approve_task(task_id, approver_id="current_user", comment=comment)
        return {"success": True, "data": {"id": task.id, "status": task.status}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tasks/{task_id}/reject", summary="拒绝RCC任务")
async def reject_rcc_task(task_id: str, reason: str, db: AsyncSession = Depends(get_db)):
    """拒绝RCC任务"""
    from core.rcc.services import RCCTaskService

    service = RCCTaskService(db)
    try:
        task = await service.reject_task(task_id, approver_id="current_user", reason=reason)
        return {"success": True, "data": {"id": task.id, "status": task.status}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== 可调参数 ====================

@router.get("/params", summary="查询可调参数")
async def list_adjustable_params(
    org_unit_id: Optional[str] = None,
    category: Optional[str] = None,
    sensitivity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询可调参数"""
    from core.rcc.services import ParamAdjustmentService

    service = ParamAdjustmentService(db)
    try:
        params = await service.list_params(org_unit_id=org_unit_id, category=category, sensitivity=sensitivity)
        return {"items": [
            {
                "id": p.id, "param_code": p.param_code, "param_name": p.param_name,
                "category": p.category, "param_type": p.param_type,
                "current_value": p.current_value, "target_value": p.target_value,
                "sensitivity": p.sensitivity, "options": p.options,
                "min_value": p.min_value, "max_value": p.max_value, "unit": p.unit,
                "org_unit_id": p.org_unit_id, "position_cap_id": p.position_cap_id,
                "changed_by": p.changed_by, "change_reason": p.change_reason,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            } for p in params
        ], "total": len(params)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/params/{param_id}", summary="调整参数")
async def adjust_parameter(param_id: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """调整参数（根据敏感度决定是否需要RCC审批）"""
    from core.rcc.services import ParamAdjustmentService

    service = ParamAdjustmentService(db)
    try:
        result = await service.adjust_parameter(
            param_id=param_id,
            new_value=payload["new_value"],
            changed_by=payload.get("changed_by", "current_user"),
            reason=payload.get("reason", ""),
            source=payload.get("source", "panel"),
        )
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/params/{param_id}/impact", summary="参数影响分析")
async def analyze_param_impact(param_id: str, new_value: str = Query(...), db: AsyncSession = Depends(get_db)):
    """分析参数变更影响"""
    from core.rcc.services import ParamAdjustmentService

    service = ParamAdjustmentService(db)
    try:
        impact = await service.analyze_impact(param_id, new_value)
        return {"success": True, "data": impact}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/params/audit", summary="参数变更历史")
async def list_param_audit(
    param_id: Optional[str] = None,
    changed_by: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询参数变更审计记录"""
    from database.models import ParameterChangeAudit
    from sqlalchemy import select as sa_select

    query = sa_select(ParameterChangeAudit)
    if param_id:
        query = query.where(ParameterChangeAudit.param_id == param_id)
    if changed_by:
        query = query.where(ParameterChangeAudit.changed_by == changed_by)
    query = query.order_by(ParameterChangeAudit.changed_at.desc()).offset((page-1)*page_size).limit(page_size)
    
    records = list((await db.execute(query)).scalars().all())
    return {"items": [
        {
            "id": r.id, "param_id": r.param_id, "from_value": r.from_value,
            "to_value": r.to_value, "changed_by": r.changed_by,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            "reason": r.reason, "approval_status": r.approval_status, "source": r.source,
        } for r in records
    ], "total": len(records)}


# ==================== Chatbot 工单 ====================

@router.post("/chatbot/tickets/create", status_code=201, summary="创建Chatbot工单")
async def create_chatbot_ticket(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """创建Chatbot工单"""
    from core.rcc.services import ChatbotTicketService

    service = ChatbotTicketService(db)
    try:
        ticket = await service.create_ticket(
            message=payload["message"],
            requester_id=payload["requester_id"],
            ticket_type=payload.get("ticket_type", "support_request"),
            parsed_intents=payload.get("parsed_intents", {}),
            parsed_slots=payload.get("parsed_slots", {}),
            related_param_id=payload.get("related_param_id"),
            related_rcc_task_id=payload.get("related_rcc_task_id"),
            related_work_order_id=payload.get("related_work_order_id"),
            requested_resource=payload.get("requested_resource", {}),
            requested_time_window=payload.get("requested_time_window", {}),
        )
        return {"success": True, "data": {
            "id": ticket.id, "ticket_code": ticket.ticket_code, "status": ticket.status,
        }}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/chatbot/tickets/{ticket_id}/route", summary="路由Chatbot工单")
async def route_chatbot_ticket(ticket_id: str, target_org_unit: str, target_position: str, db: AsyncSession = Depends(get_db)):
    """路由工单到指定组织和职位"""
    from core.rcc.services import ChatbotTicketService

    service = ChatbotTicketService(db)
    try:
        ticket = await service.route_ticket(ticket_id, target_org_unit, target_position)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status}}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/chatbot/tickets/{ticket_id}/resolve", summary="解决Chatbot工单")
async def resolve_chatbot_ticket(ticket_id: str, resolution: str, resolved_by: str, db: AsyncSession = Depends(get_db)):
    """解决工单"""
    from core.rcc.services import ChatbotTicketService

    service = ChatbotTicketService(db)
    try:
        ticket = await service.resolve_ticket(ticket_id, resolution, resolved_by)
        return {"success": True, "data": {"id": ticket.id, "status": ticket.status}}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/chatbot/tickets", summary="查询Chatbot工单")
async def list_chatbot_tickets(
    requester_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询工单列表"""
    from core.rcc.services import ChatbotTicketService

    service = ChatbotTicketService(db)
    try:
        tickets = await service.list_tickets(requester_id=requester_id, status=status, page=page, page_size=page_size)
        return {"items": [
            {
                "id": t.id, "ticket_code": t.ticket_code, "requester_id": t.requester_id,
                "ticket_type": t.ticket_type, "raw_message": t.raw_message,
                "status": t.status, "priority": t.priority,
                "routed_to_org_unit": t.routed_to_org_unit, "routed_to_position": t.routed_to_position,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            } for t in tickets
        ], "total": len(tickets)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== 确定性逻辑链 ====================

@router.post("/logic-chains/evaluate", summary="评估并执行逻辑链")
async def evaluate_logic_chain(event: Dict[str, Any], context_org_unit: str = Query(...), db: AsyncSession = Depends(get_db)):
    """全局逻辑链评估：根据事件触发所有匹配的逻辑链并执行动作"""
    from core.rcc.services import LogicChainEngine

    engine = LogicChainEngine(db)
    try:
        results = await engine.evaluate(event=event, context_org_unit=context_org_unit)
        return {"success": True, "results": results}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/logic-chains", summary="查询逻辑链配置")
async def list_logic_chains(
    org_unit_id: Optional[str] = None,
    trigger_event: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询确定性逻辑链配置"""
    from core.rcc.models import DeterministicLogicChain
    from sqlalchemy import select as sa_select

    query = sa_select(DeterministicLogicChain)
    if org_unit_id:
        query = query.where(DeterministicLogicChain.org_unit_id == org_unit_id)
    if trigger_event:
        query = query.where(DeterministicLogicChain.trigger_event == trigger_event)
    
    chains = list((await db.execute(query)).scalars().all())
    return {"items": [
        {
            "id": c.id, "chain_code": c.chain_code, "chain_name": c.chain_name,
            "trigger_event": c.trigger_event, "conditions": c.conditions,
            "action_sequence": c.action_sequence, "enabled": c.enabled,
            "execution_order": c.execution_order,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in chains
    ], "total": len(chains)}


@router.post("/logic-chains", status_code=201, summary="创建逻辑链")
async def create_logic_chain(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """创建确定性逻辑链（可视化编排器保存）"""
    from core.rcc.models import DeterministicLogicChain

    for f in ("chain_code", "chain_name", "trigger_event"):
        if not payload.get(f):
            raise HTTPException(status_code=400, detail=f"缺少必填字段：{f}")
    chain = DeterministicLogicChain(
        chain_code=payload["chain_code"],
        chain_name=payload["chain_name"],
        trigger_event=payload["trigger_event"],
        conditions=payload.get("conditions") or [],
        action_sequence=payload.get("action_sequence") or [],
        org_unit_id=payload.get("org_unit_id"),
        enabled=bool(payload.get("enabled", True)),
        execution_order=int(payload.get("execution_order", 0)),
    )
    db.add(chain)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"保存失败（chain_code 可能重复）：{exc}")
    return {"id": chain.id, "chain_code": chain.chain_code}


@router.put("/logic-chains/{chain_id}", summary="更新逻辑链")
async def update_logic_chain(chain_id: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """更新确定性逻辑链配置"""
    from core.rcc.models import DeterministicLogicChain
    from sqlalchemy import select as sa_select

    chain = (await db.execute(
        sa_select(DeterministicLogicChain).where(DeterministicLogicChain.id == chain_id)
    )).scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="逻辑链不存在")
    for f in ("chain_name", "trigger_event", "conditions", "action_sequence", "org_unit_id"):
        if f in payload:
            setattr(chain, f, payload[f])
    if "enabled" in payload:
        chain.enabled = bool(payload["enabled"])
    if "execution_order" in payload:
        chain.execution_order = int(payload["execution_order"])
    await db.commit()
    return {"id": chain.id, "chain_code": chain.chain_code, "updated": True}


@router.delete("/logic-chains/{chain_id}", summary="删除逻辑链")
async def delete_logic_chain(chain_id: str, db: AsyncSession = Depends(get_db)):
    """删除确定性逻辑链"""
    from core.rcc.models import DeterministicLogicChain
    from sqlalchemy import select as sa_select

    chain = (await db.execute(
        sa_select(DeterministicLogicChain).where(DeterministicLogicChain.id == chain_id)
    )).scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="逻辑链不存在")
    await db.delete(chain)
    await db.commit()
    return {"deleted": True}


__all__ = ["router"]


