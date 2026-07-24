"""
设备 TPM 服务 - OEE/停机/维护工单/预防维护
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Equipment, EquipmentDowntime, MaintenanceOrder, MaintenancePlan,
    ProductionReport,
)

logger = logging.getLogger(__name__)


class EquipmentTpmService:
    """设备 TPM 服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============== 停机管理 ==============

    async def record_downtime(
        self,
        equipment_id: str,
        factory_id: str,
        start_time: datetime,
        downtime_category: str = "breakdown",
        reason_code: Optional[str] = None,
        description: Optional[str] = None,
        reported_by: Optional[str] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """记录停机"""
        duration = None
        if end_time:
            duration = (end_time - start_time).total_seconds() / 60

        record = EquipmentDowntime(
            id=str(uuid.uuid4()),
            equipment_id=equipment_id,
            factory_id=factory_id,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            downtime_category=downtime_category,
            reason_code=reason_code,
            description=description,
            reported_by=reported_by,
        )
        self.db.add(record)

        # 更新设备状态
        eq = await self.db.get(Equipment, equipment_id)
        if eq and downtime_category == "breakdown":
            eq.status = "broken"
            eq.updated_at = datetime.utcnow()

        await self.db.commit()
        return {"success": True, "downtime_id": record.id}

    async def end_downtime(self, downtime_id: str) -> Dict[str, Any]:
        """结束停机"""
        record = await self.db.get(EquipmentDowntime, downtime_id)
        if not record:
            return {"success": False, "message": "停机记录不存在"}
        record.end_time = datetime.utcnow()
        record.duration_minutes = (record.end_time - record.start_time).total_seconds() / 60

        # 恢复设备状态
        eq = await self.db.get(Equipment, record.equipment_id)
        if eq and eq.status == "broken":
            eq.status = "available"
            eq.updated_at = datetime.utcnow()

        await self.db.commit()
        return {"success": True, "duration_minutes": record.duration_minutes}

    # ============== OEE 计算 ==============

    async def calculate_oee(
        self,
        factory_id: str,
        equipment_id: Optional[str] = None,
        days: int = 7,
    ) -> Dict[str, Any]:
        """真实计算 OEE（从报工 + 停机数据）"""
        now = datetime.utcnow()
        start = now - timedelta(days=days)

        # 计划生产时间（天 × 12h 标准班）
        planned_minutes = days * 12 * 60

        # 查询停机时间
        dt_stmt = select(func.coalesce(func.sum(EquipmentDowntime.duration_minutes), 0)).where(
            EquipmentDowntime.factory_id == factory_id,
            EquipmentDowntime.start_time >= start,
        )
        if equipment_id:
            dt_stmt = dt_stmt.where(EquipmentDowntime.equipment_id == equipment_id)
        total_downtime = (await self.db.execute(dt_stmt)).scalar() or 0

        # 可用率
        availability = max(0, (planned_minutes - total_downtime) / planned_minutes) if planned_minutes > 0 else 0

        # 查询报工数据（产出）
        pr_stmt = select(
            func.coalesce(func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty), 0),
            func.coalesce(func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty), 0),
        ).where(
            ProductionReport.factory_id == factory_id,
            ProductionReport.created_at >= start,
        )
        pr_result = await self.db.execute(pr_stmt)
        row = pr_result.fetchone()
        total_produced = row[0] if row else 0
        total_defects = row[1] if row else 0

        # 性能率（简化：假设理想节拍 = 计划时间 / 目标产出）
        running_minutes = planned_minutes - total_downtime
        performance = min(1.0, (total_produced * 0.2) / running_minutes) if running_minutes > 0 else 0
        # 注：0.2 min/件为默认理想节拍，实际应从工艺路线获取

        # 良品率
        quality_rate = ((total_produced - total_defects) / total_produced) if total_produced > 0 else 1.0

        oee = availability * performance * quality_rate

        return {
            "factory_id": factory_id,
            "equipment_id": equipment_id,
            "period_days": days,
            "availability": round(availability * 100, 1),
            "performance": round(performance * 100, 1),
            "quality": round(quality_rate * 100, 1),
            "oee": round(oee * 100, 1),
            "planned_minutes": planned_minutes,
            "downtime_minutes": round(total_downtime, 1),
            "total_produced": total_produced,
            "total_defects": total_defects,
        }

    # ============== 维护工单 ==============

    async def create_maintenance_order(
        self,
        factory_id: str,
        equipment_id: str,
        maintenance_type: str = "corrective",
        priority: str = "medium",
        description: Optional[str] = None,
        planned_date: Optional[datetime] = None,
        assigned_to: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建维护工单"""
        now = datetime.utcnow()
        order_code = f"MO-{factory_id[:4]}-{now.strftime('%Y%m%d%H%M')}-{str(uuid.uuid4())[:4].upper()}"

        order = MaintenanceOrder(
            id=str(uuid.uuid4()),
            order_code=order_code,
            factory_id=factory_id,
            equipment_id=equipment_id,
            maintenance_type=maintenance_type,
            priority=priority,
            status="open",
            description=description,
            planned_date=planned_date,
            assigned_to=assigned_to,
            created_by=created_by,
        )
        self.db.add(order)

        # 更新设备状态为维护中
        eq = await self.db.get(Equipment, equipment_id)
        if eq:
            eq.status = "maintenance"
            eq.updated_at = now

        await self.db.commit()
        return {"success": True, "order_id": order.id, "order_code": order_code}

    async def update_maintenance_order(
        self,
        order_id: str,
        status: Optional[str] = None,
        result_summary: Optional[str] = None,
        downtime_minutes: Optional[float] = None,
    ) -> Dict[str, Any]:
        """更新维护工单状态"""
        order = await self.db.get(MaintenanceOrder, order_id)
        if not order:
            return {"success": False, "message": "维护工单不存在"}

        if status:
            order.status = status
            if status == "in_progress" and not order.started_at:
                order.started_at = datetime.utcnow()
            elif status == "completed":
                order.completed_at = datetime.utcnow()
                # 恢复设备状态
                eq = await self.db.get(Equipment, order.equipment_id)
                if eq:
                    eq.status = "available"
                    eq.last_maintenance_date = datetime.utcnow()
                    eq.updated_at = datetime.utcnow()

        if result_summary:
            order.result_summary = result_summary
        if downtime_minutes is not None:
            order.downtime_minutes = downtime_minutes

        await self.db.commit()
        return {"success": True, "message": f"维护工单状态: {order.status}"}

    # ============== 预防维护计划 ==============

    async def create_maintenance_plan(
        self,
        factory_id: str,
        equipment_id: str,
        plan_name: str,
        frequency_days: int,
        checklist: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建预防维护计划"""
        now = datetime.utcnow()
        plan = MaintenancePlan(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            equipment_id=equipment_id,
            plan_name=plan_name,
            frequency_days=frequency_days,
            next_due_at=now + timedelta(days=frequency_days),
            checklist=checklist,
            is_active=True,
        )
        self.db.add(plan)
        await self.db.commit()
        return {"success": True, "plan_id": plan.id}

    async def get_maintenance_schedule(self, factory_id: str) -> Dict[str, Any]:
        """获取预防维护日历"""
        stmt = select(MaintenancePlan).where(
            MaintenancePlan.factory_id == factory_id,
            MaintenancePlan.is_active == True,
        ).order_by(MaintenancePlan.next_due_at.asc())
        result = await self.db.execute(stmt)
        plans = result.scalars().all()

        now = datetime.utcnow()
        items = []
        for p in plans:
            overdue = p.next_due_at and p.next_due_at < now
            items.append({
                "id": p.id,
                "equipment_id": p.equipment_id,
                "plan_name": p.plan_name,
                "frequency_days": p.frequency_days,
                "last_executed_at": p.last_executed_at.isoformat() if p.last_executed_at else None,
                "next_due_at": p.next_due_at.isoformat() if p.next_due_at else None,
                "is_overdue": overdue,
                "checklist": p.checklist,
            })

        return {"items": items, "overdue_count": sum(1 for i in items if i["is_overdue"])}

    # ============== 设备看板 ==============

    async def get_equipment_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """设备看板"""
        # 设备状态分布
        eq_stmt = select(Equipment.status, func.count()).where(
            Equipment.factory_id == factory_id
        ).group_by(Equipment.status)
        eq_result = await self.db.execute(eq_stmt)
        status_dist = {r[0]: r[1] for r in eq_result.fetchall()}

        # 近7天停机统计
        week_ago = datetime.utcnow() - timedelta(days=7)
        dt_stmt = select(
            EquipmentDowntime.downtime_category,
            func.count(),
            func.coalesce(func.sum(EquipmentDowntime.duration_minutes), 0),
        ).where(
            EquipmentDowntime.factory_id == factory_id,
            EquipmentDowntime.start_time >= week_ago,
        ).group_by(EquipmentDowntime.downtime_category)
        dt_result = await self.db.execute(dt_stmt)
        downtime_stats = [
            {"category": r[0], "count": r[1], "total_minutes": round(r[2], 1)}
            for r in dt_result.fetchall()
        ]

        # 待处理维护工单
        mo_stmt = select(func.count()).where(
            MaintenanceOrder.factory_id == factory_id,
            MaintenanceOrder.status.in_(["open", "in_progress"]),
        )
        open_maint = (await self.db.execute(mo_stmt)).scalar() or 0

        # OEE
        oee = await self.calculate_oee(factory_id, days=7)

        return {
            "factory_id": factory_id,
            "status_distribution": status_dist,
            "total_equipment": sum(status_dist.values()),
            "downtime_7d": downtime_stats,
            "open_maintenance_orders": open_maint,
            "oee_7d": oee,
        }
