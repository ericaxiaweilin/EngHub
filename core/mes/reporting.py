"""
MES Production Reporting Service
生产报工模块

功能:
- 正常报工
- 补料报工
- 返工报工
- 产量统计
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class ReportType(str, Enum):
    """报工类型"""
    NORMAL = "normal"           # 正常报工
    ADDITIONAL = "additional"   # 补料报工
    REWORK = "rework"           # 返工报工
    SPECIAL = "special"         # 特殊报工


class Shift(str, Enum):
    """班次"""
    DAY = "day"         # 日班
    NIGHT = "night"     # 夜班
    SHIFT_A = "shift_a"  # A班
    SHIFT_B = "shift_b"  # B班


class ProductionReportingService:
    """
    生产报工服务
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    def generate_report_code(self, work_order_code: str, report_date: str) -> str:
        sequence = "001"
        return f"PR-{work_order_code}-{report_date}-{sequence}"
    
    async def create_report(
        self,
        work_order_id: str,
        work_center_id: str,
        operator_id: str,
        report_type: str = ReportType.NORMAL.value,
        shift: str = Shift.DAY.value,
        quantity_produced: int = 0,
        quantity_qualified: int = 0,
        quantity_rejected: int = 0,
        rejected_reasons: Optional[List[Dict[str, Any]]] = None,
        machine_id: Optional[str] = None,
        hours_worked: Optional[float] = None,
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        report_id = str(uuid.uuid4())
        report_code = self.generate_report_code(
            work_order_code="WO001",
            report_date=datetime.now().strftime("%Y%m%d")
        )
        
        report = {
            "id": report_id,
            "report_code": report_code,
            "work_order_id": work_order_id,
            "work_center_id": work_center_id,
            "report_date": datetime.now().date(),
            "shift": shift,
            "report_type": report_type,
            "quantity_produced": quantity_produced,
            "quantity_qualified": quantity_qualified,
            "quantity_rejected": quantity_rejected,
            "rejected_reasons": rejected_reasons or [],
            "operator_id": operator_id,
            "machine_id": machine_id,
            "hours_worked": hours_worked,
            "remark": remark,
            "created_at": datetime.now(),
        }
        
        return report
    
    async def validate_report(
        self,
        work_order_id: str,
        quantity_to_report: int,
    ) -> Dict[str, Any]:
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "remaining_qty": 0,
            "total_reported_qty": 0,
        }
        return validation_result
    
    async def detect_report_conflict(
        self,
        work_order_id: str,
        work_center_id: str,
        shift: str,
        report_date: str,
    ) -> Optional[Dict[str, Any]]:
        return None
    
    async def get_reports_by_work_order(
        self,
        work_order_id: str,
    ) -> List[Dict[str, Any]]:
        return []
    
    async def get_reports_by_station(
        self,
        station_id: str,
        shift_date: str,
        shift: str,
    ) -> List[Dict[str, Any]]:
        return []
    
    async def get_daily_summary(
        self,
        factory_id: str,
        report_date: str,
    ) -> Dict[str, Any]:
        summary = {
            "date": report_date,
            "factory_id": factory_id,
            "total_work_orders": 0,
            "total_produced": 0,
            "total_qualified": 0,
            "total_rejected": 0,
            "first_pass_rate": 0.0,
            "stations": [],
        }
        return summary
    
    async def create_additional_material_report(
        self,
        work_order_id: str,
        operator_id: str,
        material_code: str,
        quantity: int,
        reason: str,
    ) -> Dict[str, Any]:
        report = {
            "id": str(uuid.uuid4()),
            "work_order_id": work_order_id,
            "report_type": ReportType.ADDITIONAL.value,
            "material_code": material_code,
            "quantity": quantity,
            "reason": reason,
            "operator_id": operator_id,
            "created_at": datetime.now(),
        }
        return report
    
    async def create_rework_report(
        self,
        original_work_order_id: str,
        operator_id: str,
        rework_quantity: int,
        rework_reason: str,
    ) -> Dict[str, Any]:
        report = {
            "id": str(uuid.uuid4()),
            "original_work_order_id": original_work_order_id,
            "report_type": ReportType.REWORK.value,
            "rework_quantity": rework_quantity,
            "rework_reason": rework_reason,
            "operator_id": operator_id,
            "created_at": datetime.now(),
        }
        return report


__all__ = [
    "ProductionReportingService",
    "ReportType",
    "Shift",
]
