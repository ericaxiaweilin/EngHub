"""MES Repository Module

Handles all data access operations for MES-related entities.
This layer separates business logic from database operations.
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ....models.work_order import WorkOrder
from ....models.production_report import ProductionReport
from ....schemas.mes_schemas import WorkOrderQueryCriteria


class MESRepository:
    """MES data access layer. All database interactions happen through this class.
    
    Responsibility: CRUD operations on work orders, production reports, etc.
    No business logic here - just persistence.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def find_work_orders(self, criteria: WorkOrderQueryCriteria) -> List[WorkOrder]:
        """Retrieve work orders with filtering, pagination, and ordering."""
        query = select(WorkOrder).where(WorkOrder.factory_id == criteria.factory_id)
        
        if criteria.status:
            query = query.where(WorkOrder.status == criteria.status)
        
        if criteria.product_id:
            # Join to filter by product code/name (simplified)
            from ....models.product import Product
            query = query.join(Product, WorkOrder.product_id == Product.id)
            query = query.where(Product.product_code == criteria.product_id)
        
        # Apply pagination
        offset = (criteria.page - 1) * criteria.size
        query = query.offset(limit=criteria.size).order_by(WorkOrder.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def count_work_orders(self, criteria: WorkOrderQueryCriteria) -> int:
        """Count matching work orders for pagination."""
        query = select(func.count()).select_from(WorkOrder).where(WorkOrder.factory_id == criteria.factory_id)
        
        if criteria.status:
            query = query.where(WorkOrder.status == criteria.status)
        
        if criteria.product_id:
            from ....models.product import Product
            query = query.join(Product, WorkOrder.product_id == Product.id)
            query = query.where(Product.product_code == criteria.product_id)
        
        result = await self.db.execute(query)
        return result.scalar_one()
    
    async def get_work_order_by_id(self, order_id: str) -> Optional[WorkOrder]:
        """Fetch a single work order by ID."""
        result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == order_id))
        return result.scalar_one_or_none()
    
    async def update_work_order_status(self, order_id: str, new_status: str, updated_by: Optional[str] = None) -> WorkOrder:
        """Update work order status within a transaction."""
        order = await self.get_work_order_by_id(order_id)
        if not order:
            raise ValueError(f"Work order {order_id} not found")
        
        old_status = order.status
        order.status = new_status
        order.updated_at = datetime.now()
        if updated_by:
            order.updated_by = updated_by
        
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        
        return order
    
    async def create_production_report(self, report_data: Dict[str, Any]) -> ProductionReport:
        """Create and persist a new production report."""
        from datetime import datetime
        
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
        """Generate a UUID string for primary keys."""
        import uuid
        return str(uuid.uuid4())