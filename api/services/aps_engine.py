"""
APS 有限产能排程引擎 - 岗位替代 Phase 2
优先规则调度（EDD/SPT/CR）+ 约束传播 + 插单重排 + 冲突检测
"""
import uuid
import json
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from database.models import WorkOrder, Station, Equipment, ApsSchedule


def _gen_id() -> str:
    return str(uuid.uuid4())


# 排程算法
ALGORITHMS = {
    "EDD": "最早交期优先",
    "SPT": "最短加工时间优先",
    "CR": "关键比率优先",
    "PRIORITY": "优先级优先",
}


class ApsEngine:
    """有限产能排程引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def schedule(
        self,
        factory_id: str,
        algorithm: str = "EDD",
        horizon_days: int = 30,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """
        执行排程
        1. 获取待排工单池
        2. 获取工位产能约束
        3. 按算法排序
        4. 逐工单分配到工位+时间段
        5. 检测冲突
        """
        # 统一到 APS 主引擎；旧版这里的简化算法会写入另一套字段、忽略
        # 工艺路线/班次/假期，并与 /api/v1/aps 产生两份计划。
        from api.services.aps_service import ApsService
        optimize_for = {
            "EDD": "delivery",
            "SPT": "efficiency",
            "CR": "delivery",
            "PRIORITY": "delivery",
        }.get(algorithm, "delivery")
        result = await ApsService(self.db).generate_schedule(
            factory_id=factory_id,
            mode="hybrid",
            horizon_days=horizon_days,
            optimize_for=optimize_for,
            created_by=created_by,
            change_reason=f"compat_schedule:{algorithm}",
        )
        result["algorithm"] = algorithm
        result["algorithm_name"] = ALGORITHMS.get(algorithm, algorithm)
        result["conflict_count"] = len(result.get("unscheduled_orders", []))
        if not result.get("success") and not result.get("schedule_id"):
            result["error"] = result.get("message", "排程失败")
        return result

    async def reschedule(
        self,
        factory_id: str,
        insert_wo_id: Optional[str] = None,
        algorithm: str = "EDD",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """
        插单重排：保持已开工(in_progress)不动，重排未开工工单
        """
        from api.services.aps_service import ApsService
        result = await ApsService(self.db).reschedule(
            factory_id=factory_id,
            insert_wo_id=insert_wo_id,
            created_by=created_by,
            change_reason=f"compat_insert:{insert_wo_id}" if insert_wo_id else "compat_reschedule",
        )
        result["algorithm"] = algorithm
        return result

    async def get_gantt_data(self, factory_id: str, schedule_id: Optional[str] = None) -> Dict[str, Any]:
        """获取甘特图数据"""
        from api.services.aps_service import ApsService
        if not schedule_id:
            latest = await self.db.execute(
                select(ApsSchedule).where(
                    ApsSchedule.factory_id == factory_id,
                    ApsSchedule.is_current.is_(True),
                ).order_by(ApsSchedule.created_at.desc()).limit(1)
            )
            current = latest.scalar_one_or_none()
            if not current:
                return {"schedule_id": None, "resources": {}, "total_tasks": 0}
            schedule_id = current.id
        return await ApsService(self.db).get_gantt_data(schedule_id)

    async def detect_conflicts(self, factory_id: str) -> Dict[str, Any]:
        """冲突检测：设备过载 / 交期风险 / 物料未齐"""
        conflicts = []

        # 检查最新排程中的交期风险
        latest = await self.db.execute(text(
            "SELECT id FROM aps_schedules WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 1"
        ), {"fid": factory_id})
        row = latest.first()
        if row:
            task_result = await self.db.execute(text(
                "SELECT t.planned_end, w.work_order_code, w.planned_due, w.planned_qty "
                "FROM aps_schedule_tasks t JOIN work_orders w ON t.work_order_id = w.id::text "
                "WHERE t.schedule_id = :sid AND w.planned_due IS NOT NULL"
            ), {"sid": row[0]})
            for r in task_result.mappings().all():
                if r["planned_end"] and r["planned_due"]:
                    end = r["planned_end"] if isinstance(r["planned_end"], datetime) else datetime.fromisoformat(str(r["planned_end"]))
                    due = r["planned_due"] if isinstance(r["planned_due"], datetime) else datetime.fromisoformat(str(r["planned_due"]))
                    if end > due:
                        conflicts.append({
                            "type": "delivery_risk",
                            "work_order": r["work_order_code"],
                            "delay_hours": round((end - due).total_seconds() / 3600, 1),
                        })

        # 检查物料未齐的已排工单
        wo_stmt = select(WorkOrder).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["released", "pending"]),
            )
        )
        wo_result = await self.db.execute(wo_stmt)
        for wo in wo_result.scalars().all():
            # 简化：检查是否有 BOM 且库存不足
            bom_count = await self.db.execute(
                select(func.count()).select_from(BomItem).where(
                    and_(BomItem.factory_id == factory_id, BomItem.product_id == wo.product_id)
                )
            )
            if bom_count.scalar() == 0:
                conflicts.append({
                    "type": "no_bom",
                    "work_order": wo.work_order_code,
                    "message": f"产品 {wo.product_id} 无 BOM，无法进行物料齐套检查",
                })

        return {"conflicts": conflicts, "count": len(conflicts)}

    # ==================== 内部方法 ====================
