"""
PP Master Production Schedule (MPS) Service
主生产计划模块

功能:
- 计划创建/查询
- 交期优先+客户等级排程
- 产能负荷分析
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum


class PlanStatus(str, Enum):
    """计划状态"""
    DRAFT = "draft"           # 草稿
    CONFIRMED = "confirmed"   # 已确认
    RELEASED = "released"    # 已下达
    IN_PROGRESS = "in_progress"  # 执行中
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消


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
    主生产计划服务
    
    核心功能:
    - 创建/修改生产计划
    - 排程: 交期优先 + 客户等级
    - 产能负荷分析
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    def generate_plan_code(self, factory_code: str) -> str:
        today = datetime.now().strftime("%Y%W")
        return f"MPS-{factory_code}-{today}"
    
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
        """创建生产计划"""
        plan = {
            "id": str(uuid.uuid4()),
            "plan_code": self.generate_plan_code(factory_id),
            "factory_id": factory_id,
            "product_id": product_id,
            "sales_order_id": sales_order_id,
            "quantity": quantity,
            "required_date": required_date,
            "plan_type": plan_type,
            "customer_level": customer_level,
            "priority": priority,
            "status": PlanStatus.DRAFT.value,
            "due_date": required_date,
            "created_by": created_by,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        # 计算优先级分数 = 交期紧迫度 + 客户等级权重
        plan["priority_score"] = self._calculate_priority_score(
            required_date=required_date,
            customer_level=customer_level,
            priority=priority
        )
        
        return plan
    
    def _calculate_priority_score(
        self,
        required_date: datetime,
        customer_level: str,
        priority: int,
    ) -> float:
        """
        计算优先级分数
        
        公式: 交期紧迫度(0-100) + 客户等级权重(0-50) + 原始优先级(0-50)
        """
        # 交期紧迫度: 距离需求日期越近分数越高
        days_until_due = (required_date - datetime.now()).days
        if days_until_due <= 0:
            due_score = 100  # 已过期，最高优先级
        elif days_until_due <= 7:
            due_score = 80 + (7 - days_until_due) * 3
        elif days_until_due <= 14:
            due_score = 60 + (14 - days_until_due) * 2
        elif days_until_due <= 30:
            due_score = 30 + (30 - days_until_due)
        else:
            due_score = max(0, 30 - (days_until_due - 30) * 0.5)
        
        # 客户等级权重
        level_scores = {
            CustomerLevel.VIP.value: 50,
            CustomerLevel.A.value: 35,
            CustomerLevel.B.value: 20,
            CustomerLevel.C.value: 10,
        }
        level_score = level_scores.get(customer_level, 20)
        
        # 原始优先级
        priority_score = priority
        
        return due_score + level_score + priority_score
    
    async def confirm_plan(
        self,
        plan_id: str,
        confirmed_by: str,
    ) -> Dict[str, Any]:
        """确认生产计划"""
        plan = await self.get_plan(plan_id)
        if plan["status"] != PlanStatus.DRAFT.value:
            raise ValueError("只有草稿状态的计划可以确认")
        
        plan["status"] = PlanStatus.CONFIRMED.value
        plan["confirmed_by"] = confirmed_by
        plan["confirmed_at"] = datetime.now()
        
        return plan
    
    async def release_plan(
        self,
        plan_id: str,
        released_by: str,
    ) -> Dict[str, Any]:
        """下达生产计划"""
        plan = await self.get_plan(plan_id)
        if plan["status"] != PlanStatus.CONFIRMED.value:
            raise ValueError("只有已确认的计划可以下达")
        
        plan["status"] = PlanStatus.RELEASED.value
        plan["released_by"] = released_by
        plan["released_at"] = datetime.now()
        
        return plan
    
    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划详情"""
        pass
    
    async def list_plans(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """获取计划列表 (按优先级分数排序)"""
        return []
    
    async def analyze_capacity_load(
        self,
        factory_id: str,
        station_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        """
        产能负荷分析
        
        分析指定产线在日期范围内的产能使用情况
        """
        load_analysis = {
            "station_id": station_id,
            "period": f"{from_date.date()} - {to_date.date()}",
            "total_capacity_hours": 0,
            "allocated_hours": 0,
            "available_hours": 0,
            "utilization_rate": 0.0,
            "overloaded_dates": [],
            "bottleneck_stations": [],
        }
        
        # TODO: 查询实际数据计算负荷
        # 1. 获取产线产能 (每小时产能 * 工作小时数)
        # 2. 获取已分配工单的工时
        # 3. 计算利用率
        # 4. 识别超负荷日期
        # 5. 识别瓶颈工序
        
        return load_analysis
    
    async def detect_capacity_conflict(
        self,
        plan_id: str,
    ) -> List[Dict[str, Any]]:
        """
        检测产能冲突
        
        检查计划是否能按时完成，是否有产能冲突
        """
        conflicts = []
        
        plan = await self.get_plan(plan_id)
        if not plan:
            return conflicts
        
        # TODO: 
        # 1. 检查产线可用产能
        # 2. 检查物料可用量
        # 3. 返回冲突列表
        
        return conflicts


__all__ = ["MPSService", "PlanStatus", "PlanType", "CustomerLevel"]
