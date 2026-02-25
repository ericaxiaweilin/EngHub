"""
QMS API Routes
检验管理、不良品管理
"""

from fastapi import APIRouter, Header
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["qms"])

# --- Inspection Endpoints ---

class InspectionCreate(BaseModel):
    factory_id: str
    inspection_type: str  # iqc, ipqc, fqc, oqc
    product_id: Optional[str] = None
    material_id: Optional[str] = None
    batch_id: Optional[str] = None
    batch_size: int = 0
    work_order_id: Optional[str] = None
    aql_level: float = 1.0
    inspection_level: str = "general_ii"


class InspectionResultSubmit(BaseModel):
    inspected_qty: int
    defective_qty: int
    defect_details: Optional[List[dict]] = None


@router.post("/inspections")
async def create_inspection(ins: InspectionCreate):
    """
    创建检验单
    
    业务规则:
    - IQC: material_id必填, work_order_id可选
    - IPQC/FQC/OQC: work_order_id必填
    """
    return {
        "id": "ins-001",
        "inspection_code": "INS-F1-IQC-20260224",
        "status": "pending"
    }


@router.get("/inspections")
async def list_inspections(
    factory_id: str,
    inspection_type: Optional[str] = None,
    status: Optional[str] = None,
    work_order_id: Optional[str] = None,
    material_id: Optional[str] = None,
):
    """获取检验单列表"""
    return {"items": [], "total": 0}


@router.get("/inspections/{inspection_id}")
async def get_inspection(inspection_id: str):
    """获取检验单详情"""
    return {"id": inspection_id}


@router.post("/inspections/{inspection_id}/submit")
async def submit_inspection_result(
    inspection_id: str,
    result: InspectionResultSubmit
):
    """
    提交检验结果
    
    - 自动AQL判定
    - 不合格自动创建不良品单
    """
    return {
        "id": inspection_id,
        "status": "passed",  # or failed
        "aql_result": {"result": "pass", "ac": 3, "re": 4},
        "defect_created": False
    }


@router.post("/inspections/{inspection_id}/associate")
async def associate_work_order(
    inspection_id: str,
    work_order_id: str
):
    """将IQC检验单关联到工单"""
    return {"work_order_id": work_order_id}


# --- Defect Endpoints ---

class DispositionSubmit(BaseModel):
    disposition: str  # rework, repair, scrap, concession, return
    disposition_qty: Optional[int] = None
    remark: Optional[str] = None


@router.get("/defects")
async def list_defects(
    factory_id: str,
    status: Optional[str] = None,
    defect_type: Optional[str] = None,
    work_order_id: Optional[str] = None,
    batch_id: Optional[str] = None,
):
    """获取不良品列表"""
    return {"items": [], "total": 0}


@router.get("/defects/{defect_id}")
async def get_defect(defect_id: str):
    """获取不良品详情"""
    return {"id": defect_id}


@router.post("/defects/{defect_id}/disposition")
async def submit_disposition(
    defect_id: str,
    disposition: DispositionSubmit
):
    """提交处置方案"""
    return {
        "id": defect_id,
        "status": "resolved",
        "disposition": disposition.disposition
    }


@router.post("/defects/{defect_id}/ocap")
async def trigger_ocap(defect_id: str):
    """触发OCAP"""
    return {
        "defect_id": defect_id,
        "ocap_status": "triggered",
        "ocap_id": "ocap-001"
    }


@router.get("/defects/batch/{batch_id}/trace")
async def trace_by_batch(batch_id: str):
    """批次追溯"""
    return {
        "batch_id": batch_id,
        "material_info": {},
        "work_orders": [],
        "inspections": [],
        "defects": []
    }


@router.get("/defects/statistics")
async def get_defect_statistics(
    factory_id: str,
    from_date: str,
    to_date: str,
):
    """不良品统计"""
    return {
        "period": f"{from_date} - {to_date}",
        "total_defects": 0,
        "by_type": {},
        "by_station": {}
    }


# --- OCAP Endpoints ---

@router.get("/ocaps")
async def list_ocaps(
    factory_id: str,
    status: Optional[str] = None,
):
    """获取OCAP列表"""
    return {"items": [], "total": 0}


@router.get("/ocaps/{ocap_id}")
async def get_ocap(ocap_id: str):
    """获取OCAP详情"""
    return {"id": ocap_id}


__all__ = ["router"]
