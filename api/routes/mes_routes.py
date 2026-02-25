"""
MES API Routes
工单管理、生产报工、工艺路线、工位管理、设备管理
"""

from fastapi import APIRouter, HTTPException, Header
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["mes"])

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


class WorkOrderUpdate(BaseModel):
    planned_qty: Optional[int] = None
    planned_due: Optional[str] = None
    priority: Optional[str] = None
    station_id: Optional[str] = None
    remark: Optional[str] = None


class WorkOrderSplit(BaseModel):
    split_qty: int
    remark: Optional[str] = None


class ProductionReportCreate(BaseModel):
    factory_id: str
    work_order_id: str
    station_id: str
    good_qty: int
    defect_qty: int = 0
    report_type: str = "normal"
    shift: str = "day"
    operator_id: Optional[str] = None
    remark: Optional[str] = None


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


# --- Work Order Endpoints ---

@router.post("/work-orders")
async def create_work_order(
    wo: WorkOrderCreate,
    x_factory_id: Optional[str] = Header(None)
):
    """创建工单"""
    # TODO: 调用WorkOrderService.create_work_order()
    return {
        "id": "wo-001",
        "work_order_code": "WO-20260224-001",
        "status": "draft",
        "created_at": datetime.now().isoformat()
    }


@router.get("/work-orders")
async def list_work_orders(
    factory_id: str,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """获取工单列表"""
    # TODO: 调用WorkOrderService.list_work_orders()
    return {
        "items": [],
        "total": 0,
        "page": page,
        "page_size": page_size
    }


@router.get("/work-orders/{work_order_id}")
async def get_work_order(work_order_id: str):
    """获取工单详情"""
    # TODO: 调用WorkOrderService.get_work_order()
    return {
        "id": work_order_id,
        "work_order_code": "WO-20260224-001",
        "status": "pending"
    }


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str,
    wo: WorkOrderUpdate
):
    """更新工单"""
    # TODO: 调用WorkOrderService.update_work_order()
    # 检查产能冲突
    return {
        "id": work_order_id,
        "status": "pending",
        "warning": None  # 有冲突时返回提示
    }


@router.post("/work-orders/{work_order_id}/release")
async def release_work_order(work_order_id: str):
    """下达工单"""
    # TODO: 检查设备状态
    return {"status": "released"}


@router.post("/work-orders/{work_order_id}/start")
async def start_work_order(work_order_id: str):
    """开始工单"""
    return {"status": "in_progress"}


@router.post("/work-orders/{work_order_id}/complete")
async def complete_work_order(work_order_id: str):
    """完成工单"""
    return {"status": "completed"}


@router.post("/work-orders/{work_order_id}/cancel")
async def cancel_work_order(work_order_id: str, reason: str):
    """取消工单"""
    return {"status": "cancelled"}


@router.post("/work-orders/{work_order_id}/split")
async def split_work_order(
    work_order_id: str,
    data: WorkOrderSplit
):
    """
    拆分工单
    
    规则:
    - 只能拆分 draft/pending 状态的工单
    - 拆分数量 >= 计划数的50%
    """
    # TODO: 验证拆分规则
    # TODO: 调用WorkOrderService.split_work_order()
    return {
        "original_work_order_id": work_order_id,
        "new_work_order_id": "wo-new-001",
        "split_qty": data.split_qty
    }


# --- Production Report Endpoints ---

@router.post("/production-reports")
async def create_production_report(report: ProductionReportCreate):
    """
    创建生产报工
    
    - 报工时自动扣减库存 (BOM计算消耗量)
    - 24小时内可修改
    """
    # TODO: 
    # 1. 验证工单状态
    # 2. 计算物料消耗并扣减库存
    # 3. 创建报工记录
    # 4. 如果有不良品，触发检验
    return {
        "id": "pr-001",
        "status": "submitted",
        "materials_deducted": []  # 物料扣减记录
    }


@router.get("/production-reports")
async def list_production_reports(
    factory_id: str,
    work_order_id: Optional[str] = None,
    station_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """获取报工列表"""
    return {"items": [], "total": 0}


@router.get("/production-reports/{report_id}")
async def get_production_report(report_id: str):
    """获取报工详情"""
    return {"id": report_id}


@router.patch("/production-reports/{report_id}")
async def update_production_report(
    report_id: str,
    report: ProductionReportCreate
):
    """
    修改报工
    
    - 24小时内允许修改
    - 需要输入修改原因
    - 自动重新计算库存变化
    """
    # TODO: 检查是否在24小时内
    # TODO: 重新计算库存调整
    return {
        "id": report_id,
        "status": "modified",
        "inventory_adjustment": {}
    }


@router.post("/production-reports/{report_id}/comments")
async def add_report_comment(
    report_id: str,
    comment: ProductionReportComment
):
    """添加报工Comment (不允许修改时的说明)"""
    return {
        "id": "comment-001",
        "report_id": report_id,
        "comment": comment.comment
    }


@router.get("/production-reports/daily-summary")
async def get_daily_summary(
    factory_id: str,
    station_id: str,
    date: str
):
    """获取日报表"""
    return {
        "date": date,
        "station_id": station_id,
        "total_good_qty": 0,
        "total_defect_qty": 0,
        "reports": []
    }


# --- Station Endpoints ---

@router.post("/stations")
async def create_station(station: StationCreate):
    """创建工位"""
    return {"id": "st-001", "status": "active"}


@router.get("/stations")
async def list_stations(
    factory_id: str,
    station_type: Optional[str] = None,
    status: Optional[str] = None,
):
    """获取工位列表"""
    return {"items": []}


@router.get("/stations/{station_id}")
async def get_station(station_id: str):
    """获取工位详情"""
    return {"id": station_id}


@router.patch("/stations/{station_id}/status")
async def update_station_status(
    station_id: str,
    status: str
):
    """更新工位状态"""
    return {"id": station_id, "status": status}


@router.get("/stations/{station_id}/availability")
async def check_station_availability(station_id: str):
    """
    检查工位可用性
    
    - 检查设备状态
    - 检查产能
    """
    return {
        "can_proceed": True,
        "reason": "设备正常"
    }


# --- Routing Endpoints ---

@router.post("/routings")
async def create_routing(routing: RoutingCreate):
    """创建工艺路线"""
    return {"id": "rt-001"}


@router.get("/routings")
async def list_routings(
    factory_id: str,
    product_id: Optional[str] = None,
):
    """获取工艺路线列表"""
    return {"items": []}


@router.get("/routings/product/{product_id}")
async def get_routing_by_product(product_id: str):
    """获取产品的工艺路线"""
    return {"product_id": product_id, "steps": []}


# --- Equipment Endpoints ---

@router.get("/equipment/{equipment_id}/status")
async def get_equipment_status(equipment_id: str):
    """获取设备状态"""
    return {"id": equipment_id, "status": "running"}


@router.get("/equipment/station/{station_id}/availability")
async def check_equipment_for_station(station_id: str):
    """
    检查工位关联设备是否可用
    
    设备故障时阻止下达工单
    """
    return {
        "can_produce": True,
        "equipment_status": "running"
    }


__all__ = ["router"]
