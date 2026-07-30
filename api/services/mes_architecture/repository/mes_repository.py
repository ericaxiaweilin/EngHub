"""MES Repository Module - Absolute Import Version"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime

# Absolute imports
from database.models import WorkOrder, ProductionReport, Product
from api.schemas.mes_schemas import WorkOrderQueryCriteria


class MESRepository:
    """MES data access layer."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def find_work_orders(self, criteria: WorkOrderQueryCriteria) -> List[WorkOrder]:
        query = select(WorkOrder).where(WorkOrder.factory_id == criteria.factory_id)
        
        if criteria.status:
            query = query.where(WorkOrder.status == criteria.status)
        
        if criteria.product_id:
            query = query.join(Product, WorkOrder.product_id == Product.id)
            query = query.where(Product.product_code == criteria.product_id)
        
        offset = (criteria.page - 1) * criteria.size
        query = query.offset(offset=offset).limit(criteria.size).order_by(WorkOrder.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def count_work_orders(self, criteria: WorkOrderQueryCriteria) -> int:
        query = select(func.count()).select_from(WorkOrder).where(WorkOrder.factory_id == criteria.factory_id)
        
        if criteria.status:
            query = query.where(WorkOrder.status == criteria.status)
        
        if criteria.product_id:
            query = query.join(Product, WorkOrder.product_id == Product.id)
            query = query.where(Product.product_code == criteria.product_id)
        
        result = await self.db.execute(query)
        return result.scalar_one()
    
    async def get_work_order_by_id(self, order_id: str) -> Optional[WorkOrder]:
        result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == order_id))
        return result.scalar_one_or_none()
    
    async def update_work_order_status(self, order_id: str, new_status: str, updated_by: Optional[str] = None) -> WorkOrder:
        order = await self.get_work_order_by_id(order_id)
        if not order:
            raise ValueError(f"Work order {order_id} not found")
        
        order.status = new_status
        order.updated_at = datetime.now()
        if updated_by:
            order.updated_by = updated_by
        
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        
        return order
    
    async def create_production_report(self, report_data: Dict[str, Any]) -> ProductionReport:
        report = ProductionReport(
            id=self._generate_uuid(),
            factory_id=report_data["factory_id"],
            work_order_id=report_data["work_order_id"],
            station_id=report_data["station_id"],
            operator_id=report_data["operator_id"],
            created_at=datetime.now(),
            good_qty=report_data["good_qty"],
            defect_qty=report_data["defect_qty"],
            total_qty=report_data["quantity"]
        )
        
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        
        return report
    
    def _generate_uuid(self) -> str:
        import uuid
        return str(uuid.uuid4())