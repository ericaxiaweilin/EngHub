"""
成本核算 Pydantic Schemas
提供工单成本、标准成本和成本分析的数据验证和序列化
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


class WorkOrderCostBase(BaseModel):
    """工单成本基础 Schema"""
    work_order_code: str
    factory_id: str
    product_id: str
    material_cost: Decimal = Field(default=0, ge=0)
    labor_cost: Decimal = Field(default=0, ge=0)
    overhead_cost: Decimal = Field(default=0, ge=0)


class WorkOrderCostCreate(WorkOrderCostBase):
    """创建工单成本 Schema"""
    produced_qty: int = Field(default=0, ge=0)


class WorkOrderCostResponse(WorkOrderCostBase):
    """工单成本响应 Schema"""
    id: str
    work_order_id: str
    produced_qty: int = 0
    total_cost: Decimal = 0
    unit_cost: Decimal = 0
    status: str = "pending"
    calculated_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CostSummaryResponse(BaseModel):
    """成本汇总响应 Schema"""
    total_material_cost: float = 0.0
    total_labor_cost: float = 0.0
    total_overhead_cost: float = 0.0
    total_actual_cost: float = 0.0
    total_standard_cost: float = 0.0
    total_variance: float = 0.0
    avg_variance_rate: float = 0.0


class StandardCostResponse(BaseModel):
    """产品标准成本响应 Schema"""
    id: str
    product_id: str
    factory_id: str
    bom_version: Optional[str] = None
    material_cost: Decimal = 0
    labor_cost: Decimal = 0
    overhead_cost: Decimal = 0
    total_standard_cost: Decimal = 0
    is_active: bool = True
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VarianceAnalysisItem(BaseModel):
    """差异分析项"""
    work_order_id: str
    work_order_code: str
    variance_rate: float
    total_cost: Decimal
    standard_cost: Decimal
    variance: Decimal


class VarianceAnalysisResponse(BaseModel):
    """差异分析响应 Schema"""
    threshold: float
    count: int
    items: List[VarianceAnalysisItem]
