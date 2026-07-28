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
from typing import Optional, List, Dict, Any, Set
import asyncio
from enum import Enum

from core.pp.change_management import (
    ChangeManagementService,
    ChangeRequestStatus,
    ChangeRequestLevel,
    ChangeRequest,
    PlanVersion
)


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
    主生产计划服务
    
    核心功能:
    - 创建/修改生产计划
    - 排程: 交期优先 + 客户等级
    - 产能负荷分析
    
    注意：使用内存存储模拟数据库，实际项目应连接真实数据库
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        # 内存存储模拟（生产环境替换为数据库查询）
        self._plans: Dict[str, Dict] = {}
        self._plan_history: List[Dict] = []
        
        # 模拟MES工站数据（产能信息）
        self._workstations: Dict[str, Dict] = {
            "STA-ASSY-01": {"name": "总装线1", "capacity_per_hour": 60, "factory_id": "FACT-001"},
            "STA-TEST-01": {"name": "测试线1", "capacity_per_hour": 40, "factory_id": "FACT-001"},
            "STA-PACK-01": {"name": "包装线1", "capacity_per_hour": 80, "factory_id": "FACT-001"},
            "STA-ASSY-02": {"name": "总装线2", "capacity_per_hour": 60, "factory_id": "FACT-001"},
        }
        
        # 模拟在产品库存（在制品）
        self._wip_inventory: Dict[str, int] = {
            "PRODUCT-A": 50,
            "PRODUCT-B": 30,
        }
        
        # 模拟MES工单记录
        self._work_orders: Dict[str, Dict] = {}
        
        # 模拟产品工时定额（小时/台）
        
        # === APS 智能联动配置 ===
        self.aps_auto_trigger_enabled = False  # 是否启用 MRP 后自动触发 APS 重排

        # === 计划变更管理（版本追溯与审批流程）===
        self.change_mgmt = ChangeManagementService()
        self.aps_shortage_threshold_items = 2   # 触发 APS 的短缺项数阈值（≥此值则触发）
        self.aps_shortage_threshold_qty_ratio = 0.5  # 触发 APS 的短缺比例阈值（总需求/可用量 ≥ 此值则触发）
        self.aps_override_horizon_days = 7      # APS 覆盖的时间范围（天）
        self.aps_optimize_for = "delivery"      # 优化目标 (delivery/efficiency/cost)
        self._product_std_hours: Dict[str, float] = {
            "PRODUCT-A": 2.5,
            "PRODUCT-B": 3.0,
            "PRODUCT-C": 1.8,
        }

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
        plan_id = str(uuid.uuid4())
        plan_code = self.generate_plan_code(factory_id)
        
        # 计算优先级分数
        priority_score = self._calculate_priority_score(
            required_date=required_date,
            customer_level=customer_level,
            priority=priority
        )
        
        plan = {
            "id": plan_id,
            "plan_code": f"{plan_code}-{len(self._plans)+1:03d}",
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
            "priority_score": priority_score,
            "estimated_hours": self._estimate_plan_hours(product_id, quantity),
        }
        
        self._plans[plan_id] = plan
        self._plan_history.append(plan.copy())
        

        # 创建初始版本（版本 1）
        self.change_mgmt.add_version(
            plan_id=plan["id"],
            version_number=1,
            changed_by=created_by or "system",
            change_type="create",
            description=f"计划 {plan['plan_code']} 初始创建",
            previous_state={},
            current_state=plan.copy(),
        )
        return plan
    
    def _estimate_plan_hours(self, product_id: str, quantity: int) -> float:
        """估算计划所需标准工时"""
        std_hour = self._product_std_hours.get(product_id, 2.0)
        return round(std_hour * quantity, 2)
    
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
        
        # 原始优先级（0-50），限制为50以内
        priority_score = min(max(priority, 0), 50)
        
        # 最终总分也限制在150以内（100+50+50）
        total = round(due_score + level_score + priority_score, 1)
        return min(total, 150)
    
    async def confirm_plan(
        self,
        plan_id: str,
        confirmed_by: str,
    ) -> Dict[str, Any]:
        """确认生产计划"""
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        if plan["status"] != PlanStatus.DRAFT.value:
            raise ValueError("只有草稿状态的计划可以确认")
        
        plan["status"] = PlanStatus.CONFIRMED.value
        plan["confirmed_by"] = confirmed_by
        plan["confirmed_at"] = datetime.now()
        plan["updated_at"] = datetime.now()
        
        return plan
    
    async def release_plan(
        self,
        plan_id: str,
        released_by: str,
        trigger_aps: bool = True,
    ) -> Dict[str, Any]:
        """下达生产计划（自动触发MRP、工单生成和可选APS排程）"""
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        if plan["status"] != PlanStatus.CONFIRMED.value:
            raise ValueError("只有已确认的计划可以下达")
        
        # 先检查产能冲突
        conflicts = await self.detect_capacity_conflict(plan_id)
        if conflicts:
            # 不阻止下达，但记录警告
            plan["release_warning"] = f"检测到{len(conflicts)}个产能冲突"
        
        plan["status"] = PlanStatus.RELEASED.value
        plan["released_by"] = released_by
        plan["released_at"] = datetime.now()
        plan["updated_at"] = datetime.now()
        
        # 生成MES工单（模拟）
        work_order = await self._generate_work_order_from_plan(plan_id)
        plan["work_order_id"] = work_order["id"] if work_order else None
        
        # 异步触发APS排程（非阻塞调用）
        if trigger_aps and hasattr(self, "_aps_trigger_enabled") and self._aps_trigger_enabled:
            asyncio.create_task(self._trigger_automated_aps(plan_id, released_by))
            plan["aps_trigger_queued"] = True
        
        return plan
    
    async def _trigger_automated_aps(self, plan_id: str, user: str):
        """异步触发APS排程（后台任务）"""
        try:
            print(f"[APS Trigger] 为计划 {plan_id} 触发自动APS排程...")
            # APS触发逻辑将在API层通过服务完成
        except Exception as e:
            print(f"[APS Trigger] 触发失败: {e}")

    async def enable_aps_integration(self):
        """启用APS自动触发功能"""
        self._aps_trigger_enabled = True
        print("✓ APS自动触发功能已启用")
    
    async def _generate_work_order_from_plan(self, plan_id: str) -> Optional[Dict]:
        """从MPS计划生成MES工单（模拟）"""
        plan = self._plans[plan_id]
        wo_id = str(uuid.uuid4())
        
        work_order = {
            "id": wo_id,
            "work_order_code": f"WO-{plan['plan_code']}",
            "factory_id": plan["factory_id"],
            "product_id": plan["product_id"],
            "planned_qty": plan["quantity"],
            "completed_qty": 0,
            "status": "draft",  # draft -> pending -> released
            "due_date": plan["required_date"],
            "source_plan_id": plan_id,
            "created_at": datetime.now(),
        }
        
        self._work_orders[wo_id] = work_order
        
        # 减少WIP库存（模拟领料）
        if plan["product_id"] in self._wip_inventory:
            self._wip_inventory[plan["product_id"]] = max(0, 
                self._wip_inventory[plan["product_id"]] - plan["quantity"])
        
        return work_order
    
    async def complete_plan(self, plan_id: str, completed_by: str) -> Dict[str, Any]:
        """完成生产计划"""
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        if plan["status"] not in [PlanStatus.RELEASED.value, PlanStatus.IN_PROGRESS.value]:
            raise ValueError("只能完成正在执行的计划")
        
        plan["status"] = PlanStatus.COMPLETED.value
        plan["completed_by"] = completed_by
        plan["completed_at"] = datetime.now()
        plan["updated_at"] = datetime.now()
        
        return plan
    
    async def cancel_plan(self, plan_id: str, cancelled_by: str, reason: str = "") -> Dict[str, Any]:
        """取消生产计划"""
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        if plan["status"] in [PlanStatus.COMPLETED.value, PlanStatus.CANCELLED.value]:
            raise ValueError("计划已完成或已取消，无法再次取消")
        
        plan["status"] = PlanStatus.CANCELLED.value
        plan["cancelled_by"] = cancelled_by
        plan["cancelled_at"] = datetime.now()
        plan["update_reason"] = reason
        plan["updated_at"] = datetime.now()
        
        return plan
    
    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划详情"""
        return self._plans.get(plan_id)
    
    async def list_plans(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取计划列表 (按优先级分数排序)"""
        plans = list(self._plans.values())
        
        # 过滤条件
        if factory_id:
            plans = [p for p in plans if p["factory_id"] == factory_id]
        if status:
            plans = [p for p in plans if p["status"] == status]
        if product_id:
            plans = [p for p in plans if p["product_id"] == product_id]
        if from_date:
            plans = [p for p in plans if p["required_date"] >= from_date]
        if to_date:
            plans = [p for p in plans if p["required_date"] <= to_date]
        
        # 按优先级分数降序排序
        plans.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        
        return plans[:limit]
    
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
        if station_id not in self._workstations:
            raise f"工站 {station_id} 不存在"
        
        workstation = self._workstations[station_id]
        
        # 计算期间工作小时数（假设每天8小时，周末休息）
        total_days = (to_date - from_date).days + 1
        working_days = sum(1 for i in range(total_days) 
                         if (from_date + timedelta(days=i)).weekday() < 5)  # 周一到周五
        total_capacity_hours = workstation["capacity_per_hour"] * 8 * working_days
        
        # 计算已分配的工时（来自已发布的计划和工单）
        allocated_hours = 0
        released_plans = [p for p in self._plans.values() 
                         if p["factory_id"] == factory_id 
                         and p["status"] in [PlanStatus.RELEASED.value, PlanStatus.IN_PROGRESS.value]
                         and p["required_date"] >= from_date and p["required_date"] <= to_date]
        
        for plan in released_plans:
            # 估算该计划在该工站的工时（简化：按比例分配）
            allocated_hours += plan.get("estimated_hours", 0) * 0.6  # 假设60%工时在此工站
        
        # 已完成的工单工时
        completed_wo_hours = sum(
            wo.get("estimated_hours", 0) for wo in self._work_orders.values()
            if wo.get("status") == "completed"
        )
        allocated_hours += completed_wo_hours / 2  # 简化计算
        
        available_hours = max(0, total_capacity_hours - allocated_hours)
        utilization_rate = round((allocated_hours / total_capacity_hours * 100) if total_capacity_hours > 0 else 0, 1)
        
        # 识别超负荷日期（简单模拟）
        overloaded_dates = []
        if utilization_rate > 90:
            overloaded_dates.append(f"{from_date.date()} 至 {to_date.date()} 负荷率 {utilization_rate}%")
        
        # 瓶颈工站分析（所有工站）
        bottleneck_stations = []
        all_factory_stations = {sid: w for sid, w in self._workstations.items() if w["factory_id"] == factory_id}
        
        if all_factory_stations:
            # 找出负荷最高的前3个工站
            station_loads = []
            for sid, ws in all_factory_stations.items():
                ws_total = ws["capacity_per_hour"] * 8 * working_days
                ws_allocated = sum(
                    p.get("estimated_hours", 0) * 0.6 for p in released_plans
                    if p["factory_id"] == factory_id
                )
                ws_util = round(ws_allocated / ws_total * 100) if ws_total > 0 else 0
                station_loads.append((sid, ws_util))
            
            station_loads.sort(key=lambda x: x[1], reverse=True)
            bottleneck_stations = [(sid, util) for sid, util in station_loads[:3]]
        
        load_analysis = {
            "station_id": station_id,
            "station_name": workstation["name"],
            "period": f"{from_date.date()} - {to_date.date()}",
            "total_capacity_hours": total_capacity_hours,
            "allocated_hours": round(allocated_hours, 2),
            "available_hours": round(available_hours, 2),
            "utilization_rate": utilization_rate,
            "overloaded_dates": overloaded_dates,
            "bottleneck_stations": bottleneck_stations,
        }
        
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
        
        if plan_id not in self._plans:
            return conflicts
        
        plan = self._plans[plan_id]
        
        # 检查产能冲突
        try:
            # 找一个典型工站进行分析
            factory_stations = [sid for sid, w in self._workstations.items() 
                              if w["factory_id"] == plan["factory_id"]]
            if factory_stations:
                sample_station = factory_stations[0]
                load_analysis = await self.analyze_capacity_load(
                    factory_id=plan["factory_id"],
                    station_id=sample_station,
                    from_date=plan["required_date"] - timedelta(days=7),
                    to_date=plan["required_date"]
                )
                if load_analysis["utilization_rate"] > 95:
                    conflicts.append({
                        "type": "capacity_overload",
                        "station_id": sample_station,
                        "message": f"工站 {sample_station} 负荷率 {load_analysis['utilization_rate']}%，可能无法按时交付",
                        "severity": "HIGH"
                    })
        except Exception as e:
            conflicts.append({
                "type": "analysis_error",
                "message": f"产能分析失败: {str(e)}",
                "severity": "MEDIUM"
            })
        
        # 检查物料冲突（简单模拟）
        if plan["quantity"] > 1000:
            conflicts.append({
                "type": "material_high_volume",
                "message": f"计划数量 {plan['quantity']} 较大，需确认物料供应能力",
                "severity": "MEDIUM"
            })
        
        return conflicts
    
    async def get_factory_plans(self, factory_id: str) -> List[Dict]:
        """获取工厂的所有计划"""
        return [p for p in self._plans.values() if p["factory_id"] == factory_id]
    
    async def update_plan_quantity(self, plan_id: str, new_quantity: int, updated_by: str) -> Dict:
        """更新计划数量"""
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        old_quantity = plan["quantity"]
        plan["quantity"] = new_quantity
        plan["estimated_hours"] = self._estimate_plan_hours(plan["product_id"], new_quantity)
        plan["priority_score"] = self._calculate_priority_score(
            required_date=plan["required_date"],
            customer_level=plan["customer_level"],
            priority=plan["priority"]
        )
        plan["updated_by"] = updated_by
        plan["updated_at"] = datetime.now()
        
        return plan




    async def update_plan(
        self,
        plan_id: str,
        updates: Dict[str, Any],
        updated_by: str,
        trigger_aps_replan: bool = True,
    ) -> Dict[str, Any]:
        """
        更新计划（支持多字段变更）
        
        Args:
            plan_id: 计划ID
            updates: 要更新的字段字典（如 {"quantity": 200, "required_date": datetime(...)}）
            updated_by: 更新人
            trigger_aps_replan: 是否触发APS重排（默认True）
        
        Returns:
            更新后的计划对象
        """
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        old_state = {k: v for k, v in plan.items() if k in updates}  # 记录变更前状态
        
        # 应用更新
        for key, value in updates.items():
            if key in plan:
                plan[key] = value
        
        # 需要重新计算的字段
        if "quantity" in updates or "required_date" in updates or "priority" in updates or "customer_level" in updates:
            plan["estimated_hours"] = self._estimate_plan_hours(plan["product_id"], plan["quantity"])
            plan["priority_score"] = self._calculate_priority_score(
                required_date=plan["required_date"],
                customer_level=plan["customer_level"],
                priority=plan["priority"]
            )
        
        plan["updated_by"] = updated_by
        plan["updated_at"] = datetime.now()
        
        # === 智能联动：计划变更后是否需要触发APS重排 ===
        if trigger_aps_replan and getattr(self, "_aps_trigger_enabled", False):
            # 如果关键业务字段发生变化，触发MRP+APS联动
            changed_fields = [k for k in updates.keys() if k in ["quantity", "required_date", "priority", "customer_level"]]
            if changed_fields:
                print(f"[计划变更] 计划 {plan_id} 发生变更 ({changed_fields}) → 触发MRP重算 + APS重排...")
                
                # 异步触发（非阻塞）
                asyncio.create_task(self._execute_plan_change_workflow(plan_id, updated_by, changed_fields))
        
        return plan
    
    async def _trigger_aps_on_plan_change(self, plan_id: str, user: str):
        """计划变更后触发APS重排的内部方法"""
        try:
            
            plan = self._plans.get(plan_id)
            if not plan:
                print(f"[APS] 计划 {plan_id} 不存在，跳过重排")
                return
            
            factory_id = plan.get("factory_id", "FACT-001")
            
            # 创建链接器（实际项目应传入真实DB session）
            link = PPAPSLinker(None)  # 内存模式
            
            # 通过PPAPSLinker触发APS重排
            result = await link.trigger_aps_after_mrp(
                plan_id=plan_id,
                horizon_days=getattr(self, "aps_override_horizon_days", 7),
                optimize_for=getattr(self, "aps_optimize_for", "delivery"),
                auto_confirm=False,  # 生产环境建议先人工确认
                notify_user=user,
            )
            
            print(f"[APS] 计划 {plan_id} 重排结果: {result.get('message')}")
            
            # 如果需要，可以更新计划的APS状态字段
            plan["last_aps_replan"] = result.get("schedule_id")
            
        except Exception as e:
            print(f"[APS] 计划 {plan_id} 重排失败: {e}")
            # 可选：将错误记录到告警队列或发送通知
        
        finally:
            # 清理临时资源（如需要）
            pass

    async def create_change_request(
        self,
        plan_id: str,
        applicant: str,
        changes: Dict[str, Any],
        description: str,
        change_type: str = "update",
) -> Dict[str, Any]:
        """
        创建生产计划变更申请单
        
        Args:
            plan_id: 计划ID
            applicant: 申请人
            changes: 变更内容 {field: {"old": old_value, "new": new_value}}
            description: 变更描述
            change_type: 变更类型 (update/rebalance/cancel/etc.)
        
        Returns:
            变更请求信息
        """
        if plan_id not in self._plans:
            raise ValueError("计划不存在")
        
        plan = self._plans[plan_id]
        
        # 获取变更前状态
        previous_state = plan.copy()
        
        # 应用变更到计划的内存副本（暂不提交，待审批通过后再正式应用）
        for field, value_info in changes.items():
            if field in plan:
                plan[field] = value_info["new"]
        
        # 创建变更请求
        request_id = f"PCR-{datetime.utcnow().strftime('%Y%m%d')}-{int(uuid().hex[:8],16)}"
        request = ChangeRequest(
            request_id=request_id,
            plan_id=plan_id,
            factory_id=plan["factory_id"],
            applicant=applicant,
            changes=changes,
            description=description,
            change_type=change_type,
        )
        
        # 保存变更请求
        self.change_mgmt._requests[request_id] = request
        
        # 计算影响分析
        impact = self.change_mgmt.generate_impact_analysis(plan_id, changes)
        request.set_impact_analysis(impact)
        
        return {
            "request_id": request_id,
            "plan_id": plan_id,
            "status": request.status.value,
            "level": request.level.value,
            "changes": changes,
            "impact_analysis": impact,
        }
    
    async def submit_change_request(self, request_id: str, approved_by: Optional[str] = None) -> bool:
        """
        提交变更请求进行审批（如果是 level1 则自动批准，否则等待人工审批）
        
        Args:
            request_id: 变更请求ID
            approved_by: 批准人（仅在需要人工审批时提供）
        
        Returns:
            是否成功提交/批准
        """
        request = self.change_mgmt._requests.get(request_id)
        if not request or request.status != ChangeRequestStatus.PENDING:
            return False
        
        # Level1 变更自动批准
        if request.level == ChangeRequestLevel.LEVEL_1:
            request.approve(approved_by or "auto")
            await self._apply_change_request(request)
            return True
        
        # Level2/Level3 需要人工审批 - 保持 pending 状态
        return True
    
    async def approve_change_request(self, request_id: str, approved_by: str) -> bool:
        """
        人工批准变更请求（仅适用于 Level2/Level3）
        
        Args:
            request_id: 变更请求ID
            approved_by: 批准人
        
        Returns:
            是否批准成功
        """
        request = self.change_mgmt._requests.get(request_id)
        if not request or request.status != ChangeRequestStatus.PENDING:
            return False
        
        request.approve(approved_by)
        await self._apply_change_request(request)
        return True
    
    async def reject_change_request(self, request_id: str, reason: str) -> bool:
        """
        拒绝变更请求
        
        Args:
            request_id: 变更请求ID
            reason: 拒绝原因
        
        Returns:
            是否拒绝成功
        """
        request = self.change_mgmt._requests.get(request_id)
        if not request or request.status != ChangeRequestStatus.PENDING:
            return False
        
        request.reject(reason)
        return True
    
    async def _apply_change_request(self, request: ChangeRequest) -> bool:
        """
        内部方法：应用已批准的变更到计划，并记录版本历史
        
        注意：此方法会直接修改计划的内存状态
        """
        plan_id = request.plan_id
        if plan_id not in self._plans:
            return False
        
        plan = self._plans[plan_id]
        applicant = request.applicant
        
        # 获取变更前状态（snapshot）
        previous_state = plan.copy()
        
        # 应用变更
        for field, value_info in request.changes.items():
            if field in plan:
                plan[field] = value_info["new"]
        
        plan["updated_by"] = applicant
        plan["updated_at"] = datetime.now()
        
        # 记录版本历史
        current_version = len(self.change_mgmt.get_versions(plan_id)) + 1
        self.change_mgmt.add_version(
            plan_id=plan_id,
            version_number=current_version,
            changed_by=applicant,
            change_type=request.change_type,
            description=request.description,
            previous_state=previous_state,
            current_state=plan.copy(),
        )
        
        # 标记为已处理
        request.process()
        
        return True
    def generate_plan_code(self, factory_code: str) -> str:
        """生成计划编码格式：MPS-YYYYWW-工厂码"""
        today = datetime.now()
        return f'MPS-{today.strftime("%Y%W")}-{factory_code}'




    async def _execute_plan_change_workflow(self, plan_id, user, changed_fields):
        try:
            plan = self._plans.get(plan_id)
            if not plan:
                return
            if 'quantity' in changed_fields:
                print('MRP重算: 计划数量变化')
            print('APS重排: 计划变更通知')
            link = PPAPSLinker(None)
            await link.trigger_aps_after_mrp(plan_id=plan_id, horizon_days=7, optimize_for='delivery', auto_confirm=False, notify_user=user)
            print('计划变更完成')
        except Exception as e:
            print('失败:', str(e))

__all__ = ["MPSService", "PlanStatus", "PlanType", "CustomerLevel"]