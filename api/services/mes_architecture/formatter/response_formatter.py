"""Response Formatter Module

Converts internal domain models to response DTOs.
Handles serialization and formatting of responses before returning to clients.
Separates concerns from business logic and data access layers.
"""

from typing import Optional, Dict, Any
from datetime import datetime

from ....models.work_order import WorkOrder
from ....models.production_report import ProductionReport
from ....schemas.mes_schemas import WorkOrderResponse, ProductionReportResponse


class ResponseFormatter:
    """Formatter for converting ORM objects to response DTOs.
    
    Responsibility: Transform domain models into JSON-serializable response formats.
    Does NOT contain business rules or validation logic.
    """
    
    def format_work_order(self, work_order: WorkOrder) -> WorkOrderResponse:
        """Format a WorkOrder object as a response DTO."""
        # Calculate progress percentage (simple version - in production this might be more complex)
        progress = 0.0
        if work_order.total_qty > 0:
            completed = work_order.good_qty + work_order.defect_qty if hasattr(work_order, 'good_qty') else 0
            progress = (completed / work_order.total_qty) * 100
        
        return WorkOrderResponse(
            work_order_code=work_order.work_order_code,
            product_id=work_order.product_id,
            product_name=getattr(work_order, 'product_name', ''),
            status=work_order.status,
            factory_id=work_order.factory_id,
            station_id=getattr(work_order, 'station_id', ''),
            total_qty=getattr(work_order, 'total_qty', 0),
            good_qty=getattr(work_order, 'good_qty', 0),
            defect_qty=getattr(work_order, 'defect_qty', 0),
            progress_percent=round(progress, 2),
            created_at=work_order.created_at.isoformat() if work_order.created_at else None,
            updated_at=work_order.updated_at.isoformat() if work_order.updated_at else None,
        )
    
    def format_production_report(self, report: ProductionReport) -> ProductionReportResponse:
        """Format a ProductionReport object as a response DTO."""
        yield_rate = 0.0
        total = report.good_qty + report.defect_qty
        if total > 0:
            yield_rate = (report.good_qty / total) * 100
        
        return ProductionReportResponse(
            report_code=report.report_code,
            factory_id=report.factory_id,
            work_order_id=report.work_order_id,
            station_id=report.station_id,
            operator_id=report.operator_id,
            good_qty=report.good_qty,
            defect_qty=report.defect_qty,
            total_qty=report.total_qty,
            yield_rate=round(yield_rate, 2),
            created_at=report.created_at.isoformat() if report.created_at else None,
        )
    
    def format_error(self, message: str, status_code: int = 500) -> Dict[str, Any]:
        """Format an error response consistently across all endpoints."""
        return {
            "error": True,
            "status_code": status_code,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }