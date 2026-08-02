"""MES Pydantic Schemas - Data transfer objects for Mes operations."""

from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
from datetime import datetime
from dataclasses import dataclass, asdict


# ─── Pydantic Models (API Request/Response) ────────────────────────

class WorkOrderQueryRequest(BaseModel):
    """Request parameters for querying work orders."""
    
    factory_id: str = Field(default="F01", description="Factory ID")
    status: Optional[str] = None
    product_id: Optional[str] = None
    page: int = Field(default=1, ge=1, description="Page number")
    size: int = Field(default=10, ge=1, le=100, description="Items per page")


class WorkOrderUpdateRequest(BaseModel):
    """Request to update work order status."""
    
    new_status: str = Field(..., description="New status value")
    
    def __root_valid__(cls, values):
        valid_statuses = {"created", "released", "in_progress", "paused", 
                         "resumed", "completed", "cancelled", "rework_needed"}
        if values.get("new_status") not in valid_statuses:
            raise ValueError(f"Invalid status: {values['new_status']}")
        return values


class ProductionReportRequest(BaseModel):
    """Request data for creating a production report."""
    
    factory_id: str = Field(..., description="Factory ID")
    work_order_id: str = Field(..., description="Work order ID to link to")
    station_id: str = Field(..., description="Station where production occurred")
    operator_id: str = Field(..., description="Operator ID who performed the work")
    quantity: int = Field(..., ge=0, description="Total quantity reported")
    good_qty: int = Field(..., ge=0, description="Quantity of good products")
    defect_qty: int = Field(default=0, ge=0, description="Quantity of defective products")


# ─── Response Models ───────────────────────────────────────────────

class WorkOrderResponse(BaseModel):
    """Response model for a single work order."""
    
    work_order_code: str
    product_id: str
    product_name: str
    status: str
    factory_id: str
    station_id: str
    total_qty: int
    good_qty: int
    defect_qty: int
    progress_percent: float
    created_at: Optional[str]
    updated_at: Optional[str]


class ProductionReportResponse(BaseModel):
    """Response model for a production report."""
    
    report_code: str
    factory_id: str
    work_order_id: str
    station_id: str
    operator_id: str
    good_qty: int
    defect_qty: int
    total_qty: int
    yield_rate: float
    created_at: str


class WorkOrdersListResponse(BaseModel):
    """Response model for paginated work orders list."""
    
    items: List[WorkOrderResponse]
    total: int
    page: int
    size: int
    factory_id: str


# ─── Internal Data Classes (NOT for API, just for internal parsing) ───

@dataclass
class WorkOrderQueryCriteria:
    """Structured criteria for work order query - internal use only."""
    factory_id: str = "F01"
    status: Optional[str] = None
    product_id: Optional[str] = None
    page: int = 1
    size: int = 10
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)