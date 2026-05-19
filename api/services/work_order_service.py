"""
WorkOrder Service - 工单管理服务
处理工单相关的业务逻辑
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import WorkOrder, ProductionReport


class WorkOrderService:
    """工单服务类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_work_order_by_id(self, work_order_id: str) -> Optional[WorkOrder]:
        """根据 ID 获取工单"""
        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id)
        )
        return result.scalar_one_or_none()
    
    async def get_work_order_by_code(self, work_order_code: str) -> Optional[WorkOrder]:
        """根据工单号获取工单"""
        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.work_order_code == work_order_code)
        )
        return result.scalar_one_or_none()
    
    async def create_work_order(
        self,
        factory_id: str,
        product_id: str,
        planned_qty: int,
        planned_due: datetime,
        priority: str = "medium",
        sales_order_id: Optional[str] = None,
        routing_id: Optional[str] = None,
        assigned_station_id: Optional[str] = None,
        bom_version: Optional[str] = None,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> WorkOrder:
        """创建工单"""
        # 生成工单号
        work_order_code = f"WO-{datetime.now().strftime('%Y%m%d')}-{await self._get_next_wo_number(factory_id)}"
        
        work_order = WorkOrder(
            work_order_code=work_order_code,
            factory_id=factory_id,
            product_id=product_id,
            planned_qty=planned_qty,
            planned_due=planned_due,
            status="draft",
            priority=priority,
            sales_order_id=sales_order_id,
            routing_id=routing_id,
            assigned_station_id=assigned_station_id,
            bom_version=bom_version,
            remark=remark,
            created_by=created_by,
        )
        
        self.db.add(work_order)
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def _get_next_wo_number(self, factory_id: str) -> int:
        """获取下一个工单序号"""
        today = datetime.now().date()
        result = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                func.date(WorkOrder.created_at) == today
            )
        )
        count = result.scalar() or 0
        return count + 1
    
    async def list_work_orders(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        priority: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[WorkOrder]:
        """获取工单列表"""
        query = select(WorkOrder).where(WorkOrder.factory_id == factory_id)
        
        if status:
            query = query.where(WorkOrder.status == status)
        if product_id:
            query = query.where(WorkOrder.product_id == product_id)
        if priority:
            query = query.where(WorkOrder.priority == priority)
        
        query = query.order_by(WorkOrder.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_work_order(
        self,
        work_order_id: str,
        **kwargs
    ) -> Optional[WorkOrder]:
        """更新工单"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        # 只允许更新特定状态的工单
        if work_order.status in ["completed", "cancelled"]:
            raise ValueError(f"Cannot update work order with status {work_order.status}")
        
        allowed_fields = [
            "planned_qty", "planned_due", "priority", "assigned_station_id",
            "routing_id", "bom_version", "remark"
        ]
        
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None:
                setattr(work_order, field, kwargs[field])
        
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def release_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """下达工单"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != "draft":
            raise ValueError(f"Can only release draft work orders, current status: {work_order.status}")
        
        work_order.status = "pending"
        work_order.planned_start = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def start_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """开始工单"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status not in ["pending", "released"]:
            raise ValueError(f"Can only start pending/released work orders")
        
        work_order.status = "in_progress"
        work_order.actual_start = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def complete_work_order(
        self, 
        work_order_id: str,
        completed_qty: int = None,
        good_qty: int = None,
        defect_qty: int = None,
    ) -> Optional[WorkOrder]:
        """完成工单"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != "in_progress":
            raise ValueError(f"Can only complete in_progress work orders")
        
        # 如果有数量信息，更新工单
        if completed_qty is not None:
            work_order.completed_qty = completed_qty
        if good_qty is not None:
            work_order.good_qty = good_qty
        if defect_qty is not None:
            work_order.defect_qty = defect_qty
        
        work_order.status = "completed"
        work_order.actual_complete = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def cancel_work_order(self, work_order_id: str, reason: str) -> Optional[WorkOrder]:
        """取消工单"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status in ["completed", "cancelled"]:
            raise ValueError(f"Cannot cancel work order with status {work_order.status}")
        
        work_order.status = "cancelled"
        work_order.remark = f"{work_order.remark or ''}\n[Cancelled]: {reason}"
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        
        return work_order
    
    async def split_work_order(
        self,
        work_order_id: str,
        split_qty: int,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> tuple[WorkOrder, WorkOrder]:
        """
        拆分工单
        返回 (原工单，新工单)
        """
        original_wo = await self.get_work_order_by_id(work_order_id)
        if not original_wo:
            raise ValueError("Work order not found")
        
        if original_wo.status not in ["draft", "pending"]:
            raise ValueError(f"Can only split draft/pending work orders")
        
        if split_qty >= original_wo.planned_qty:
            raise ValueError("Split quantity must be less than planned quantity")
        
        if split_qty < original_wo.planned_qty * 0.5:
            raise ValueError("Split quantity must be at least 50% of planned quantity")
        
        # 创建新工单
        new_wo = await self.create_work_order(
            factory_id=original_wo.factory_id,
            product_id=original_wo.product_id,
            planned_qty=split_qty,
            planned_due=original_wo.planned_due,
            priority=original_wo.priority,
            sales_order_id=original_wo.sales_order_id,
            routing_id=original_wo.routing_id,
            assigned_station_id=original_wo.assigned_station_id,
            bom_version=original_wo.bom_version,
            remark=f"Split from {original_wo.work_order_code}. {remark or ''}",
            created_by=created_by,
        )
        
        # 更新原工单数量
        original_wo.planned_qty -= split_qty
        original_wo.remark = f"{original_wo.remark or ''}\n[Split]: Created {new_wo.work_order_code} with qty {split_qty}"
        original_wo.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(original_wo)
        
        return original_wo, new_wo
