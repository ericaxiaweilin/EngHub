"""MES Routes with Adapter Pattern - Using future annotations to avoid eval issues."""

from __future__ import annotations  # Defer evaluation of type hints
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Imports
from database.db_config import get_db
from api.schemas.mes_schemas import (
    WorkOrderQueryCriteria, WorkOrderResponse,
    WorkOrderUpdateRequest, ProductionReportRequest, ProductionReportResponse
)
from api.services.mes_architecture.adapters.mes_adapter import (
    MESAdapter, get_mes_adapter
)

router = APIRouter(prefix="/api/v1/mes", tags=["mes"])


@router.get("/work-orders")
async def list_work_orders(
    db: AsyncSession = Depends(get_db),  # Now safe with future annotations
    factory_id: str = Query("F01", description="Factory ID"),
    status: Optional[str] = Query(None, description="Work order status"),
    product_id: Optional[str] = Query(None, description="Product ID or code"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Items per page"),
    adapter: MESAdapter = Depends(get_mes_adapter),
):
    """List work orders with filtering and pagination."""
    try:
        criteria = WorkOrderQueryCriteria(
            factory_id=factory_id,
            status=status,
            product_id=product_id,
            page=page,
            size=size
        )
        result = await adapter.get_work_orders(criteria)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work-orders/{order_id}/status")
async def update_work_order_status(
    order_id: str,
    request: WorkOrderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    adapter: MESAdapter = Depends(get_mes_adapter),
):
    """Update work order status through validated state transition."""
    try:
        result = await adapter.update_work_order_status(request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/production-reports")
async def create_production_report(
    request: ProductionReportRequest,
    db: AsyncSession = Depends(get_db),
    adapter: MESAdapter = Depends(get_mes_adapter),
):
    """Create a new production report with full validation."""
    try:
        result = await adapter.create_production_report(request.dict())
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))