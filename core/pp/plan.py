"""
PP Master Production Schedule (MPS) Service - Database Persistent Version
主生产计划模块（持久化版）

功能:
- 计划创建/查询
- 交期优先+客户等级排程
- 产能负荷分析
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set
from enum import Enum

from sqlalchemy import select, update, delete, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.pp.change_management import (
    ChangeManagementService,
    ChangeRequestStatus,
    ChangeRequestLevel,
    ChangeRequest,
    PlanVersion
)

from database.models import Plan


class PlanStatus(str, Enum):
    """计划状态"""
    DRAFT = "draft"           # 草稿
    CONFIRMED = "confirmed"   # 已确认
    RELEASED = "released"     # 已下达
    IN_PROGRESS = "in_progress"  # 执行中
    COMPLETED = "completed"   # 已完成
    CANCELLED = "cancelled"   # 已取消


class PlanType(str, Enum):
    """计划类型"""
    MPS = "mps"         # 主生产计划
    FORECAST = "forecast"  # 预测


class CustomerLevel(str, Enum):
    """客户等级 (用于排程优先级)"""
    VIP = "vip"       # VIP客户
    A = "a"           # A级客户
    B = "b"           # B级客户
    C = "c"           # C级客户


class MPSService:
    """
    主生产计划服务 (数据库持久化版)
    
    核心功能:
    - 创建/修改生产计划 (持久化到 pp_plans 表)
    - 排程: 交期优先 + 客户等级
    - 产能负荷分析
    
    使用 SQLAlchemy 与数据库直接交互，生产环境建议传入 db_session。
    """
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
        self.change_mgmt = ChangeManagementService()
        
        # === APS 智能联动配置 ===
        self.aps_auto_trigger_enabled = False  # 是否启用 MRP 后触发 APS 重排
        self.aps_shortage_threshold_items = 2   # 触发 APS 的短缺项数阈值（≥此值则触发）
        self.aps_shortage_threshold_qty_ratio = 0.5  # 触发 APS 的短缺比例阈值
        self.aps_override_horizon_days = 7      # APS 覆盖的时间范围（天）
        self.aps_optimize_for = "delivery"      # 优化目标 (delivery/efficiency/cost)
        
        # 产品工时定额（小时/台）- 可从数据库或配置加载
        self._product_std_hours: Dict[str, float] = {
            "PRODUCT-A": 2.5,
            "PRODUCT-B": 3.0,
            "PRODUCT-C": 1.8,
        }
    
    async def _get_db(self) -> AsyncSession:
        """获取数据库会话，如无则抛出异常"""
        if self.db is None:
            raise RuntimeError("MPSService requires a database session for operation")
        return self.db
    
    async def _insert_plan(self, plan_data: Dict[str, Any]) -> str:
        """插入新计划到数据库，返回 plan_id"""
        db = await self._get_db()
        
        plan_id = str(uuid.uuid4())
        plan_code = self.generate_plan_code(plan_data["factory_id"])
        plan_data["id"] = plan_id
        plan_data["plan_code"] = f"{plan_code}-{self._get_next_plan_number(plan_data['factory_id']):03d}"
        plan_data["created_at"] = datetime.utcnow()
        plan_data["updated_at"] = datetime.utcnow()
        
        # 从 plan_data 构建 Plan ORM 对象
        from database.models import Plan
        # 注意：需要根据 Plan model 的属性映射数据
        plan_obj = Plan(
            id=plan_id,
            factory_id=plan_data["factory_id"],
            plan_code=plan_data["plan_code"],
            plan_type=plan_data["plan_type"],
            product_id=plan_data["product_id"],
            sales_order_id=plan_data.get("sales_order_id"),
            quantity=plan_data["quantity"],
            required_date=plan_data["required_date"].date() if isinstance(plan_data["required_date"], datetime) else plan_data["required_date"],
            due_date=plan_data["due_date"].date() if isinstance(plan_data["due_date"], datetime) else plan_data["due_date"],
            customer_level=plan_data["customer_level"],
            priority=plan_data["priority"],
            priority_score=plan_data["priority_score"],
            status=plan_data["status"],
            created_by=plan_data.get("created_by"),
            updated_by=plan_data.get("created_by"),
        )
        
        db.add(plan_obj)
        await db.commit()
        await db.refresh(plan_obj)
        
        return plan_id
    
    async def _update_plan(self, plan_id: str, updates: Dict[str, Any]) -> bool:
        """更新计划字段，返回是否成功"""
        db = await self._get_db()
        
        update_stmt = update(Plan).where(Plan.id == plan_id).values({
            k: v for k, v in updates.items() if v is not None and k != 'id'
        })
        update_stmt = update_stmt.updated_at(datetime.utcnow())
        result = await db.execute(update_stmt)
        await db.commit()
        return result.rowcount > 0
    
    async def _get_plan_by_id(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """通过 plan_id 获取计划详情"""
        if self.db is None:
            return None  # 在内存模式下这会不同
        
        db = await self._get_db()
        query = select(Plan).where(Plan.id == plan_id)
        result = await db.execute(query)
        plan = result.scalar_one_or_none()
        
        if plan:
            return self._plan_to_dict(plan)
        return None
    
    async def _get_plans_by_factory(
        self,
        factory_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """按工厂获取计划列表"""
        if self.db is None:
            return []
        
        db = await self._get_db()
        query = select(Plan).where(Plan.factory_id == factory_id)
        
        if status:
            query = query.where(Plan.status == status)
        
        query = query.order_by(desc(Plan.priority_score)).limit(limit).offset(offset)
        result = await db.execute(query)
        plans = result.scalars().all()
        
        return [self._plan_to_dict(p) for p in plans]
    
    async def _delete_plan(self, plan_id: str) -> bool:
        """逻辑删除计划（置为cancelled）"""
        if self.db is None:
            return False
        
        db = await self._get_db()
        update_stmt = update(Plan).where(Plan.id == plan_id).values(
            status=PlanStatus.CANCELLED.value,
            updated_at=datetime.utcnow(),
        )
        result = await db.execute(update_stmt)
        await db.commit()
        return result.rowcount > 1
    
    def _plan_to_dict(self, plan_obj) -> Dict[str, Any]:
        """将 Plan ORM 对象转换为字典"""
        return {
            "id": plan_obj.id,
            "plan_code": plan_obj.plan_code,
            "factory_id": plan_obj.factory_id,
            "product_id": plan_obj.product_id,
            "sales_order_id": plan_obj.sales_order_id,
            "quantity": plan_obj.quantity,
            "required_date": plan_obj.required_date,
            "due_date": plan_obj.due_date,
            "customer_level": plan_obj.customer_level,
            "priority": plan_obj.priority,
            "priority_score": float(plan_obj.priority_score) if plan_obj.priority_score else None,
            "status": plan_obj.status,
            "station_id": plan_obj.station_id,
            "scheduled_start_date": plan_obj.scheduled_start_date,
            "scheduled_end_date": plan_obj.scheduled_end_date,
            "mrp_status": plan_obj.mrp_status,
            "created_by": plan_obj.created_by,
            "updated_by": plan_obj.updated_by,
            "confirmed_by": plan_obj.confirmed_by,
            "released_by": plan_obj.released_by,
            "confirmed_at": plan_obj.confirmed_at,
            "released_at": plan_obj.released_at,
            "created_at": plan_obj.created_at,
            "updated_at": plan_obj.updated_at,
        }
    
    def _get_next_plan_number(self, factory_id: str) -> int:
        """获取下一个计划编号（内存模拟）"""
        # 实际应从数据库计数获取
        return 1  # 简化处理
    
    def generate_plan_code(self, factory_id: str) -> str:
        """生成计划编码前缀"""
        return f"MPS-{factory_id}"
    
    async def create_plan(
        self,
        factory_id: str,
        product_id: str,
        quantity: int,
        required_date: datetime,
        plan_type: str = PlanType.MPS.value,
        sales_order_id: Optional[str] = None,
        customer_level: str = CustomerLevel.B.value,
        priority: int = 50,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """创建生产计划 - 持久化到数据库"""
        plan_id = await self._insert_plan({
            "factory_id": factory_id,
            "product_id": product_id,
            "quantity": quantity,
            "required_date": required_date,
            "plan_type": plan_type,
            "sales_order_id": sales_order_id,
            "customer_level": customer_level,
            "priority": priority,
            "status": PlanStatus.DRAFT.value,
            "due_date": required_date,
            "created_by": created_by,
            "priority_score": self._calculate_priority_score(
                required_date=required_date,
                customer_level=customer_level,
                priority=priority
            ),
            "estimated_hours": self._estimate_plan_hours(product_id, quantity),
        })
        
        plan = await self.get_plan(plan_id)
        
        # 创建初始版本（版本 1）
        self.change_mgmt.add_version(
            plan_id=plan_id,
            version=1,
            user=created_by,
            action="create",
            description=f"创建生产计划 {plan['plan_code']}",
        )
        
        return plan
    
    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划详情 - 从数据库查询"""
        if self.db is None:
            return None
        return await self._get_plan_by_id(plan_id)
    
    async def update_plan_partial(
        self,
        plan_id: str,
        updates: Dict[str, Any],
        updated_by: str = None,
    ) -> bool:
        """部分更新计划字段"""
        if self.db is None:
            return False
        
        updates["updated_at"] = datetime.utcnow()
        if updated_by:
            updates["updated_by"] = updated_by
        
        return await self._update_plan(plan_id, updates)
    
    async def list_plans(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取计划列表 (支持按状态和物料过滤，按优先级排序)"""
        if self.db is None:
            return []
        
        db = await self._get_db()
        query = select(Plan).where(Plan.factory_id == factory_id)
        
        if status:
            query = query.where(Plan.status == status)
        if product_id:
            query = query.where(Plan.product_id == product_id)
        
        query = query.order_by(desc(Plan.priority_score)).limit(limit)
        result = await db.execute(query)
        plans = result.scalars().all()
        
        return [self._plan_to_dict(p) for p in plans]
    
    async def confirm_plan(
        self,
        plan_id: str,
        confirmed_by: str,
    ) -> Dict[str, Any]:
        """确认生产计划 - 持久化更新"""
        if self.db is None:
            raise RuntimeError("Database session required for confirm_plan")
        
        plan = await self._get_plan_by_id(plan_id)
        if not plan:
            raise ValueError("计划不存在")
        
        if plan["status"] != PlanStatus.DRAFT.value:
            raise ValueError("只有草稿状态的计划可以确认")
        
        # 更新数据库
        success = await self._update_plan(plan_id, {
            "status": PlanStatus.CONFIRMED.value,
            "confirmed_by": confirmed_by,
            "confirmed_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "updated_by": confirmed_by,
        })
        
        if success:
            self.change_mgmt.add_version(
                plan_id=plan_id,
                version=self.change_mgmt.get_current_version(plan_id) + 1 if self.change_mgmt.get_current_version(plan_id) else 2,
                user=confirmed_by,
                action="confirm",
                description=f"确认生产计划 {plan['plan_code']}",
            )
        
        return await self.get_plan(plan_id)
    
    async def release_plan(
        self,
        plan_id: str,
        released_by: str,
        trigger_aps: bool = True,
    ) -> Dict[str, Any]:
        """下达生产计划（持久化）"""
        if self.db is None:
            raise RuntimeError("Database session required for release_plan")
        
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError("计划不存在")
        
        if plan["status"] != PlanStatus.CONFIRMED.value:
            raise ValueError("只有已确认的计划可以下达")
        
        # 检查产能冲突
        conflicts = await self.detect_capacity_conflict(plan_id)
        if conflicts:
            plan["release_warning"] = f"检测到{len(conflicts)}个产能冲突"
        
        # 更新数据库
        success = await self._update_plan(plan_id, {
            "status": PlanStatus.RELEASED.value,
            "released_by": released_by,
            "released_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "updated_by": released_by,
        })
        
        if success:
            # 生成MES工单（通过API层调用）
            # 异步触发APS排程（如果启用）
            if trigger_aps and self.aps_auto_trigger_enabled:
                import asyncio
                asyncio.create_task(self._trigger_automated_aps(plan_id, released_by))
        
        return await self.get_plan(plan_id)
    
    async def complete_plan(self, plan_id: str, completed_by: str) -> Dict[str, Any]:
        """完成生产计划 - 持久化更新"""
        if self.db is None:
            raise RuntimeError("Database session required for complete_plan")
        
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError("计划不存在")
        
        if plan["status"] not in [PlanStatus.RELEASED.value, PlanStatus.IN_PROGRESS.value]:
            raise ValueError("只能完成正在执行的计划")
        
        success = await self._update_plan(plan_id, {
            "status": PlanStatus.COMPLETED.value,
            "completed_by": completed_by,
            "completed_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "updated_by": completed_by,
        })
        
        if success:
            return await self.get_plan(plan_id)
        raise RuntimeError("计划更新失败")
    
    async def cancel_plan(self, plan_id: str, cancelled_by: str, reason: str = "") -> Dict[str, Any]:
        """取消生产计划（软删除）"""
        if self.db is None:
            raise RuntimeError("Database session required for cancel_plan")
        
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError("计划不存在")
        
        if plan["status"] in [PlanStatus.COMPLETED.value, PlanStatus.CANCELLED.value]:
            raise ValueError("计划已完成或已取消，无法再次取消")
        
        success = await self._update_plan(plan_id, {
            "status": PlanStatus.CANCELLED.value,
            "cancelled_by": cancelled_by,
            "cancelled_at": datetime.utcnow(),
            "update_reason": reason,
            "updated_at": datetime.utcnow(),
            "updated_by": cancelled_by,
        })
        
        if success:
            return await self.get_plan(plan_id)
        raise RuntimeError("计划取消失败")
    
    async def detect_capacity_conflict(self, plan_id: str) -> List[Dict[str, Any]]:
        """检测产能冲突 - 检查计划所需工站的负荷情况"""
        plan = await self.get_plan(plan_id)
        if not plan:
            return []
        
        conflicts = []
        # 此处应连接MES系统查询实际工站负荷
        # 简化实现：无实际数据时返回空列表
        return conflicts
    
    def _calculate_priority_score(
        self,
        required_date: datetime,
        customer_level: str,
        priority: int,
    ) -> float:
        """计算计划优先级分数（基于交期紧迫度、客户等级、自定义优先级）"""
        now = datetime.now()
        days_until_deadline = max(1, (required_date - now).days)
        
        # 交期紧迫度得分（越临近分数越高）
        due_score = min(100, max(0, (30 - days_until_deadline) * 2))
        
        # 客户等级得分
        level_scores = {"vip": 50, "a": 40, "b": 20, "c": 10}
        level_score = level_scores.get(customer_level.lower(), 10)
        
        # 自定义优先级（归一化到0-50）
        priority_score = min(max(priority, 0), 50)
        
        total = due_score + level_score + priority_score
        return round(min(total, 150), 1)
    
    def _estimate_plan_hours(self, product_id: str, quantity: int) -> float:
        """估算计划所需工时"""
        std_hours = self._product_std_hours.get(product_id, 2.0)
        return round(std_hours * quantity, 2)
    
    async def _trigger_automated_aps(self, plan_id: str, user: str):
        """异步触发APS排程（后台任务）"""
        try:
            print(f"[APS Trigger] 为计划 {plan_id} 触发自动APS排程...")
        except Exception as e:
            print(f"[APS Trigger] 触发失败: {e}")


__all__ = ["MPSService", "PlanStatus", "PlanType", "CustomerLevel"]