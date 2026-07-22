"""
PP API Routes
生产计划 (MPS), 物料需求计划 (MRP) — 真实 DB 查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User, Plan

router = APIRouter(prefix="/api/v1", tags=["pp"])


# --- MPS Endpoints ---


class PlanCreate(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    required_date: str
    sales_order_id: Optional[str] = None
    customer_level: str = "b"
    priority: int = 50


@router.get("/plans")
async def list_plans(
    factory_id: str,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取计划列表 (按优先级排序)"""
    query = select(Plan).where(Plan.factory_id == factory_id)

    if status:
        query = query.where(Plan.status == status)
    if product_id:
        query = query.where(Plan.product_id == product_id)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(Plan.priority.desc(), Plan.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    return {
        "items": [_serialize_plan(p) for p in rows],
        "total": total,
    }


@router.post("/plans")
async def create_plan(
    plan: PlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建生产计划"""
    plan_id = f"plan-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    new_plan = Plan(
        plan_code=f"MPS-{plan.factory_id[:8]}-{datetime.utcnow().strftime('%Y%m')}",
        factory_id=plan.factory_id,
        product_id=plan.product_id,
        quantity=plan.quantity,
        required_date=datetime.fromisoformat(plan.required_date),
        sales_order_id=plan.sales_order_id,
        customer_level=plan.customer_level,
        priority=plan.priority,
        status="draft",
        priority_score=float(plan.priority),
        created_by=current_user.username if current_user else "system",
    )
    db.add(new_plan)
    await db.commit()
    await db.refresh(new_plan)
    return _serialize_plan(new_plan)


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取计划详情"""
    p = await db.get(Plan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="计划不存在")
    return _serialize_plan(p)


@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认计划"""
    p = await db.get(Plan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="计划不存在")
    p.status = "confirmed"
    p.confirmed_by = current_user.username if current_user else "system"
    p.confirmed_at = datetime.utcnow()
    p.updated_at = datetime.utcnow()
    await db.commit()
    return _serialize_plan(p)


@router.post("/plans/{plan_id}/release")
async def release_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下达计划"""
    p = await db.get(Plan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="计划不存在")
    p.status = "released"
    p.released_by = current_user.username if current_user else "system"
    p.released_at = datetime.utcnow()
    p.updated_at = datetime.utcnow()
    await db.commit()
    return _serialize_plan(p)


# --- MRP / Capacity stubs (暂无独立表) ---


@router.get("/capacity/analysis")
async def analyze_capacity(
    factory_id: str,
    station_id: str,
    from_date: str,
    to_date: str,
):
    """产能负荷分析"""
    return {
        "station_id": station_id,
        "utilization_rate": 0.85,
        "overloaded_dates": [],
    }


def _serialize_plan(p: Plan) -> dict:
    """序列化计划，字段对齐前端"""
    return {
        "id": p.id,
        "plan_code": p.plan_code,
        "factory_id": p.factory_id,
        "product_id": p.product_id,
        "sales_order_id": p.sales_order_id,
        "quantity": p.quantity,
        "required_date": p.required_date.isoformat() if p.required_date else None,
        "plan_type": p.plan_type,
        "customer_level": p.customer_level,
        "priority": p.priority,
        "status": p.status,
        "due_date": p.due_date.isoformat() if p.due_date else None,
        "priority_score": p.priority_score,
        "confirmed_by": p.confirmed_by,
        "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
        "released_by": p.released_by,
        "released_at": p.released_at.isoformat() if p.released_at else None,
        "created_by": p.created_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


__all__ = ["router"]
