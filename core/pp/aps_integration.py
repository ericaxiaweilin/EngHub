"""
PP-MRP-APS 业务集成层 - 修复版本
实现物料需求计划与高级排程之间的业务联动
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


try:
    from api.services.aps_service import ApsService
    APS_AVAILABLE = True
except ImportError:
    APS_AVAILABLE = False


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
        
        # 只认真实数据库会话。原来 db_session 为 None 时会落到 MockApsService，
        # 返回 success=True + 随机 schedule_id + 写死的 95% 准时率/75% 利用率，
        # 界面看起来"已自动重排"，实际库里什么都没发生。
        self._aps_service = ApsService(db_session) if (APS_AVAILABLE and db_session) else None
        
    
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
        if self.db is None:
            return {
                "success": False,
                "plan_id": plan_id,
                "schedule_id": None,
                "action_taken": "error",
                "message": "APS 联动必须使用真实数据库会话",
            }

        from database.models import Plan, WorkOrder
        plan = await self.db.get(Plan, plan_id)
        if not plan:
            return {
                "success": False,
                "plan_id": plan_id,
                "schedule_id": None,
                "action_taken": "error",
                "message": "计划不存在，未触发 APS",
            }

        work_order_result = await self.db.execute(
            select(WorkOrder).where(
                WorkOrder.factory_id == plan.factory_id,
                WorkOrder.source_plan_id == plan_id,
                WorkOrder.status.in_(["pending", "released", "in_progress"]),
                WorkOrder.wo_type == "master",
            )
        )
        work_orders = list(work_order_result.scalars().all())
        
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
                factory_id=plan.factory_id,
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
                confirmation = await aps_svc.confirm_schedule(
                    aps_result["schedule_id"],
                    confirmed_by=notify_user or "system",
                )
                result["confirmation"] = confirmation
            
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
            result = await self._aps_service.reschedule(
                factory_id=factory_id,
                insert_wo_id=new_work_order_id,
                created_by=created_by,
                change_reason=f"insert:{new_work_order_id}",
            )
            return {
                "success": result.get("success", False),
                "schedule_id": result.get("schedule_id"),
                "message": result.get("message", "重排已触发"),
                "unscheduled_orders": result.get("unscheduled_orders", []),
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
    
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
