"""
成本核算 API 路由模块
提供工单成本计算、标准成本管理和成本差异分析功能
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime

from database.db_config import get_db
from core.cost.costing import CostingService
from database.models import WorkOrderCost, ProductStandardCost
from api.schemas.cost_schemas import (
    WorkOrderCostResponse,
    WorkOrderCostCreate,
    CostSummaryResponse,
    StandardCostResponse,
)

router = APIRouter(prefix="/api/costs", tags=["Cost Management"])


@router.get("/work-orders", response_model=List[WorkOrderCostResponse])
async def get_work_order_costs(
    skip: int = 0,
    limit: int = 100,
    work_order_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取工单成本列表"""
    query = select(WorkOrderCost)
    
    if work_order_id:
        query = query.where(WorkOrderCost.work_order_id == work_order_id)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    costs = result.scalars().all()
    
    return costs


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderCostResponse)
async def get_work_order_cost(
    work_order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取指定工单的成本"""
    result = await db.execute(
        select(WorkOrderCost).where(WorkOrderCost.work_order_id == work_order_id)
    )
    cost = result.scalar_one_or_none()
    
    if not cost:
        # 如果不存在，尝试计算
        costing_service = CostingService(db)
        cost = await costing_service.calculate_work_order_cost(work_order_id)
    
    return cost


@router.post("/work-orders/{work_order_id}/calculate")
async def calculate_work_order_cost(
    work_order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """手动触发工单成本计算"""
    try:
        costing_service = CostingService(db)
        cost = await costing_service.calculate_work_order_cost(work_order_id)
        
        if not cost:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="工单不存在或无法计算成本"
            )
        
        return {
            "message": "成本计算成功",
            "work_order_id": work_order_id,
            "total_cost": cost.total_actual_cost,
            "variance_rate": cost.variance_rate,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"成本计算失败：{str(e)}"
        )


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取成本汇总统计"""
    query = select(
        func.sum(WorkOrderCost.material_cost).label('total_material_cost'),
        func.sum(WorkOrderCost.labor_cost).label('total_labor_cost'),
        func.sum(WorkOrderCost.overhead_cost).label('total_overhead_cost'),
        func.sum(WorkOrderCost.total_actual_cost).label('total_actual_cost'),
        func.sum(WorkOrderCost.standard_cost).label('total_standard_cost'),
        func.sum(WorkOrderCost.cost_variance).label('total_variance'),
        func.avg(WorkOrderCost.variance_rate).label('avg_variance_rate'),
    )
    
    if start_date and end_date:
        # 需要通过 work_order_id 关联工单的创建时间
        # 这里简化处理，实际应该 JOIN work_orders 表
        pass
    
    result = await db.execute(query)
    row = result.first()
    
    return CostSummaryResponse(
        total_material_cost=float(row.total_material_cost or 0),
        total_labor_cost=float(row.total_labor_cost or 0),
        total_overhead_cost=float(row.total_overhead_cost or 0),
        total_actual_cost=float(row.total_actual_cost or 0),
        total_standard_cost=float(row.total_standard_cost or 0),
        total_variance=float(row.total_variance or 0),
        avg_variance_rate=float(row.avg_variance_rate or 0),
    )


@router.get("/products/{product_id}/standard-cost", response_model=StandardCostResponse)
async def get_product_standard_cost(
    product_id: int,
    version: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取产品标准成本"""
    query = select(ProductStandardCost).where(
        ProductStandardCost.product_id == product_id
    )
    
    if version:
        query = query.where(ProductStandardCost.version == version)
    else:
        # 默认获取最新版本
        query = query.order_by(ProductStandardCost.version.desc()).limit(1)
    
    result = await db.execute(query)
    standard_cost = result.scalar_one_or_none()
    
    if not standard_cost:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="产品标准成本未找到"
        )
    
    return standard_cost


@router.post("/products/{product_id}/standard-cost")
async def update_product_standard_cost(
    product_id: int,
    cost_data: WorkOrderCostCreate,
    db: AsyncSession = Depends(get_db),
):
    """更新产品标准成本"""
    try:
        costing_service = CostingService(db)
        standard_cost = await costing_service.update_standard_cost(
            product_id=product_id,
            cost_data=cost_data,
        )
        
        return {
            "message": "标准成本更新成功",
            "product_id": product_id,
            "new_standard_cost": standard_cost.standard_cost,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新标准成本失败：{str(e)}"
        )


@router.get("/variance/analysis")
async def get_variance_analysis(
    threshold: float = 5.0,
    db: AsyncSession = Depends(get_db),
):
    """获取成本差异分析报告（差异率超过阈值的工单）"""
    result = await db.execute(
        select(WorkOrderCost)
        .where(func.abs(WorkOrderCost.variance_rate) > threshold)
        .order_by(WorkOrderCost.variance_rate.desc())
    )
    
    high_variance_costs = result.scalars().all()
    
    return {
        "threshold": threshold,
        "count": len(high_variance_costs),
        "items": high_variance_costs,
    }
