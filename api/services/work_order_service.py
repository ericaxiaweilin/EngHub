"""
WorkOrder Service - 工单管理服务 v2
完整状态机 + 暂停/恢复/待入库 + 统计
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database.models import WorkOrder, ProductionReport


# ============================================================
# 工单状态枚举
# ============================================================
class WOStatus:
    DRAFT = "draft"              # 草稿
    PENDING = "pending"          # 待下发
    RELEASED = "released"        # 已下达
    IN_PROGRESS = "in_progress"  # 生产中
    ON_HOLD = "on_hold"          # 暂停
    PENDING_INBOUND = "pending_inbound"  # 待入库
    COMPLETED = "completed"      # 已完成
    CLOSED = "closed"            # 已关闭
    CANCELLED = "cancelled"      # 已取消

    ALL = [DRAFT, PENDING, RELEASED, IN_PROGRESS, ON_HOLD, PENDING_INBOUND, COMPLETED, CLOSED, CANCELLED]

    DISPLAY = {
        "draft": "草稿",
        "pending": "待下发",
        "released": "已下达",
        "in_progress": "生产中",
        "on_hold": "暂停",
        "pending_inbound": "待入库",
        "completed": "已完成",
        "closed": "已关闭",
        "cancelled": "已取消",
    }

    COLORS = {
        "draft": "default",
        "pending": "processing",
        "released": "blue",
        "in_progress": "blue",
        "on_hold": "warning",
        "pending_inbound": "cyan",
        "completed": "success",
        "closed": "default",
        "cancelled": "error",
    }

    # 状态转移规则：当前状态 -> 可转移到的状态
    TRANSITIONS = {
        "draft": ["pending", "cancelled"],
        "pending": ["released", "cancelled"],
        "released": ["in_progress", "on_hold", "cancelled"],
        "in_progress": ["on_hold", "pending_inbound", "completed", "cancelled"],
        "on_hold": ["in_progress", "cancelled"],
        "pending_inbound": ["completed"],
        "completed": [],
        "closed": [],
        "cancelled": [],
    }


# ============================================================
# 工单优先级
# ============================================================
class WOPriority:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

    DISPLAY = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "urgent": "紧急",
    }

    COLORS = {
        "low": "default",
        "medium": "blue",
        "high": "orange",
        "urgent": "red",
    }


class WorkOrderService:
    """工单服务类 v2"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_work_order_by_id(self, work_order_id: str) -> Optional[WorkOrder]:
        # 预加载报工关联（selectin），避免 async 上下文中同步 lazy-load 报 MissingGreenlet
        result = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.id == work_order_id)
            .options(selectinload(WorkOrder.production_reports))
        )
        return result.scalar_one_or_none()
    
    async def get_work_order_by_code(self, work_order_code: str) -> Optional[WorkOrder]:
        result = await self.db.execute(select(WorkOrder).where(WorkOrder.work_order_code == work_order_code))
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
        work_order_code = f"WO-{datetime.now().strftime('%Y%m%d')}-{await self._get_next_wo_number(factory_id)}"
        
        work_order = WorkOrder(
            work_order_code=work_order_code,
            factory_id=factory_id,
            product_id=product_id,
            planned_qty=planned_qty,
            planned_due=planned_due,
            status=WOStatus.DRAFT,
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
        station_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[WorkOrder]:
        query = select(WorkOrder).where(WorkOrder.factory_id == factory_id)
        
        if status:
            query = query.where(WorkOrder.status == status)
        if product_id:
            query = query.where(WorkOrder.product_id == product_id)
        if priority:
            query = query.where(WorkOrder.priority == priority)
        if station_id:
            query = query.where(WorkOrder.assigned_station_id == station_id)
        
        query = query.order_by(WorkOrder.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_stats(self, factory_id: str) -> Dict[str, Any]:
        """获取工单统计"""
        total = await self.db.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.factory_id == factory_id)
        )
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.created_at >= today_start,
            )
        )
        in_progress = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.IN_PROGRESS,
            )
        )
        overdue = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_([WOStatus.IN_PROGRESS, WOStatus.ON_HOLD]),
                WorkOrder.planned_due < datetime.utcnow(),
            )
        )
        completed_today = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.COMPLETED,
                WorkOrder.updated_at >= today_start,
            )
        )
        pending = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.PENDING,
            )
        )
        
        # 注意：Result.scalar() 读取后即关闭，不能对同一 Result 重复调用，
        # 先统一提取到局部变量再组装返回值
        total_v = total.scalar() or 0
        today_new = today_count.scalar() or 0
        in_progress_v = in_progress.scalar() or 0
        overdue_v = overdue.scalar() or 0
        completed_today_v = completed_today.scalar() or 0
        pending_v = pending.scalar() or 0

        return {
            "total": total_v,
            "today_new": today_new,
            "in_progress": in_progress_v,
            "overdue_risk": overdue_v,
            "completed_today": completed_today_v,
            "pending_release": pending_v,
            "completion_rate_24h": round(
                (completed_today_v / max(today_new, 1)) * 100
            ),
        }
    
    async def update_work_order(
        self, work_order_id: str, **kwargs
    ) -> Optional[WorkOrder]:
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED]:
            raise ValueError(f"Cannot update work order with status {work_order.status}")
        
        allowed_fields = [
            "planned_qty", "planned_due", "priority", "assigned_station_id",
            "routing_id", "bom_version", "remark",
        ]
        
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None:
                setattr(work_order, field, kwargs[field])
        
        work_order.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def release_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """待下发 → 已下达"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.DRAFT:
            raise ValueError(f"只能下达草稿状态的工单，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.RELEASED
        work_order.planned_start = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def start_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """已下达 → 生产中"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status not in [WOStatus.PENDING, WOStatus.RELEASED]:
            raise ValueError(f"只能开工待下发/已下达的工单，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.IN_PROGRESS
        work_order.actual_start = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def pause_work_order(self, work_order_id: str, reason: str = "") -> Optional[WorkOrder]:
        """生产中 → 暂停"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.IN_PROGRESS:
            raise ValueError(f"只能暂停生产中的工单，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.ON_HOLD
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[暂停]: {reason}"
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def resume_work_order(self, work_order_id: str, reason: str = "") -> Optional[WorkOrder]:
        """暂停 → 生产中"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.ON_HOLD:
            raise ValueError(f"只能恢复暂停的工单，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.IN_PROGRESS
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[恢复]: {reason}"
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def mark_pending_inbound(self, work_order_id: str) -> Optional[WorkOrder]:
        """生产中 → 待入库"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.IN_PROGRESS:
            raise ValueError(f"只能将生产中的工单标记为待入库，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.PENDING_INBOUND
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def complete_work_order(
        self, 
        work_order_id: str,
        completed_qty: Optional[int] = None,
        good_qty: Optional[int] = None,
        defect_qty: Optional[int] = None,
    ) -> Optional[WorkOrder]:
        """待入库/生产中 → 已完成"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status not in [WOStatus.IN_PROGRESS, WOStatus.PENDING_INBOUND]:
            raise ValueError(f"只能完成生产中/待入库的工单，当前状态: {work_order.status}")
        
        if completed_qty is not None:
            work_order.completed_qty = completed_qty
        if good_qty is not None:
            work_order.good_qty = good_qty
        if defect_qty is not None:
            work_order.defect_qty = defect_qty
        
        work_order.status = WOStatus.COMPLETED
        work_order.actual_complete = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def close_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """已完成 → 已关闭"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.COMPLETED:
            raise ValueError(f"只能关闭已完成的工单，当前状态: {work_order.status}")
        
        work_order.status = WOStatus.CLOSED
        work_order.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def cancel_work_order(self, work_order_id: str, reason: str) -> Optional[WorkOrder]:
        """取消工单（draft/pending/released/in_progress/on_hold 均可取消）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED]:
            raise ValueError(f"无法取消 {work_order.status} 状态的工单")
        
        work_order.status = WOStatus.CANCELLED
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[取消]: {reason}"
        
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
        original_wo = await self.get_work_order_by_id(work_order_id)
        if not original_wo:
            raise ValueError("Work order not found")
        
        if original_wo.status not in [WOStatus.DRAFT, WOStatus.PENDING, WOStatus.RELEASED]:
            raise ValueError(f"只能拆分草稿/待下发/已下达的工单")
        
        if split_qty >= original_wo.planned_qty:
            raise ValueError("拆分数量必须小于计划数量")
        
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
        
        original_wo.planned_qty -= split_qty
        original_wo.remark = f"{original_wo.remark or ''}\n[Split]: Created {new_wo.work_order_code} with qty {split_qty}"
        original_wo.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(original_wo)
        
        return original_wo, new_wo
    
    async def get_progress(self, work_order: WorkOrder) -> Dict[str, Any]:
        """计算工单进度信息"""
        planned_qty = work_order.planned_qty or 0
        completed_qty = work_order.completed_qty or 0
        good_qty = work_order.good_qty or 0
        defect_qty = work_order.defect_qty or 0
        
        progress_rate = round((completed_qty / planned_qty * 100) if planned_qty > 0 else 0, 1)
        yield_rate = round((good_qty / completed_qty * 100) if completed_qty > 0 else 0, 1)
        
        # 估算剩余时间（基于实际开工时间和当前进度）
        remaining_time = None
        if work_order.actual_start and completed_qty > 0:
            elapsed = datetime.utcnow() - work_order.actual_start
            rate_per_hour = completed_qty / max(elapsed.total_seconds() / 3600, 0.01)
            remaining_qty = planned_qty - completed_qty
            if remaining_qty > 0 and rate_per_hour > 0:
                remaining_hours = remaining_qty / rate_per_hour
                remaining_time = f"{int(remaining_hours)}h {int(remaining_hours % 1 * 60)}m"
        
        return {
            "progress_rate": progress_rate,
            "yield_rate": yield_rate,
            "remaining_qty": max(planned_qty - completed_qty, 0),
            "remaining_time": remaining_time,
            "is_overdue": work_order.planned_due is not None and work_order.planned_due < datetime.utcnow()
                           and work_order.status not in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED],
        }
    
    def to_dict(self, wo: WorkOrder) -> Dict[str, Any]:
        """工单转字典"""
        return {
            "id": str(wo.id),
            "work_order_code": wo.work_order_code,
            "factory_id": wo.factory_id,
            "sales_order_id": wo.sales_order_id,
            "product_id": wo.product_id,
            "routing_id": wo.routing_id,
            "planned_qty": wo.planned_qty,
            "unit": wo.unit,
            "completed_qty": wo.completed_qty,
            "good_qty": wo.good_qty,
            "defect_qty": wo.defect_qty,
            "scrap_qty": wo.scrap_qty,
            "status": wo.status,
            "status_text": WOStatus.DISPLAY.get(wo.status, wo.status),
            "priority": wo.priority,
            "priority_text": WOPriority.DISPLAY.get(wo.priority, wo.priority),
            "planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
            "planned_due": wo.planned_due.isoformat() if wo.planned_due else None,
            "actual_start": wo.actual_start.isoformat() if wo.actual_start else None,
            "actual_complete": wo.actual_complete.isoformat() if wo.actual_complete else None,
            "assigned_station_id": wo.assigned_station_id,
            "current_routing_step": wo.current_routing_step,
            "bom_version": wo.bom_version,
            "created_by": wo.created_by,
            "updated_by": wo.updated_by,
            "remark": wo.remark,
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
            "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
        }
