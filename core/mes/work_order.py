"""
MES Work Order Service - Production Implementation
生产工单管理模块 (完整实现)

功能:
- 工单 CRUD 操作
- 工单状态流转
- 工单与订单关联
- 数据库集成
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import WorkOrder as WorkOrderModel


class WorkOrderStatus(str, Enum):
    """工单状态枚举"""
    PENDING = "pending"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    PENDING_INBOUND = "pending_inbound"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class WorkOrderPriority(str, Enum):
    """工单优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class WorkOrderService:
    """生产工单服务"""
    
    VALID_STATUS_TRANSITIONS = {
        WorkOrderStatus.PENDING.value: [WorkOrderStatus.RELEASED.value, WorkOrderStatus.CANCELLED.value],
        WorkOrderStatus.RELEASED.value: [WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.ON_HOLD.value, WorkOrderStatus.CANCELLED.value],
        WorkOrderStatus.IN_PROGRESS.value: [WorkOrderStatus.COMPLETED.value, WorkOrderStatus.ON_HOLD.value],
        WorkOrderStatus.ON_HOLD.value: [WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.CANCELLED.value],
        WorkOrderStatus.PENDING_INBOUND.value: [WorkOrderStatus.COMPLETED.value],
    }
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    def generate_work_order_code(self, factory_code: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        sequence = str(uuid.uuid4())[:6].upper()
        return f"WO-{factory_code}-{today}-{sequence}"
    
    async def create_work_order(
        self, factory_id: str, product_id: str, planned_qty: int, created_by: str,
        sales_order_id: Optional[str] = None, routing_id: Optional[str] = None,
        priority: str = "medium", planned_start: Optional[datetime] = None,
        planned_due: Optional[datetime] = None, assigned_station_id: Optional[str] = None,
        remark: Optional[str] = None, bom_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        work_order_id = uuid.uuid4()
        work_order_code = self.generate_work_order_code(factory_code=factory_id[:3].upper())
        
        work_order = WorkOrderModel(
            id=work_order_id, work_order_code=work_order_code, factory_id=factory_id,
            sales_order_id=sales_order_id, product_id=product_id, routing_id=routing_id,
            planned_qty=planned_qty, unit="pcs", completed_qty=0, good_qty=0,
            defect_qty=0, scrap_qty=0, status=WorkOrderStatus.PENDING.value,
            priority=priority, planned_start=planned_start, planned_due=planned_due,
            assigned_station_id=assigned_station_id, current_routing_step=0,
            bom_version=bom_version, created_by=created_by, remark=remark,
        )
        
        self.db.add(work_order)
        await self.db.commit()
        await self.db.refresh(work_order)
        return self._model_to_dict(work_order)
    
    async def get_work_order(self, work_order_id: str) -> Optional[Dict[str, Any]]:
        result = await self.db.execute(
            select(WorkOrderModel).where(WorkOrderModel.id == work_order_id)
            .options(selectinload(WorkOrderModel.production_reports))
        )
        work_order = result.scalar_one_or_none()
        return self._model_to_dict(work_order) if work_order else None
    
    async def list_work_orders(
        self, factory_id: str, status: Optional[str] = None, product_id: Optional[str] = None,
        station_id: Optional[str] = None, start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None, page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        query = select(WorkOrderModel).where(WorkOrderModel.factory_id == factory_id)
        count_query = select(func.count()).select_from(WorkOrderModel).where(WorkOrderModel.factory_id == factory_id)
        
        for field, value in [("status", status), ("product_id", product_id), ("assigned_station_id", station_id)]:
            if value:
                query = query.where(getattr(WorkOrderModel, field) == value)
                count_query = count_query.where(getattr(WorkOrderModel, field) == value)
        
        if start_date:
            query = query.where(WorkOrderModel.created_at >= start_date)
            count_query = count_query.where(WorkOrderModel.created_at >= start_date)
        if end_date:
            query = query.where(WorkOrderModel.created_at <= end_date)
            count_query = count_query.where(WorkOrderModel.created_at <= end_date)
        
        offset = (page - 1) * page_size
        query = query.order_by(WorkOrderModel.created_at.desc()).offset(offset).limit(page_size)
        
        total = (await self.db.execute(count_query)).scalar()
        items = (await self.db.execute(query)).scalars().all()
        
        return {"items": [self._model_to_dict(item) for item in items], "total": total, "page": page, "page_size": page_size, "total_pages": (total + page_size - 1) // page_size}
    
    async def update_work_order(self, work_order_id: str, updated_by: str, **kwargs) -> Optional[Dict[str, Any]]:
        allowed_fields = {"planned_qty", "planned_due", "priority", "assigned_station_id", "remark", "bom_version"}
        update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not update_data:
            return await self.get_work_order(work_order_id)
        
        update_data.update({"updated_by": updated_by, "updated_at": datetime.utcnow()})
        await self.db.execute(update(WorkOrderModel).where(WorkOrderModel.id == work_order_id).values(**update_data))
        await self.db.commit()
        return await self.get_work_order(work_order_id)
    
    async def _change_status(self, work_order_id: str, new_status: str, operator: str, remark: Optional[str] = None) -> Dict[str, Any]:
        work_order = await self.get_work_order(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        
        current_status = work_order["status"]
        valid_transitions = self.VALID_STATUS_TRANSITIONS.get(current_status, [])
        if new_status not in valid_transitions:
            raise ValueError(f"Invalid status transition from {current_status} to {new_status}")
        
        update_data = {"status": new_status, "updated_by": operator, "updated_at": datetime.utcnow()}
        if remark:
            update_data["remark"] = remark
        
        await self.db.execute(update(WorkOrderModel).where(WorkOrderModel.id == work_order_id).values(**update_data))
        await self.db.commit()
        return await self.get_work_order(work_order_id)
    
    async def release_work_order(self, work_order_id: str, released_by: str) -> Dict[str, Any]:
        return await self._change_status(work_order_id, WorkOrderStatus.RELEASED.value, released_by)
    
    async def start_work_order(self, work_order_id: str, started_by: str) -> Dict[str, Any]:
        await self._change_status(work_order_id, WorkOrderStatus.IN_PROGRESS.value, started_by)
        await self.db.execute(update(WorkOrderModel).where(WorkOrderModel.id == work_order_id).values(actual_start=datetime.utcnow()))
        await self.db.commit()
        return await self.get_work_order(work_order_id)
    
    async def complete_work_order(self, work_order_id: str, completed_by: str) -> Dict[str, Any]:
        await self._change_status(work_order_id, WorkOrderStatus.COMPLETED.value, completed_by)
        await self.db.execute(update(WorkOrderModel).where(WorkOrderModel.id == work_order_id).values(actual_complete=datetime.utcnow()))
        await self.db.commit()
        return await self.get_work_order(work_order_id)
    
    async def cancel_work_order(self, work_order_id: str, cancelled_by: str, reason: str) -> Dict[str, Any]:
        work_order = await self.get_work_order(work_order_id)
        if not work_order or work_order["status"] not in [WorkOrderStatus.PENDING.value, WorkOrderStatus.RELEASED.value]:
            raise ValueError(f"Cannot cancel work order in status {work_order['status'] if work_order else 'not found'}")
        return await self._change_status(work_order_id, WorkOrderStatus.CANCELLED.value, cancelled_by, f"Cancelled: {reason}")
    
    async def get_work_order_progress(self, work_order_id: str) -> Dict[str, Any]:
        work_order = await self.get_work_order(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        
        planned_qty = work_order.get("planned_qty", 0) or 0
        completed_qty = work_order.get("completed_qty", 0) or 0
        good_qty = work_order.get("good_qty", 0) or 0
        
        return {
            "work_order_id": work_order_id, "status": work_order.get("status"),
            "planned_qty": planned_qty, "completed_qty": completed_qty, "good_qty": good_qty,
            "defect_qty": work_order.get("defect_qty", 0),
            "completion_rate": round((completed_qty / planned_qty * 100) if planned_qty > 0 else 0, 2),
            "yield_rate": round((good_qty / completed_qty * 100) if completed_qty > 0 else 0, 2),
        }
    
    def _model_to_dict(self, model: WorkOrderModel) -> Dict[str, Any]:
        return {
            "id": str(model.id), "work_order_code": model.work_order_code, "factory_id": model.factory_id,
            "sales_order_id": model.sales_order_id, "product_id": model.product_id, "routing_id": model.routing_id,
            "planned_qty": model.planned_qty, "unit": model.unit, "completed_qty": model.completed_qty,
            "good_qty": model.good_qty, "defect_qty": model.defect_qty, "scrap_qty": model.scrap_qty,
            "status": model.status, "priority": model.priority,
            "planned_start": model.planned_start.isoformat() if model.planned_start else None,
            "planned_due": model.planned_due.isoformat() if model.planned_due else None,
            "actual_start": model.actual_start.isoformat() if model.actual_start else None,
            "actual_complete": model.actual_complete.isoformat() if model.actual_complete else None,
            "assigned_station_id": model.assigned_station_id, "current_routing_step": model.current_routing_step,
            "bom_version": model.bom_version, "created_by": model.created_by, "updated_by": model.updated_by,
            "remark": model.remark,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }


__all__ = ["WorkOrderService", "WorkOrderStatus", "WorkOrderPriority"]
