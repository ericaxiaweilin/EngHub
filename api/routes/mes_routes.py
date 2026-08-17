"""
MES API Routes
工单管理、生产报工、工艺路线、工位管理、设备管理
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Optional, List, Dict, Any
import json
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.db_config import get_db
from database.models import User, Product, RoutingTemplate, RoutingTemplateStep, WorkOrder as WorkOrderModel
from api.services.work_order_service import WorkOrderService, WOStatus, WoPermissionError
from api.services.mes_services import (
    ProductionReportService,
    StationService,
    RoutingService,
)
from api.services.dispatch_service import dispatch_operations, advance_flow
from core.auth.security import enforce_tenant, get_current_user

router = APIRouter(prefix="/api/v1", tags=["mes"], dependencies=[Depends(enforce_tenant)])


# --- Request/Response Models ---

class WorkOrderCreate(BaseModel):
    factory_id: str
    product_id: str
    planned_qty: int
    planned_due: str
    priority: str = "medium"
    station_id: Optional[str] = None
    bom_version: Optional[str] = None
    remark: Optional[str] = None
    routing_template_id: Optional[str] = None  # 工艺路线模板（可选，下达时自动派工）


class WorkOrderUpdate(BaseModel):
    planned_qty: Optional[int] = None
    planned_due: Optional[str] = None
    priority: Optional[str] = None
    station_id: Optional[str] = None
    remark: Optional[str] = None


class WorkOrderSplit(BaseModel):
    split_qty: int
    remark: Optional[str] = None


class WorkOrderAction(BaseModel):
    reason: Optional[str] = None


class ProductionReportCreate(BaseModel):
    factory_id: str
    work_order_id: str
    station_id: str
    good_qty: int
    defect_qty: int = 0
    report_type: str = "normal"
    shift: str = "day"
    operator_id: Optional[str] = None
    assistant_operator_ids: List[str] = []
    operation_seq: Optional[int] = None
    operation_name: Optional[str] = None
    machine_id: Optional[str] = None
    actual_start_time: Optional[datetime] = None
    actual_end_time: Optional[datetime] = None
    quality_check_passed: Optional[bool] = None
    remark: Optional[str] = None
    report_date: Optional[datetime] = None  # 可选报工日期（补录历史报工）


class ProductionReportComment(BaseModel):
    comment: str


class StationCreate(BaseModel):
    factory_id: str
    station_code: str
    station_name: str
    station_type: str
    capacity_per_hour: int
    workshop_id: Optional[str] = None


class RoutingCreate(BaseModel):
    factory_id: str
    product_id: str
    version: str = "v1"
    steps: List[dict]


# ============================================================
# Work Order Endpoints
# ============================================================

@router.post("/work-orders", status_code=201)
async def create_work_order(
    wo: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工单（草稿状态）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.create_work_order(
            factory_id=wo.factory_id,
            product_id=wo.product_id,
            planned_qty=wo.planned_qty,
            planned_due=datetime.fromisoformat(wo.planned_due.replace('Z', '+00:00')),
            priority=wo.priority,
            assigned_station_id=wo.station_id,
            bom_version=wo.bom_version,
            remark=wo.remark,
            created_by=current_user.username,
            routing_template_id=wo.routing_template_id,
            derive_operations=not wo.routing_template_id,  # 有模板时跳过旧派生，下达时按模板派工
        )
        return service.to_dict(work_order)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/work-orders")
async def list_work_orders(
    factory_id: str,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    priority: Optional[str] = None,
    station_id: Optional[str] = None,
    wo_type: Optional[str] = Query("master", description="工单层级：master=主工单 / operation=工序工单 / all=全部"),
    parent_work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单列表（含进度信息）。默认只返回主工单，传 wo_type=all 含工序工单。"""
    service = WorkOrderService(db)
    skip = (page - 1) * page_size
    work_orders = await service.list_work_orders(
        factory_id=factory_id,
        status=status,
        product_id=product_id,
        priority=priority,
        station_id=station_id,
        wo_type=wo_type,
        parent_work_order_id=parent_work_order_id,
        skip=skip,
        limit=page_size,
    )
    total = len(work_orders)

    items = []
    for wo in work_orders:
        d = service.to_dict(wo)
        progress = await service.get_progress(wo)
        d.update(progress)
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/work-orders/stats")
async def get_work_order_stats(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单统计卡片数据"""
    service = WorkOrderService(db)
    return await service.get_stats(factory_id)


# ============================================================
# 多视角查询端点（016）—— 必须放在 /{work_order_id} 之前
# ============================================================

@router.get("/work-orders/global-flow")
async def global_flow_view(
    factory_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """全局宏观视角：所有主工单 + 工序进度摘要（data_scope: factory+）"""
    # 权限检查：仅 factory/all 级别可访问
    scope = getattr(current_user, "data_scope", None)
    if isinstance(scope, dict):
        scope_type = scope.get("type", "own")
    else:
        scope_type = "factory"  # 默认
    if scope_type not in ("all", "factory"):
        raise HTTPException(403, "全局视角需要 factory 级及以上权限")

    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import selectinload

    # 查询主工单
    query = select(WorkOrderModel).where(
        WorkOrderModel.factory_id == factory_id,
        WorkOrderModel.wo_type == "master",
    ).order_by(WorkOrderModel.created_at.desc())

    total_result = await db.execute(
        select(sa_func.count()).select_from(WorkOrderModel).where(
            WorkOrderModel.factory_id == factory_id,
            WorkOrderModel.wo_type == "master",
        )
    )
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    masters = result.scalars().all()

    items = []
    for m in masters:
        # 查询子工序工单摘要
        ops_result = await db.execute(
            select(WorkOrderModel).where(
                WorkOrderModel.parent_work_order_id == m.id,
                WorkOrderModel.wo_type == "operation",
            ).order_by(WorkOrderModel.operation_seq)
        )
        ops = ops_result.scalars().all()
        ops_summary = [
            {
                "id": op.id,
                "code": op.work_order_code,
                "seq": op.operation_seq,
                "process_code": op.process_code,
                "work_center": op.work_center,
                "status": op.status,
                "assigned_to": op.assigned_to,
            }
            for op in ops
        ]
        done_count = sum(1 for op in ops if op.status in ("completed", "closed"))
        items.append({
            "id": m.id,
            "work_order_code": m.work_order_code,
            "product_id": m.product_id,
            "status": m.status,
            "priority": m.priority,
            "planned_qty": m.planned_qty,
            "planned_due": m.planned_due.isoformat() if m.planned_due else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "operations": ops_summary,
            "op_total": len(ops),
            "op_done": done_count,
            "progress_pct": round(done_count / len(ops) * 100) if ops else 0,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/work-orders/queue")
async def process_queue_view(
    factory_id: str,
    work_center: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部门/工序组队列：指定工序组的工序工单（按优先级+交期排序）"""
    from sqlalchemy import func as sa_func

    # 确定工序组：显式传入 > 用户绑定的 work_center > 全部
    wc_filter = work_center or getattr(current_user, "work_center", None)

    query = select(WorkOrderModel).where(
        WorkOrderModel.factory_id == factory_id,
        WorkOrderModel.wo_type == "operation",
    )
    count_query = select(sa_func.count()).select_from(WorkOrderModel).where(
        WorkOrderModel.factory_id == factory_id,
        WorkOrderModel.wo_type == "operation",
    )

    if wc_filter:
        query = query.where(WorkOrderModel.work_center == wc_filter)
        count_query = count_query.where(WorkOrderModel.work_center == wc_filter)
    if status:
        query = query.where(WorkOrderModel.status == status)
        count_query = count_query.where(WorkOrderModel.status == status)

    total = (await db.execute(count_query)).scalar() or 0

    # 排序：优先级(urgent>high>medium>low) + 交期
    query = query.order_by(WorkOrderModel.priority.desc(), WorkOrderModel.planned_due.asc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    ops = result.scalars().all()

    service = WorkOrderService(db)
    items = [service.to_dict(op) for op in ops]

    # 统计卡片
    stats_result = await db.execute(
        select(WorkOrderModel.status, sa_func.count()).where(
            WorkOrderModel.factory_id == factory_id,
            WorkOrderModel.wo_type == "operation",
            *([WorkOrderModel.work_center == wc_filter] if wc_filter else []),
        ).group_by(WorkOrderModel.status)
    )
    status_counts = {row[0]: row[1] for row in stats_result.all()}

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "work_center": wc_filter,
        "stats": {
            "pending": status_counts.get("pending", 0),
            "released": status_counts.get("released", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "completed": status_counts.get("completed", 0),
        },
    }


@router.get("/work-orders/my-tasks")
async def my_tasks_view(
    factory_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """我的任务：assigned_to=当前用户的工序工单"""
    from sqlalchemy import func as sa_func

    user_id = str(current_user.id)
    query = select(WorkOrderModel).where(
        WorkOrderModel.factory_id == factory_id,
        WorkOrderModel.assigned_to == user_id,
    )
    count_query = select(sa_func.count()).select_from(WorkOrderModel).where(
        WorkOrderModel.factory_id == factory_id,
        WorkOrderModel.assigned_to == user_id,
    )

    if status:
        query = query.where(WorkOrderModel.status == status)
        count_query = count_query.where(WorkOrderModel.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(WorkOrderModel.priority.desc(), WorkOrderModel.planned_due.asc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    tasks = result.scalars().all()

    service = WorkOrderService(db)
    return {"items": [service.to_dict(t) for t in tasks], "total": total, "page": page, "page_size": page_size}


@router.get("/work-orders/{work_order_id}/flow-detail")
async def flow_detail_view(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """单张主工单的工序流转详情（含每道状态/操作人/时间）"""
    service = WorkOrderService(db)
    master = await service.get_work_order_by_id(work_order_id)
    if not master:
        raise HTTPException(404, "Work order not found")

    # 查询所有工序工单
    ops_result = await db.execute(
        select(WorkOrderModel).where(
            WorkOrderModel.parent_work_order_id == work_order_id,
            WorkOrderModel.wo_type == "operation",
        ).order_by(WorkOrderModel.operation_seq)
    )
    ops = ops_result.scalars().all()

    flow_steps = [
        {
            "id": op.id,
            "seq": op.operation_seq,
            "process_code": op.process_code,
            "work_center": op.work_center,
            "remark": op.remark,
            "status": op.status,
            "assigned_to": op.assigned_to,
            "released_by": op.released_by,
            "completed_by": op.completed_by,
            "actual_start": op.actual_start.isoformat() if op.actual_start else None,
            "actual_complete": op.actual_complete.isoformat() if op.actual_complete else None,
            "is_qc_gate": "QC_GATE" in (op.remark or ""),
        }
        for op in ops
    ]

    done_count = sum(1 for op in ops if op.status in ("completed", "closed"))
    current_step = next((op.operation_seq for op in ops if op.status in ("released", "in_progress")), None)

    return {
        "master": service.to_dict(master),
        "flow_steps": flow_steps,
        "total_steps": len(ops),
        "done_steps": done_count,
        "current_step": current_step,
        "progress_pct": round(done_count / len(ops) * 100) if ops else 0,
    }


@router.get("/work-orders/{work_order_id}")
async def get_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单详情"""
    service = WorkOrderService(db)
    work_order = await service.get_work_order_by_id(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    reports = []
    if hasattr(work_order, 'production_reports') and work_order.production_reports:
        reports = [
            {
                "id": str(r.id), "report_code": r.report_code,
                "work_order_id": str(r.work_order_id) if r.work_order_id else None,
                "station_id": r.station_id, "good_qty": r.good_qty,
                "defect_qty": r.defect_qty, "scrap_qty": r.scrap_qty,
                "report_type": r.report_type, "shift": r.shift,
                "operator_id": r.operator_id, "remark": r.remark,
                "is_modified": r.is_modified,
                "modified_at": r.modified_at.isoformat() if r.modified_at else None,
                "modified_by": r.modified_by,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in work_order.production_reports
        ]

    result = service.to_dict(work_order)
    result["production_reports"] = reports
    result["progress"] = await service.get_progress(work_order)
    return result


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str,
    wo: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新工单"""
    service = WorkOrderService(db)
    try:
        work_order = await service.update_work_order(
            work_order_id=work_order_id,
            planned_qty=wo.planned_qty,
            planned_due=datetime.fromisoformat(wo.planned_due.replace('Z', '+00:00')) if wo.planned_due else None,
            priority=wo.priority,
            assigned_station_id=wo.station_id,
            remark=wo.remark,
        )
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/release")
async def release_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """待下发 → 已下达（审核门槛：管理角色 + 创建人不能下达自己的工单）+ 自动派工"""
    service = WorkOrderService(db)
    try:
        work_order = await service.release_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")

        # 工序派工：如果主工单绑定了工艺路线模板，自动生成工序工单
        dispatch_result = None
        if work_order.routing_template_id and work_order.wo_type == "master":
            from sqlalchemy.orm import selectinload
            from sqlalchemy import select as sa_select
            tpl_result = await db.execute(
                sa_select(RoutingTemplate)
                .where(RoutingTemplate.id == work_order.routing_template_id)
                .options(selectinload(RoutingTemplate.steps))
            )
            template = tpl_result.scalar_one_or_none()
            if template and template.steps:
                ops = await dispatch_operations(db, work_order, template.steps, current_user.username)
                await db.commit()
                dispatch_result = {
                    "dispatched_count": len(ops),
                    "operation_codes": [op.work_order_code for op in ops],
                }

        resp = service.to_dict(work_order)
        if dispatch_result:
            resp["dispatch"] = dispatch_result
        return resp
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/start")
async def start_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """已下达 → 生产中（父子约束：已拆分的主工单由子工单分别开工）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.start_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/pause")
async def pause_work_order(
    work_order_id: str,
    data: WorkOrderAction = WorkOrderAction(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中 → 暂停"""
    service = WorkOrderService(db)
    try:
        work_order = await service.pause_work_order(work_order_id, data.reason or "", user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/resume")
async def resume_work_order(
    work_order_id: str,
    data: WorkOrderAction = WorkOrderAction(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停 → 生产中"""
    service = WorkOrderService(db)
    try:
        work_order = await service.resume_work_order(work_order_id, data.reason or "", user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/pending-inbound")
async def mark_pending_inbound(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中 → 待入库"""
    service = WorkOrderService(db)
    try:
        work_order = await service.mark_pending_inbound(work_order_id, user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/complete")
async def complete_work_order(
    work_order_id: str,
    completed_qty: Optional[int] = None,
    good_qty: Optional[int] = None,
    defect_qty: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生产中/待入库 → 已完成（审核门槛：品质角色 + 实际产出 + 子工单全部完工）+ 工序流转"""
    service = WorkOrderService(db)
    try:
        work_order = await service.complete_work_order(
            work_order_id, completed_qty, good_qty, defect_qty, user=current_user
        )
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")

        # 工序流转：如果是工序工单完工，自动释放下一道工序
        flow_result = None
        if work_order.wo_type == "operation" and work_order.parent_work_order_id:
            flow_result = await advance_flow(db, work_order, current_user.username)
            await db.commit()

        resp = service.to_dict(work_order)
        if flow_result:
            resp["flow"] = flow_result
        return resp
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/close")
async def close_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """已完成 → 已关闭（审核门槛：厂长 / 管理员）"""
    service = WorkOrderService(db)
    try:
        work_order = await service.close_work_order(work_order_id, current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except WoPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/cancel")
async def cancel_work_order(
    work_order_id: str,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消工单"""
    service = WorkOrderService(db)
    try:
        work_order = await service.cancel_work_order(work_order_id, reason, user=current_user)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work order not found")
        return service.to_dict(work_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/work-orders/{work_order_id}/split")
async def split_work_order(
    work_order_id: str,
    data: WorkOrderSplit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """拆分工单"""
    service = WorkOrderService(db)
    try:
        original_wo, new_wo = await service.split_work_order(
            work_order_id=work_order_id,
            split_qty=data.split_qty,
            remark=data.remark,
            created_by=current_user.username,
            user=current_user,
        )
        return {
            "original_work_order": service.to_dict(original_wo),
            "new_work_order": service.to_dict(new_wo),
            "split_qty": data.split_qty,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/work-orders/{work_order_id}/split-preview")
async def split_work_order_preview(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    method: str = Query(default="simple", description="Split method: simple|by_routing|by_batch|by_ratio"),
    parameters: Optional[str] = None,
):
    """拆分预览：模拟拆分操作并返回拟生成的工单列表，不实际修改数据"""
    service = WorkOrderService(db)
    try:
        params = json.loads(parameters) if parameters else {}
        result = await service.split_preview(work_order_id, method, params)
        return {"preview": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work-orders/{work_order_id}/split-advanced")
async def split_work_order_advanced(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    req: Dict[str, Any] = None,
):
    """高级拆分执行 - 支持多种拆分模式（simple/by_routing/by_batch/by_ratio）"""
    from sqlalchemy import text
    
    method = req.get("method", "simple")
    parameters = req.get("parameters", {})
    remark = req.get("remark", "")
    
    service = WorkOrderService(db)
    try:
        result = await service.split_advanced(
            work_order_id=work_order_id,
            method=method,
            parameters=parameters,
            operator=current_user.username,
            remark=remark,
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/work-orders/{work_order_id}/reverse-split")
async def reverse_split_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    latest_only: bool = Query(default=True, description="Only reverse the most recent split"),
):
    """反拆分：将子工单合并回主工单"""
    service = WorkOrderService(db)
    try:
        result = await service.reverse_split(work_order_id, latest_only=latest_only, operator=current_user.username)
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work-orders/{work_order_id}/split-history")
async def get_work_order_split_history(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单拆分历史"""
    service = WorkOrderService(db)
    try:
        history = await service.get_split_history(work_order_id)
        return {"history": history, "total": len(history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work-orders/{work_order_id}/tree")
async def get_work_order_tree(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工单树形结构（包含所有层级的子工单）"""
    service = WorkOrderService(db)
    try:
        tree = await service.get_work_order_tree(work_order_id)
        return {"tree": tree}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work-orders/{work_order_id}/status-logs")
async def get_work_order_status_logs(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """状态操作日志（审核追溯：谁/什么角色/何时/做了什么）"""
    service = WorkOrderService(db)
    logs = await service.get_status_logs(work_order_id)
    return {"items": logs, "total": len(logs)}


@router.get("/work-orders/{work_order_id}/children")
async def get_work_order_children(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """子工单列表（含进度，主工单详情页使用）"""
    service = WorkOrderService(db)
    children = await service.get_children_detail(work_order_id)
    return {"items": children, "total": len(children)}


# ============================================================
# Production Report Endpoints
# ============================================================

@router.get("/production-reports")
async def list_production_reports(
    factory_id: str,
    work_order_id: Optional[str] = None,
    station_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取生产报工列表（看板/报工页使用）"""
    service = ProductionReportService(db)
    skip = max(page - 1, 0) * page_size
    reports = await service.list_reports(
        factory_id=factory_id,
        work_order_id=work_order_id,
        station_id=station_id,
        skip=skip,
        limit=page_size,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "report_code": r.report_code,
                "factory_id": r.factory_id,
                "work_order_id": str(r.work_order_id) if r.work_order_id else None,
                "station_id": r.station_id,
                "good_qty": r.good_qty,
                "defect_qty": r.defect_qty,
                "scrap_qty": r.scrap_qty,
                "report_type": r.report_type,
                "shift": r.shift,
                "operator_id": r.operator_id,
                "assistant_operator_ids": r.assistant_operator_ids or [],
                "operation_seq": r.operation_seq,
                "operation_name": r.operation_name,
                "machine_id": r.machine_id,
                "actual_start_time": r.start_time.isoformat() if r.start_time else None,
                "actual_end_time": r.end_time.isoformat() if r.end_time else None,
                "quality_check_passed": r.quality_check_passed,
                "remark": r.remark,
                "is_modified": r.is_modified,
                "modified_at": r.modified_at.isoformat() if r.modified_at else None,
                "modified_by": r.modified_by,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "total": len(reports),
    }


@router.post("/production-reports")
async def create_production_report(
    report: ProductionReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建生产报工"""
    service = ProductionReportService(db)
    try:
        production_report = await service.create_report(
            factory_id=report.factory_id,
            work_order_id=report.work_order_id,
            station_id=report.station_id,
            good_qty=report.good_qty,
            defect_qty=report.defect_qty,
            scrap_qty=0,
            report_type=report.report_type,
            shift=report.shift,
            operator_id=report.operator_id,
            assistant_operator_ids=report.assistant_operator_ids,
            operation_seq=report.operation_seq,
            operation_name=report.operation_name,
            machine_id=report.machine_id,
            start_time=report.actual_start_time,
            end_time=report.actual_end_time,
            quality_check_passed=report.quality_check_passed,
            remark=report.remark,
            created_by=current_user.username,
            report_date=report.report_date,
        )
        return {
            "id": production_report.id,
            "report_code": production_report.report_code,
            "status": "submitted",
            "created_at": production_report.created_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Station Endpoints ---

@router.post("/stations")
async def create_station(
    station: StationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工位"""
    service = StationService(db)
    try:
        result = await service.create_station(
            factory_id=station.factory_id,
            station_code=station.station_code,
            station_name=station.station_name,
            station_type=station.station_type,
            capacity_per_hour=station.capacity_per_hour,
            workshop_id=station.workshop_id,
            created_by=current_user.username,
        )
        return {"id": str(result.id), "station_code": result.station_code, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stations")
async def list_stations(
    factory_id: str,
    station_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工位列表"""
    service = StationService(db)
    stations = await service.list_stations(factory_id=factory_id, station_type=station_type)
    return {
        "items": [
            {
                "id": str(s.id), "station_code": s.station_code,
                "station_name": s.station_name, "factory_id": s.factory_id,
                "station_type": s.station_type, "capacity_per_hour": s.capacity_per_hour,
                "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in stations
        ],
        "total": len(stations),
    }


@router.get("/stations/{station_id}")
async def get_station(station_id: str, db: AsyncSession = Depends(get_db)):
    """获取工位详情"""
    service = StationService(db)
    station = await service.get_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return {
        "id": str(station.id), "station_code": station.station_code,
        "station_name": station.station_name, "factory_id": station.factory_id,
        "station_type": station.station_type, "capacity_per_hour": station.capacity_per_hour,
        "status": station.status,
    }


# --- Routing Endpoints ---

@router.post("/routings")
async def create_routing(
    routing: RoutingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工艺路线"""
    service = RoutingService(db)
    try:
        result = await service.create_routing(
            factory_id=routing.factory_id,
            product_id=routing.product_id,
            version=routing.version,
            steps=routing.steps,
            created_by=current_user.username,
        )
        return {"id": str(result.id), "routing_code": result.routing_code, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/routings")
async def list_routings(
    factory_id: str,
    product_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工艺路线列表"""
    service = RoutingService(db)
    routings = await service.list_routings(factory_id=factory_id, product_id=product_id)
    return {
        "items": [
            {
                "id": str(r.id), "routing_code": r.routing_code,
                "factory_id": r.factory_id, "product_id": r.product_id,
                "version": r.version, "is_active": r.is_active,
                "steps": r.steps,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in routings
        ],
        "total": len(routings),
    }


@router.get("/routings/{routing_id}")
async def get_routing(
    routing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工艺路线详情（含工序步骤，供工单详情追溯当前工序）"""
    service = RoutingService(db)
    routing = await service.get_routing_by_id(routing_id)
    if not routing:
        raise HTTPException(status_code=404, detail="工艺路线不存在")
    return {
        "id": str(routing.id), "routing_code": routing.routing_code,
        "factory_id": routing.factory_id, "product_id": routing.product_id,
        "version": routing.version, "is_active": routing.is_active,
        "steps": routing.steps,
        "created_by": routing.created_by,
        "created_at": routing.created_at.isoformat() if routing.created_at else None,
        "updated_at": routing.updated_at.isoformat() if routing.updated_at else None,
    }


# --- Product Endpoints ---

@router.get("/products")
async def list_products(
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取产品列表（供各页面把 product_id 解析为可读的产品编码/名称）。
    factory_id 可选：不传则返回全部产品，避免跨厂区引用的产品解析不到。"""
    query = select(Product)
    if factory_id:
        query = query.where(Product.factory_id == factory_id)
    query = query.order_by(Product.created_at.desc())
    result = await db.execute(query)
    products = list(result.scalars().all())
    return {
        "items": [
            {
                "id": str(p.id), "product_code": p.product_code,
                "product_name": p.product_name, "factory_id": p.factory_id,
                "category": p.category, "unit": p.unit, "status": p.status,
                "current_bom_version": p.current_bom_version,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in products
        ],
        "total": len(products),
    }


# ==================== 工单模板 ====================

@router.get("/work-order-templates")
async def list_work_order_templates(
    request: Request = None,
    module: str = Query(None, description="按模块过滤: qms/equipment/wms/production/pp"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前工厂的工单模板列表（含动态表单字段定义，支持按模块过滤）"""
    from sqlalchemy import text as sa_text
    import json as _json
    fid = (request.headers.get("x-factory-id") if request else None) or getattr(current_user, "active_factory_id", None) or current_user.factory_id or "FAC_MECH_001"
    sql = """
        SELECT id, factory_id, template_code, template_name, wo_type, description,
               default_priority, is_active, module, form_fields, standard_ref,
               badge_text, color, sort_order
        FROM work_order_templates
        WHERE factory_id = :fid AND is_active = true
    """
    params: dict = {"fid": fid}
    if module:
        sql += " AND module = :module"
        params["module"] = module
    sql += " ORDER BY module, sort_order, template_code"
    rows = (await db.execute(sa_text(sql), params)).fetchall()
    result = []
    for r in rows:
        fields_raw = r[9]
        if isinstance(fields_raw, str):
            try:
                fields_raw = _json.loads(fields_raw)
            except Exception:
                fields_raw = []
        result.append({
            "id": r[0], "factory_id": r[1], "template_code": r[2],
            "template_name": r[3], "wo_type": r[4], "description": r[5],
            "default_priority": r[6], "is_active": r[7],
            "module": r[8] or "production",
            "form_fields": fields_raw or [],
            "standard_ref": r[10],
            "badge_text": r[11],
            "color": r[12] or "#1677ff",
            "sort_order": r[13] or 0,
        })
    return result


__all__ = ["router"]


@router.get("/work-orders/{work_order_id}/relations", summary="工单跨表关联数据（BOM/物料库存/在途PO/报工）")
async def work_order_relations(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工单关联数据聚合（只读，飞书式跨表引用）：
    1. 物料齐套：work_order_materials（需求/已收/缺口）
    2. 库存：inventory（各物料可用量）
    3. 在途采购：purchase_orders（PO 状态/ETA）
    4. 报工记录：production_reports（良品/不良/报废）
    """
    from sqlalchemy import text as _t
    # 1) 工单基本信息
    wo = (await db.execute(_t(
        "SELECT id, work_order_code, product_id, planned_qty, completed_qty, status FROM work_orders WHERE id=:id OR work_order_code=:id"
    ), {"id": work_order_id})).mappings().first()
    if not wo:
        raise HTTPException(404, "工单不存在")

    # 2) 物料齐套 + 库存 + 在途 PO（一次查）
    mats = (await db.execute(_t("""
        SELECT wom.material_code, wom.material_name, wom.required_qty, wom.received_qty, wom.shortage_qty,
               (SELECT COALESCE(SUM(i.available_qty),0) FROM inventory i
                WHERE i.material_code=wom.material_code AND i.factory_id=wo.factory_id) AS inv_qty,
               (SELECT COALESCE(SUM(po.qty),0) FROM purchase_orders po
                WHERE po.material_code=wom.material_code AND po.factory_id=wo.factory_id
                  AND po.status IN ('ordered','confirmed','shipped')) AS po_qty,
               (SELECT MIN(po2.expected_date) FROM purchase_orders po2
                WHERE po2.material_code=wom.material_code AND po2.factory_id=wo.factory_id
                  AND po2.status IN ('ordered','confirmed','shipped')) AS po_eta
        FROM work_order_materials wom
        JOIN work_orders wo ON wo.id=wom.work_order_id
        WHERE wom.work_order_id=:id
        ORDER BY wom.required_qty DESC
    """), {"id": wo["id"]})).mappings().all()

    # 3) 报工记录
    reports = (await db.execute(_t("""
        SELECT pr.report_code, pr.good_qty, pr.defect_qty, pr.scrap_qty, pr.shift, pr.operator_id, pr.created_at
        FROM production_reports pr WHERE pr.work_order_id=:id
        ORDER BY pr.created_at DESC LIMIT 10
    """), {"id": wo["id"]})).mappings().all()

    # 4) 汇总齐套状态
    shortage_total = sum(float(m["shortage_qty"] or 0) for m in mats)
    return {
        "success": True,
        "work_order": {"code": wo["work_order_code"], "product": wo["product_id"],
                       "planned_qty": wo["planned_qty"], "completed_qty": wo["completed_qty"],
                       "status": wo["status"]},
        "materials": [{"material_code": m["material_code"], "material_name": m["material_name"] or m["material_code"],
                       "required": float(m["required_qty"] or 0), "received": float(m["received_qty"] or 0),
                       "shortage": float(m["shortage_qty"] or 0),
                       "inventory": float(m["inv_qty"] or 0),
                       "on_order": float(m["po_qty"] or 0),
                       "po_eta": str(m["po_eta"])[:10] if m["po_eta"] else None,
                       "ready": float(m["shortage_qty"] or 0) <= 0} for m in mats],
        "reports": [{"code": r["report_code"], "good": float(r["good_qty"] or 0),
                     "defect": float(r["defect_qty"] or 0), "scrap": float(r["scrap_qty"] or 0),
                     "shift": r["shift"], "operator": r["operator_id"],
                     "at": str(r["created_at"])[:16]} for r in reports],
        "summary": {"material_count": len(mats),
                    "kitting_ok": shortage_total <= 0,
                    "total_shortage": round(shortage_total, 1),
                    "report_count": len(reports)},
        "note": "跨表关联（只读）：物料齐套 ← work_order_materials，库存 ← inventory，在途 ← purchase_orders，报工 ← production_reports",
    }


# ==================== 标准模板程序工单（8D/CAR/退料单等模板一键开单） ====================

async def _ensure_pwo_table(db: AsyncSession):
    from sqlalchemy import text as sa_text
    # asyncpg 不支持多语句一次执行，逐条下发
    await db.execute(sa_text("""
        CREATE TABLE IF NOT EXISTS program_work_orders (
            id VARCHAR(50) PRIMARY KEY,
            factory_id VARCHAR(50),
            pwo_code VARCHAR(50) NOT NULL,
            template_code VARCHAR(50) NOT NULL,
            template_name VARCHAR(120),
            module VARCHAR(30),
            title VARCHAR(300) NOT NULL,
            priority VARCHAR(20) DEFAULT 'medium',
            status VARCHAR(20) DEFAULT 'open',
            form_data JSONB DEFAULT '{}'::jsonb,
            source_ticket_id VARCHAR(50),
            created_by VARCHAR(80),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            closed_at TIMESTAMP,
            closed_by VARCHAR(80)
        )
    """))
    await db.execute(sa_text("CREATE INDEX IF NOT EXISTS idx_pwo_factory_status ON program_work_orders(factory_id, status)"))
    await db.execute(sa_text("CREATE INDEX IF NOT EXISTS idx_pwo_template ON program_work_orders(template_code)"))
    await db.commit()  # DDL 先行落盘，避免与后续业务写入同事务


class TemplateCreatePayload(BaseModel):
    factory_id: Optional[str] = None
    template_code: str
    title: str
    priority: Optional[str] = "medium"
    data: Optional[Dict[str, Any]] = None
    metadata_: Optional[Dict[str, Any]] = None


def _resolve_fid(request: Request, current_user: User, payload_fid: Optional[str] = None) -> str:
    return ((request.headers.get("x-factory-id") if request else None)
            or payload_fid
            or getattr(current_user, "active_factory_id", None)
            or current_user.factory_id or "FAC_MECH_001")


@router.post("/work-order-templates/create", summary="基于标准模板创建程序工单（8D/CAR/退料单等）")
async def create_from_template(
    payload: TemplateCreatePayload,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import text as sa_text
    import uuid as _uuid
    fid = _resolve_fid(request, current_user, payload.factory_id)
    # 模板存在性校验（当前厂，允许跨厂公共模板回退）
    tpl = (await db.execute(sa_text("""
        SELECT template_code, template_name, module, default_priority
        FROM work_order_templates
        WHERE template_code=:c AND is_active=true AND (factory_id=:f OR factory_id IS NULL)
        ORDER BY (factory_id=:f) DESC LIMIT 1
    """), {"c": payload.template_code, "f": fid})).fetchone()
    if not tpl:
        raise HTTPException(status_code=404, detail=f"模板不存在或未启用: {payload.template_code}")
    await _ensure_pwo_table(db)
    # 编号：PWO-YYYYMMDD-序号（当日自增）
    seq = (await db.execute(sa_text("""
        SELECT COUNT(*)+1 FROM program_work_orders
        WHERE created_at >= CURRENT_DATE AND factory_id=:f
    """), {"f": fid})).scalar()
    pwo_code = f"PWO-{datetime.now().strftime('%Y%m%d')}-{int(seq):03d}"
    pwo_id = str(_uuid.uuid4())
    meta = payload.metadata_ or {}
    await db.execute(sa_text("""
        INSERT INTO program_work_orders
        (id, factory_id, pwo_code, template_code, template_name, module, title, priority,
         status, form_data, source_ticket_id, created_by)
        VALUES (:id,:f,:code,:tpl,:name,:module,:title,:pri,'open',CAST(:data AS jsonb),:src,:by)
    """), {
        "id": pwo_id, "f": fid, "code": pwo_code, "tpl": tpl[0], "name": tpl[1],
        "module": tpl[2], "title": payload.title, "pri": payload.priority or tpl[3] or "medium",
        "data": json.dumps(payload.data or {}, ensure_ascii=False),
        "src": meta.get("source_ticket_id"), "by": current_user.username,
    })
    await db.commit()
    return {"success": True, "id": pwo_id, "work_order_code": pwo_code,
            "template_code": tpl[0], "template_name": tpl[1], "status": "open"}


@router.get("/work-order-templates/orders", summary="程序工单列表（标准模板开出的 8D/CAR 等单据）")
async def list_program_work_orders(
    request: Request = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import text as sa_text
    fid = _resolve_fid(request, current_user)
    await _ensure_pwo_table(db)
    sql = "SELECT id, pwo_code, template_code, template_name, module, title, priority, status, form_data, created_by, created_at, closed_at FROM program_work_orders WHERE factory_id=:f"
    params: dict = {"f": fid, "limit": limit}
    if status:
        sql += " AND status=:s"
        params["s"] = status
    sql += " ORDER BY created_at DESC LIMIT :limit"
    rows = (await db.execute(sa_text(sql), params)).fetchall()
    return {"items": [{
        "id": r[0], "pwo_code": r[1], "template_code": r[2], "template_name": r[3],
        "module": r[4], "title": r[5], "priority": r[6], "status": r[7],
        "form_data": r[8] if isinstance(r[8], dict) else {},
        "created_by": r[9], "created_at": str(r[10])[:16],
        "closed_at": str(r[11])[:16] if r[11] else None,
    } for r in rows]}


@router.post("/work-order-templates/orders/{order_id}/close", summary="关闭程序工单")
async def close_program_work_order(
    order_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import text as sa_text
    fid = _resolve_fid(request, current_user)
    await _ensure_pwo_table(db)
    res = await db.execute(sa_text("""
        UPDATE program_work_orders SET status='closed', closed_at=NOW(), closed_by=:by, updated_at=NOW()
        WHERE id=:id AND factory_id=:f AND status<>'closed'
    """), {"id": order_id, "f": fid, "by": current_user.username})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="程序工单不存在或已关闭")
    return {"success": True}
