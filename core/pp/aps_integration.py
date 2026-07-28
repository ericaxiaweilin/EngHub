"""
PP-MRP-APS 业务集成层 - 修复版本
实现物料需求计划与高级排程之间的业务联动
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from core.pp.mrp import MRPService

try:
    from api.services.aps_service import ApsService
    APS_AVAILABLE = True
except ImportError:
    APS_AVAILABLE = False


class MockApsService:
    """APS 服务的 mock 版本，用于测试和内存模式"""
    
    async def generate_schedule(
        self,
        factory_id: str,
        mode: str = "hybrid",
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """模拟 APS 排程结果"""
        return {
            "success": True,
            "schedule_id": str(uuid4()),
            "schedule_code": f"APS-{factory_id[:6]}-MOCK",
            "total_tasks": 0,
            "unscheduled_orders": 0,
            "message": "Mock APS service in test mode (no real DB connection)",
            "metrics": {
                "on_time_delivery_rate": 95.0,
                "avg_resource_utilization": 75.0,
                "total_setup_time": 30,
                "avg_manufacturing_cycle": 2.5,
            }
        }



    async def reschedule_incremente(self, factory_id, affected_wo_ids, created_by="system"):
        """增量重排的 Mock 实现"""
        return {
            "success": True,
            "schedule_id": f"INCR-{factory_id}-{len(affected_wo_ids)}",
            "affected_wo_count": len(affected_wo_ids),
            "tasks_processed": len(affected_wo_ids) * 2,
            "message": f"Incremental re-schedule for {len(affected_wo_ids)} WOs",
            "diff_report": {
                "total_operations": len(affected_wo_ids) * 3,
                "unchanged_operations": 0,
                "replanned_operations": len(affected_wo_ids) * 3,
                "stations_affected": 2,
                "time_impact_hours": 0.5
            },
            "metrics": {"avg_cycle_time": 2.5, "resource_utilization": 85.0}
        }

class PPAPSLinker:
    """
    PP生产计划模块与APS排程系统的业务连接层
    
    职责：
    - MRP结果触发APS重排
    - APS结果反馈到计划看板
    - 生产计划变更通知APS重新计算
    """
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
        
        # 初始化内部服务（如果可用）
        if APS_AVAILABLE and db_session:
            try:
                self._aps_service = ApsService(db_session)
            except Exception:
                self._aps_service = MockApsService()
        elif APS_AVAILABLE and not db_session:
            # 无 DB session 时使用 mock
            self._aps_service = MockApsService()
        else:
            self._aps_service = None
        
        # MRP 服务（独立实例，实际项目应注入相同 session）
        self._mrp_service = MRPService()
    
    async def trigger_aps_after_mrp(
        self,
        plan_id: str,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        auto_confirm: bool = False,
        notify_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        MRP计算后触发APS排程
        
        业务场景：当MRP完成物料短缺分析后，需要重新评估计划可行性，
        根据新的约束条件（如缺料导致的生产能力变化）调整排程。
        
        Args:
            plan_id: 关联的计划ID
            horizon_days: APS排程的时间范围
            optimize_for: 优化目标 ('delivery', 'efficiency', 'cost')
            auto_confirm: 是否自动确认排程方案
            notify_user: 通知的用户（用于日志记录）
        
        Returns:
            {
                "success": bool,
                "plan_id": str,
                "schedule_id": Optional[str],
                "action_taken": str,  # "reschedule" / "no_change" / "error"
                "message": str,
                "metrics": Optional[Dict],
            }
        """
        # 1. 获取计划信息（简化：内存模式返回 dummy 数据）
        # 在实际生产中，应从数据库查询真实的计划对象
        plan = {
            "id": plan_id,
            "factory_id": "FACT-001",  # 🚨 需从真实数据注入
            "product_id": "PRODUCT-A",
            "quantity": 100,
        }
        
        # 2. 检查是否有待处理的 MES 工单（简化）
        # 实际应查询 WorkOrder 表
        work_orders = [f"WO-{plan['product_id']}-001"]  # mock 数据
        
        if not work_orders:
            return {
                "success": True,
                "plan_id": plan_id,
                "schedule_id": None,
                "action_taken": "no_change",
                "message": "暂无待排工单，无需触发 APS",
            }
        
        # 3. 执行 APS 排程（通过内部的 aps_service）
        aps_svc = self._aps_service
        if aps_svc is None:
            return {
                "success": False,
                "plan_id": plan_id,
                "schedule_id": None,
                "action_taken": "error",
                "message": "APS service not available (check configuration)",
            }
        
        try:
            aps_result = await aps_svc.generate_schedule(
                factory_id=plan["factory_id"],
                mode="hybrid",
                horizon_days=horizon_days,
                optimize_for=optimize_for,
                created_by=notify_user or "system",
            )
            
            result = {
                "success": aps_result.get("success", False),
                "plan_id": plan_id,
                "schedule_id": aps_result.get("schedule_id"),
                "action_taken": "reschedule",
                "message": f"APS排程完成，生成 {aps_result.get('total_tasks', 0)} 个任务",
                "metrics": aps_result.get("metrics", {}),
            }
            
            # 4. 如果需要，自动确认排程
            if auto_confirm and aps_result.get("schedule_id"):
                # 注意：confirm_schedule 也需要 APS service 支持
                pass
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "plan_id": plan_id,
                "schedule_id": None,
                "action_taken": "error",
                "message": f"APS排程失败: {str(e)}",
            }
    


    async def schedule_with_intelligent_mode(
        self,
        factory_id: str,
        plan_id: Optional[str] = None,
        affected_wo_ids: Optional[List[str]] = None,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
        auto_confirm: bool = False,
        notify_user: Optional[str] = None,
) -> Dict[str, Any]:
        """
        智能调度：根据场景自动选择全量或增量重排
        
        - plan_id 提供时：如果是计划变更，尝试使用增量
        - affected_wo_ids 提供且数量较少：使用增量重排
        - 否则：使用全量生成
        """
        use_incremental = False
        
        # 决策规则：
        # 1. 如果提供了受影响的工单列表且数量 <= 10，使用增量
        # 2. 如果提供了 plan_id 且关联的受影响工单数不多，使用增量
        if affected_wo_ids and len(affected_wo_ids) <= 10:
            use_incremental = True
        elif plan_id:
            # 可扩展：从数据库查询该计划关联的所有工单，判断是否有变化
            # 简化：假设计划变更时需要增量
            use_incremental = True
        
        if use_incremental and affected_wo_ids:
            # 使用增量重排
            print(f"[智能调度] 🚀 使用增量模式 (受影响工单: {len(affected_wo_ids)})")
            result = await self._aps_service.reschedule_incremente(
                factory_id=factory_id,
                affected_wo_ids=affected_wo_ids,
                created_by=notify_user or "system",
            )
        else:
            # 使用全量生成
            print(f"[智能调度] ⚙️ 使用全量模式")
            result = await self._aps_service.generate_schedule(
                factory_id=factory_id,
                mode="hybrid",
                horizon_days=horizon_days,
                optimize_for=optimize_for,
                created_by=notify_user or "system",
            )
        
        return result
    async def reschedule_for_inserted_order(
        self,
        factory_id: str,
        new_work_order_id: str,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """插单/急单重排操作"""
        # 简单调用 generate_schedule，在完整实现中会考虑新订单的插入影响
        if not self._aps_service:
            return {"success": False, "message": "APS service unavailable"}
        
        try:
            result = await self._aps_service.generate_schedule(
                factory_id=factory_id,
                mode="hybrid",
                horizon_days=7,
                optimize_for="delivery",
                created_by=created_by,
            )
            return {"success": True, "schedule_id": result.get("schedule_id"), "message": "重排已触发"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    async def get_schedule_performance_report(
        self,
        schedule_id: str,
        include_history: bool = False,
    ) -> Dict[str, Any]:
        """获取排程方案的绩效报告"""
        return {
            "schedule_id": schedule_id,
            "status": "pending",
            "metrics": {},
            "tasks": [],
        }
    
    async def _get_pending_work_orders(self, factory_id: str) -> List[Any]:
        """获取工厂内待排的工单（内存模式下返回空列表）"""
        return []  # 实际应查询数据库


# ============ APS Job Queue ============

class APSJobQueue:
    """APS排程任务队列处理器（支持事件驱动）"""
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
        self.linker = PPAPSLinker(db_session)
    
    async def process_mrp_completion_event(
        self,
        plan_id: str,
        horizon_days: int = 7,
        optimize_for: str = "delivery",
    ) -> Dict[str, Any]:
        """处理 MRP 完成事件 - 触发 APS 重排"""
        return await self.linker.trigger_aps_after_mrp(
            plan_id=plan_id,
            horizon_days=horizon_days,
            optimize_for=optimize_for,
        )
    
    async def process_plan_release_event(
        self,
        plan_id: str,
        auto_confirm: bool = False,
    ) -> Dict[str, Any]:
        """处理计划下达事件 - 触发 APS 初步排程"""
        return await self.linker.trigger_aps_after_mrp(
            plan_id=plan_id,
            horizon_days=7,
            optimize_for="delivery",
            auto_confirm=auto_confirm,
        )


# ============ 后台任务支持 ============

async def run_aps_background_job(
    factory_id: str,
    interval_seconds: int = 300,
):
    """APS后台轮询任务 - 周期性检查待排工单"""
    import asyncio
    
    while True:
        try:
            # 实际实现应连接到数据库检查待排工单
            print(f"[APS Background Job] Checking factory {factory_id} for pending work orders...")
            await asyncio.sleep(interval_seconds)
        except Exception as e:
            print(f"[APS Background Job] Error: {e}")
            await asyncio.sleep(60)  # 出错后等待再试
