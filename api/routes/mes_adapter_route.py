"""MES Routes with Adapter Pattern

This file provides the FastAPI routes for MES operations, using the new
MES Adapter pattern to decouple routing from business logic.

All business logic is in api/services/mes_architecture/adapters/mes_adapter.py
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....database.session import get_db  # Assuming this exists
from ....schemas.mes_schemas import (
    WorkOrderQueryCriteria, WorkOrderResponse,
    WorkOrderUpdateRequest, ProductionReportRequest, ProductionReportResponse
)
from ....services.mes_architecture.adapters.mes_adapter import (
    MESAdapter, get_mes_adapter
)

router = APIRouter(prefix="/api/v1/mes", tags=["mes"])


# ────────────────────────────────────────
# Work Order Operations
# ────────────────────────────────────────

@router.get("/work-orders", response_model=dict)
async def list_work_orders(
    db: AsyncSession = Depends(get_db),
    factory_id: str = Query("F01", description="Factory ID"),
    status: Optional[str] = Query(None, description="Work order status"),
    product_id: Optional[str] = Query(None, description="Product ID or code"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, "Items per page"),
    adapter: MESAdapter = Depends(get_mes_adapter)  # DI provides fresh adapter per request
):
    """List work orders with filtering and pagination."""
    
    try:
        # Build criteria object from query params
        criteria = WorkOrderQueryCriteria(
            factory_id=factory_id,
            status=status,
            product_id=product_id,
            page=page,
            size=size
        )
        
        # Delegate to adapter (no business logic here!)
        result = await adapter.get_work_orders(criteria)
        return result
        
    except Exception as e:
        # Log the exception (in production use proper logger)
        print(f"Error listing work orders: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error when fetching work orders"
        )


@router.post("/work-orders/{order_id}/status", response_model=dict)
async def update_work_order_status(
    order_id: str,
    request: WorkOrderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    adapter: MESAdapter = Depends(get_mes_adapter)
):
    """Update work order status through validated state transition."""
    
    try:
        # Validate order_id format (basic check)
        if not order_id or len(order_id) < 3:
            raise HTTPException(status_code=400, detail="Invalid order ID")
        
        result = await adapter.update_work_order_status(request)
        return result
        
    except HTTPException:
        # Re-raise HTTP exceptions (400, 403, 422, etc.)
        raise
    except Exception as e:
        # Catch any unexpected errors
        raise HTTPException(
            status_code=500,
            detail=f"Error updating work order status: {str(e)}"
        )


# ────────────────────────────────────────
# Production Report Operations
# ────────────────────────────────────────

@router.post("/production-reports", response_model=ProductionReportResponse)
async def create_production_report(
    request: ProductionReportRequest,
    db: AsyncSession = Depends(get_db),
    adapter: MESAdapter = Depends(get_mes_adapter)
):
    """Create a new production report with full validation."""
    
    try:
        # Basic validation on input model (pydantic does most of this)
        if not request.factory_id or not request.work_order_id:
            raise HTTPException(status_code=400, detail="Required fields missing")
        
        # Delegate to adapter (recovery strategies applied inside)
        result = await adapter.create_production_report(request.dict())
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creating production report: {str(e)}"
        )