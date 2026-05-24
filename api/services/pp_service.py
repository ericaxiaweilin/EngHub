"""
PP API Service Layer
生产计划与物料需求计划服务
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from core.pp.plan import MPSService, PlanStatus
from core.pp.mrp import MRPService, MRPStatus
from database.db_config import db_config
from database.models import ProductionPlan, MRPResult, MRPItem
import uuid


class PPService:
    """生产计划服务层"""
    
    def __init__(self):
        self.mps_service = MPSService()
        self.mrp_service = MRPService()
    
    async def create_plan(
        self,
        factory_id: str,
        product_id: str,
        quantity: int,
        required_date: str,
        sales_order_id: Optional[str] = None,
        customer_level: str = "b",
        priority: int = 50,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """创建生产计划"""
        # 调用核心服务创建计划
        plan_data = await self.mps_service.create_plan(
            factory_id=factory_id,
            product_id=product_id,
            quantity=quantity,
            required_date=datetime.fromisoformat(required_date),
            sales_order_id=sales_order_id,
            customer_level=customer_level,
            priority=priority,
            created_by=created_by,
        )
        
        # 保存到数据库
        async with db_config.session_factory() as db:
            plan = ProductionPlan(**plan_data)
            db.add(plan)
            await db.commit()
            await db.refresh(plan)
            
            return {
                "id": str(plan.id),
                "plan_code": plan.plan_code,
                "status": plan.status,
                "priority_score": float(plan.priority_score) if plan.priority_score else 0,
            }
    
    async def list_plans(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取计划列表"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            query = select(ProductionPlan).where(ProductionPlan.factory_id == factory_id)
            
            if status:
                query = query.where(ProductionPlan.status == status)
            if product_id:
                query = query.where(ProductionPlan.product_id == product_id)
            if from_date:
                query = query.where(ProductionPlan.required_date >= datetime.fromisoformat(from_date))
            if to_date:
                query = query.where(ProductionPlan.required_date <= datetime.fromisoformat(to_date))
            
            # 按优先级分数降序排序
            result = await db.execute(query.order_by(ProductionPlan.priority_score.desc()))
            plans = result.scalars().all()
            
            return [
                {
                    "id": str(p.id),
                    "plan_code": p.plan_code,
                    "product_id": p.product_id,
                    "quantity": p.quantity,
                    "required_date": p.required_date.isoformat() if p.required_date else None,
                    "status": p.status,
                    "priority_score": float(p.priority_score) if p.priority_score else 0,
                    "customer_level": p.customer_level,
                }
                for p in plans
            ]
    
    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划详情"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            stmt = select(ProductionPlan).where(ProductionPlan.id == plan_id)
            result = await db.execute(stmt)
            plan = result.scalar_one_or_none()
            
            if not plan:
                return None
            
            return {
                "id": str(plan.id),
                "plan_code": plan.plan_code,
                "factory_id": plan.factory_id,
                "product_id": plan.product_id,
                "sales_order_id": plan.sales_order_id,
                "quantity": plan.quantity,
                "required_date": plan.required_date.isoformat() if plan.required_date else None,
                "plan_type": plan.plan_type,
                "customer_level": plan.customer_level,
                "priority": plan.priority,
                "priority_score": float(plan.priority_score) if plan.priority_score else 0,
                "status": plan.status,
                "due_date": plan.due_date.isoformat() if plan.due_date else None,
                "confirmed_by": plan.confirmed_by,
                "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
                "released_by": plan.released_by,
                "released_at": plan.released_at.isoformat() if plan.released_at else None,
                "created_at": plan.created_at.isoformat(),
            }
    
    async def confirm_plan(self, plan_id: str, confirmed_by: str) -> Dict[str, Any]:
        """确认计划"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            stmt = select(ProductionPlan).where(ProductionPlan.id == plan_id)
            result = await db.execute(stmt)
            plan = result.scalar_one_or_none()
            
            if not plan:
                raise ValueError("计划不存在")
            
            if plan.status != PlanStatus.DRAFT.value:
                raise ValueError("只有草稿状态的计划可以确认")
            
            plan.status = PlanStatus.CONFIRMED.value
            plan.confirmed_by = confirmed_by
            plan.confirmed_at = datetime.utcnow()
            
            await db.commit()
            await db.refresh(plan)
            
            return {"id": str(plan.id), "status": plan.status}
    
    async def release_plan(self, plan_id: str, released_by: str) -> Dict[str, Any]:
        """下达计划"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            stmt = select(ProductionPlan).where(ProductionPlan.id == plan_id)
            result = await db.execute(stmt)
            plan = result.scalar_one_or_none()
            
            if not plan:
                raise ValueError("计划不存在")
            
            if plan.status != PlanStatus.CONFIRMED.value:
                raise ValueError("只有已确认的计划可以下达")
            
            plan.status = PlanStatus.RELEASED.value
            plan.released_by = released_by
            plan.released_at = datetime.utcnow()
            
            await db.commit()
            await db.refresh(plan)
            
            return {"id": str(plan.id), "status": plan.status}
    
    async def calculate_mrp(self, plan_id: str, target_date: str, created_by: str) -> Dict[str, Any]:
        """计算 MRP"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            # 获取计划
            stmt = select(ProductionPlan).where(ProductionPlan.id == plan_id)
            result = await db.execute(stmt)
            plan = result.scalar_one_or_none()
            
            if not plan:
                raise ValueError("计划不存在")
            
            # 调用核心服务计算 MRP
            mrp_data = await self.mrp_service.calculate_mrp(
                plan_id=plan_id,
                target_date=datetime.fromisoformat(target_date),
            )
            
            # 创建 MRP 结果
            mrp_result = MRPResult(
                id=str(uuid.uuid4()),
                mrp_code=f"MRP-{plan.factory_id}-{datetime.now().strftime('%Y%m%d')}",
                plan_id=plan_id,
                factory_id=plan.factory_id,
                target_date=datetime.fromisoformat(target_date),
                status=MRPStatus.CALCULATED.value,
                total_shortage=mrp_data.get("total_shortage", 0),
                total_value=mrp_data.get("total_value", 0),
                calculated_at=datetime.utcnow(),
                created_by=created_by,
            )
            
            db.add(mrp_result)
            await db.commit()
            await db.refresh(mrp_result)
            
            return {
                "id": str(mrp_result.id),
                "mrp_code": mrp_result.mrp_code,
                "status": mrp_result.status,
            }
    
    async def get_mrp_result(self, mrp_id: str) -> Optional[Dict[str, Any]]:
        """获取 MRP 结果"""
        async with db_config.session_factory() as db:
            from sqlalchemy import select
            
            stmt = select(MRPResult).where(MRPResult.id == mrp_id)
            result = await db.execute(stmt)
            mrp = result.scalar_one_or_none()
            
            if not mrp:
                return None
            
            items_stmt = select(MRPItem).where(MRPItem.mrp_id == mrp_id)
            items_result = await db.execute(items_stmt)
            items = items_result.scalars().all()
            
            return {
                "id": str(mrp.id),
                "mrp_code": mrp.mrp_code,
                "plan_id": str(mrp.plan_id),
                "target_date": mrp.target_date.isoformat() if mrp.target_date else None,
                "status": mrp.status,
                "total_shortage": mrp.total_shortage,
                "total_value": float(mrp.total_value) if mrp.total_value else 0,
                "items": [
                    {
                        "material_id": i.material_id,
                        "material_code": i.material_code,
                        "material_name": i.material_name,
                        "required_qty": i.required_qty,
                        "available_qty": i.available_qty,
                        "shortage_qty": i.shortage_qty,
                        "suggested_qty": i.suggested_qty,
                        "priority": i.priority,
                    }
                    for i in items
                ],
            }
    
    async def analyze_capacity(
        self,
        factory_id: str,
        station_id: str,
        from_date: str,
        to_date: str,
    ) -> Dict[str, Any]:
        """产能负荷分析"""
        result = await self.mps_service.analyze_capacity_load(
            factory_id=factory_id,
            station_id=station_id,
            from_date=datetime.fromisoformat(from_date),
            to_date=datetime.fromisoformat(to_date),
        )
        
        return result
    
    async def get_inventory_alerts(self, factory_id: str) -> List[Dict[str, Any]]:
        """获取库存预警"""
        alerts = await self.mrp_service.get_inventory_alerts(factory_id=factory_id)
        return alerts


__all__ = ["PPService"]
